from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.db.models import Prefetch
from cases.models import Caso

from .models import Cliente
from .forms import ClienteForm

@login_required
def editar_cliente(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == "POST":
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, f"Cliente '{cliente.nombre_completo}' actualizado.")
            # Si aún no tienes 'clients:detalle', redirige a listar:
            return redirect(reverse("clients:listar"))
            # o si ya existe detalle:
            # return redirect(reverse("clients:detalle", args=[cliente.pk]))
        else:
            messages.error(request, "Corrige los errores del formulario.")
    else:
        form = ClienteForm(instance=cliente)
    return render(request, "clients/editar.html", {"form": form, "cliente": cliente})

@login_required
def listar_clientes(request):
    """
    Muestra la lista de clientes.
    Si el usuario es administrador (propiedad es_administrador=True),
    ve todos los clientes; en el futuro se podrá filtrar solo los propios.
    """
    if getattr(request.user, "es_administrador", False):
        qs = Cliente.objects.all().order_by("-creado_en")
    else:
        qs = Cliente.objects.all().order_by("-creado_en")
        # TODO: filtrar luego por clientes asociados al abogado logueado

    return render(request, "clients/listar.html", {"clientes": qs})


# === Crear nuevo cliente ===
@login_required
def crear_cliente(request):
    """
    Permite crear un nuevo cliente mediante el formulario ClienteForm.
    """
    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            cliente = form.save()
            messages.success(request, f"Cliente '{cliente.nombre_completo}' creado correctamente.")
            return redirect(reverse("clients:listar"))
        else:
            messages.error(request, "Por favor corrige los errores del formulario.")
    else:
        form = ClienteForm()

    return render(request, "clients/crear.html", {"form": form})


@login_required
def detalle_cliente(request, pk):
    qs_casos = (Caso.objects
                .select_related("abogado_responsable", "cliente")
                .order_by("-creado_en"))

    cliente = get_object_or_404(
        Cliente.objects.prefetch_related(Prefetch("casos", queryset=qs_casos)),
        pk=pk
    )

    # Marcar a cuáles puede acceder el usuario actual
    es_admin = request.user.is_superuser or getattr(request.user, "rol", "") == "ADMINISTRADOR"
    if es_admin:
        accesibles = {c.id for c in cliente.casos.all()}
    else:
        accesibles = {c.id for c in cliente.casos.all() if c.abogado_responsable_id == request.user.id}

    return render(request, "clients/detalle.html", {
        "cliente": cliente,
        "casos": cliente.casos.all(),  
        "accesibles": accesibles,    
    })