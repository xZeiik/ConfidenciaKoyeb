from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from core import views as core_views



urlpatterns = [
    path("admin/", admin.site.urls),  # ✅ Panel de administración
    path("", include("core.urls")),              # ← registra el namespace 'core'
    path("cuentas/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("clientes/", include(("clients.urls", "clients"), namespace="clients")),
    path("casos/", include(("cases.urls", "cases"), namespace="cases")),  # <--- namespace
    
    
]