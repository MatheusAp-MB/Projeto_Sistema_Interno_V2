# * [RESUMO] → Grade de Precificação ML: preço BASE (sem promoção, sem
#              rebate) calculado via Goal Seek, por Produto × combinação
#              de tipo de anúncio × margem-alvo. NÃO fica presa a
#              nenhum MLB/Variação — todos os MLBs do mesmo SKU
#              compartilham a mesma linha (mesmo custo, mesmos
#              impostos, mesmas taxas). É a fonte de verdade do preço
#              base — substitui a inferência frágil que existia antes
#              via variacao.preco_original (pendência registrada em
#              12/07, resolvida aqui).

from django.db import models
from django.core.serializers.json import DjangoJSONEncoder


class GradePrecificacaoML(models.Model):

    class MargemAlvo(models.TextChoices):
        MINIMA = 'minima', 'Mínima'
        PADRAO = 'padrao', 'Padrão'
        COMPETICAO = 'competicao', 'Competição'
        MAXIMA = 'maxima', 'Máxima'

    produto = models.ForeignKey(
        'produtos.Produto', on_delete=models.CASCADE, related_name='grade_precificacao_ml'
    )
    # * [EXPLICAÇÃO] → Reaproveita as 8 combinações que já existem e já
    #                  são validadas (Clássico/Premium × FULL/Coleta ×
    #                  Catálogo/Não) — não duplica essa classificação.
    tipo_anuncio = models.ForeignKey(
        'mercado_livre.ConfiguracaoTipoAnuncioMercadoLivre', on_delete=models.CASCADE,
        related_name='grade_precificacao',
    )
    margem_alvo = models.CharField(max_length=12, choices=MargemAlvo.choices)

    preco_calculado = models.DecimalField(max_digits=10, decimal_places=2)
    # * [EXPLICAÇÃO] → Margem realmente obtida recalculando "pra frente"
    #                  (calcular_margem) com o preco_calculado já
    #                  arredondado pra 2 casas — validação cruzada
    #                  contra a margem_alvo, pra pegar qualquer diferença
    #                  de centavo introduzida pelo arredondamento.
    margem_percentual_obtida = models.DecimalField(max_digits=6, decimal_places=2)

    calculado_em = models.DateTimeField(auto_now=True)

    # * [EXPLICAÇÃO] → Guarda o passo a passo completo do Goal Seek
    #                  (custo, peso, faixa de frete usada, FIXO, taxa,
    #                  denominador, preço exato antes do RoundUp90) —
    #                  pro modal de "como chegamos nesse preço" LER,
    #                  nunca recalcular ao vivo (regra do projeto:
    #                  tudo vem do banco). Nulo até rodar o cálculo em
    #                  lote de novo depois dessa migração.
    detalhamento = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        unique_together = ['produto', 'tipo_anuncio', 'margem_alvo']

    def __str__(self):
        return f'{self.produto} | {self.tipo_anuncio} | {self.margem_alvo}: R$ {self.preco_calculado}'
    



