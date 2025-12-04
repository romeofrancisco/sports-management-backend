from django.conf import settings
from teams.models import Team
import firebase_admin
from firebase_admin import credentials, messaging
from .models import FCMDevice, NotificationLog

# Initialize Firebase Admin SDK
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_KEY)
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Admin initialization error: {e}")


def log_notification(recipient, notification_type, action_type, title, body, related_object_id=None, related_object_type=None, click_action=None):
    """
    Create a notification log entry for a recipient.
    
    Args:
        recipient: The User who received the notification
        notification_type: Type of notification (from NotificationLog.NotificationType)
        action_type: Action type (from NotificationLog.ActionType)
        title: Notification title
        body: Notification body
        related_object_id: ID of the related object (game, event, etc.)
        related_object_type: Type name of the related object
        click_action: URL to navigate to when notification is clicked
    """
    try:
        NotificationLog.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            action_type=action_type,
            title=title,
            body=body,
            related_object_id=related_object_id,
            related_object_type=related_object_type,
            click_action=click_action
        )
    except Exception as e:
        print(f"Error logging notification: {e}")


def get_frontend_url():
    """Get the frontend URL from settings, defaulting to production URL."""
    url = getattr(settings, 'FRONTEND_URL', None)
    
    # Default to production URL if not set or empty
    if not url:
        return 'https://sports-management-frontend.vercel.app'
    
    url = url.strip()
    
    # For localhost, keep http (FCM doesn't require https for localhost)
    if 'localhost' in url or '127.0.0.1' in url:
        # Remove trailing slash and return as-is
        return url.rstrip('/')
    
    # For production, ensure URL starts with https://
    if not url.startswith('https://'):
        if url.startswith('http://'):
            url = url.replace('http://', 'https://', 1)
        else:
            url = f'https://{url}'
    
    # Remove trailing slash
    return url.rstrip('/')


