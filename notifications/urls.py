from django.urls import path
from . import views

urlpatterns = [
    path('subscribe/', views.subscribe_to_push, name='subscribe_to_push'),
    path('logs/', views.get_notification_logs, name='notification_logs'),
    path('logs/<int:notification_id>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('logs/<int:notification_id>/delete/', views.delete_notification, name='delete_notification'),
    path('logs/mark-all-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('logs/delete-all/', views.delete_all_notifications, name='delete_all_notifications'),
    path('logs/unread-count/', views.get_unread_count, name='unread_notification_count'),
]
