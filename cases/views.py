from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django import forms
from .models import Caso
from clients.models import Cliente
from django.contrib import messages
from django.urls import reverse
from django.shortcuts import render
from .permissions import is_admin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views import View
from .forms import CasoForm
from django.utils import timezone
from django.views.generic import DetailView


@login_required
def listar_casos(request):
    u = request.user
    if getattr(u, "es_administrador", False):
        qs = Caso.objects.select_related("cliente", "abogado_responsable")
    else:
        qs = (Caso.objects.filter(abogado_responsable=u) |
              Caso.objects.filter(accesos__abogado=u)).select_related("cliente", "abogado_responsable")
    qs = qs.distinct().order_by("-creado_en")
    return render(request, "cases/listar.html", {"casos": qs})

@login_required
def detalle_caso(request, pk: int):
    caso = get_object_or_404(Caso.objects.select_related("cliente", "abogado_responsable"), pk=pk)
    u = request.user
    if not (getattr(u, "es_administrador", False) or
            caso.abogado_responsable_id == u.id or
            caso.accesos.filter(abogado=u).exists()):
        return render(request, "403.html", status=403)
    return render(request, "cases/detalle.html", {"caso": caso})

@login_required
def crear_caso(request):
    form = CasoForm(request.POST or None)

    if request.method == "POST":
        if form.is_valid():
            caso = form.save(commit=False)
            caso.abogado_responsable = request.user
            caso.save()
            messages.success(request, f"Caso '{caso.titulo}' creado correctamente.")
            return redirect("clients:detalle", pk=caso.cliente_id)
        messages.error(request, "Revisa los campos marcados.")

    # precargar cliente si viene ?cliente=ID
    if request.method == "GET":
        cid = request.GET.get("cliente")
        if cid and not form.is_bound:
            form.initial["cliente"] = cid

    return render(request, "cases/crear.html", {"form": form})



class ListadoCasosArchivosView(LoginRequiredMixin, View):
    template_name = "cases/listado_casos_archivos.html"

    def get(self, request):
        user = request.user
        if is_admin(user):
            casos = Caso.objects.select_related("cliente", "abogado_responsable").order_by("-id")
        else:
            casos = (Caso.objects
                     .filter(Q(abogado_responsable=user) | Q(accesocaso__abogado=user))
                     .distinct()
                     .select_related("cliente", "abogado_responsable")
                     .order_by("-id"))
        return render(request, self.template_name, {"casos": casos})
    
class CasoDetailView(DetailView):
    model = Caso
    template_name = "cases/detalle.html"   
    context_object_name = "caso"

    