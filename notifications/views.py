# notifications/views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from push_notifications.models import WebPushDevice

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def subscribe_to_push(request):
    subscription_data = request.data.get('subscription')
    user = request.user

    if not subscription_data:
        return Response({'error': 'Subscription required'}, status=400)

    device, created = WebPushDevice.objects.get_or_create(
        user=user,
        defaults={
            'registration_id': subscription_data.get('endpoint'),
            'p256dh': subscription_data.get('keys', {}).get('p256dh'),
            'auth': subscription_data.get('keys', {}).get('auth'),
            'browser': 'CHROME',
        }
    )

    if not created:
        device.registration_id = subscription_data.get('endpoint')
        device.p256dh = subscription_data.get('keys', {}).get('p256dh')
        device.auth = subscription_data.get('keys', {}).get('auth')
        device.save()

    return Response({'status': 'Subscribed successfully'})
