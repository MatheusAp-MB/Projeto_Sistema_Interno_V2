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

    # * [EXPLICAÇÃO] → Tamanho do pool DESSA fase (ex: 10 pra Diária, 4 pra Semanal,
    #                  3 pra Mensal) — comparado contra ConfiguracaoFase.periodo
    #                  DESSA MESMA fase (nunca fixo em Diária, como era antes).
    quantidade_roteiros = models.PositiveIntegerField(default=0)
    roteiros_insuficientes = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Preparação de Vídeo por Fase'
        verbose_name_plural = 'Preparações de Vídeo por Fase'
        unique_together = ['produto', 'fase']

    # Função Objetivo: Recalcula 'roteiros_insuficientes' sempre que o registro é salvo.
    def save(self, *args, **kwargs):
        self.roteiros_insuficientes = self._calcular_roteiros_insuficientes()
        super().save(*args, **kwargs)

    # Função Objetivo: Compara o pool disponível contra o período DESTA fase específica.
    def _calcular_roteiros_insuficientes(self):
        from .configuracao_fase import ConfiguracaoFase
        try:
            periodo = ConfiguracaoFase.objects.get(fase=self.fase).periodo
        except ConfiguracaoFase.DoesNotExist:
            return False
        return self.quantidade_roteiros < periodo

    def __str__(self):
        return f'{self.produto.sku or self.produto.ean} — {self.get_fase_display()}'