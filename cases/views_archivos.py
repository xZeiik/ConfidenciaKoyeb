import io
import mimetypes
import tempfile
import os

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import (
    FileResponse, Http404, HttpResponse, HttpResponseForbidden,
    HttpResponseRedirect, JsonResponse
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from core.google_drive import _svc, list_files, upload_file
from .models import ArchivoCaso, Caso
from .permissions import is_admin, puede_subir_caso, puede_ver_caso


# =========================
# Helpers bitácora
# =========================
def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        # Remover puerto si existe (ej: "179.60.70.50:48431" → "179.60.70.50")
        return xff.split(",")[0].strip().split(":")[0]
    remote = request.META.get("REMOTE_ADDR", "")
    return remote.split(":")[0] if remote else ""


def log_evento(caso, accion, request=None, archivo=None, detalle=""):
    from .models import ArchivoEvento  # import local para evitar ciclos
    ArchivoEvento.objects.create(
        caso=caso,
        archivo=archivo,
        accion=accion,
        usuario=(request.user if request else None),
        detalle=(detalle or "")[:255],
        ip=_client_ip(request) if request else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "") if request else ""),
        creado_en=timezone.now(),
    )


# =========================
# Utilidades de edición
# =========================
def _editor_url(file_id: str, mime: str) -> str:
    if mime == "application/vnd.google-apps.document":
        return f"https://docs.google.com/document/d/{file_id}/edit"
    if mime == "application/vnd.google-apps.spreadsheet":
        return f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
    if mime == "application/vnd.google-apps.presentation":
        return f"https://docs.google.com/presentation/d/{file_id}/edit"
    # fallback: preview
    return f"https://drive.google.com/file/d/{file_id}/preview"


# Extensión → tipo Google editable
EXT_TO_GOOGLE = {
    ".doc":  "application/vnd.google-apps.document",
    ".docx": "application/vnd.google-apps.document",
    ".odt":  "application/vnd.google-apps.document",
    ".rtf":  "application/vnd.google-apps.document",
    ".txt":  "application/vnd.google-apps.document",

    ".xls":  "application/vnd.google-apps.spreadsheet",
    ".xlsx": "application/vnd.google-apps.spreadsheet",
    ".csv":  "application/vnd.google-apps.spreadsheet",

    ".ppt":  "application/vnd.google-apps.presentation",
    ".pptx": "application/vnd.google-apps.presentation",
    ".odp":  "application/vnd.google-apps.presentation",
}


# =========================
# Vistas
# =========================

def _forbidden(request, caso, motivo="No tienes permiso para ver este caso."):
    return render(
        request,
        "errors/caso_sin_permiso.html",
        {"caso": caso, "motivo": motivo},
        status=403,
    )



class ListadoCasosArchivosView(LoginRequiredMixin, View):
    template_name = "cases/listado_casos_archivos.html"

    def get(self, request):
        user = request.user
        base = Caso.objects.select_related("cliente", "abogado_responsable")

        if is_admin(user):
            casos = base.order_by("-id")
        else:
            casos = (
                base.filter(
                    Q(abogado_responsable=user) |
                    Q(accesos__abogado=user)      # ← nombre correcto del related_name
                )
                .distinct()
                .order_by("-id")
            )

        return render(request, self.template_name, {"casos": casos})

class ListaArchivosCasoView(LoginRequiredMixin, View):
    template_name = "cases/archivos_caso.html"

    def get(self, request, caso_id):
        caso = get_object_or_404(Caso.objects.select_related("cliente"), id=caso_id)
        if not puede_ver_caso(request.user, caso):
            return _forbidden(request, caso, "Este caso pertenece a otro abogado.")

        # Asegurar carpeta de Drive
        if not caso.drive_folder_id:
            from core.google_drive import ensure_folder
            root = ensure_folder("Clientes")
            cliente = ensure_folder(caso.cliente.nombre_completo, root)
            caso.drive_folder_id = ensure_folder(caso.codigo_caso, cliente)
            caso.save(update_fields=["drive_folder_id"])

        # Sync manual (solo si ?sync=1)
        do_sync = request.GET.get("sync") == "1"
        if do_sync:
            items = list_files(caso.drive_folder_id)
            current_ids = []

            for f in items:
                obj, _ = ArchivoCaso.objects.update_or_create(
                    drive_file_id=f["id"],
                    defaults={
                        "caso": caso,
                        "nombre": f["name"],
                        "tipo_mime": f.get("mimeType", ""),
                        "tamano": int(f.get("size", 0)) if f.get("size") else None,
                        "modificado_en": f.get("modifiedTime"),
                    },
                )
                current_ids.append(obj.drive_file_id)

            # 🔥 Eliminar los registros que ya no están en Drive
            ArchivoCaso.objects.filter(caso=caso).exclude(drive_file_id__in=current_ids).delete()

        archivos = (
            ArchivoCaso.objects
            .filter(caso=caso, drive_file_id__isnull=False)
            .exclude(drive_file_id="")
            .order_by("-modificado_en", "-creado_en")
        )

        puede_subir = puede_subir_caso(request.user, caso)

        choices = getattr(Caso, "ESTADO_CHOICES", None) or getattr(Caso, "ESTADOS", None)
        return render(request, self.template_name, {
            "caso": caso,
            "archivos": archivos,
            "puede_subir": puede_subir,
            "did_sync": do_sync,
            "estados": choices or [("ABIERTO", "Abierto"), ("EN_PROCESO", "En proceso"), ("CERRADO", "Cerrado")],
            "categorias": getattr(Caso, "CATEGORIA_CHOICES", []),
                })


