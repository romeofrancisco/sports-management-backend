from django.conf import settings
from teams.models import Team
import firebase_admin
from firebase_admin import credentials, messaging
from .models import FCMDevice

# Initialize Firebase Admin SDK
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_KEY)
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Admin initialization error: {e}")


def send_game_notification(game, creator=None):
    """
    Send FCM push notifications to all players and coaches of both teams when a new game is scheduled.

    Args:
        game: The Game instance that was created
        creator: The user who created the game (optional, to exclude from notifications)
    """
    try:
        home_team = game.home_team
        away_team = game.away_team
        
        if not home_team or not away_team:
            return
    except Exception as e:
        return

    # Get all users from both teams (players and coaches)
    team_users = []
    
    for team in [home_team, away_team]:
        # Add coaches
        if team.head_coach and team.head_coach.user:
            team_users.append(team.head_coach.user)
        if team.assistant_coach and team.assistant_coach.user:
            team_users.append(team.assistant_coach.user)
        # Add players
        team_users.extend([player.user for player in team.players.all() if player.user])

    # Remove duplicates and exclude creator
    team_users = list(set([u for u in team_users if u and u != creator]))

    if not team_users:
        return

    # Get FCM tokens for these users
    devices = FCMDevice.objects.filter(user__in=team_users)

    if not devices.exists():
        return

    # Prepare the notification payload
    game_date = game.date.strftime("%B %d, %Y") if game.date else "TBD"
    game_time = game.time.strftime("%I:%M %p") if game.time else "TBD"
    
    # Determine game type label and click action
    game_type_label = "Game"
    click_action = f"/games?gameId={game.id}"
    
    if game.type == "league" and game.league and game.season:
        game_type_label = "League Game"
        click_action = f"/leagues/{game.league.id}/seasons/{game.season.id}/games?gameId={game.id}"
    elif game.type == "tournament" and game.tournament:
        game_type_label = "Tournament Game"
        click_action = f"/tournaments/{game.tournament.id}/games?gameId={game.id}"
    elif game.type == "practice":
        game_type_label = "Practice Game"
        click_action = f"/games?gameId={game.id}"
    
    notification_title = f"New {game_type_label} Scheduled"
    notification_body = f"{home_team.name} vs {away_team.name} on {game_date} at {game_time}"


    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "game",
                    "game_id": str(game.id),
                    "game_type": str(game.type),
                    "home_team_id": str(home_team.id),
                    "away_team_id": str(away_team.id),
                    "home_team_name": home_team.name,
                    "away_team_name": away_team.name,
                    "click_action": click_action
                },
                token=device.fcm_token,
            )

            response = messaging.send(message)
            success_count += 1

        except Exception as e:
            error_msg = str(e)
            if 'unregistered' in error_msg.lower() or 'invalid' in error_msg.lower() or 'auth error' in error_msg.lower():
                failed_tokens.append(device.fcm_token)

    # Remove invalid tokens
    if failed_tokens:
        FCMDevice.objects.filter(fcm_token__in=failed_tokens).delete()


def send_bulk_game_notifications(games, creator=None):
    """
    Send FCM push notifications for multiple games at once (e.g., round robin creation).
    Sends a summary notification instead of one per game to avoid notification spam.

    Args:
        games: List of Game instances that were created
        creator: The user who created the games (optional, to exclude from notifications)
    """
    if not games:
        return
    
    # Collect all unique teams and users
    all_teams = set()
    for game in games:
        if game.home_team:
            all_teams.add(game.home_team)
        if game.away_team:
            all_teams.add(game.away_team)
    
    if not all_teams:
        return

    # Get all users from all teams
    team_users = []
    for team in all_teams:
        if team.head_coach and team.head_coach.user:
            team_users.append(team.head_coach.user)
        if team.assistant_coach and team.assistant_coach.user:
            team_users.append(team.assistant_coach.user)
        team_users.extend([player.user for player in team.players.all() if player.user])

    # Remove duplicates and exclude creator
    team_users = list(set([u for u in team_users if u and u != creator]))

    if not team_users:
        return

    # Get FCM tokens for these users
    devices = FCMDevice.objects.filter(user__in=team_users)

    if not devices.exists():
        return

    # Determine the context (tournament or league)
    first_game = games[0]
    context_name = ""
    game_type_label = "Games"
    click_action = "/games"
    
    if first_game.tournament:
        context_name = first_game.tournament.name
        game_type_label = "Tournament Games"
        click_action = f"/tournaments/{first_game.tournament.id}/games"
    elif first_game.season and first_game.league:
        context_name = f"{first_game.league.name} - {first_game.season.name}"
        game_type_label = "League Games"
        click_action = f"/leagues/{first_game.league.id}/seasons/{first_game.season.id}/games"
    
    notification_title = f"{len(games)} New {game_type_label} Scheduled"
    notification_body = f"New games have been scheduled for {context_name}. Check the schedule for details."

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "bulk_games",
                    "games_count": str(len(games)),
                    "game_type": str(first_game.type),
                    "context_name": context_name,
                    "click_action": click_action
                },
                token=device.fcm_token,
            )

            response = messaging.send(message)
            success_count += 1

        except Exception as e:
            error_msg = str(e)
            if 'unregistered' in error_msg.lower() or 'invalid' in error_msg.lower() or 'auth error' in error_msg.lower():
                failed_tokens.append(device.fcm_token)

    # Remove invalid tokens
    if failed_tokens:
        FCMDevice.objects.filter(fcm_token__in=failed_tokens).delete()


