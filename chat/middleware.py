from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from urllib.parse import parse_qs
import jwt
from django.conf import settings

User = get_user_model()

@database_sync_to_async
def get_user_from_token(token):
    """
    Get user from JWT token
    """
    try:
        # Decode the token
        access_token = AccessToken(token)
        user_id = access_token['user_id']
        user = User.objects.get(id=user_id)
        return user
    except (InvalidToken, TokenError, User.DoesNotExist):
        return AnonymousUser()

class JWTAuthMiddleware:
    """
    Custom middleware to authenticate WebSocket connections using JWT tokens
    """
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        # Only apply to WebSocket connections
        if scope["type"] == "websocket":
            # Try to get token from query parameters first
            query_string = scope.get("query_string", b"").decode()
            query_params = parse_qs(query_string)
            
            token = None            # Check for token in query parameters
            if "token" in query_params:
                token = query_params["token"][0]
            
            # Check for token in headers (for Authorization header)
            if not token:
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode()
                if auth_header.startswith("Bearer "):
                    token = auth_header.split(" ")[1]
            
            if token:
                user = await get_user_from_token(token)
                scope["user"] = user
            else:
                scope["user"] = AnonymousUser()
        
        return await self.inner(scope, receive, send)

def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
