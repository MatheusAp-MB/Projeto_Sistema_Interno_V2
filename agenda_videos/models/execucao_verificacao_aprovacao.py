# agenda_videos/models/execucao_verificacao_aprovacao.py

# Função Objetivo: Representa 1 "rodada" de Verificação de Aprovação —
# mesma estrutura de ExecucaoReplicacaoAutomatica (heartbeat, status
# compartilhado), só que pro fluxo de ler o estado (Estado) de cada
# anúncio na tela do Mercado Livre e aplicar a mudança de status na agenda.

from django.db import models
from .status_execucao import StatusExecucao


class ExecucaoVerificacaoAprovacao(models.Model):
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=StatusExecucao.choices, default=StatusExecucao.AGUARDANDO_INICIO,
    )
    # * [EXPLICAÇÃO] → Mesmo mecanismo de "batimento cardíaco" já validado na
    #                  Postagem/Replicação Automática — o Django nunca
    #                  consegue "ir lá" checar se o agente ainda está vivo;
    #                  só percebe o silêncio.
    ultimo_heartbeat_agente = models.DateTimeField(null=True, blank=True)

    LIMITE_SEGUNDOS_SEM_HEARTBEAT = 30

    @property
    def travada(self):
        from django.utils import timezone
        if self.status not in (StatusExecucao.RODANDO, StatusExecucao.PAUSADO):
            return False
        referencia = self.ultimo_heartbeat_agente or self.iniciado_em
        segundos_sem_noticia = (timezone.now() - referencia).total_seconds()
        return segundos_sem_noticia > self.LIMITE_SEGUNDOS_SEM_HEARTBEAT

    class Meta:
        verbose_name = 'Execução de Verificação de Aprovação'
        verbose_name_plural = 'Execuções de Verificação de Aprovação'
        ordering = ['-iniciado_em']

    def __str__(self):
        return f'Execução Verificação #{self.id} — {self.get_status_display()} ({self.iniciado_em:%d/%m/%Y %H:%M})'