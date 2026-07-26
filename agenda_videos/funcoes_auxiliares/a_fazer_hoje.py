# agenda_videos/funcoes_auxiliares/a_fazer_hoje.py

# Função Objetivo: Lista produtos "A Fazer Hoje" — puramente por ESTADO (ocorrência
# atual ainda não chegou em Replicado) + a janela dessa ocorrência já ter começado.
# Explicação em detalhe: atrasados aparecem de propósito (nunca somem da lista, são
# prioridade). "Risco de atraso" só existe pra Semanal/Mensal (Diária nunca tem, o
# dia inteiro já é a urgência — decisão do usuário).
#
# * [ATENÇÃO DE ESCALA] → Calculado em Python, não em SQL — aceitável pro volume
# atual (dezenas de produtos ativos na Agenda), mas escala mal se isso crescer pra
# milhares (1 query de Postagem por produto candidato). Se o volume crescer muito,
# revisar pra Subquery/annotate, mesmo padrão já usado pro status de Postagem
# recente na listagem principal.

from datetime import date
from django.db.models import Q
from produtos.models import Produto
from agenda_videos.models import Postagem, StatusPostagem, Fase
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import (
    calcular_janela_ocorrencia, adicionar_dias_uteis, ultimo_dia_util_ou_hoje,
)
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_indicador_pool_insuficiente

DIAS_RISCO = 1  # "hoje e o próximo dia útil" — janela de risco de 1 dia útil à frente


# Função Objetivo: Calcula e anexa os 3 indicadores de atraso/risco em 1 produto só.
# Explicação em detalhe: extraído (25/07) pra ser reaproveitado também depois de
# qualquer clique no roadmap — sem isso, o produto buscado "do zero" nas views de
# ação nunca tinha esses atributos calculados, e o badge sumia da resposta do
# clique mesmo que estivesse visível na lista antes.
def calcular_indicadores_atraso(produto, andamento, data_referencia=None):
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())
    limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
    fase = andamento.fase_atual.fase
    janela = calcular_janela_ocorrencia(fase, andamento.inicio_fase, andamento.ocorrencia_atual)

    produto.a_fazer_hoje_atrasado = janela.fim < hoje
    produto.a_fazer_hoje_risco = (
        not produto.a_fazer_hoje_atrasado and fase != Fase.DIARIA and janela.fim <= limite_risco
    )
    produto.a_fazer_hoje_vencimento = janela.fim
    return janela


def listar_a_fazer_hoje(busca=None, data_referencia=None):
    # * [EXPLICAÇÃO] → "data_referencia" existe só pra permitir simular outra data em
    #                  teste.py — a view real nunca passa esse parâmetro, sempre usa
    #                  a data de hoje de verdade.
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())

    from agenda_videos.models import StatusManualAgenda

    candidatos = Produto.objects.filter(
        andamento_agenda__isnull=False, andamento_agenda__concluido=False,
        andamento_agenda__status_manual=StatusManualAgenda.ATIVO,
    ).select_related(
        'andamento_agenda', 'andamento_agenda__fase_atual', 'progresso_producao_video', 'roadmap_agenda',
    )

    if busca:
        for termo in busca.split():
            candidatos = candidatos.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    resultado = []
    for produto in candidatos:
        andamento = produto.andamento_agenda
        fase = andamento.fase_atual.fase
        janela = calcular_janela_ocorrencia(fase, andamento.inicio_fase, andamento.ocorrencia_atual)

        if hoje < janela.inicio:
            continue  # ainda não chegou a vez dessa ocorrência

        postagem_atual = Postagem.objects.filter(
            produto=produto, fase=fase, numero_ocorrencia=andamento.ocorrencia_atual,
        ).order_by('-criado_em').first()

        if postagem_atual is not None and postagem_atual.status == StatusPostagem.REPLICADO:
            continue  # essa ocorrência já foi concluída, não aparece mais

        # * [EXPLICAÇÃO] → "status_postagem_recente" precisa existir aqui TAMBÉM
        #                  (não só na listagem normal, que usa annotate/Subquery) —
        #                  é o mesmo template pros 2 modos.
        produto.status_postagem_recente = postagem_atual.status if postagem_atual else None
        calcular_indicadores_atraso(produto, andamento, data_referencia=hoje)
        produto.pool_insuficiente_tipo = calcular_indicador_pool_insuficiente(produto, andamento)
        resultado.append(produto)

    # * [EXPLICAÇÃO] → Mesma prioridade da listagem principal, calculada em Python
    #                  aqui (já era assim — essa função nunca virou queryset puro,
    #                  por causa do cálculo de janela por ocorrência):
    #                  1. Urgente  2. Atrasado  3. Sem vídeo (UP_HAS_SHORTS)  4. Resto.
    for produto in resultado:
        produto.prioridade_ordenacao = _calcular_prioridade(produto)
        produto.ordenacao_fase = _calcular_ordem_fase(produto)

    resultado.sort(key=lambda p: (p.prioridade_ordenacao, p.ordenacao_fase, p.a_fazer_hoje_vencimento))
    return resultado


# Função Objetivo: Mesmo grupo de fase da listagem principal — Diária → Semanal
# → Mensal, grupo intermediário (não critério), entre prioridade e vencimento.
MAPA_ORDEM_FASE = {'diaria': 1, 'semanal': 2, 'mensal': 3}


def _calcular_ordem_fase(produto):
    andamento = getattr(produto, 'andamento_agenda', None)
    if andamento is None:
        return 4
    return MAPA_ORDEM_FASE.get(andamento.fase_atual.fase, 4)


# Função Objetivo: Mesma regra de prioridade da listagem principal — 6 níveis,
# cruzando Urgente/Atrasado com "Sem vídeo" (um Urgente sem vídeo é mais crítico
# que um Urgente comum, mesma lógica pra Atrasado):
#   1. Urgente + Sem vídeo    2. Urgente
#   3. Atrasado + Sem vídeo   4. Atrasado
#   5. Sem vídeo              6. Resto
def _calcular_prioridade(produto):
    roadmap_agenda = getattr(produto, 'roadmap_agenda', None)
    urgente = roadmap_agenda is not None and roadmap_agenda.urgente
    sem_video = roadmap_agenda is not None and roadmap_agenda.tem_video_reprovado
    atrasado = produto.a_fazer_hoje_atrasado

    if urgente and sem_video:
        return 1
    if urgente:
        return 2
    if atrasado and sem_video:
        return 3
    if atrasado:
        return 4
    if sem_video:
        return 5
    return 6