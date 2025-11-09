from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django import forms
from .models import Usuario
from .forms import AbogadoCrearForm, UsuarioEditForm, AccountEmailForm

# =========================
# Auth
# =========================
def es_admin(user):
    return user.is_authenticated and (getattr(user, "es_administrador", False) or user.is_superuser)



def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if getattr(user, "rol", None) == "DESHABILITADO":
                messages.error(request, "Tu cuenta está deshabilitada. Contacta al administrador.")
                return redirect("accounts:login")
            login(request, user)
            messages.success(request, f"Bienvenido, {user.username}")
            return redirect("core:home")
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")
    return render(request, "accounts/login.html")

@login_required
def logout_view(request):
    logout(request)
    return redirect("accounts:login")


# =========================
# Helpers de acceso (solo admin / superuser)
# =========================

Usuario = get_user_model()

def _es_admin(user):
    # permite superuser o usuarios con rol ADMINISTRADOR
    return bool(user.is_authenticated and (user.is_superuser or getattr(user, "rol", "") == "ADMINISTRADOR"))


# =========================
# Gestión de Abogados (solo admin)
# =========================

@login_required
@user_passes_test(es_admin)
def crear_abogado(request):
    if request.method == "POST":
        form = AbogadoCrearForm(request.POST)
        if form.is_valid():
            u = form.save(commit=False)
            u.rol = Usuario.Rol.ABOGADO
            u.is_active = True
            u.set_password(form.cleaned_data["password1"])
            u.save()
            messages.success(request, "Abogado creado correctamente.")
            return redirect("accounts:listar_abogados")
    else:
        form = AbogadoCrearForm()
    return render(request, "accounts/crear_abogado.html", {"form": form})

@login_required
@user_passes_test(_es_admin)
def listar_abogados(request):
    abogados = Usuario.objects.filter(rol="ABOGADO").order_by("first_name", "last_name", "username")
    return render(request, "accounts/listar_abogados.html", {"abogados": abogados})



@login_required
@user_passes_test(es_admin)
def editar_abogado(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)

    # Impedir editar a otro administrador
    if usuario.rol == Usuario.Rol.ADMINISTRADOR:
        messages.warning(request, "No puedes editar a otro administrador.")
        return redirect("accounts:listar_abogados")

    if request.method == "POST":
        form = UsuarioEditForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil actualizado correctamente.")
            return redirect("accounts:listar_abogados")
    else:
        form = UsuarioEditForm(instance=usuario)

    return render(request, "accounts/editar_abogado.html", {"form": form, "usuario": usuario})



@login_required
def detalle_cuenta(request):
    # Forms base
    email_form = AccountEmailForm(instance=request.user)
    password_form = PasswordChangeForm(user=request.user)

    # ---- Asegurar estilos y UX en widgets ----
    # Email
    email_form.fields["email"].widget.attrs.update({
        "class": "form-control",
        "autocomplete": "email",
        "placeholder": "tu@correo.cl"
    })
    # Passwords
    for name, attrs in {
        "old_password":     {"id": "id_old_password",  "autocomplete": "current-password", "placeholder": "••••••••"},
        "new_password1":    {"id": "id_new_password1", "autocomplete": "new-password",     "placeholder": "••••••••"},
        "new_password2":    {"id": "id_new_password2", "autocomplete": "new-password",     "placeholder": "••••••••"},
    }.items():
        password_form.fields[name].widget.attrs.update({"class": "form-control", **attrs})

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "update_email":
            email_form = AccountEmailForm(request.POST, instance=request.user)
            # re-aplicar atributos por si el form se re-renderiza con errores
            email_form.fields["email"].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "tu@correo.cl"
            })
            if email_form.is_valid():
                email_form.save()
                messages.success(request, "Correo actualizado correctamente.")
                return redirect("accounts:detalle_cuenta")
            messages.error(request, "Revisa los errores en el formulario de correo.")

        elif action == "change_password":
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            # re-aplicar atributos
            for name, attrs in {
                "old_password":  {"id": "id_old_password",  "autocomplete": "current-password", "placeholder": "••••••••"},
                "new_password1": {"id": "id_new_password1", "autocomplete": "new-password",     "placeholder": "••••••••"},
                "new_password2": {"id": "id_new_password2", "autocomplete": "new-password",     "placeholder": "••••••••"},
            }.items():
                password_form.fields[name].widget.attrs.update({"class": "form-control", **attrs})

            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)  # mantiene la sesión
                messages.success(request, "Contraseña cambiada correctamente.")
                return redirect("accounts:detalle_cuenta")
            messages.error(request, "No se pudo cambiar la contraseña. Revisa los errores.")

        else:
            messages.error(request, "Acción no válida.")

    # Help text (validadores de contraseña)
    password_help = password_form.fields["new_password1"].help_text

    return render(request, "accounts/detalle_cuenta.html", {
        "email_form": email_form,
        "password_form": password_form,
        "password_help": password_help,
    })



