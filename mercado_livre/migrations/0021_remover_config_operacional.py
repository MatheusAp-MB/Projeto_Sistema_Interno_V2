from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('mercado_livre', '0020_variacaoanunciomercadolivre_altura_declarada_cm_and_more'),
    ]

    operations = [
        migrations.DeleteModel(name='ConfiguracaoMercadoLivre'),
        migrations.DeleteModel(name='FaixaArmazenagemMercadoLivre'),
    ]