def send_fcm_notification(sender, team_id, message_text, message_id, team_name):
    """
    Send FCM push notifications for a chat message to all team members except the sender.

    Args:
        sender: The user who sent the message
        team_id: ID of the team
        message_text: The message content
        message_id: ID of the message
        team_name: Name of the team
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        print(f"Team {team_id} not found")
        return

    # Get all users in the team except the sender
    team_users = []
    if team.head_coach:
        team_users.append(team.head_coach.user)
    if team.assistant_coach:
        team_users.append(team.assistant_coach.user)
    team_users.extend([player.user for player in team.players.all()])
    team_users = [u for u in team_users if u != sender]

    # Get their FCM tokens
    devices = FCMDevice.objects.filter(user__in=team_users)

    if not devices.exists():
        print(f"No FCM devices found for team {team_id}")
        return

    # Prepare the notification payload
    sender_name = sender.get_full_name() or sender.username
    notification_body = f"{sender_name}: {message_text[:100]}{'...' if len(message_text) > 100 else ''}"

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []
    
    for device in devices:
        try:
            # Include notification field to ensure delivery on all platforms
            # Send data-only message - service worker will create the notification
            # This prevents FCM from auto-showing a notification
            message = messaging.Message(
                data={
                    "title": f"New message in {team_name}",
                    "body": notification_body,
                    "team_id": str(team_id),
                    "message_id": str(message_id),
                    "sender_id": str(sender.id),
                    "sender_name": sender_name,
                    "click_action": f"/chat/team/{team_id}"
                },
                token=device.fcm_token,
            )
            
            # Send the message
            response = messaging.send(message)
            success_count += 1
            print(f"✓ FCM notification sent to user {device.user.id}: {response}")
            
        except Exception as e:
            error_msg = str(e)
            print(f"✗ Error sending to user {device.user.id}: {error_msg}")
            # Remove token if it's invalid (unregistered, invalid, etc.)
            if 'unregistered' in error_msg.lower() or 'invalid' in error_msg.lower():
                failed_tokens.append(device.fcm_token)
    
    print(f"✓ Successfully sent {success_count} FCM notifications")
    
    # Remove invalid tokens
    if failed_tokens:
        FCMDevice.objects.filter(fcm_token__in=failed_tokens).delete()
        print(f"Removed {len(failed_tokens)} invalid FCM tokens")


def send_training_session_notification(training_session, creator=None):
    """
    Send FCM push notifications to all players in a team when a new training session is created.

    Args:
        training_session: The TrainingSession instance that was created
        creator: The user who created the training session (optional, to exclude from notifications)
    """
    print(f"[Training Notification] Starting notification for session: {training_session.title}")
    
    try:
        team = training_session.team
        if not team:
            print("[Training Notification] No team associated with training session")
            return
    except Exception as e:
        print(f"[Training Notification] Error getting team: {e}")
        return

    print(f"[Training Notification] Team: {team.name} (ID: {team.id})")

    # Get all players in the team
    team_players = team.players.all()
    
    if not team_players.exists():
        print(f"[Training Notification] No players in team {team.name}")
        return

    print(f"[Training Notification] Found {team_players.count()} players in team")

    # Get user objects for all players, excluding the creator
    player_users = [player.user for player in team_players if player.user and player.user != creator]

    if not player_users:
        print(f"[Training Notification] No player users to notify for team {team.name}")
        return

    print(f"[Training Notification] Will notify {len(player_users)} players (excluding creator)")

    # Get FCM tokens for these users
    devices = FCMDevice.objects.filter(user__in=player_users)

    if not devices.exists():
        print(f"[Training Notification] No FCM devices found for players in team {team.name}")
        return

    print(f"[Training Notification] Found {devices.count()} FCM devices")

    # Prepare the notification payload
    session_date = training_session.date.strftime("%B %d, %Y") if training_session.date else "TBD"
    session_time = training_session.start_time.strftime("%I:%M %p") if training_session.start_time else "TBD"
    
    notification_title = f"New Training Session: {training_session.title}"
    notification_body = f"Scheduled for {session_date} at {session_time} - {training_session.location or 'Location TBD'}"

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "training_session",
                    "session_id": str(training_session.session_id),
                    "team_id": str(team.id),
                    "team_name": team.name,
                    "click_action": f"/"
                },
                token=device.fcm_token,
            )

            response = messaging.send(message)
            success_count += 1
            print(f"✓ Training notification sent to user {device.user.id}: {response}")

        except Exception as e:
            error_msg = str(e)
            print(f"✗ Error sending training notification to user {device.user.id}: {error_msg}")
            if 'unregistered' in error_msg.lower() or 'invalid' in error_msg.lower():
                failed_tokens.append(device.fcm_token)

    print(f"✓ Successfully sent {success_count} training session notifications")

    # Remove invalid tokens
    if failed_tokens:
        FCMDevice.objects.filter(fcm_token__in=failed_tokens).delete()
        print(f"Removed {len(failed_tokens)} invalid FCM tokens")


def send_event_notification(event, creator=None):
    """
    Send FCM push notifications for a new event.
    
    - If admin creates the event: notify all coaches
    - If coach creates the event: notify all players on teams they coach

    Args:
        event: The Event instance that was created
        creator: The user who created the event
    """
    from users.models import User
    from teams.models import Coach
    from django.db import models as db_models
    
    if not creator:
        return
    
    target_users = []
    
    # Determine who to notify based on creator's role
    if creator.role == User.Role.ADMIN or creator.is_superuser:
        # Admin created the event - notify all coaches
        coaches = Coach.objects.select_related('user').all()
        target_users = [coach.user for coach in coaches if coach.user and coach.user != creator]
    elif creator.role == User.Role.COACH or hasattr(creator, 'coach_profile'):
        # Coach created the event - notify all players on their teams
        try:
            coach_profile = creator.coach_profile
            # Get all teams where this coach is head or assistant coach
            coached_teams = Team.objects.filter(
                db_models.Q(head_coach=coach_profile) | db_models.Q(assistant_coach=coach_profile)
            )
            # Get all players from these teams
            for team in coached_teams:
                for player in team.players.all():
                    if player.user and player.user != creator:
                        target_users.append(player.user)
        except Exception:
            return
    
    # Remove duplicates
    target_users = list(set(target_users))
    
    if not target_users:
        return

    # Get FCM tokens for these users
    devices = FCMDevice.objects.filter(user__in=target_users)

    if not devices.exists():
        return

    # Prepare the notification payload
    event_date = event.startDate.strftime("%B %d, %Y") if event.startDate else "TBD"
    event_time = event.startDate.strftime("%I:%M %p") if event.startDate else "TBD"
    
    notification_title = f"New Event: {event.title}"
    notification_body = f"Scheduled for {event_date} at {event_time}"
    if event.description:
        notification_body += f" - {event.description[:50]}{'...' if len(event.description) > 50 else ''}"

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "event",
                    "event_id": str(event.id),
                    "event_title": event.title,
                    "click_action": "/calendar"
                },
                token=device.fcm_token,
            )

            response = messaging.send(message)
            success_count += 1

        except Exception as e:
            error_msg = str(e)
            if 'unregistered' in error_msg.lower() or 'invalid' in error_msg.lower() or 'auth error' in error_msg.lower():
                failed_tokens.append(device.fcm_token)

    # Remove invalid tokens
    if failed_tokens:
        FCMDevice.objects.filter(fcm_token__in=failed_tokens).delete()