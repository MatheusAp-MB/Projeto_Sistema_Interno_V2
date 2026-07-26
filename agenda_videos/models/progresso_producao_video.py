# agenda_videos/models/progresso_producao_video.py

# Função Objetivo: Rastreia o progresso dos 2 vídeos ÚNICOS do produto (Simples/Base
# — feitos 1 vez só, nunca por fase). O progresso POR FASE (Roteiros/Completos de
# Diária/Semanal/Mensal) mora em PreparacaoVideoFase agora — model separado, 1 linha
# por fase, porque cada fase tem seu próprio pool de vídeo.

from django.db import models
from produtos.models import Produto


class StatusVideo(models.TextChoices):
    NAO_GERADO = 'nao_gerado', 'Não gerado'
    GERADO = 'gerado', 'Gerado'


class ProgressoProducaoVideo(models.Model):
    produto = models.OneToOneField(
        Produto, on_delete=models.CASCADE, related_name='progresso_producao_video')

    video_simples_status = models.CharField(
        max_length=15, choices=StatusVideo.choices, default=StatusVideo.NAO_GERADO)
    video_base_status = models.CharField(
        max_length=15, choices=StatusVideo.choices, default=StatusVideo.NAO_GERADO)

    # * [EXPLICAÇÃO] → Timestamp do momento exato do clique que marcou como
    #                  Gerado (26/07, linha do tempo completa) — None = nunca
    #                  marcado OU marcado antes desse rastreio existir (dado
    #                  legado, decisão: nunca inventar data pra ele).
    video_simples_marcado_em = models.DateTimeField(null=True, blank=True)
    video_base_marcado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Progresso de Produção de Vídeo'
        verbose_name_plural = 'Progressos de Produção de Vídeo'

    def __str__(self):
        return f'{self.produto.sku} — vídeo simples: {self.get_video_simples_status_display()}'