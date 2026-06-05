from rest_framework.generics import RetrieveUpdateAPIView, GenericAPIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
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
from google.oauth2 import id_token
from google.auth.transport import requests

User = get_user_model()

from .serializers import (
    UserSerializer,
    UserProfileUpdateSerializer,
    LoginUserSerializer,
)

class UserInfoView(RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_object(self):
        return self.request.user
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return UserProfileUpdateSerializer
        return UserSerializer
    
    def update(self, request, *args, **kwargs):
        """Override update to handle partial updates properly"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        # Return the updated user data using UserSerializer
        return Response(UserSerializer(instance, context={'request': request}).data)
    
    def partial_update(self, request, *args, **kwargs):
        """Handle PATCH requests"""
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)


class LoginView(GenericAPIView):
    serializer_class = LoginUserSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data

        # Validate player/team constraints first
        try:
            # Only enforce this for player role
            if user.role == User.Role.PLAYER:
                # Check if player profile exists and has a team
                from teams.models import Player
                try:
                    player_profile = Player.objects.get(user=user)
                    if not player_profile.team:
                        return Response({
                            "error": "Player account has no team assigned. Contact your administrator."},
                            status=status.HTTP_403_FORBIDDEN
                        )
                except Player.DoesNotExist:
                    return Response({"error": "Player profile not found. Contact your administrator."}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            print(f"Login validation error: {e}")
            # Fall back to the standard login flow and let authentication proceed normally

        # Update last_login field manually since we're using custom JWT auth
        update_last_login(None, user)

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        
        response = Response(
            {
                "user": UserSerializer(user, context={'request': request}).data,
                "tokens": {
                    "access_token": access_token,
                    "refresh_token": str(refresh),
                },
            },
            status=status.HTTP_200_OK,
        )
        return response


class LogoutView(APIView):
    authentication_classes = [] 
    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get("refresh") or request.data.get("refresh_token")
        if refresh_token:
            try:
                # Blacklist the token if possible.
                RefreshToken(refresh_token).blacklist()
            except Exception as e:
                # Log the error but continue with logout flow
                print(f"Token blacklist error (might be expired): {str(e)}")

        response = Response(
            {"message": "Successfully logged out!"}, status=status.HTTP_200_OK
        )
        return response

class AppTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get("refresh") or request.data.get("refresh_token")
        if not refresh_token:
            return Response(
                {"error": "Refresh token not provided"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)
            response = Response(
                {"access_token": access_token},
                status=status.HTTP_200_OK,
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

GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID 

class GoogleOneTapLoginView(APIView):
    permission_classes = (AllowAny,) # Allow unauthenticated access for login/signup

    def post(self, request, *args, **kwargs):
        id_token_credential = request.data.get("credential") # Name from the Google response

        if not id_token_credential:
            return Response({"error": "Google ID Token not provided."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 1. Verify the Google ID Token
            # This is the crucial step where the token's authenticity is confirmed by Google's servers.
            # Allow 30 seconds of clock skew to handle minor time differences between servers
            google_user_data = id_token.verify_oauth2_token(
                id_token_credential, 
                requests.Request(), 
                GOOGLE_CLIENT_ID,
                clock_skew_in_seconds=30
            )

            # The 'aud' (audience) must match your client ID.
            if google_user_data['aud'] != GOOGLE_CLIENT_ID:
                raise ValueError('Audience mismatch.')
            
            email = google_user_data['email']
            first_name = google_user_data.get('given_name', '')
            last_name = google_user_data.get('family_name', '')
            
            print(f"Google login attempt for email: {email}")  # Debug log
            
            # 2. Only allow login for existing users - no auto-registration
            user = User.objects.filter(email=email).first()
            if not user:
                print(f"User not found for email: {email}")  # Debug log
                return Response(
                    {"error": "No account found with this email. Please contact an administrator to create your account."}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            # Update name if changed
            if user.first_name != first_name or user.last_name != last_name:
                user.first_name = first_name
                user.last_name = last_name
                user.save()

            # Additional validation: ensure Player has a team
            try:
                if user.role == User.Role.PLAYER:
                    from teams.models import Player
                    try:
                        player_profile = Player.objects.get(user=user)
                        if not player_profile.team:
                            return Response({"error": "Player account has no team assigned. Contact your administrator."}, status=status.HTTP_403_FORBIDDEN)
                    except Player.DoesNotExist:
                        return Response({"error": "Player profile not found. Contact your administrator."}, status=status.HTTP_403_FORBIDDEN)
            except Exception as e:
                print(f"Google OneTap validation error: {e}")

            # 3. Issue and Set Application's JWTs
            update_last_login(None, user) # Manually update last login

            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)
            
            response = Response(
                {
                    "user": UserSerializer(user, context={'request': request}).data,
                    "tokens": {
                        "access_token": access_token,
                        "refresh_token": str(refresh),
                    },
                },
                status=status.HTTP_200_OK,
            )
            return response
            
        except ValueError as e:
            # Handle invalid tokens, expired tokens, or other verification errors
            print(f"Google Token Verification Failed: {e}")
            return Response({"error": "Invalid Google login token."}, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            # Catch other potential errors
            print(f"Login processing error: {e}")
            return Response({"error": "An unexpected error occurred during login."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_admin_contact_info(request):
    """Get contact information for all admin users"""
    admins = User.objects.filter(role=User.Role.ADMIN, is_active=True)
    
    emails = [admin.email for admin in admins if admin.email]
    phone_numbers = [admin.phone_number for admin in admins if admin.phone_number]
    
    return Response({
        'emails': emails,
        'phone_numbers': phone_numbers
    }, status=status.HTTP_200_OK)

