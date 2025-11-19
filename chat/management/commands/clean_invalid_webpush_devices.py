import json
import traceback
from django.core.management.base import BaseCommand
from push_notifications.models import WebPushDevice
from django.conf import settings
from pywebpush import webpush, WebPushException

class Command(BaseCommand):
    help = "Deactivate invalid WebPushDevice entries to prevent 401 Unauthorized errors"

    def handle(self, *args, **options):
        devices = WebPushDevice.objects.filter(active=True)
        vapid_private_key = settings.PUSH_NOTIFICATIONS_SETTINGS.get('VAPID_PRIVATE_KEY')
        vapid_claims = settings.PUSH_NOTIFICATIONS_SETTINGS.get('WP_CLAIMS', {"sub": "mailto:romeofrancisco.works@gmail.com"})

        if not vapid_private_key:
            self.stdout.write(self.style.ERROR("VAPID_PRIVATE_KEY not configured!"))
            return

        for device in devices:
            subscription_info = {
                "endpoint": device.registration_id,
                "keys": {
                    "p256dh": device.p256dh,
                    "auth": device.auth
                }
            }

            try:
                # Send a lightweight test push (empty payload)
                webpush(
                    subscription_info=subscription_info,
                    data=json.dumps({"test": True}),
                    vapid_private_key=vapid_private_key,
                    vapid_claims=vapid_claims
                )
                self.stdout.write(self.style.SUCCESS(f"Device {device.id} OK"))

            except WebPushException as ex:
                status_code = ex.response.status_code if ex.response else None
                if status_code in [401, 404, 410]:
                    device.active = False
                    device.save()
                    self.stdout.write(self.style.WARNING(f"Deactivated device {device.id} (status {status_code})"))
                else:
                    self.stdout.write(self.style.ERROR(f"Failed for device {device.id}: {ex}"))
                    traceback.print_exc()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Unexpected error for device {device.id}: {e}"))
                traceback.print_exc()
