# agenda_videos/funcoes_auxiliares/postagem_ciclica.py

# Função Objetivo: Ações compartilhadas entre o clique manual (views.py) e a
# Postagem Automática (orquestrador) — fonte única, nunca duplicada nos 2
# lugares. Reestruturação completa (30/07): o CicloVideo da ocorrência atual
# já existe ANTES de postar — "postar" é só marcar esse registro existente,
# nunca criar um novo (diferente de como funcionava antes).

import datetime
from datetime import date

from django.db.models import Exists, OuterRef
from django.utils import timezone

from agenda_videos.models import CicloVideo


# Função Objetivo: Trava de segurança — "1 vídeo por dia por produto,
# sempre" (regra do usuário, 28/07). Confere se JÁ existe CicloVideo marcado
# como postado HOJE (dia real do calendário) pra esse produto — protege
# contra duplo-clique, 2ª rodada de Postagem Automática no mesmo dia, ou
# aprovar+replicar rápido demais fazendo o produto "voltar" a ficar elegível
# ainda no mesmo dia.
def ja_postou_hoje(produto, data_referencia=None):
    dia = data_referencia or timezone.localtime(timezone.now()).date()
    inicio_do_dia = timezone.make_aware(datetime.datetime.combine(dia, datetime.time.min))
    fim_do_dia = timezone.make_aware(datetime.datetime.combine(dia, datetime.time.max))
    return CicloVideo.objects.filter(
        produto=produto, aguardando_aprovacao_em__gte=inicio_do_dia, aguardando_aprovacao_em__lte=fim_do_dia,
    ).exists()


# Função Objetivo: Marca o CicloVideo ATUAL do produto como postado.
def marcar_ciclo_atual_aguardando_aprovacao(produto, mlb_postado=None):
    ciclo = produto.ciclos_video.first()  # já ordenado por -criado_em
    ciclo.marcar_aguardando_aprovacao(mlb_postado=mlb_postado)
    return ciclo


# Função Objetivo: Condição SQL "já postou hoje" — pra filtrar queryset.
# Espelha ja_postou_hoje() acima: mudou a regra, mexe nas 2 juntas.
def construir_condicao_postou_hoje(data_referencia: date | None = None) -> Exists:
    dia = data_referencia or timezone.localtime(timezone.now()).date()
    inicio_do_dia = timezone.make_aware(datetime.datetime.combine(dia, datetime.time.min))
    fim_do_dia = timezone.make_aware(datetime.datetime.combine(dia, datetime.time.max))
    return Exists(CicloVideo.objects.filter(
        produto=OuterRef('pk'), aguardando_aprovacao_em__gte=inicio_do_dia, aguardando_aprovacao_em__lte=fim_do_dia,
    ))