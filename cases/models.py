from django.db import models
from django.conf import settings
from clients.models import Cliente
from django.utils.crypto import get_random_string
from django.db.models import Q


class Caso(models.Model):
    ESTADOS = [
        ("ABIERTO", "Abierto"),
        ("EN_PROCESO", "En proceso"),
        ("CERRADO", "Cerrado"),
    ]

    CATEGORIA_CHOICES = [
        ("HERENCIA", "Herencia"),
        ("DEMANDA_CIVIL", "Demanda civil"),
        ("JUICIO_LABORAL", "Juicio laboral"),
        ("CONTRATO", "Contrato"),
        ("ASESORIA", "Asesoría"),
        ("OTROS", "Otros"),
    ]

    cliente = models.ForeignKey("clients.Cliente", on_delete=models.CASCADE, related_name="casos")
    abogado_responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="casos_responsables"
    )
    titulo = models.CharField(max_length=180)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=40, choices=ESTADOS, default="ABIERTO")
    categoria = models.CharField(
        max_length=40,  # ← sube a 40 (o 50)
        choices=CATEGORIA_CHOICES,
        default="OTROS",
        db_index=True,
    )
    codigo_caso = models.CharField(max_length=20, unique=True, editable=False)
    drive_folder_id = models.CharField(max_length=128, blank=True, null=True)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]
        verbose_name = "Caso"
        verbose_name_plural = "Casos"

    def __str__(self):
        return f"{self.codigo_caso} - {self.titulo}"

    def save(self, *args, **kwargs):
        if not self.codigo_caso:
            prefix = "CASO"
            random_suffix = get_random_string(4, allowed_chars="0123456789")
            self.codigo_caso = f"{prefix}-{random_suffix}"
        super().save(*args, **kwargs)


class AccesoCaso(models.Model):
    caso = models.ForeignKey(Caso, on_delete=models.CASCADE, related_name="accesos")
    abogado = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accesos_casos")
    puede_editar = models.BooleanField(default=False)

    class Meta:
        unique_together = ("caso", "abogado")
        verbose_name = "Acceso a Caso"
        verbose_name_plural = "Accesos a Casos"

    def __str__(self):
        return f"{self.abogado} → {self.caso} ({'edita' if self.puede_editar else 'solo lectura'})"
    


class ArchivoCaso(models.Model):
    caso = models.ForeignKey(Caso, on_delete=models.CASCADE, related_name="archivos")
    drive_file_id = models.CharField(max_length=128, unique=True)
    nombre = models.CharField(max_length=255)
    tipo_mime = models.CharField(max_length=255, blank=True)
    tamano = models.BigIntegerField(null=True, blank=True)
    modificado_en = models.DateTimeField(null=True, blank=True)
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Archivo de Caso"
        verbose_name_plural = "Archivos de Casos"
        ordering = ["-modificado_en", "-creado_en"]

    def __str__(self):
        return f"{self.nombre} ({self.caso.codigo_caso})"
    

class ArchivoEvento(models.Model):
    class Accion(models.TextChoices):
        SUBIDO = "subido", "Subido"
        DESCARGADO = "descargado", "Descargado"
        VISTO = "visto", "Visto"
        SINCRONIZADO = "sincronizado", "Sincronizado"

    caso = models.ForeignKey("cases.Caso", on_delete=models.CASCADE, related_name="eventos")
    archivo = models.ForeignKey("cases.ArchivoCaso", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="eventos")
    accion = models.CharField(max_length=40, choices=Accion.choices)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="eventos_archivo")
    detalle = models.CharField(max_length=255, blank=True)  # p.ej. nombre del archivo
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["caso", "-creado_en"]),
            models.Index(fields=["accion", "-creado_en"]),
        ]

    def __str__(self):
        u = self.usuario or "sistema"
        return f"[{self.creado_en:%Y-%m-%d %H:%M}] {self.get_accion_display()} por {u}"    
    

class CasoQuerySet(models.QuerySet):
    def visibles_para(self, user, es_admin: bool):
        return self if es_admin else self.filter(
            Q(abogado_responsable=user) | Q(accesos__abogado=user)
        ).distinct()    