from django.db import models


class ConfiguracaoMagalu(models.Model):
    # * [EXPLICAÇÃO] → Singleton — só deve existir 1 linha. Diferente do ML
    #                  (comissão por tipo_anuncio Clássico/Premium), o Magalu
    #                  tem 1 comissão flat só, confirmada com o usuário como
    #                  ~6% hoje (a planilha original tinha 10%, desatualizado
    #                  — por isso editável aqui, não fixo em código).

    class FaixaReputacao(models.TextChoices):
        BAIXA = 'baixa', '< 92% (0% desconto)'
        MEDIA = 'media', '92-97% (25% desconto)'
        ALTA = 'alta', '> 97% (50% desconto)'

    comissao_percentual = models.DecimalField(
        max_digits=5, decimal_places=2, default=6,
        help_text='Comissão flat do Magalu, em %.'
    )
    taxa_unidade_fixa = models.DecimalField(
        max_digits=8, decimal_places=2, default=5,
        help_text='Taxa fixa em R$, cobrada por unidade vendida — independente do preço.'
    )
    faixa_reputacao_atual = models.CharField(
        max_length=10, choices=FaixaReputacao.choices, default=FaixaReputacao.ALTA,
        help_text='Define qual das 3 colunas de frete usar — muda conforme o desempenho da conta vendedora.'
    )

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração Magalu'
        verbose_name_plural = 'Configuração Magalu'

    def __str__(self):
        return 'Configuração Magalu'

    @classmethod
    def obter(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config