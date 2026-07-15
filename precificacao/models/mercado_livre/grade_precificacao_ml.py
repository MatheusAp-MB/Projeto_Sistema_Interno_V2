# * [RESUMO] → Reformulado em 15/07: passa a viver por VARIAÇÃO (MLB
#              real), não mais por Produto — porque foi descoberto
#              que o Mercado Livre calcula um "frete real" (medição
#              física de peso/dimensão no envio), que pode divergir
#              do frete da tabela, e pode divergir ENTRE VARIAÇÕES DO
#              MESMO PRODUTO. variacao=None é o FALLBACK por produto
#              (usado quando ainda não existe MLB publicado, ou como
#              base pra novo anúncio) — sempre calculado com o frete
#              da tabela. variacao preenchida é o cálculo real daquele
#              MLB específico, usando frete real quando existir.
#
#              1 linha guarda os DOIS tipos (Clássico e Premium) ao
#              mesmo tempo, com as 4 margens de cada — não são 2
#              tipos concorrentes, é o mesmo card mostrando os 2. Pra
#              um MLB real, só as 4 colunas do SEU tipo verdadeiro
#              (anuncio.tipo_de_anuncio.tipo_anuncio) fazem sentido —
#              as do outro tipo ficam vazias (nunca vai ser o outro
#              tipo, não é ambiguidade, é "não se aplica"). Pra
#              fallback de produto, as 8 são calculadas (ainda não se
#              sabe qual tipo vai virar quando publicar).
#
#              Frete é guardado por GRUPO (Clássico/Premium), não por
#              margem — não muda entre as 4 margens do mesmo tipo.

from django.db import models
from django.core.serializers.json import DjangoJSONEncoder


class GradePrecificacaoML(models.Model):

    produto = models.ForeignKey(
        'produtos.Produto', on_delete=models.CASCADE, related_name='grade_precificacao_ml'
    )
    # * [EXPLICAÇÃO] → None = fallback do produto. Preenchida = MLB real.
    variacao = models.ForeignKey(
        'mercado_livre.VariacaoAnuncioMercadoLivre', on_delete=models.CASCADE,
        related_name='grade_precificacao_ml', null=True, blank=True,
    )

    # --- Frete usado por grupo (Clássico/Premium) ---
    frete_classico_usado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    frete_classico_origem = models.CharField(
        max_length=10, choices=[('tabela', 'Tabela'), ('real', 'Real (API)')], null=True, blank=True
    )
    frete_premium_usado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    frete_premium_origem = models.CharField(
        max_length=10, choices=[('tabela', 'Tabela'), ('real', 'Real (API)')], null=True, blank=True
    )

    # --- Clássico: 4 margens ---
    classico_minima_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    classico_minima_margem = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    classico_padrao_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    classico_padrao_margem = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    classico_maxima_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    classico_maxima_margem = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    classico_competicao_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    classico_competicao_margem = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    classico_detalhamento = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    # --- Premium: 4 margens ---
    premium_minima_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    premium_minima_margem = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    premium_padrao_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    premium_padrao_margem = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    premium_maxima_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    premium_maxima_margem = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    premium_competicao_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    premium_competicao_margem = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    premium_detalhamento = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    calculado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['produto', 'variacao']
        verbose_name = 'Grade de Precificação ML'
        verbose_name_plural = 'Grade de Precificação ML'

    def __str__(self):
        if self.variacao:
            return f'{self.produto} — MLB {self.variacao.anuncio.mlb}'
        return f'{self.produto} — fallback (sem MLB)'