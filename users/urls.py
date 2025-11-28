from django.urls import path
from .views import (
    UserInfoView,
    LoginView,
    LogoutView,
    CookieTokenRefreshView,
    GoogleOneTapLoginView,
    change_password,
    set_password,
    reset_password,
    forgot_password,
)

urlpatterns = [
    # Auth api
    path("get-user/", UserInfoView.as_view(), name="get-user-info"),
    path("login/", LoginView.as_view(), name="user-login"),
    path("logout/", LogoutView.as_view(), name="user-logout"),
    path("refresh/", CookieTokenRefreshView.as_view(), name="token-refresh"),
    path("set-password/", set_password, name="set-password"),
    path("change-password/", change_password, name="change-password"),
    path("reset-password/", reset_password, name="reset-password"),
    path("forgot-password/", forgot_password, name="forgot-password"),
    
    path('google-signin/', GoogleOneTapLoginView.as_view(), name='google-signin'),
]
