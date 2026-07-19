from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('precificacao', '0008_gradeprecificacaoraia'),
    ]

    operations = [
        migrations.CreateModel(
            name='TabelaComissaoShopee',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('preco_min', models.DecimalField(decimal_places=2, max_digits=10)),
                ('preco_max', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('comissao_percentual', models.DecimalField(decimal_places=2, max_digits=5)),
                ('adicional_fixo', models.DecimalField(decimal_places=2, max_digits=8)),
            ],
            options={
                'verbose_name': 'Faixa de Comissão Shopee',
                'verbose_name_plural': 'Faixas de Comissão Shopee',
                'ordering': ['preco_min'],
            },
        ),
    ]