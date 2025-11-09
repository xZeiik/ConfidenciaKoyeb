from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.conf import settings

from cases.models import Caso
import random
import datetime
import json

@login_required
def home(request):
    # últimos 5 casos reales (si existen)
    casos_activos = list(Caso.objects.select_related("cliente").order_by("-creado_en")[:5])

    # Generar meses (últimos 6 meses en formato corto)
    today = datetime.date.today()
    meses = []
    for i in range(5, -1, -1):
        dt = (today - datetime.timedelta(days=30*i))
        meses.append(dt.strftime("%b"))  # 'Oct', 'Nov', etc.

    # Datos aleatorios de ejemplo (clientes y casos por mes)
    datos_clientes = [random.randint(3, 25) for _ in meses]
    datos_casos = [random.randint(1, 12) for _ in meses]

    # Distribución ficticia de tipos de caso
    dist = {
        "Herencias": random.randint(5, 20),
        "Demandas Civiles": random.randint(3, 18),
        "Juicios Laborales": random.randint(0, 12),
        "Contratos": random.randint(2, 15),
        "Asesorías": random.randint(1, 14),
        "Otros": random.randint(0, 8),
    }

    context = {
        "casos_activos": casos_activos,
        "meses_json": json.dumps(meses),
        "datos_clientes_json": json.dumps(datos_clientes),
        "datos_casos_json": json.dumps(datos_casos),
        "dist_json": json.dumps(dist),
    }
    return render(request, "core/home.html", context)


