from django.db import models


class ConfiguracaoRaia(models.Model):
    # * [EXPLICAÇÃO] → Caso mais simples entre os marketplaces até agora —
    #                  comissão e frete são valores FIXOS, sem tabela, sem
    #                  faixa nenhuma. Singleton — só deve existir 1 linha.

    comissao_percentual = models.DecimalField(
        max_digits=5, decimal_places=2, default=22,
        help_text='Comissão flat da Raia, em %.'
    )
    frete_fixo = models.DecimalField(
        max_digits=8, decimal_places=2, default=24,
        help_text='Frete fixo em R$ — não depende de peso nem preço.'
    )

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração Raia'
        verbose_name_plural = 'Configuração Raia'

    def __str__(self):
        return 'Configuração Raia'

    @classmethod
    def obter(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config