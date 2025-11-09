from django.db import models

class Cliente(models.Model):
    creado_en = models.DateTimeField(auto_now_add=True)
    nombre_completo = models.CharField(max_length=180)
    rut = models.CharField(max_length=20, unique=True)
    correo = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    direccion = models.TextField(blank=True)
    notas = models.TextField(blank=True)  # antecedentes relevantes
    es_sensible = models.BooleanField(default=True)
    drive_folder_id = models.CharField(max_length=128, blank=True, null=True)

    class Meta:
        ordering = ["-creado_en"]
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self):
        return f"{self.nombre_completo} ({self.rut})"