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
    # * [EXPLICAÇÃO] → "Batimento cardíaco" do agente (29/07) — o Django
    #                  nunca consegue "ir lá" checar se o agente ainda está
    #                  vivo (não tem como alcançar a máquina dele, ainda
    #                  mais uma vez na AWS). Em vez disso, o AGENTE avisa
    #                  periodicamente "ainda aqui" — o Django só percebe o
    #                  silêncio (ver propriedade `travada`), nunca pergunta
    #                  ativamente.
    ultimo_heartbeat_agente = models.DateTimeField(null=True, blank=True)

    # * [EXPLICAÇÃO] → Generoso o bastante pra sobreviver uma variação normal
    #                  de rede (download de vídeo grande, por exemplo), mas
    #                  curto o bastante pra detectar rápido um agente
    #                  realmente morto/fechado no meio do processo.
    LIMITE_SEGUNDOS_SEM_HEARTBEAT = 30

    @property
    def travada(self):
        from django.utils import timezone
        if self.status not in (StatusExecucao.RODANDO, StatusExecucao.PAUSADO):
            return False

        # * [EXPLICAÇÃO] → Corrigido (30/07) — "nunca recebi heartbeat" NÃO
        #                  significa "ainda não começou" (isso já é avisado
        #                  em outro lugar, quando status ainda é
        #                  Aguardando Início). Se o status já virou Rodando
        #                  mas o heartbeat nunca chegou, conta a partir de
        #                  QUANDO A EXECUÇÃO COMEÇOU, não trata como "tudo
        #                  bem" pra sempre — foi exatamente esse o caso
        #                  real encontrado (placeholder rápido demais pra
        #                  a 1ª thread de heartbeat, de 10 em 10s, disparar
        #                  sequer 1 vez antes do processamento acabar).
        referencia = self.ultimo_heartbeat_agente or self.iniciado_em
        segundos_sem_noticia = (timezone.now() - referencia).total_seconds()
        return segundos_sem_noticia > self.LIMITE_SEGUNDOS_SEM_HEARTBEAT

    class Meta:
        verbose_name = 'Execução de Postagem Automática'
        verbose_name_plural = 'Execuções de Postagem Automática'
        ordering = ['-iniciado_em']

    def __str__(self):
        return f'Execução #{self.id} — {self.get_status_display()} ({self.iniciado_em:%d/%m/%Y %H:%M})'