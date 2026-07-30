# agenda_videos/funcoes_auxiliares/postagem_ciclica.py

# Função Objetivo: Cria a Postagem inicial (Aguardando Aprovação) pra 1
# produto, na ocorrência atual do AndamentoAgenda — fonte única, reaproveitada
# pelo clique manual (views.py — Postar e Nova Tentativa, que tinham essa
# mesma criação duplicada) e pela Postagem Automática (orquestrador).

import datetime
from django.utils import timezone
from agenda_videos.models import Postagem, StatusPostagem
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia


# Função Objetivo: Trava de segurança — "1 vídeo por dia por produto,
# sempre" (regra do usuário, 28/07). Confere se JÁ existe Postagem criada
# HOJE (dia real do calendário) pra esse produto, não importa a ocorrência —
# protege contra duplo-clique, 2ª rodada de Postagem Automática no mesmo
# dia, ou aprovar+replicar rápido demais fazendo o produto "voltar" a ficar
# elegível ainda no mesmo dia.
# * [EXPLICAÇÃO] → Aceita data_referencia (29/07) — pro mesmo motivo de todo
#                  outro cálculo de "hoje" na Agenda: se a tela está
#                  simulando outra data, essa checagem precisa respeitar a
#                  mesma simulação, não silenciosamente usar a data real por
#                  baixo. A Postagem Automática, por decisão já tomada, nunca
#                  passa data_referencia — sempre usa a real.
def ja_postou_hoje(produto, data_referencia=None):
    # * [EXPLICAÇÃO] → Corrigido (29/07) — NÃO usa mais "__date" (esse lookup
    #                  depende do MySQL saber converter fuso horário via
    #                  CONVERT_TZ(), que exige as tabelas de fuso carregadas
    #                  no servidor — comuns de faltar no Windows. Sem elas,
    #                  o MySQL devolve NULL silenciosamente, e a comparação
    #                  NUNCA bate com nada, sem erro nenhum aparecer. Em vez
    #                  disso, calcula o intervalo do dia inteiro em PYTHON
    #                  (já no fuso certo) e compara contra o datetime bruto —
    #                  nenhuma conversão de fuso acontece dentro do banco.
    dia = data_referencia or timezone.localtime(timezone.now()).date()
    inicio_do_dia = timezone.make_aware(datetime.datetime.combine(dia, datetime.time.min))
    fim_do_dia = timezone.make_aware(datetime.datetime.combine(dia, datetime.time.max))
    return Postagem.objects.filter(
        produto=produto, aguardando_aprovacao_em__gte=inicio_do_dia, aguardando_aprovacao_em__lte=fim_do_dia,
    ).exists()


def criar_postagem_aguardando_aprovacao(produto, andamento):
    agora = timezone.now()
    fase = andamento.fase_atual.fase
    janela = calcular_janela_ocorrencia(fase, andamento.inicio_fase, andamento.ocorrencia_atual)
    return Postagem.objects.create(
        produto=produto, fase=fase, numero_ocorrencia=andamento.ocorrencia_atual,
        inicio_ocorrencia=janela.inicio, fim_ocorrencia=janela.fim,
        status=StatusPostagem.AGUARDANDO_APROVACAO, aguardando_aprovacao_em=agora,
    )