class SubirArchivoCasoView(LoginRequiredMixin, View):
    def post(self, request, caso_id):
        caso = get_object_or_404(Caso, id=caso_id)
        if not puede_subir_caso(request.user, caso):
            return HttpResponseForbidden("No puedes subir archivos aquí.")

        archivo = request.FILES.get("file")
        if not archivo:
            return JsonResponse({"error": "No se envió archivo"}, status=400)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            for chunk in archivo.chunks():
                tmp.write(chunk)
            tmp.flush()

        mime = archivo.content_type or mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
        res = upload_file(tmp.name, archivo.name, caso.drive_folder_id, mime_type=mime)

        obj, _ = ArchivoCaso.objects.update_or_create(
            drive_file_id=res["id"],
            defaults={
                "caso": caso,
                "nombre": res["name"],
                "tipo_mime": res.get("mimeType", ""),
                "subido_por": request.user,
            },
        )

        log_evento(caso, "subido", request, archivo=obj, detalle=f"Archivo subido: {obj.nombre}")
        return redirect("cases:archivos_caso", caso_id=caso.id)


class DescargarArchivoCasoView(LoginRequiredMixin, View):
    def get(self, request, file_id):
        archivo = get_object_or_404(ArchivoCaso, drive_file_id=file_id)
        if not puede_ver_caso(request.user, archivo.caso):
            return _forbidden("No puedes acceder a este archivo.")

        svc = _svc()
        try:
            req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
            meta = svc.files().get(fileId=file_id, fields="name").execute()
        except Exception:
            raise Http404()

        from googleapiclient.http import MediaIoBaseDownload
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)

        log_evento(archivo.caso, "descargado", request, archivo=archivo, detalle=archivo.nombre)
        return FileResponse(buf, as_attachment=True, filename=meta.get("name", "archivo"))


class FicherosRecientesView(LoginRequiredMixin, View):
    template_name = "cases/ficheros_recientes.html"

    def get(self, request):
        user = request.user
        if is_admin(user):
            archivos = (ArchivoCaso.objects
                        .select_related("caso", "caso__cliente")
                        .order_by("-modificado_en", "-creado_en")[:20])
        else:
            archivos = (ArchivoCaso.objects
                        .filter(caso__abogado_responsable=user)
                        .select_related("caso", "caso__cliente")
                        .order_by("-modificado_en", "-creado_en")[:20])

        return render(request, self.template_name, {"archivos": archivos})


class VerArchivoCasoView(LoginRequiredMixin, View):
    template_name = "cases/ver_archivo.html"

    def get(self, request, file_id):
        archivo = get_object_or_404(ArchivoCaso.objects.select_related("caso"), drive_file_id=file_id)
        if not puede_ver_caso(request.user, archivo.caso):
            return _forbidden("Sin permiso")
        log_evento(archivo.caso, "visto", request, archivo=archivo, detalle="Vista previa")
        return render(request, self.template_name, {"archivo": archivo})


