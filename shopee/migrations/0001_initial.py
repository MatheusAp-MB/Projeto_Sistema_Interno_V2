from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='ConfiguracaoShopee',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('frete_padrao', models.DecimalField(decimal_places=2, default=0, help_text='Frete fixo em R$ — presunção não confirmada (logística própria da Shopee).', max_digits=8)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Configuração Shopee',
                'verbose_name_plural': 'Configuração Shopee',
            },
        ),
    ]