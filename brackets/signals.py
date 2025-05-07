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
    # Only process completed games that are part of a tournament or league
    if instance.status != Game.Status.COMPLETED or instance.type == Game.Type.NORMAL:
        return

    try:
        # Safely check if the game has a bracket_match
        if not hasattr(instance, 'bracket_match') or not instance.bracket_match:
            return

        match = instance.bracket_match
        winner = instance.winner

        # If winner hasn't changed, no need to proceed
        if match.winner == winner:
            return

        # First, ensure the teams in the match match the teams in the game
        update_fields = []
        if match.home_team != instance.home_team:
            match.home_team = instance.home_team
            update_fields.append("home_team")
            logger.info(f"Updated match {match.id} home team to {instance.home_team.id} to sync with game")
        
        if match.away_team != instance.away_team:
            match.away_team = instance.away_team
            update_fields.append("away_team")
            logger.info(f"Updated match {match.id} away team to {instance.away_team.id} to sync with game")

        # Validate that winner is one of the participating teams
        if winner and winner not in [match.home_team, match.away_team]:
            logger.error(f"Game {instance.id} has winner ID {winner.id} which is not one of the teams in match {match.id} " +
                        f"(home: {match.home_team.id if match.home_team else 'None'}, " +
                        f"away: {match.away_team.id if match.away_team else 'None'})")
            
            # Determine the correct winner based on scores
            if instance.home_team_score > instance.away_team_score:
                winner = instance.home_team
                logger.info(f"Corrected winner to home team {winner.id} based on scores")
            elif instance.away_team_score > instance.home_team_score:
                winner = instance.away_team
                logger.info(f"Corrected winner to away team {winner.id} based on scores")
            else:
                logger.error(f"Cannot determine winner for tied game {instance.id}")
                return
        
        # Update the match winner
        match.winner = winner
        update_fields.append("winner")
        match.save(update_fields=update_fields)

        # Wait for next round creation with a maximum of 3 attempts
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                match.refresh_from_db()
                if match.next_match:
                    break
            except Exception:
                if attempt == max_attempts - 1:
                    raise
            sleep(0.2)  # Small delay to allow transaction to complete

        # Update the next match if it exists
        if match.next_match:
            next_match = match.next_match
            update_fields = []
            
            if not next_match.home_team:
                next_match.home_team = winner
                update_fields.append("home_team")
            elif not next_match.away_team:
                next_match.away_team = winner
                update_fields.append("away_team")
            
            if update_fields:
                next_match.save(update_fields=update_fields)

    except Exception as e:
        # Log the error but don't prevent the game from completing
        logger.error(f"Error updating bracket match winner: {str(e)}")


@receiver(post_save, sender=BracketMatch)
def handle_match_completion(sender, instance, **kwargs):
    if (
        instance.winner
        and instance.round.round_number == instance.bracket.current_round
    ):
        bracket = instance.bracket
        current_round_number = bracket.current_round
        current_round = bracket.rounds.get(round_number=current_round_number)

        if not current_round.matches.filter(winner__isnull=True).exists():
            logger.info(
                f"All matches completed for round {current_round_number} of bracket {bracket.id}"
            )
            
            # Stop here for round robin tournaments if we've reached the expected number of rounds
            if bracket.elimination_type == 'round_robin':
                # Get total teams to calculate expected rounds
                teams_count = bracket.season.teams.count()
                expected_rounds = teams_count - 1 if teams_count > 1 else 0
                
                # If we've completed all rounds for round robin, mark as complete and exit
                if current_round_number >= expected_rounds:
                    logger.info(f"Round robin tournament completed with {current_round_number} rounds.")
                    bracket.is_complete = True
                    # Determine the bracket winner based on team with most wins
                    from django.db.models import Count
                    winner_team = BracketMatch.objects.filter(
                        bracket=bracket, 
                        winner__isnull=False
                    ).values('winner').annotate(
                        win_count=Count('winner')
                    ).order_by('-win_count').first()
                    
                    if winner_team:
                        bracket.winner_id = winner_team['winner']
                        bracket.save(update_fields=["is_complete", "winner"])
                    else:
                        bracket.save(update_fields=["is_complete"])
                    return
            
            viewset = BracketViewSet()

            with transaction.atomic():
                # Create the next round
                viewset._create_next_round(bracket)

                # Get the next round using the known number
                next_round = bracket.rounds.filter(
                    round_number=bracket.current_round + 1
                ).first()
                if not next_round:
                    logger.info(
                        f"No next round exists. Bracket {bracket.id} has likely finished."
                    )
                    return
                next_match = next_round.matches.first()

                # Get winners from the completed round
                winners = list(current_round.matches.values_list("winner", flat=True))

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
            matches_in_round = list(instance.round.matches.order_by("id"))
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
                type=Game.Type.LEAGUE,
                season=instance.bracket.season,
                league=(
                    instance.bracket.season.league if instance.bracket.season else None
                ),
                date=scheduled_datetime,
            )
            instance.game = game
            instance.save(update_fields=["game"])
            logger.info(
                f"Game created for match {instance.id} scheduled at {scheduled_datetime}"
            )
        except Exception as e:
            logger.error(f"Failed to create game for match {instance.id}: {str(e)}")


@receiver(pre_delete, sender=Bracket)
def delete_bracket_games(sender, instance, **kwargs):
    Game.objects.filter(bracket_match__bracket=instance).delete()
    logger.info(f"Deleted all games for bracket {instance.id}")
