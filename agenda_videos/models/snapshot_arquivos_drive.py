# agenda_videos/models/snapshot_arquivos_drive.py

# Função Objetivo: Guarda o resultado da ÚLTIMA varredura do Google Drive pra
# 1 produto — nomes+IDs brutos de Videos/ e Videos/usados/, sem interpretação
# nenhuma (a interpretação — parsear em ArquivosProdutoDrive — é feita na
# hora de exibir, sempre em cima deste dado salvo, nunca ao vivo no Drive).
#
# ⚠️ ATENÇÃO — isso é CÓPIA da última varredura, nunca a fonte real (a fonte
# real é o próprio Drive). Tem validade: passado VALIDADE_SNAPSHOT_DRIVE
# desde a última atualização, considera-se "não sincronizado" — ver
# propriedade `expirado`. Atualizado por 2 caminhos: a varredura completa
# (escanear_drive_completo.py, roda pra todo produto de uma vez) e a
# verificação individual (verificar_arquivos_drive.py, roda pra 1 produto
# só) — dado da API é caro, nunca descartado depois de usado 1 vez.

from datetime import timedelta
from django.db import models
from django.utils import timezone
from produtos.models import Produto

VALIDADE_SNAPSHOT_DRIVE = timedelta(hours=8)


class SnapshotArquivosDrive(models.Model):
    produto = models.OneToOneField(Produto, on_delete=models.CASCADE, related_name='snapshot_drive')

    pasta_encontrada = models.BooleanField(default=False)
    motivo_nao_encontrado = models.CharField(max_length=255, blank=True, null=True)

    # * [EXPLICAÇÃO] → ID das pastas Videos/ e Videos/usados/ no Drive
    #                  (20/08/2026) — guardado pra montar link direto pra
    #                  pasta (Portal do Drive, "Abrir pasta no Drive") sem
    #                  precisar de chamada ao vivo só pra redescobrir o ID.
    #                  Vazio quando a pasta correspondente não existe.
    pasta_videos_id = models.CharField(max_length=255, blank=True, default='')
    pasta_usados_id = models.CharField(max_length=255, blank=True, default='')

    # * [EXPLICAÇÃO] → Lista bruta de {"id":..., "name":...}, igual ao que a
    #                  API do Drive devolve — sem interpretação nenhuma ainda
    #                  (isso é papel do parser, sempre recalculado na hora de
    #                  exibir, nunca guardado já processado).
    arquivos_videos = models.JSONField(default=list)
    arquivos_usados = models.JSONField(default=list)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Snapshot de Arquivos do Drive'
        verbose_name_plural = 'Snapshots de Arquivos do Drive'

    @property
    def expirado(self):
        return timezone.now() - self.atualizado_em > VALIDADE_SNAPSHOT_DRIVE

    def __str__(self):
        return f'{self.produto.ean} — atualizado em {self.atualizado_em:%d/%m/%Y %H:%M}'