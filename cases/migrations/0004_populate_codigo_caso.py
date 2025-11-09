from django.db import migrations
from django.utils.crypto import get_random_string
from django.utils import timezone

def gen_code():
    year = timezone.now().year
    return f"CASO-{year}-{get_random_string(4, allowed_chars='0123456789')}"

def forwards(apps, schema_editor):
    Caso = apps.get_model('cases', 'Caso')
    used = set(Caso.objects.exclude(codigo_caso__isnull=True).values_list('codigo_caso', flat=True))
    for caso in Caso.objects.filter(codigo_caso__isnull=True):
        code = gen_code()
        while code in used:
            code = gen_code()
        caso.codigo_caso = code
        caso.save(update_fields=['codigo_caso'])
        used.add(code)

def backwards(apps, schema_editor):
    Caso = apps.get_model('cases', 'Caso')
    Caso.objects.update(codigo_caso=None)

class Migration(migrations.Migration):

    dependencies = [
        ('cases', '0003_alter_accesocaso_options_remove_caso_prioridad_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
