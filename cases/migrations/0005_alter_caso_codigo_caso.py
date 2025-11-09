from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('cases', '0004_populate_codigo_caso'),
    ]
    operations = [
        migrations.AlterField(
            model_name='caso',
            name='codigo_caso',
            field=models.CharField(max_length=20, unique=True, editable=False),
        ),
    ]