def send_game_notification(game, creator=None, is_update=False):
    """
    Send FCM push notifications to all players and coaches of both teams when a game is scheduled or updated.

    Args:
        game: The Game instance that was created or updated
        creator: The user who created/updated the game (optional, to exclude from notifications)
        is_update: Boolean indicating if this is an update notification
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

    # Prepare the notification payload
    game_date = game.date.strftime("%B %d, %Y") if game.date else "TBD"
    game_time = game.time.strftime("%I:%M %p") if game.time else "TBD"
    
    # Determine game type label and click action
    frontend_url = get_frontend_url()
    game_type_label = "Game"
    click_action = f"{frontend_url}/games?gameId={game.id}"
    
    if game.type == "league" and game.league and game.season:
        game_type_label = "League Game"
        click_action = f"{frontend_url}/leagues/{game.league.id}/seasons/{game.season.id}/games?gameId={game.id}"
    elif game.type == "tournament" and game.tournament:
        game_type_label = "Tournament Game"
        click_action = f"{frontend_url}/tournaments/{game.tournament.id}/games?gameId={game.id}"
    elif game.type == "practice":
        game_type_label = "Practice Game"
        click_action = f"{frontend_url}/games?gameId={game.id}"
    
    action_word = "Updated" if is_update else "New"
    notification_title = f"{action_word} {game_type_label} Scheduled"
    notification_body = f"{home_team.name} vs {away_team.name} on {game_date} at {game_time}"

    # Determine notification type
    if game.type == "league":
        notif_type = NotificationLog.NotificationType.LEAGUE_GAME
    elif game.type == "tournament":
        notif_type = NotificationLog.NotificationType.TOURNAMENT_GAME
    else:
        notif_type = NotificationLog.NotificationType.PRACTICE_GAME

    # Log notifications for ALL users (regardless of FCM device registration)
    for user in team_users:
        log_notification(
            recipient=user,
            notification_type=notif_type,
            action_type=NotificationLog.ActionType.UPDATED if is_update else NotificationLog.ActionType.CREATED,
            title=notification_title,
            body=notification_body,
            related_object_id=game.id,
            related_object_type='Game',
            click_action=click_action
        )

    # Get FCM tokens for these users
    devices = FCMDevice.objects.filter(user__in=team_users)

    if not devices.exists():
        return

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            # Use data-only message - service worker will handle notification display
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "game",
                    "is_update": str(is_update).lower(),
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


def send_bulk_game_notifications(games, creator=None, is_update=False):
    """
    Send FCM push notifications for multiple games at once (e.g., round robin creation).
    Sends a summary notification instead of one per game to avoid notification spam.

    Args:
        games: List of Game instances that were created or updated
        creator: The user who created/updated the games (optional, to exclude from notifications)
        is_update: Boolean indicating if this is an update notification
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

    # Determine the context (tournament or league)
    first_game = games[0]
    frontend_url = get_frontend_url()
    context_name = ""
    game_type_label = "Games"
    click_action = f"{frontend_url}/games"
    
    if first_game.tournament:
        context_name = first_game.tournament.name
        game_type_label = "Tournament Games"
        click_action = f"{frontend_url}/tournaments/{first_game.tournament.id}/games"
    elif first_game.season and first_game.league:
        context_name = f"{first_game.league.name} - {first_game.season.name}"
        game_type_label = "League Games"
        click_action = f"{frontend_url}/leagues/{first_game.league.id}/seasons/{first_game.season.id}/games"
    
    action_word = "Updated" if is_update else "New"
    notification_title = f"{len(games)} {action_word} {game_type_label} Scheduled"
    notification_body = f"{'Games have been updated' if is_update else 'New games have been scheduled'} for {context_name}. Check the schedule for details."

    # Log notifications for ALL users (regardless of FCM device registration)
    for user in team_users:
        log_notification(
            recipient=user,
            notification_type=NotificationLog.NotificationType.BULK_GAMES,
            action_type=NotificationLog.ActionType.UPDATED if is_update else NotificationLog.ActionType.CREATED,
            title=notification_title,
            body=notification_body,
            related_object_id=first_game.id,
            related_object_type='BulkGames',
            click_action=click_action
        )

    # Get FCM tokens for these users
    devices = FCMDevice.objects.filter(user__in=team_users)

    if not devices.exists():
        return

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            # Use data-only message - service worker will handle notification display
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "bulk_games",
                    "is_update": str(is_update).lower(),
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
    Also includes admins who can view all team chats.

    Args:
        sender: The user who sent the message
        team_id: ID of the team
        message_text: The message content
        message_id: ID of the message
        team_name: Name of the team
    """
    from users.models import User  # Import here to avoid circular imports
    
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        print(f"Team {team_id} not found")
        return

    # Get all users in the team except the sender
    team_users = []
    if team.head_coach and team.head_coach.user:
        team_users.append(team.head_coach.user)
    if team.assistant_coach and team.assistant_coach.user:
        team_users.append(team.assistant_coach.user)
    team_users.extend([player.user for player in team.players.all() if player.user])
    
    # Also include admins (they can view all team chats)
    admin_users = User.objects.filter(is_superuser=True)
    team_users.extend(list(admin_users))
    
    # Remove duplicates and exclude sender
    team_users = list(set([u for u in team_users if u and u != sender]))

    # Get their FCM tokens
    devices = FCMDevice.objects.filter(user__in=team_users)

    if not devices.exists():
        print(f"No FCM devices found for team {team_id}")
        return

    # Prepare the notification payload
    sender_name = sender.get_full_name() or sender.username
    notification_body = f"{sender_name}: {message_text[:100]}{'...' if len(message_text) > 100 else ''}"
    notification_title = f"New message in {team_name}"
    frontend_url = get_frontend_url()
    click_action = f"{frontend_url}/chat/team/{team_id}"
    
    print(f"[Chat Notification] Frontend URL: {frontend_url}, Click action: {click_action}")

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []
    
    for device in devices:
        try:
            # Use data-only message - service worker will handle notification display
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "chat",
                    "team_id": str(team_id),
                    "message_id": str(message_id),
                    "sender_id": str(sender.id),
                    "sender_name": sender_name,
                    "click_action": click_action
                },
                token=device.fcm_token,
            )
            
            # Send the message
            response = messaging.send(message)
            success_count += 1
            print(f"✓ FCM notification sent to user {device.user.id}: {response}")
            
        except Exception as e:
            error_msg = str(e).lower()
            print(f"✗ Error sending to user {device.user.id}: {e}")
            # Remove token if it's invalid (various error types)
            if any(err in error_msg for err in ['unregistered', 'invalid', 'not found', 'not a valid fcm', 'auth error']):
                failed_tokens.append(device.fcm_token)
    
    print(f"✓ Successfully sent {success_count} FCM notifications")
    
    # Remove invalid tokens
    if failed_tokens:
        deleted_count = FCMDevice.objects.filter(fcm_token__in=failed_tokens).delete()[0]
        print(f"🗑️ Removed {deleted_count} invalid FCM tokens")


def send_training_session_notification(training_session, creator=None, is_update=False):
    """
    Send FCM push notifications to all players in a team when a training session is created or updated.

    Args:
        training_session: The TrainingSession instance that was created or updated
        creator: The user who created/updated the training session (optional, to exclude from notifications)
        is_update: Boolean indicating if this is an update notification
    """
    action_word = "Updated" if is_update else "Starting"
    print(f"[Training Notification] {action_word} notification for session: {training_session.title}")
    
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

    # Prepare the notification payload
    session_date = training_session.date.strftime("%B %d, %Y") if training_session.date else "TBD"
    session_time = training_session.start_time.strftime("%I:%M %p") if training_session.start_time else "TBD"
    
    action_word = "Updated" if is_update else "New"
    notification_title = f"{action_word} Training Session: {training_session.title}"
    notification_body = f"Scheduled for {session_date} at {session_time} - {training_session.location or 'Location TBD'}"
    frontend_url = get_frontend_url()
    click_action = f"{frontend_url}/"

    # Log notifications for ALL users (regardless of FCM device registration)
    for user in player_users:
        log_notification(
            recipient=user,
            notification_type=NotificationLog.NotificationType.TRAINING,
            action_type=NotificationLog.ActionType.UPDATED if is_update else NotificationLog.ActionType.CREATED,
            title=notification_title,
            body=notification_body,
            related_object_id=training_session.session_id,
            related_object_type='TrainingSession',
            click_action=click_action
        )

    # Get FCM tokens for these users
    devices = FCMDevice.objects.filter(user__in=player_users)

    if not devices.exists():
        print(f"[Training Notification] No FCM devices found for players in team {team.name}")
        return

    print(f"[Training Notification] Found {devices.count()} FCM devices")

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            # Use data-only message - service worker will handle notification display
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "training_session",
                    "is_update": str(is_update).lower(),
                    "session_id": str(training_session.session_id),
                    "team_id": str(team.id),
                    "team_name": team.name,
                    "click_action": click_action
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


def send_event_notification(event, creator=None, is_update=False):
    """
    Send FCM push notifications for a new or updated event.
    
    - If admin creates/updates the event: notify all coaches
    - If coach creates/updates the event: notify all players on teams they coach

    Args:
        event: The Event instance that was created or updated
        creator: The user who created/updated the event
        is_update: Boolean indicating if this is an update notification
    """
    from users.models import User
    from teams.models import Coach
    from django.db import models as db_models
    
    if not creator:
        return
    
    target_users = []
    
    # Determine who to notify based on creator's role
    if creator.role == User.Role.ADMIN or creator.is_superuser:
        # Admin created the event - notify all coaches and players
        users = User.objects.all()
        target_users = [user for user in users if user != creator]
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

    # Prepare the notification payload
    event_date = event.startDate.strftime("%B %d, %Y") if event.startDate else "TBD"
    event_time = event.startDate.strftime("%I:%M %p") if event.startDate else "TBD"
    
    action_word = "Updated" if is_update else "New"
    notification_title = f"{action_word} Event: {event.title}"
    notification_body = f"Scheduled for {event_date} at {event_time}"
    if event.description:
        notification_body += f" - {event.description[:50]}{'...' if len(event.description) > 50 else ''}"
    frontend_url = get_frontend_url()
    click_action = f"{frontend_url}/calendar"

    # Log notifications for ALL users (regardless of FCM device registration)
    for user in target_users:
        log_notification(
            recipient=user,
            notification_type=NotificationLog.NotificationType.EVENT,
            action_type=NotificationLog.ActionType.UPDATED if is_update else NotificationLog.ActionType.CREATED,
            title=notification_title,
            body=notification_body,
            related_object_id=event.id,
            related_object_type='Event',
            click_action=click_action
        )

    # Get FCM tokens for these users
    devices = FCMDevice.objects.filter(user__in=target_users)

    if not devices.exists():
        return

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            # Use data-only message - service worker will handle notification display
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "event",
                    "is_update": str(is_update).lower(),
                    "event_id": str(event.id),
                    "event_title": event.title,
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


def send_reservation_created_notification(reservation, is_update=False):
    """
    Send FCM push notification to all admins when a reservation is created or updated.

    Args:
        reservation: The Reservation instance that was created or updated
        is_update: Boolean indicating if this is an update notification
    """
    from users.models import User
    
    # Get all admin users
    admin_users = list(User.objects.filter(role=User.Role.ADMIN))
    
    if not admin_users:
        return

    # Prepare the notification payload
    coach_name = reservation.coach.get_full_name() if reservation.coach else "Unknown"
    facility_name = reservation.facility.name if reservation.facility else "Unknown Facility"
    reservation_date = reservation.start_datetime.strftime("%B %d, %Y") if reservation.start_datetime else "TBD"
    reservation_time = reservation.start_datetime.strftime("%I:%M %p") if reservation.start_datetime else "TBD"
    
    action_word = "Updated" if is_update else "New"
    notification_title = f"{action_word} Facility Reservation Request"
    notification_body = f"{coach_name} {'updated their request for' if is_update else 'requested'} {facility_name} on {reservation_date} at {reservation_time}"
    frontend_url = get_frontend_url()
    click_action = f"{frontend_url}/facility-reservation/approvals"

    # Log notifications for ALL admin users (regardless of FCM device registration)
    for user in admin_users:
        log_notification(
            recipient=user,
            notification_type=NotificationLog.NotificationType.FACILITY,
            action_type=NotificationLog.ActionType.UPDATED if is_update else NotificationLog.ActionType.CREATED,
            title=notification_title,
            body=notification_body,
            related_object_id=reservation.id,
            related_object_type='Reservation',
            click_action=click_action
        )

    # Get FCM tokens for admin users
    devices = FCMDevice.objects.filter(user__in=admin_users)

    if not devices.exists():
        return

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            # Use data-only message - service worker will handle notification display
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "reservation_request",
                    "is_update": str(is_update).lower(),
                    "reservation_id": str(reservation.id),
                    "facility_id": str(reservation.facility.id) if reservation.facility else "",
                    "facility_name": facility_name,
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


def send_reservation_status_notification(reservation, new_status):
    """
    Send FCM push notification to the coach when their reservation is approved or rejected.

    Args:
        reservation: The Reservation instance that was updated
        new_status: The new status ('approved' or 'rejected')
    """
    if not reservation.coach:
        return

    # Prepare the notification payload
    facility_name = reservation.facility.name if reservation.facility else "Unknown Facility"
    reservation_date = reservation.start_datetime.strftime("%B %d, %Y") if reservation.start_datetime else "TBD"
    reservation_time = reservation.start_datetime.strftime("%I:%M %p") if reservation.start_datetime else "TBD"
    
    status_text = "Approved" if new_status == "approved" else "Rejected"
    status_emoji = "✅" if new_status == "approved" else "❌"
    
    notification_title = f"Reservation {status_text} {status_emoji}"
    notification_body = f"Your reservation for {facility_name} on {reservation_date} at {reservation_time} has been {new_status}"
    frontend_url = get_frontend_url()
    click_action = f"{frontend_url}/facility-reservation/approvals"

    # Log notification for the coach (regardless of FCM device registration)
    log_notification(
        recipient=reservation.coach,
        notification_type=NotificationLog.NotificationType.FACILITY_STATUS,
        action_type=NotificationLog.ActionType.STATUS_CHANGE,
        title=notification_title,
        body=notification_body,
        related_object_id=reservation.id,
        related_object_type='Reservation',
        click_action=click_action
    )

    # Get FCM tokens for the coach
    devices = FCMDevice.objects.filter(user=reservation.coach)

    if not devices.exists():
        return

    # Send individual messages to each token
    success_count = 0
    failed_tokens = []

    for device in devices:
        try:
            # Use data-only message - service worker will handle notification display
            message = messaging.Message(
                data={
                    "title": notification_title,
                    "body": notification_body,
                    "type": "reservation_status",
                    "reservation_id": str(reservation.id),
                    "facility_id": str(reservation.facility.id) if reservation.facility else "",
                    "facility_name": facility_name,
                    "status": new_status,
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