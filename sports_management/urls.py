from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

def health_check(request):
    """Simple health check endpoint"""
    return JsonResponse({"status": "ok", "message": "Server is running"})

def root(request):
    return JsonResponse({"message": "Welcome to Sports Management API"})

urlpatterns = [
    path('', root),
    path('admin/', admin.site.urls),
    path('api/health/', health_check, name='health_check'),
    path('api/', include('users.urls')),
    path('api/', include('sports.urls')),
    path('api/', include('teams.urls')),
    path('api/', include('games.urls')),
    path('api/', include('leagues.urls')),
    path('api/', include('brackets.urls')),
    path('api/', include('trainings.urls')),
    path('api/', include('events.urls')),
    path('api/', include('facilities.urls')),
    path('api/', include('dashboard.urls')),
    path('api/chat/', include('chat.urls')),
    path('api/documents/', include('documents.urls')),
    path('api/', include('tournaments.urls')),
    path('api/notifications/', include('notifications.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
