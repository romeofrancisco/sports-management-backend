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

# Track games created in bulk for round robin notifications
_bulk_games_cache = {}


def _advance_bye_winner(current_match, bye_winner):
    """
    Recursively advance a bye winner through subsequent matches.
    This handles the case where a team gets a bye and their next opponent
    also comes from a double default or bye situation.
    """
    if not current_match.next_match:
        return
    
    next_match = BracketMatch.objects.select_for_update().get(id=current_match.next_match.id)
    
    # Find parent matches
    parent_matches = list(BracketMatch.objects.filter(
        next_match=next_match
    ).order_by('id'))
    
    # Determine position and assign team
    parent_ids = [pm.id for pm in parent_matches]
    try:
        position = parent_ids.index(current_match.id)
        if position == 0:
            if next_match.home_team != bye_winner:
                next_match.home_team = bye_winner
                next_match.save(update_fields=["home_team"])
        else:
            if next_match.away_team != bye_winner:
                next_match.away_team = bye_winner
                next_match.save(update_fields=["away_team"])
    except ValueError:
        pass
    
    # Check if the other parent match had a double default or no winner
    other_parent = None
    for pm in parent_matches:
        if pm.id != current_match.id:
            other_parent = pm
            break
    
    if other_parent:
        # Check if other parent's game was a double default
        other_had_double_default = (
            other_parent.game and 
            other_parent.game.status == Game.Status.DOUBLE_DEFAULT
        )
        # Or if other parent has no winner and its game is finished
        other_finished_no_winner = (
            other_parent.game and 
            other_parent.game.status in [Game.Status.DOUBLE_DEFAULT] and
            other_parent.winner is None
        )
        
        if other_had_double_default or other_finished_no_winner:
            # Bye winner advances through this match too
            logger.info(f"Bye winner {bye_winner.name} also advances through match {next_match.id} (opponent had double default)")
            next_match.winner = bye_winner
            next_match.save(update_fields=["winner"])
            
            # Mark the game as default win if scheduled
            if next_match.game and next_match.game.status == Game.Status.SCHEDULED:
                bye_game = next_match.game
                if bye_game.home_team == bye_winner:
                    bye_game.status = Game.Status.DEFAULT_HOME_WIN
                else:
                    bye_game.status = Game.Status.DEFAULT_AWAY_WIN
                bye_game.winner_team = bye_winner
                bye_game.save(update_fields=["status", "winner_team"])
                logger.info(f"Marked game {bye_game.id} as default win for {bye_winner.name}")
            
            # Continue advancing
            _advance_bye_winner(next_match, bye_winner)


def _send_game_notification_async(game):
    """Helper to send game notification in a separate thread to avoid blocking"""
    try:
        from notifications.utils import send_game_notification
        send_game_notification(game)
    except Exception as e:
        logger.error(f"Failed to send game notification: {e}")


def _send_bulk_game_notifications_async(games):
    """Helper to send bulk game notifications in a separate thread to avoid blocking"""
    try:
        from notifications.utils import send_bulk_game_notifications
        send_bulk_game_notifications(games)
    except Exception as e:
        logger.error(f"Failed to send bulk game notifications: {e}")


# Game statuses that count as "finished" for bracket advancement
FINISHED_GAME_STATUSES = [
    Game.Status.COMPLETED,
    Game.Status.DEFAULT_HOME_WIN,
    Game.Status.DEFAULT_AWAY_WIN,
    Game.Status.DOUBLE_DEFAULT,
    Game.Status.FORFEITED,
]


