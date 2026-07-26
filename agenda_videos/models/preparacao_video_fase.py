# agenda_videos/models/preparacao_video_fase.py

# Função Objetivo: Progresso de produção de vídeo, POR FASE (Diária/Semanal/Mensal) —
# 1 linha por combinação produto+fase, nunca 1 só pro produto inteiro.
# Explicação em detalhe: cada fase tem seu próprio pool de vídeo, preparado só quando
# o produto CHEGA nela (não adianta o usuário preparar Semanal/Mensal com antecedência
# — regra de negócio confirmada: prioridade é sempre o pool da Diária). Isso também é
# o que permite uma automação futura saber, com certeza, se existe vídeo pronto pra
# postar numa fase específica, sem ambiguidade.

from django.db import models
from produtos.models import Produto
from .configuracao_fase import Fase


class PreparacaoVideoFase(models.Model):
    produto = models.ForeignKey(
        Produto, on_delete=models.CASCADE, related_name='preparacoes_video')
    fase = models.CharField(max_length=10, choices=Fase.choices)

    roteiros_gerados = models.BooleanField(default=False)
    completos_produzidos = models.BooleanField(default=False)

    # * [EXPLICAÇÃO] → Quantidade que a config (periodo) tinha NO MOMENTO do clique
    #                  em "Roteiros"/"Completos" — reintroduzido em 26/07. Tinha sido
    #                  removido em 25/07 porque, na época, periodo nunca mudava depois
    #                  do clique. Com a tela de Configuração de Fases (26/07), periodo
    #                  pode mudar a qualquer momento — esses campos permitem comparar
    #                  o que foi feito contra a exigência ATUAL, sem exigir digitação
    #                  manual (o usuário continua só clicando; o número é capturado
    #                  sozinho). None = nunca foi marcado (equivalente a "não gerado").
    roteiros_quantidade_no_clique = models.PositiveIntegerField(null=True, blank=True)
    completos_quantidade_no_clique = models.PositiveIntegerField(null=True, blank=True)

    # * [EXPLICAÇÃO] → Timestamp do momento exato do clique (26/07, linha do tempo
    #                  completa) — None = nunca marcado OU marcado antes desse
    #                  rastreio existir (dado legado, nunca inventamos a data).
    roteiros_marcado_em = models.DateTimeField(null=True, blank=True)
    completos_marcado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Preparação de Vídeo por Fase'
        verbose_name_plural = 'Preparações de Vídeo por Fase'
        unique_together = ['produto', 'fase']

    def __str__(self):
        return f'{self.produto.sku or self.produto.ean} — {self.get_fase_display()}'