import django.core.serializers.json
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('precificacao', '0004_alter_gradeprecificacaoml_options_and_more'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='gradeprecificacaoml',
            unique_together=set(),
        ),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='frete_classico_usado'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='frete_classico_origem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='frete_premium_usado'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='frete_premium_origem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_minima_preco'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_minima_margem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_padrao_preco'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_padrao_margem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_maxima_preco'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_maxima_margem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_competicao_preco'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_competicao_margem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='classico_detalhamento'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_minima_preco'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_minima_margem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_padrao_preco'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_padrao_margem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_maxima_preco'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_maxima_margem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_competicao_preco'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_competicao_margem'),
        migrations.RemoveField(model_name='gradeprecificacaoml', name='premium_detalhamento'),
        migrations.AddField(
            model_name='gradeprecificacaoml',
            name='tipo_anuncio',
            field=models.CharField(
                choices=[('classico', 'Clássico'), ('premium', 'Premium')],
                default='classico', max_length=10,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='gradeprecificacaoml',
            name='margem',
            field=models.CharField(
                choices=[('minima', 'Mínima'), ('padrao', 'Padrão'), ('maxima', 'Máxima'), ('competicao', 'Competição')],
                default='padrao', max_length=12,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='gradeprecificacaoml',
            name='preco',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='gradeprecificacaoml',
            name='margem_percentual_obtida',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='gradeprecificacaoml',
            name='frete_usado',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='gradeprecificacaoml',
            name='origem_dimensao',
            field=models.CharField(
                blank=True, null=True, max_length=15,
                choices=[('variacao_ml', 'Variação ML'), ('produto_erp', 'Produto ERP')],
            ),
        ),
        migrations.AddField(
            model_name='gradeprecificacaoml',
            name='detalhamento',
            field=models.JSONField(blank=True, null=True, encoder=django.core.serializers.json.DjangoJSONEncoder),
        ),
        migrations.AlterUniqueTogether(
            name='gradeprecificacaoml',
            unique_together={('produto', 'variacao', 'tipo_anuncio', 'margem')},
        ),
    ]