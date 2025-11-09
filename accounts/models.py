from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator
from django.conf import settings

class Usuario(AbstractUser):
    username = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Nombre de usuario",
        help_text="Requerido. 150 caracteres o menos. Solo letras, números y los símbolos @ . + - _",
        validators=[
            RegexValidator(
                regex=r'^[\w.@+-]+$',
                message="Solo se permiten letras, números y los símbolos @ . + - _"
            ),
        ],
        error_messages={
            "unique": "Ya existe un usuario con ese nombre de usuario.",
        },
    )

    class Rol(models.TextChoices):
        ADMINISTRADOR = "ADMINISTRADOR", "Administrador"
        ABOGADO = "ABOGADO", "Abogado"
        DESHABILITADO = "DESHABILITADO", "Deshabilitado"

    rol = models.CharField(
        max_length=20,
        choices=Rol.choices,
        default=Rol.ABOGADO,
        verbose_name="Rol",
        help_text="Define el rol del usuario dentro del sistema (Administrador, Abogado o Deshabilitado)."
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
        help_text="Indica si este usuario puede iniciar sesión. Desmarca esta opción en lugar de eliminar la cuenta."
    )
    is_staff = models.BooleanField(
        default=False,
        verbose_name="Acceso al panel de administración",
        help_text="Permite que el usuario acceda al panel de administración de Django."
    )
    is_superuser = models.BooleanField(
        default=False,
        verbose_name="Superusuario",
        help_text="Otorga todos los permisos sin necesidad de asignarlos explícitamente."
    )

    email = models.EmailField(
        verbose_name="Correo electrónico",
        help_text="Dirección de correo electrónico de contacto del usuario.",
        blank=True
    )

    first_name = models.CharField(
        max_length=150,
        verbose_name="Nombre",
        help_text="Nombre del usuario.",
        blank=True
    )

    last_name = models.CharField(
        max_length=150,
        verbose_name="Apellidos",
        help_text="Apellidos del usuario.",
        blank=True
    )

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"

    @property
    def es_administrador(self):
        return self.rol == self.Rol.ADMINISTRADOR

    @property
    def es_abogado(self):
        return self.rol == self.Rol.ABOGADO


class GoogleCalendarCredential(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="gcal")
    # Guardamos el JSON completo de las credenciales (access_token, refresh_token, expiry, etc.)
    credentials_json = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GoogleCalendarCredential<{self.user.username}>"
    

class GoogleOAuthToken(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_token")
    credentials_json = models.TextField()  # json del token (access + refresh + scopes)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GoogleToken({self.user_id})"    