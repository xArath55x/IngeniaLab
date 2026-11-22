from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("api/sesion/", views.session_info, name="session_info"),
    path("login/", views.AccountLoginView.as_view(), name="login"),
    path("logout/", views.AccountLogoutView.as_view(), name="logout"),
    path("registro/", views.signup, name="signup"),
]