@receiver(post_save, sender=Game)
def update_match_winner(sender, instance, **kwargs):
    # Only process finished games that are part of a tournament or league
    if instance.status not in FINISHED_GAME_STATUSES or instance.type == Game.Type.PRACTICE:
        return

    try:
        # Safely check if the game has a bracket_match
        if not hasattr(instance, 'bracket_match') or not instance.bracket_match:
            return

        match = instance.bracket_match
        winner = instance.winner
        is_double_default = instance.status == Game.Status.DOUBLE_DEFAULT

        # Handle double default - special case where there's no winner
        if is_double_default:
            logger.info(f"Processing double default for game {instance.id}, match {match.id}")
            
            with transaction.atomic():
                # Mark match as having no winner (both teams eliminated)
                match.winner = None
                match.save(update_fields=["winner"])
                
                # Handle advancement: the next match gets a "bye" situation
                # The opponent in the next match will need to wait for the other feeder match
                if match.next_match:
                    next_match = BracketMatch.objects.select_for_update().get(id=match.next_match.id)
                    
                    # Find all parent matches that feed into this next_match
                    parent_matches = list(BracketMatch.objects.filter(
                        next_match=next_match
                    ).order_by('id'))
                    
                    # Check if the OTHER parent match has a winner
                    other_parent = None
                    for pm in parent_matches:
                        if pm.id != match.id:
                            other_parent = pm
                            break
                    
                    if other_parent and other_parent.winner:
                        bye_winner = other_parent.winner
                        # The other match already has a winner - they get a bye (advance without playing)
                        logger.info(f"Double default in match {match.id}: {bye_winner.name} advances via bye from match {next_match.id}")
                        
                        # Ensure the winner is in the next match
                        if not next_match.home_team:
                            next_match.home_team = bye_winner
                        if not next_match.away_team and next_match.home_team != bye_winner:
                            next_match.away_team = bye_winner
                        
                        # Mark the next match with the winner directly (bye)
                        next_match.winner = bye_winner
                        next_match.save()
                        
                        # If this next match has a scheduled game, mark it as default win
                        if next_match.game and next_match.game.status == Game.Status.SCHEDULED:
                            bye_game = next_match.game
                            if bye_game.home_team == bye_winner:
                                bye_game.status = Game.Status.DEFAULT_HOME_WIN
                            else:
                                bye_game.status = Game.Status.DEFAULT_AWAY_WIN
                            bye_game.winner_team = bye_winner
                            bye_game.save(update_fields=["status", "winner_team"])
                            logger.info(f"Marked game {bye_game.id} as default win for {bye_winner.name} (bye due to double default)")
                        
                        # Recursively advance if the next_match also has a next_match
                        _advance_bye_winner(next_match, bye_winner)
                    else:
                        logger.info(f"Double default in match {match.id}: waiting for other parent match to complete")
                
                # For double elimination: both teams are eliminated, no one goes to loser bracket
                if match.next_loser_match:
                    logger.info(f"Double default in match {match.id}: no team advances to loser bracket (both eliminated)")
                    # We don't send anyone to loser bracket
                
            return  # Exit early for double default

        # If winner hasn't changed, no need to proceed
        if match.winner == winner:
            return

        # Use transaction to ensure atomicity
        with transaction.atomic():
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

            # Update the next match if it exists (advance winner)
            if match.next_match:
                # Refresh from DB with select_for_update to lock the row
                next_match = BracketMatch.objects.select_for_update().get(id=match.next_match.id)
                update_fields = []
                
                # FIXED: Determine slot based on parent match order
                # Find all parent matches that feed into this next_match
                parent_matches = BracketMatch.objects.filter(
                    next_match=next_match
                ).order_by('id')  # Order by ID for consistent positioning
                
                parent_match_ids = list(parent_matches.values_list('id', flat=True))
                
                # Check if the sibling match had a double default (no winner but game is finished)
                sibling_had_double_default = False
                for pm in parent_matches:
                    if pm.id != match.id and pm.game:
                        if pm.game.status == Game.Status.DOUBLE_DEFAULT:
                            sibling_had_double_default = True
                            logger.info(f"Sibling match {pm.id} had double default - {winner.name} gets a bye")
                            break
                
                try:
                    # Find this match's position among parent matches
                    position = parent_match_ids.index(match.id)
                    
                    if position == 0:
                        # First parent match → home team slot
                        if next_match.home_team and next_match.home_team.id != winner.id:
                            logger.warning(f"Overwriting home team {next_match.home_team.name} with {winner.name} in match {next_match.id}")
                        next_match.home_team = winner
                        update_fields.append("home_team")
                        logger.info(f"Advanced winner {winner.name} to next match {next_match.id} as home team (position {position})")
                    elif position == 1:
                        # Second parent match → away team slot
                        if next_match.away_team and next_match.away_team.id != winner.id:
                            logger.warning(f"Overwriting away team {next_match.away_team.name} with {winner.name} in match {next_match.id}")
                        next_match.away_team = winner
                        update_fields.append("away_team")
                        logger.info(f"Advanced winner {winner.name} to next match {next_match.id} as away team (position {position})")
                    else:
                        logger.error(f"Unexpected position {position} for match {match.id} feeding into {next_match.id}")
                        
                except ValueError:
                    # Fallback to old logic if position can't be determined
                    logger.warning(f"Could not determine position for match {match.id}, using fallback logic")
                    if not next_match.home_team:
                        next_match.home_team = winner
                        update_fields.append("home_team")
                        logger.info(f"Advanced winner {winner.name} to next match {next_match.id} as home team (fallback)")
                    elif not next_match.away_team:
                        next_match.away_team = winner
                        update_fields.append("away_team")
                        logger.info(f"Advanced winner {winner.name} to next match {next_match.id} as away team (fallback)")
                    else:
                        logger.error(f"Both slots filled in next match {next_match.id}. Cannot assign {winner.name}")
                
                if update_fields:
                    next_match.save(update_fields=update_fields)
                
                # If sibling had double default, this team gets a bye (auto-advance)
                if sibling_had_double_default:
                    logger.info(f"Granting bye to {winner.name} - advancing directly through match {next_match.id}")
                    next_match.winner = winner
                    next_match.save(update_fields=["winner"])
                    
                    # If the next match has a scheduled game, mark it as default win for the bye team
                    if next_match.game and next_match.game.status == Game.Status.SCHEDULED:
                        bye_game = next_match.game
                        # Determine which team gets the default win
                        if bye_game.home_team == winner:
                            bye_game.status = Game.Status.DEFAULT_HOME_WIN
                        else:
                            bye_game.status = Game.Status.DEFAULT_AWAY_WIN
                        bye_game.winner_team = winner
                        bye_game.save(update_fields=["status", "winner_team"])
                        logger.info(f"Marked game {bye_game.id} as default win for {winner.name} (bye)")
                    
                    # Recursively advance if the next_match also has opponents from double defaults
                    _advance_bye_winner(next_match, winner)
            
            # Handle double elimination: move loser to lower bracket
            if match.next_loser_match and winner:
                # Determine the loser
                loser = None
                if match.home_team and match.away_team:
                    loser = match.away_team if winner == match.home_team else match.home_team
                
                if loser:
                    # Refresh from DB with select_for_update to lock the row
                    loser_match = BracketMatch.objects.select_for_update().get(id=match.next_loser_match.id)
                    update_fields = []
                    
                    # CRITICAL FIX: Check if this match receives teams from BOTH sources
                    # (winners via next_match AND losers via next_loser_match)
                    has_winner_parents = BracketMatch.objects.filter(next_match=loser_match).exists()
                    has_loser_parents = BracketMatch.objects.filter(next_loser_match=loser_match).count() > 0
                    
                    if has_winner_parents and has_loser_parents:
                        # This match receives from both sources!
                        # Strategy: winners from next_match → home_team, losers → away_team
                        # Find all loser parent matches
                        loser_parents = BracketMatch.objects.filter(
                            next_loser_match=loser_match
                        ).order_by('id')
                        
                        loser_parent_ids = list(loser_parents.values_list('id', flat=True))
                        
                        try:
                            position = loser_parent_ids.index(match.id)
                            
                            # Losers always go to away_team when there are also winner parents
                            if position == 0:
                                # First loser parent → away_team
                                if loser_match.away_team and loser_match.away_team.id != loser.id:
                                    logger.warning(f"Overwriting away team {loser_match.away_team.name} with {loser.name} in loser match {loser_match.id}")
                                loser_match.away_team = loser
                                update_fields.append("away_team")
                                logger.info(f"Moved loser {loser.name} to lower bracket match {loser_match.id} as away team (mixed source, position {position})")
                            else:
                                # Additional losers beyond first one - this shouldn't happen in normal double elim
                                logger.error(f"Unexpected loser position {position} for match {match.id} feeding into {loser_match.id}")
                        except ValueError:
                            logger.error(f"Could not find match {match.id} in loser parents for {loser_match.id}")
                    else:
                        # Standard case: only one source type
                        # Find all parent matches that feed into this next_loser_match
                        parent_matches = BracketMatch.objects.filter(
                            next_loser_match=loser_match
                        ).order_by('id')
                        
                        parent_match_ids = list(parent_matches.values_list('id', flat=True))
                        
                        try:
                            # Find this match's position among parent matches
                            position = parent_match_ids.index(match.id)
                            
                            if position == 0:
                                # First parent match → home team slot
                                if loser_match.home_team and loser_match.home_team.id != loser.id:
                                    logger.warning(f"Overwriting home team {loser_match.home_team.name} with {loser.name} in loser match {loser_match.id}")
                                loser_match.home_team = loser
                                update_fields.append("home_team")
                                logger.info(f"Moved loser {loser.name} to lower bracket match {loser_match.id} as home team (position {position})")
                            elif position == 1:
                                # Second parent match → away team slot
                                if loser_match.away_team and loser_match.away_team.id != loser.id:
                                    logger.warning(f"Overwriting away team {loser_match.away_team.name} with {loser.name} in loser match {loser_match.id}")
                                loser_match.away_team = loser
                                update_fields.append("away_team")
                                logger.info(f"Moved loser {loser.name} to lower bracket match {loser_match.id} as away team (position {position})")
                            else:
                                logger.error(f"Unexpected position {position} for match {match.id} feeding into loser match {loser_match.id}")
                                
                        except ValueError:
                            # Fallback to old logic if position can't be determined
                            logger.warning(f"Could not determine position for match {match.id}, using fallback logic")
                            if not loser_match.home_team:
                                loser_match.home_team = loser
                                update_fields.append("home_team")
                                logger.info(f"Moved loser {loser.name} to lower bracket match {loser_match.id} as home team (fallback)")
                            elif not loser_match.away_team:
                                loser_match.away_team = loser
                                update_fields.append("away_team")
                                logger.info(f"Moved loser {loser.name} to lower bracket match {loser_match.id} as away team (fallback)")
                            else:
                                logger.error(f"Both slots filled in loser match {loser_match.id}. Cannot assign {loser.name}")
                    
                    if update_fields:
                        loser_match.save(update_fields=update_fields)

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
                teams_count = bracket.season.teams.count() if bracket.season else bracket.tournament.teams.count()
                expected_rounds = teams_count - 1 if teams_count > 1 else 0
                
                # If we've completed all rounds for round robin, mark as complete and exit
                if current_round_number >= expected_rounds:
                    logger.info(f"Round robin tournament completed with {current_round_number} rounds.")
                    bracket.is_complete = True
                    
                    # Determine the bracket winner using standings logic with proper tiebreakers
                    # This handles ties by using match points, win ratio, and point differential
                    if bracket.season:
                        standings = bracket.season.standings()
                    elif bracket.tournament:
                        standings = bracket.tournament.standings()
                    else:
                        standings = []
                    
                    # Get the top team from standings (already sorted with tiebreakers)
                    if standings and len(standings) > 0:
                        winner_team_id = standings[0]['team_id']
                        bracket.winner_id = winner_team_id
                        bracket.save(update_fields=["is_complete", "winner"])
                        logger.info(f"Round robin winner: Team ID {winner_team_id}")
                    else:
                        bracket.save(update_fields=["is_complete"])
                        logger.warning(f"No standings found for round robin bracket {bracket.id}")
                    return
            
            # Handle double elimination completion - check if this is the grand final
            if bracket.elimination_type == 'double':
                # Check if there's a next round
                has_next_round = bracket.rounds.filter(
                    round_number=current_round_number + 1
                ).exists()
                
                if not has_next_round:
                    # This is the grand final (last round) - tournament is complete
                    logger.info(f"Double elimination grand final completed for bracket {bracket.id}")
                    bracket.is_complete = True
                    
                    # The winner of the grand final (current round) is the bracket winner
                    grand_final_match = current_round.matches.first()
                    if grand_final_match and grand_final_match.winner:
                        bracket.winner = grand_final_match.winner
                        bracket.save(update_fields=["is_complete", "winner"])
                        logger.info(f"Bracket {bracket.id} winner is {grand_final_match.winner.name}")
                    else:
                        bracket.save(update_fields=["is_complete"])
                        logger.warning(f"Grand final completed but no winner found for bracket {bracket.id}")
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

                # Get all matches from current round in order
                current_matches = list(current_round.matches.order_by('id'))
                next_matches = list(next_round.matches.order_by('id'))

                # Pair winners from current round matches to next round matches
                for i, next_match in enumerate(next_matches):
                    # Each next round match gets winners from two current round matches
                    first_match_idx = i * 2
                    second_match_idx = i * 2 + 1
                    
                    update_fields = []
                    
                    # Assign home team from first match winner
                    if first_match_idx < len(current_matches) and current_matches[first_match_idx].winner:
                        if not next_match.home_team:
                            next_match.home_team = current_matches[first_match_idx].winner
                            update_fields.append("home_team")
                    
                    # Assign away team from second match winner
                    if second_match_idx < len(current_matches) and current_matches[second_match_idx].winner:
                        if not next_match.away_team:
                            next_match.away_team = current_matches[second_match_idx].winner
                            update_fields.append("away_team")
                    
                    if update_fields:
                        next_match.save(update_fields=update_fields)
                        logger.info(f"Assigned teams to next round match {next_match.id}: "
                                  f"Home: {next_match.home_team}, Away: {next_match.away_team}")

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
            # Get start date from either season or tournament
            if instance.bracket.season:
                start_date = instance.bracket.season.start_date
                if not start_date:
                    raise ValueError("Season start date is not defined.")
                sport = instance.home_team.sport
                league = instance.bracket.season.league
                season = instance.bracket.season
                game_type = Game.Type.LEAGUE
            elif instance.bracket.tournament:
                start_date = instance.bracket.tournament.start_date
                if not start_date:
                    raise ValueError("Tournament start date is not defined.")
                sport = instance.bracket.tournament.sport
                league = None
                season = None
                game_type = Game.Type.TOURNAMENT
            else:
                raise ValueError("Bracket is not associated with a season or tournament")

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

            scheduled_datetime = start_date + round_offset + time_offset

            game = Game.objects.create(
                sport=sport,
                home_team=instance.home_team,
                away_team=instance.away_team,
                status=Game.Status.SCHEDULED,
                type=game_type,
                season=season,
                league=league,
                tournament=instance.bracket.tournament if instance.bracket.tournament else None,
                date=scheduled_datetime,
            )
            instance.game = game
            instance.save(update_fields=["game"])
            logger.info(
                f"Game {game.id} created for match {instance.id} (Round {instance.round.round_number}) scheduled at {scheduled_datetime}"
            )
            
            # Track games for bulk notification (round robin creates multiple at once)
            bracket_id = instance.bracket.id
            if bracket_id not in _bulk_games_cache:
                _bulk_games_cache[bracket_id] = []
            _bulk_games_cache[bracket_id].append(game)
            
        except Exception as e:
            logger.error(f"Failed to create game for match {instance.id}: {str(e)}")


@receiver(pre_delete, sender=Bracket)
def delete_bracket_games(sender, instance, **kwargs):
    Game.objects.filter(bracket_match__bracket=instance).delete()
    logger.info(f"Deleted all games for bracket {instance.id}")
