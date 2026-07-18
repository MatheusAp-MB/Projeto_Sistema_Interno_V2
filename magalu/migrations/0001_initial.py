from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='ConfiguracaoMagalu',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('comissao_percentual', models.DecimalField(decimal_places=2, default=6, help_text='Comissão flat do Magalu, em %.', max_digits=5)),
                ('faixa_reputacao_atual', models.CharField(
                    choices=[('baixa', '< 92% (0% desconto)'), ('media', '92-97% (25% desconto)'), ('alta', '> 97% (50% desconto)')],
                    default='alta', help_text='Define qual das 3 colunas de frete usar — muda conforme o desempenho da conta vendedora.',
                    max_length=10,
                )),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Configuração Magalu',
                'verbose_name_plural': 'Configuração Magalu',
            },
        ),
        migrations.CreateModel(
            name='FreteMagalu',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('peso_min', models.DecimalField(decimal_places=3, max_digits=8)),
                ('peso_max', models.DecimalField(blank=True, decimal_places=3, max_digits=8, null=True)),
                ('valor_baixa', models.DecimalField(decimal_places=2, max_digits=8)),
                ('valor_media', models.DecimalField(decimal_places=2, max_digits=8)),
                ('valor_alta', models.DecimalField(decimal_places=2, max_digits=8)),
            ],
            options={
                'verbose_name': 'Faixa de Frete Magalu',
                'verbose_name_plural': 'Faixas de Frete Magalu',
                'ordering': ['peso_min'],
            },
        ),
    ]