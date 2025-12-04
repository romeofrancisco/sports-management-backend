# notifications/views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from push_notifications.models import WebPushDevice
from .models import NotificationLog


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_notification_logs(request):
    """
    Get notification logs for the authenticated user.
    
    Query params:
    - notification_type: Filter by type (event, league_game, tournament_game, practice_game, training, facility, etc.)
    - is_read: Filter by read status (true/false)
    - page: Page number
    - page_size: Number of items per page (default 20, max 100)
    """
    user = request.user
    queryset = NotificationLog.objects.filter(recipient=user)
    
    # Filter by notification type (supports comma-separated values for multiple types)
    notification_type = request.query_params.get('notification_type')
    if notification_type:
        types = [t.strip() for t in notification_type.split(',')]
        queryset = queryset.filter(notification_type__in=types)
    
    # Filter by read status
    is_read = request.query_params.get('is_read')
    if is_read is not None:
        is_read_bool = is_read.lower() in ('true', '1', 'yes')
        queryset = queryset.filter(is_read=is_read_bool)
    
    # Paginate
    paginator = NotificationPagination()
    page = paginator.paginate_queryset(queryset, request)
    
    # Serialize
    notifications_data = [
        {
            'id': notif.id,
            'notification_type': notif.notification_type,
            'action_type': notif.action_type,
            'title': notif.title,
            'body': notif.body,
            'related_object_id': notif.related_object_id,
            'related_object_type': notif.related_object_type,
            'click_action': notif.click_action,
            'is_read': notif.is_read,
            'created_at': notif.created_at.isoformat(),
        }
        for notif in page
    ]
    
    return paginator.get_paginated_response(notifications_data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_notification_read(request, notification_id):
    """Mark a specific notification as read."""
    user = request.user
    
    try:
        notification = NotificationLog.objects.get(id=notification_id, recipient=user)
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response({'status': 'Notification marked as read'})
    except NotificationLog.DoesNotExist:
        return Response({'error': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read(request):
    """Mark all notifications for the user as read."""
    user = request.user
    
    updated_count = NotificationLog.objects.filter(recipient=user, is_read=False).update(is_read=True)
    
    return Response({
        'status': 'All notifications marked as read',
        'updated_count': updated_count
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_unread_count(request):
    """Get the count of unread notifications for the user."""
    user = request.user
    
    unread_count = NotificationLog.objects.filter(recipient=user, is_read=False).count()
    
    return Response({'unread_count': unread_count})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_notification(request, notification_id):
    """Delete a specific notification."""
    user = request.user
    
    try:
        notification = NotificationLog.objects.get(id=notification_id, recipient=user)
        notification.delete()
        return Response({'status': 'Notification deleted'})
    except NotificationLog.DoesNotExist:
        return Response({'error': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_all_notifications(request):
    """Delete all notifications for the user."""
    user = request.user
    
    deleted_count, _ = NotificationLog.objects.filter(recipient=user).delete()
    
    return Response({
        'status': 'All notifications deleted',
        'deleted_count': deleted_count
    })
