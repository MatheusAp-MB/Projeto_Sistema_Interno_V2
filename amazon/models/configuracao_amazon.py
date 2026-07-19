from django.db import models


class ConfiguracaoAmazon(models.Model):
    # * [EXPLICAÇÃO] → Comissão FLAT (13%, confirmado provisório) — diferente de
    #                  Shopee/TikTok, aqui não varia por faixa de preço. Frete/taxa
    #                  de kg adicional ficam em precificacao/models/amazon/ (são
    #                  tabelas, não config simples). Sem nenhuma taxa fixa extra
    #                  (tipo taxa_unidade do Magalu) — confirmado que não existe.

    comissao_percentual = models.DecimalField(
        max_digits=5, decimal_places=2, default=13,
        help_text='Comissão flat da Amazon (referral fee), em %.'
    )

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração Amazon'
        verbose_name_plural = 'Configuração Amazon'

    def __str__(self):
        return 'Configuração Amazon'

    @classmethod
    def obter(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config