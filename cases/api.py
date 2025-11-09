# cases/api.py
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Value
from django.db.models.functions import Replace, Upper, Concat, Coalesce
from .models import Caso
import re

@login_required
def api_buscar_casos(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})

    q_upper = q.upper()
    q_rut_norm = re.sub(r"[^0-9K]", "", q_upper)

    qs = (
        Caso.objects.select_related("cliente")
        .annotate(
            rut_norm=Replace(Replace(Upper("cliente__rut"), Value("."), Value("")), Value("-"), Value("")),
            nombre_full=Coalesce(Concat("cliente__nombres", Value(" "), "cliente__apellidos"), Value("")),
        )
        .filter(
            Q(codigo_caso__icontains=q)
            | Q(nombre_full__icontains=q)
            | Q(rut_norm__icontains=q_rut_norm)
            | Q(pk=int(q)) if q.isdigit() else Q(pk__isnull=False)
        )
        .order_by("-creado_en")[:20]
        .values("id", "codigo_caso", "titulo", "cliente__nombres", "cliente__apellidos", "cliente__rut")
    )

    results = [
        {
            "id": c["id"],
            "codigo": c["codigo_caso"],
            "titulo": c["titulo"],
            "cliente": f'{c["cliente__nombres"]} {c["cliente__apellidos"]}'.strip(),
            "rut": c["cliente__rut"],
        }
        for c in qs
    ]
    return JsonResponse({"results": results})
