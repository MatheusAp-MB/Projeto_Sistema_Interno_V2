# agenda_videos/models/execucao_postagem_automatica.py

# Função Objetivo: Representa 1 "rodada" de Postagem Autônoma — desde o
# clique em "Iniciar" até o fim (concluída ou cancelada). Existe pra a tela
# de progresso conseguir perguntar "como está indo?" sem precisar de acesso
# direto à thread em segundo plano — o status aqui é sempre a fonte de
# verdade que a tela lê via polling.

from django.db import models


class StatusExecucao(models.TextChoices):
    AGUARDANDO_INICIO = 'aguardando_inicio', 'Aguardando você pressionar F8'
    RODANDO = 'rodando', 'Rodando'
    PAUSADO = 'pausado', 'Pausado'
    CANCELADO = 'cancelado', 'Cancelado'
    CONCLUIDO = 'concluido', 'Concluído'


class ExecucaoPostagemAutomatica(models.Model):
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=StatusExecucao.choices, default=StatusExecucao.AGUARDANDO_INICIO,
    )

    class Meta:
        verbose_name = 'Execução de Postagem Automática'
        verbose_name_plural = 'Execuções de Postagem Automática'
        ordering = ['-iniciado_em']

    def __str__(self):
        return f'Execução #{self.id} — {self.get_status_display()} ({self.iniciado_em:%d/%m/%Y %H:%M})'