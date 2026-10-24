from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render

from .forms import LoginForm, SignupForm


class StudentLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class StudentLogoutView(LogoutView):
    pass


def signup(request):
    if request.user.is_authenticated:
        return redirect("progress:dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Bienvenido(a) a IngeniaLab, {user.first_name}.")
        return redirect("progress:dashboard")
    return render(request, "accounts/signup.html", {"form": form})


# ACT-211C: refresco explícito de identidad/CSRF tras reautenticarse en otra pestaña.
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache


@never_cache
@require_GET
def session_info(request):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "session_expired", "message": "Inicia sesión para reintentar."}, status=401)
    return JsonResponse({"ok": True, "user_id": str(request.user.pk), "csrf_token": get_token(request)})


def csrf_failure(request, reason=""):
    if "/api/" in request.path:
        return JsonResponse({"ok": False, "error": "csrf_failed", "message": "El token de sesión cambió. Actualiza la sesión antes de reintentar."}, status=403)
    from django.views.csrf import csrf_failure as default_failure
    return default_failure(request, reason=reason)
