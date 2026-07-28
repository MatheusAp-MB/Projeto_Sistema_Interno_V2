# agenda_videos/funcoes_auxiliares/postagem_ciclica.py

# Função Objetivo: Cria a Postagem inicial (Aguardando Aprovação) pra 1
# produto, na ocorrência atual do AndamentoAgenda — fonte única, reaproveitada
# pelo clique manual (views.py — Postar e Nova Tentativa, que tinham essa
# mesma criação duplicada) e pela Postagem Automática (orquestrador).

from django.utils import timezone
from agenda_videos.models import Postagem, StatusPostagem
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia


def criar_postagem_aguardando_aprovacao(produto, andamento):
    agora = timezone.now()
    fase = andamento.fase_atual.fase
    janela = calcular_janela_ocorrencia(fase, andamento.inicio_fase, andamento.ocorrencia_atual)
    return Postagem.objects.create(
        produto=produto, fase=fase, numero_ocorrencia=andamento.ocorrencia_atual,
        inicio_ocorrencia=janela.inicio, fim_ocorrencia=janela.fim,
        status=StatusPostagem.AGUARDANDO_APROVACAO, aguardando_aprovacao_em=agora,
    )