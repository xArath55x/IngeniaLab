from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import AccountRole


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Usuario o contraseña incorrectos. Verifica tus datos e intenta de nuevo.",
        "inactive": "Esta cuenta está inactiva.",
    }


class SignupForm(UserCreationForm):
    role = forms.ChoiceField(label="Tipo de cuenta", choices=[("", "Selecciona una opción"), *AccountRole.Role.choices])
    first_name = forms.CharField(label="Nombre completo", max_length=150)
    email = forms.EmailField(label="Correo institucional")
    field_order = ("role", "username", "first_name", "email", "password1", "password2")

    class Meta:
        model = User
        fields = ("username", "first_name", "email")
        labels = {"username": "Matrícula o usuario"}
