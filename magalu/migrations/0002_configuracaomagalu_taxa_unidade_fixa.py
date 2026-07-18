from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('magalu', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuracaomagalu',
            name='taxa_unidade_fixa',
            field=models.DecimalField(decimal_places=2, default=5, help_text='Taxa fixa em R$, cobrada por unidade vendida — independente do preço.', max_digits=8),
        ),
    ]