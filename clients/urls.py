from django.urls import path, include
from . import views

app_name = "clients"  # <- namespace

urlpatterns = [
    path("", views.listar_clientes, name="listar"),
    path("crear/", views.crear_cliente, name="crear"),
    path("<int:pk>/", views.detalle_cliente, name="detalle"),         # puedes comentar si aún no la tienes
    path("<int:pk>/editar/", views.editar_cliente, name="editar"),     # idem
]