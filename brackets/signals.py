from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.db import transaction
from .models import Bracket, BracketMatch
from games.models import Game
from .views import BracketViewSet
import logging
from time import sleep
from datetime import timedelta

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Game)
def update_match_winner(sender, instance, **kwargs):
    if instance.status == Game.Status.COMPLETED and instance.bracket_match:
        match = instance.bracket_match
        winner = instance.winner

        if match.winner == winner:
            return

        match.winner = winner
        match.save(update_fields=["winner"])

        # --- wait for next round creation ---
        for _ in range(3):
            match.refresh_from_db()
            if match.next_match:
                break
            sleep(0.2)  # Small delay to allow transaction to complete

        if match.next_match:
            next_match = match.next_match
            if not next_match.home_team:
                next_match.home_team = winner
            elif not next_match.away_team:
                next_match.away_team = winner
            next_match.save(update_fields=["home_team", "away_team"])


@receiver(post_save, sender=BracketMatch)
def handle_match_completion(sender, instance, **kwargs):
    if instance.winner and instance.round.round_number == instance.bracket.current_round:
        bracket = instance.bracket
        current_round_number = bracket.current_round
        current_round = bracket.rounds.get(round_number=current_round_number)

        if not current_round.matches.filter(winner__isnull=True).exists():
            logger.info(f"All matches completed for round {current_round_number} of bracket {bracket.id}")
            viewset = BracketViewSet()

            with transaction.atomic():
                # Create the next round
                viewset._create_next_round(bracket)

                # Get the next round using the known number
                next_round = bracket.rounds.filter(round_number=bracket.current_round + 1).first()
                if not next_round:
                    logger.info(f"No next round exists. Bracket {bracket.id} has likely finished.")
                    return
                next_match = next_round.matches.first()

                # Get winners from the completed round
                winners = list(current_round.matches.values_list('winner', flat=True))

                if len(winners) >= 2:
                    next_match.home_team_id = winners[0]
                    next_match.away_team_id = winners[1]
                    next_match.save(update_fields=["home_team", "away_team"])

                # Now advance the bracket's round tracker
                bracket.current_round = current_round_number + 1
                bracket.save(update_fields=["current_round"])



@receiver(post_save, sender=BracketMatch)
def create_or_assign_game(sender, instance, **kwargs):
    # If the bracket is complete, do nothing
    if instance.bracket.is_complete:
        logger.info(f"Bracket {instance.bracket.id} is already complete.")
        return
     
    if instance.game:
        return  # Already linked to a game

    # Only create game if both teams have been assigned
    if instance.home_team and instance.away_team:
        try:
            # Retrieve the season start datetime from the bracket's season
            season_start = instance.bracket.season.start_date
            if not season_start:
                raise ValueError("Season start date is not defined.")

            # Calculate day offset: each round is on a new day.
            round_offset = timedelta(days=instance.round.round_number - 1)

            # Calculate the match order (2 hours per match) within the current round.
            # We simply order matches in this round by their id.
            matches_in_round = list(instance.round.matches.order_by('id'))
            try:
                match_index = matches_in_round.index(instance)
            except ValueError:
                match_index = 0
            time_offset = timedelta(hours=2 * match_index)

            scheduled_datetime = season_start + round_offset + time_offset

            game = Game.objects.create(
                sport=instance.home_team.sport,
                home_team=instance.home_team,
                away_team=instance.away_team,
                status=Game.Status.SCHEDULED,
                season=instance.bracket.season,
                league=instance.bracket.season.league if instance.bracket.season else None,
                date=scheduled_datetime  # Assuming your Game model has this field
            )
            instance.game = game
            instance.save(update_fields=["game"])
            logger.info(f"Game created for match {instance.id} scheduled at {scheduled_datetime}")
        except Exception as e:
            logger.error(f"Failed to create game for match {instance.id}: {str(e)}")


@receiver(pre_delete, sender=Bracket)
def delete_bracket_games(sender, instance, **kwargs):
    Game.objects.filter(bracket_match__bracket=instance).delete()
    logger.info(f"Deleted all games for bracket {instance.id}")
