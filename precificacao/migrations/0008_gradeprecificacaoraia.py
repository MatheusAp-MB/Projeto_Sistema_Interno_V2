import django.core.serializers.json
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('precificacao', '0007_gradeprecificacaomagalu'),
        ('produtos', '0004_rename_altura_produto_altura_produto_sem_embalar_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='GradePrecificacaoRaia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('margem', models.CharField(choices=[('minima', 'Mínima'), ('padrao', 'Padrão'), ('maxima', 'Máxima'), ('competicao', 'Competição')], max_length=12)),
                ('preco', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('margem_percentual_obtida', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('frete_usado', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('detalhamento', models.JSONField(blank=True, null=True, encoder=django.core.serializers.json.DjangoJSONEncoder)),
                ('calculado_em', models.DateTimeField(auto_now=True)),
                ('produto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grade_precificacao_raia', to='produtos.produto')),
            ],
            options={
                'verbose_name': 'Grade de Precificação Raia',
                'verbose_name_plural': 'Grade de Precificação Raia',
            },
        ),
        migrations.AlterUniqueTogether(
            name='gradeprecificacaoraia',
            unique_together={('produto', 'margem')},
        ),
    ]