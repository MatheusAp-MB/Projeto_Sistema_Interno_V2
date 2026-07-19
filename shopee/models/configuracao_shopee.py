from django.db import models


class ConfiguracaoShopee(models.Model):
    # * [EXPLICAÇÃO] → frete_padrao default 0 — PRESUNÇÃO NÃO CONFIRMADA.
    #                  Logística própria da Shopee + Programa de Frete
    #                  Grátis sugerem que não há custo de frete pro
    #                  vendedor, mas isso nunca foi confirmado de forma
    #                  explícita (só por ausência de menção contrária na
    #                  documentação oficial). Editável — se confirmado
    #                  outro valor, só mudar aqui, sem tocar em código.

    frete_padrao = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        help_text='Frete fixo em R$ — presunção não confirmada (logística própria da Shopee).'
    )
    desconto_vitrine_percentual = models.DecimalField(
        max_digits=5, decimal_places=2, default=20,
        help_text='Percentual de desconto padrão da vitrine (usado só pra calcular o preço "De" decorativo).'
    )

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração Shopee'
        verbose_name_plural = 'Configuração Shopee'

    def __str__(self):
        return 'Configuração Shopee'

    @classmethod
    def obter(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config