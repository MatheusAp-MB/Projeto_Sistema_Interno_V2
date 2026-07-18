from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='ConfiguracaoRaia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('comissao_percentual', models.DecimalField(decimal_places=2, default=22, help_text='Comissão flat da Raia, em %.', max_digits=5)),
                ('frete_fixo', models.DecimalField(decimal_places=2, default=24, help_text='Frete fixo em R$ — não depende de peso nem preço.', max_digits=8)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Configuração Raia',
                'verbose_name_plural': 'Configuração Raia',
            },
        ),
    ]