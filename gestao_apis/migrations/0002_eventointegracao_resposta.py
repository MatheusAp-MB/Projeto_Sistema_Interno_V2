# Migração do campo "resposta" (resposta real da API mostrada em "Ver detalhes")

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestao_apis', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventointegracao',
            name='resposta',
            field=models.TextField(blank=True, default=''),
        ),
    ]
