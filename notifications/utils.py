# notifications/utils.py
import json
from django.conf import settings
from pywebpush import webpush, WebPushException
from push_notifications.models import WebPushDevice
from teams.models import Team
from users.models import User

def send_web_push(sender, team_id, message_text, message_id, team_name):
    """
    Send push notifications for a chat message to all team members except the sender.

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
        return

    # Get all users in the team except the sender
    team_users = []
    if team.head_coach:
        team_users.append(team.head_coach.user)
    if team.assistant_coach:
        team_users.append(team.assistant_coach.user)
    team_users.extend([player.user for player in team.players.all()])
    team_users = [u for u in team_users if u != sender]

    # Get their WebPushDevices
    devices = WebPushDevice.objects.filter(user__in=team_users)

    if not devices:
        return

    # Get VAPID keys
    push_settings = settings.PUSH_NOTIFICATIONS_SETTINGS
    vapid_private_key = push_settings.get("VAPID_PRIVATE_KEY")
    vapid_public_key = push_settings.get("VAPID_PUBLIC_KEY")
    vapid_claims = push_settings.get("WP_CLAIMS", {"sub": "mailto:your-email@example.com"})

    if not vapid_private_key or not vapid_public_key:
        print("VAPID keys are not configured. Skipping push notifications.")
        return

    payload = {
        "title": f"New message in {team_name}",
        "body": f"{sender.get_full_name() or sender.username}: {message_text[:100]}{'...' if len(message_text) > 100 else ''}",
        "icon": "/perpetual_logo_small.png",
        "badge": "/icon-192.png",
        "data": {
            "team_id": team_id,
            "message_id": message_id,
            "url": f"/chat/{team_id}"
        }
    }

    for device in devices:
        try:
            subscription_info = {
                "endpoint": device.registration_id,
                "keys": {
                    "p256dh": device.p256dh,
                    "auth": device.auth
                }
            }

            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims
            )
            print(f"✓ Notification sent to device {device.id}")

        except WebPushException as ex:
            print(f"✗ WebPush error for device {device.id}: {ex}")
            # Remove invalid subscriptions
            if ex.response and ex.response.status_code in [404, 410]:
                print(f"Removing invalid device {device.id}")
                device.delete()
        except Exception as e:
            print(f"✗ Error sending to device {device.id}: {e}")
