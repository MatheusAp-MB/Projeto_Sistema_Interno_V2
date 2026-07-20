from django.db import models


class ConfiguracaoTiktok(models.Model):
    # * [EXPLICAÇÃO] → Só a margem de afiliado — comissão por faixa de preço fica
    #                  em TabelaComissaoTiktok (precificacao), mesmo padrão da Shopee.
    #                  8% confirmado pelo usuário (18/07) — comissão adicional que a
    #                  MB/SV PAGA (desconta da margem), só quando tipo=com_afiliado.

    margem_afiliado_percentual = models.DecimalField(
        max_digits=5, decimal_places=2, default=8,
        help_text='Comissão adicional paga quando a venda vem com afiliado, em %.'
    )
    desconto_vitrine_percentual = models.DecimalField(
        max_digits=5, decimal_places=2, default=20,
        help_text='Percentual de desconto padrão da vitrine (usado só pra calcular o preço "De" decorativo) — vale pros 2 tipos, Sem e Com Afiliado.'
    )

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração TikTok Shop'
        verbose_name_plural = 'Configuração TikTok Shop'

    def __str__(self):
        return 'Configuração TikTok Shop'

    @classmethod
    def obter(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config