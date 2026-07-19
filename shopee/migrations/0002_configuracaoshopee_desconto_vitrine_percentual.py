from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shopee', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuracaoshopee',
            name='desconto_vitrine_percentual',
            field=models.DecimalField(decimal_places=2, default=20, help_text='Percentual de desconto padrão da vitrine (usado só pra calcular o preço "De" decorativo).', max_digits=5),
        ),
    ]