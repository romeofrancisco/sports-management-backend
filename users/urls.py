from django.urls import path
from .views import UserInfoView, LoginView, LogoutView, CookieTokenRefreshView

urlpatterns = [ 
    # Auth api
    path("get-user/", UserInfoView.as_view(), name="get-user-info"),
    path("login/", LoginView.as_view(), name="user-login"),
    path("logout/", LogoutView.as_view(), name="user-logout"),
    path("refresh/", CookieTokenRefreshView.as_view(), name="token-refresh"),
]