class EditarArchivoCasoView(LoginRequiredMixin, View):
    def get(self, request, file_id):
        svc = _svc()
        archivo = get_object_or_404(ArchivoCaso.objects.select_related("caso"), drive_file_id=file_id)
        caso = archivo.caso

        if not puede_ver_caso(request.user, caso):
            return _forbidden("No tienes permiso.")

        mime = (archivo.tipo_mime or "").strip()
        if mime.startswith("application/vnd.google-apps."):
            log_evento(caso, "visto", request, archivo=archivo, detalle=f"Abrir editor ({mime})")
            return HttpResponseRedirect(_editor_url(file_id, mime))

        base, ext = os.path.splitext((archivo.nombre or "").strip())
        base_lower = (base or "Documento").strip()
        target_mime = EXT_TO_GOOGLE.get(ext.lower())
        editable_name = f"{base_lower} (Editable)"

        if target_mime:
            existente = (
                ArchivoCaso.objects
                .filter(caso=caso, nombre=editable_name, tipo_mime__startswith="application/vnd.google-apps.")
                .first()
            )
            if existente:
                log_evento(caso, "visto", request, archivo=existente, detalle="Reutiliza copia editable (BD)")
                return HttpResponseRedirect(_editor_url(existente.drive_file_id, existente.tipo_mime or target_mime))

            # Buscar en Drive una copia editable existente
            try:
                name_esc = (editable_name or "").replace("'", r"\'")
                query = (
                    f"'{caso.drive_folder_id}' in parents and "
                    f"name = '{name_esc}' and "
                    "mimeType contains 'application/vnd.google-apps' and trashed = false"
                )
                found = svc.files().list(
                    q=query,
                    spaces="drive",
                    fields="files(id,name,mimeType)",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    corpora="allDrives",
                    pageSize=1,
                ).execute().get("files", [])
            except Exception:
                found = []

            if found:
                f = found[0]
                existente, _ = ArchivoCaso.objects.update_or_create(
                    drive_file_id=f["id"],
                    defaults={
                        "caso": caso,
                        "nombre": f.get("name", editable_name),
                        "tipo_mime": f.get("mimeType", target_mime),
                        "subido_por": request.user,
                    },
                )
                log_evento(caso, "visto", request, archivo=existente, detalle="Reutiliza copia editable (Drive)")
                return HttpResponseRedirect(_editor_url(existente.drive_file_id, existente.tipo_mime or target_mime))

            # Crear copia convertida si no existe
            body = {
                "name": editable_name,
                "mimeType": target_mime,
                "parents": [caso.drive_folder_id],
            }
            res = svc.files().copy(
                fileId=file_id,
                body=body,
                supportsAllDrives=True,
                fields="id,name,mimeType",
            ).execute()

            nuevo_id = res["id"]
            nuevo_mime = res.get("mimeType", target_mime)
            nuevo, _ = ArchivoCaso.objects.update_or_create(
                drive_file_id=nuevo_id,
                defaults={
                    "caso": caso,
                    "nombre": res.get("name", editable_name),
                    "tipo_mime": nuevo_mime,
                    "subido_por": request.user,
                },
            )
            log_evento(caso, "subido", request, archivo=nuevo, detalle=f"Conversión a editable ({nuevo_mime})")
            return HttpResponseRedirect(_editor_url(nuevo_id, nuevo_mime))

        log_evento(caso, "visto", request, archivo=archivo, detalle="Ver (no editable)")
        return HttpResponseRedirect(f"https://drive.google.com/file/d/{file_id}/preview")



from django.contrib import messages

class CambiarEstadoCasoView(LoginRequiredMixin, View):
    def post(self, request, caso_id):
        caso = get_object_or_404(Caso, id=caso_id)
        if not puede_subir_caso(request.user, caso):
            return HttpResponseForbidden("No tienes permiso para cambiar el estado.")

        nuevo_estado = (request.POST.get("estado") or "").strip()

        # Detectar el nombre del choices en tu modelo
        choices = getattr(Caso, "ESTADO_CHOICES", None) or getattr(Caso, "ESTADOS", None)
        if not choices:
            # Fallback si no tienes choices en el modelo
            validos = {"ABIERTO", "EN_PROCESO", "CERRADO"}
        else:
            validos = set(dict(choices).keys())

        if nuevo_estado not in validos:
            messages.error(request, "Estado inválido.")
            return redirect("cases:archivos_caso", caso_id=caso.id)

        anterior = getattr(caso, "estado", None)
        caso.estado = nuevo_estado
        caso.save(update_fields=["estado"])

        # Registrar en bitácora
        detalle = f"Estado: {anterior or '—'} → {nuevo_estado}"
        log_evento(caso, "estado_actualizado", request, detalle=detalle)

        messages.success(request, "Estado actualizado correctamente.")
        return redirect("cases:archivos_caso", caso_id=caso.id)


class CambiarCategoriaCasoView(LoginRequiredMixin, View):
    def post(self, request, caso_id):
        caso = get_object_or_404(Caso, id=caso_id)
        if not puede_subir_caso(request.user, caso):
            return HttpResponseForbidden("No tienes permiso para cambiar la categoría.")
        nueva = (request.POST.get("categoria") or "").strip()
        validas = set(dict(Caso.CATEGORIA_CHOICES).keys())
        if nueva not in validas:
            messages.error(request, "Categoría inválida.")
            return redirect("cases:archivos_caso", caso_id=caso.id)
        anterior = caso.categoria
        caso.categoria = nueva
        caso.save(update_fields=["categoria"])
        log_evento(caso, "categoria_actualizada", request, detalle=f"Categoría: {anterior} → {nueva}")
        messages.success(request, "Categoría actualizada correctamente.")
        return redirect("cases:archivos_caso", caso_id=caso.id)
