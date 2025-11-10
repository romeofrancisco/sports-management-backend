from rest_framework.generics import RetrieveUpdateAPIView, GenericAPIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.exceptions import InvalidToken
from datetime import timedelta, datetime, timezone
from django.contrib.auth.models import update_last_login
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.utils.encoding import force_str

User = get_user_model()

from .serializers import (
    UserSerializer,
    UserProfileUpdateSerializer,
    LoginUserSerializer,
)

# Central cookie settings to avoid repetition.
# Use Django settings to determine secure/samesite behavior.
# Note: modern browsers require SameSite=None to be paired with Secure=True.
COOKIE_SETTINGS = {
    "httponly": True,
    # Use secure cookies in production (SESSION_COOKIE_SECURE is set in settings.py)
    "secure": bool(getattr(settings, "SESSION_COOKIE_SECURE", False)),
    # If secure cookies are enabled, allow cross-site cookies (needed when frontend is on a different origin).
    # Otherwise fall back to Lax for local development where Secure cannot be used over HTTP.
    "samesite": "None" if getattr(settings, "SESSION_COOKIE_SECURE", False) else "Lax",
}

def set_auth_cookies(response, access_token, refresh_token):
    expiry = datetime.now(timezone.utc) + timedelta(days=30)
    response.set_cookie("access_token", access_token, expires=expiry, **COOKIE_SETTINGS)
    response.set_cookie("refresh_token", refresh_token, expires=expiry, **COOKIE_SETTINGS)


class UserInfoView(RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return UserProfileUpdateSerializer
        return UserSerializer


class LoginView(GenericAPIView):
    serializer_class = LoginUserSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data

        # Update last_login field manually since we're using custom JWT auth
        update_last_login(None, user)

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        
        # Build response with user data and set tokens as cookies.
        response = Response(UserSerializer(user, context={'request': request}).data, status=status.HTTP_200_OK)
        set_auth_cookies(response, access_token, str(refresh))
        return response


class LogoutView(APIView):
    authentication_classes = [] 
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get("refresh_token")
        if refresh_token:
            try:
                # Blacklist the token if possible.
                RefreshToken(refresh_token).blacklist()
            except Exception as e:
                # Log the error but continue with cookie deletion
                print(f"Token blacklist error (might be expired): {str(e)}")

        response = Response(
            {"message": "Successfully logged out!"}, status=status.HTTP_200_OK
        )
        # Delete cookies by setting them with max_age=0
        for cookie_name in ["access_token", "refresh_token"]:
            response.set_cookie(
                key=cookie_name,
                value='',
                max_age=0,
                **COOKIE_SETTINGS
            )
        return response

class CookieTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get("refresh_token")
        if not refresh_token:
            return Response(
                {"error": "Refresh token not provided"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)
            response = Response(
                {"message": "Access token refreshed successfully"},
                status=status.HTTP_200_OK,
            )
            response.set_cookie(
                key="access_token", value=access_token, **COOKIE_SETTINGS
            )
            return response
        except InvalidToken:
            return Response(
                {"error": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED
            )

   

@api_view(["POST"])
def set_password(request):
    uid = request.data.get("uid")
    token = request.data.get("token")
    password = request.data.get("password")

    try:
        uid = urlsafe_base64_decode(uid).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return Response({"error": "Invalid link"}, status=status.HTTP_400_BAD_REQUEST)

    if not default_token_generator.check_token(user, token):
        return Response({"error": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(password)
    user.save()
    return Response({"message": "Password has been set successfully"})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    user = request.user
    old_password = request.data.get('old_password')
    new_password = request.data.get('new_password')

    if not user.check_password(old_password):
        return Response({'error': 'Incorrect current password'}, status=400)

    user.set_password(new_password)
    user.save()
    update_session_auth_hash(request, user)  # keep session active
    return Response({'message': 'Password changed successfully'})

@api_view(["POST"])
@permission_classes([AllowAny])
def forgot_password(request):
    """Send password reset email"""
    email = request.data.get("email")

    if not email:
        return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({"error": "No user found with that email"}, status=status.HTTP_404_NOT_FOUND)

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}"

    # Render HTML email
    html_content = render_to_string("emails/reset_password_email.html", {
        "user": user,
        "reset_link": reset_link,
    })
    text_content = f"Hi {user.first_name}, use the link below to reset your password:\n{reset_link}"

    msg = EmailMultiAlternatives(
        "Password Reset Request",
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send()

    return Response({"message": "Password reset email sent!"}, status=status.HTTP_200_OK)

@api_view(["POST"])
@permission_classes([AllowAny])
def reset_password(request):
    """Verify token and set new password"""
    uidb64 = request.data.get("uid")
    token = request.data.get("token")
    password = request.data.get("password")

    if not uidb64 or not token or not password:
        return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return Response({"error": "Invalid user"}, status=status.HTTP_400_BAD_REQUEST)

    if not default_token_generator.check_token(user, token):
        return Response({"error": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(password)
    user.save()
    return Response({"message": "Password has been reset successfully"}, status=status.HTTP_200_OK)

