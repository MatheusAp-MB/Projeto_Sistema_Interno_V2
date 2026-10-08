# Escrita à mão em 08/10/2026 (é exatamente o que o makemigrations geraria para o campo novo "flex").

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mercado_livre', '0033_variacaoanunciomercadolivre_inventory_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='consultafullmercadolivre',
            name='flex',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
