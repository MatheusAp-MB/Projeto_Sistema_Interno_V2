# agenda_videos/models/status_execucao.py

# Função Objetivo: Estados de "execução" (Postagem ou Replicação Automática)
# — extraído (30/07) de dentro de execucao_postagem_automatica.py pra ser
# compartilhado — a máquina de estados (Aguardando Início/Rodando/Pausado/
# Cancelado/Concluído) é idêntica nos 2 fluxos, não faz sentido duplicar.

from django.db import models


class StatusExecucao(models.TextChoices):
    AGUARDANDO_INICIO = 'aguardando_inicio', 'Aguardando você pressionar F8'
    RODANDO = 'rodando', 'Rodando'
    PAUSADO = 'pausado', 'Pausado'
    CANCELADO = 'cancelado', 'Cancelado'
    CONCLUIDO = 'concluido', 'Concluído'