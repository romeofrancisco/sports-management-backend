"""
ASGI config for sports_management project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')

# Initialize Django BEFORE importing routing modules
django.setup()

# Now safe to import after Django is initialized
from django.core.asgi import get_asgi_application
import chat.routing
import games.routing
from chat.middleware import JWTAuthMiddlewareStack

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddlewareStack(
        URLRouter(
            chat.routing.websocket_urlpatterns +
            games.routing.websocket_urlpatterns
        )
    ),
})
