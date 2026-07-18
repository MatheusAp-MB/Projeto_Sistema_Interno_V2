import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('precificacao', '0005_gradeprecificacaoml_formato_longo'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfiguracaoOperacional',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fator_coleta', models.DecimalField(decimal_places=2, default=72, help_text='Custo de coleta em R$ por m³.', max_digits=8)),
                ('periodo_armazenagem', models.IntegerField(default=30, help_text='Dias considerados no cálculo mensal de armazenagem.')),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Configuração Operacional',
                'verbose_name_plural': 'Configuração Operacional',
            },
        ),
        migrations.CreateModel(
            name='FaixaArmazenagem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=50)),
                ('valor_diario', models.DecimalField(decimal_places=4, max_digits=8)),
                ('max_altura', models.DecimalField(decimal_places=2, max_digits=6)),
                ('max_largura', models.DecimalField(decimal_places=2, max_digits=6)),
                ('max_profundidade', models.DecimalField(decimal_places=2, max_digits=6)),
                ('ordem', models.PositiveIntegerField(default=1)),
                ('ativo', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Faixa de Armazenagem',
                'verbose_name_plural': 'Faixas de Armazenagem',
                'ordering': ['ordem'],
            },
        ),
    ]