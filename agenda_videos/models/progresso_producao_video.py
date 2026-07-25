# agenda_videos/models/progresso_producao_video.py

# Função Objetivo: Rastreia o progresso de produção dos ativos de vídeo de 1 produto.
# Explicação em detalhe: 1 registro por Produto, nunca reinicia — diferente de Postagem
# (histórico por ocorrência). Vídeo Simples (Objetivo 01, anúncio mínimo) e Vídeo Base
# (usado pros roteiros/Completos da Agenda) são conceitos DIFERENTES e propositalmente
# separados — confirmado com o usuário: nem sempre o Simples vira a Base; às vezes a
# equipe grava um Base novo e mais detalhado.

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

    roteiros_gerados = models.BooleanField(default=False)
    completos_produzidos = models.BooleanField(default=False)

    # * [EXPLICAÇÃO] → Tamanho do "pool" de vídeos Completos disponíveis (ex: 10, 1 por
    #                  dia da Fase Diária). Comparado contra ConfiguracaoFase.quantidade_postagens
    #                  na hora de exibir o aviso "roteiros insuficientes" — não é campo de
    #                  aviso persistido, é só o dado bruto pra essa conta ser feita na hora.
    quantidade_roteiros = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Progresso de Produção de Vídeo'
        verbose_name_plural = 'Progressos de Produção de Vídeo'

    def __str__(self):
        return f'{self.produto.sku} — vídeo simples: {self.get_video_simples_status_display()}'