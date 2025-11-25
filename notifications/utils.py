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