# cases/views_busqueda.py
import re
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Value
from django.db.models.functions import Replace, Upper, Concat, Coalesce

from .models import Caso

class BuscarCasosView(LoginRequiredMixin, ListView):
    model = Caso
    template_name = "cases/casos_buscar.html"
    context_object_name = "resultados"
    paginate_by = 20

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()
        if not q:
            return Caso.objects.none()

        # Normaliza la entrada del usuario (RUT sin puntos/guión, K mayúscula)
        q_upper = q.upper()
        q_rut_norm = re.sub(r"[^0-9K]", "", q_upper)

        # ¡OJO! Evitamos 'only()' aquí para no interferir con las anotaciones
        qs = (
            Caso.objects
            .select_related("cliente", "abogado_responsable")
            .annotate(
                # nombre completo defensivo
                cliente_nombre=Coalesce(
                    Concat("cliente__nombre_completo", Value("")),
                    Value("")
                ),
                # RUT del cliente normalizado en BD (sin . ni - y en mayúsculas)
                cliente_rut_norm_db=Replace(
                    Replace(Upper("cliente__rut"), Value("."), Value("")),
                    Value("-"), Value("")
                ),
            )
        )

        filtros = (
            Q(codigo_caso__icontains=q) |
            Q(cliente_nombre__icontains=q)
        )

        if q.isdigit():
            filtros |= Q(pk=int(q))  # también por ID de caso

        if q_rut_norm:
            filtros |= Q(cliente_rut_norm_db__icontains=q_rut_norm)

        return qs.filter(filtros).order_by("-creado_en")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx
