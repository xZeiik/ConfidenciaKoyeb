# cases/signals.py
import re
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.google_drive import ensure_folder, _svc  # _svc solo si usas la opción de rename
from .models import Caso

MAX_NAME = 80  # largo máximo para la carpeta de caso (ajustable)

def _sanitize(name: str) -> str:
    """
    Quita caracteres que Drive trata mal en nombres y comprime espacios.
    """
    # reemplaza / \ : * ? " < > | por guión
    name = re.sub(r'[\/\\:\*\?"<>\|]+', " - ", name)
    # colapsa espacios y guiones múltiples
    name = re.sub(r'\s{2,}', " ", name).strip(" .-")
    return name

def _case_folder_name(caso: Caso) -> str:
    # Ej: "CASO-001 - Sucesión Pérez"
    titulo = (caso.titulo or "").strip()
    if len(titulo) > (MAX_NAME - len(caso.codigo_caso) - 3):
        titulo = titulo[: MAX_NAME - len(caso.codigo_caso) - 3].rstrip()
    return _sanitize(f"{caso.codigo_caso} - {titulo}") if titulo else _sanitize(caso.codigo_caso)

@receiver(post_save, sender=Caso)
def crear_o_actualizar_carpeta_caso(sender, instance: Caso, created, **kwargs):
    """
    Asegura la carpeta del caso en Drive:
    /Clientes/<cliente.nombre_completo>/<CODIGO - TITULO>
    - Si el cliente no tiene carpeta, la crea.
    - Si el caso no tiene carpeta, la crea.
    - (Opcional) Si cambiaste el título/código, puede renombrar la carpeta existente.
    """
    # 1) Asegura /Clientes/ y /<Cliente>/
    root_clientes = ensure_folder("Clientes")
    carpeta_cliente = ensure_folder(instance.cliente.nombre_completo, root_clientes)

    desired_name = _case_folder_name(instance)

    # 2) Si el caso aún no tiene carpeta, créala con el nombre deseado
    if not instance.drive_folder_id:
        carpeta_caso = ensure_folder(desired_name, carpeta_cliente)
        if instance.drive_folder_id != carpeta_caso:
            instance.drive_folder_id = carpeta_caso
            instance.save(update_fields=["drive_folder_id"])
        return

    # 3) (Opcional) Renombrar si cambió el nombre deseado
    #    Descomenta este bloque si quieres que al editar título/código se renombre en Drive.
    """
    try:
        svc = _svc()
        meta = svc.files().get(fileId=instance.drive_folder_id,
                               fields="id,name,parents",
                               supportsAllDrives=True).execute()
        current_name = meta.get("name")
        if current_name != desired_name:
            svc.files().update(fileId=instance.drive_folder_id,
                               body={"name": desired_name},
                               supportsAllDrives=True).execute()
    except Exception:
        # Si falla el rename, lo ignoramos para no romper el guardado del modelo
        pass
    """
