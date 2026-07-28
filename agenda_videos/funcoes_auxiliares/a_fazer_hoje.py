# agenda_videos/funcoes_auxiliares/a_fazer_hoje.py

# Função Objetivo: Lista produtos "A Fazer Hoje" — puramente por ESTADO (ocorrência
# atual ainda não chegou em Replicado) + a janela dessa ocorrência já ter começado.
# Explicação em detalhe: atrasados aparecem de propósito (nunca somem da lista, são
# prioridade). "Risco de atraso" só existe pra Semanal/Mensal (Diária nunca tem, o
# dia inteiro já é a urgência — decisão do usuário).
#
# * [ATENÇÃO DE ESCALA] → Calculado em Python, não em SQL — aceitável pro volume
# atual (dezenas de produtos ativos na Agenda). Avaliado (26/07, pente fino) e
# mantido assim de propósito — reescrever pra SQL sem necessidade real hoje seria
# risco sem ganho.
#
# A regra de prioridade/ordenação de fase usada aqui é a MESMA da listagem
# principal, só que em Python — as 2 versões vivem em prioridade_agenda_videos.py.
#
# * [EXPLICAÇÃO] → Filtros novos (26/07): mesmos filtros da listagem principal
# (marca/status manual/urgente/sem vídeo/vídeo simples/vídeo base/status de
# postagem/atrasado/risco/vencimento/pendente agora) — todos aplicáveis aqui
# também, por pedido do usuário ("todos os filtros da tela geral devem poder
# ser aplicados aqui"). "Estágio" NÃO se aplica (A Fazer Hoje e Estágio já são
# caminhos mutuamente exclusivos, por design). Roteiros/Completos/Insuficientes/
# Qtd.Roteiros continuam FORA — mesma pendência de "filtros quebrados" da tela
# principal. As 9 categorias de "Pendente agora" têm a MESMA regra em SQL, na
# listagem principal (filtros_agenda_videos.py, OPCOES_PENDENTE_AGORA/
# _condicao_pendencia) — documentada cruzada, categoria nova? Bota nas 2.

from datetime import date, datetime
from django.db.models import Q
from produtos.models import Produto
from agenda_videos.models import Postagem, StatusPostagem, Fase, StatusVideo, VALIDADE_SNAPSHOT_DRIVE
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import (
    calcular_janela_ocorrencia, adicionar_dias_uteis, ultimo_dia_util_ou_hoje,
)
from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    calcular_indicador_pool_insuficiente, calcular_indicador_divergencia_fase_concluida,
)
from agenda_videos.funcoes_auxiliares.prioridade_agenda_videos import (
    calcular_prioridade_produto, calcular_ordem_fase_produto,
)
from agenda_videos.funcoes_auxiliares.diagnostico_preparo_drive import calcular_diagnostico_preparo_drive

DIAS_RISCO = 1  # "hoje e o próximo dia útil" — janela de risco de 1 dia útil à frente


def _parse_data_faixa(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


# Função Objetivo: Versão Python das MESMAS 9 categorias de "Pendente agora"
# que existem em SQL na listagem principal (ver filtros_agenda_videos.py).
# "preparacoes_video" precisa vir prefetched por quem chama (evita N+1).
def calcular_pendencias_atuais_produto(produto, andamento, postagem_atual):
    pendencias = set()
    progresso = getattr(produto, 'progresso_producao_video', None)
    preparacoes = {p.fase: p for p in produto.preparacoes_video.all()}
    fase_atual = andamento.fase_atual.fase

    prep_diaria = preparacoes.get(Fase.DIARIA)
    simples_base_prontos = (
        progresso is not None and
        progresso.video_simples_status == StatusVideo.GERADO and
        progresso.video_base_status == StatusVideo.GERADO
    )
    if simples_base_prontos and (prep_diaria is None or not prep_diaria.roteiros_gerados):
        pendencias.add('roteiros_diaria')
    elif prep_diaria and prep_diaria.roteiros_gerados and not prep_diaria.completos_produzidos:
        pendencias.add('completos_diaria')

    for fase, chave_roteiros, chave_completos in [
        (Fase.SEMANAL, 'roteiros_semanal', 'completos_semanal'),
        (Fase.MENSAL, 'roteiros_mensal', 'completos_mensal'),
    ]:
        if fase_atual != fase:
            continue
        prep = preparacoes.get(fase)
        if prep is None or not prep.roteiros_gerados:
            pendencias.add(chave_roteiros)
        elif not prep.completos_produzidos:
            pendencias.add(chave_completos)

    prep_atual = preparacoes.get(fase_atual)
    pool_pronto = prep_atual is not None and prep_atual.roteiros_gerados and prep_atual.completos_produzidos

    if postagem_atual is None:
        if pool_pronto:
            pendencias.add('aguardando_postar')
    elif postagem_atual.status == StatusPostagem.AGUARDANDO_APROVACAO:
        pendencias.add('aguardando_aprovacao')
    elif postagem_atual.status == StatusPostagem.RECUSADO:
        pendencias.add('recusado')

    return pendencias


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


def listar_a_fazer_hoje(busca=None, filtros=None, data_referencia=None):
    # * [EXPLICAÇÃO] → "data_referencia" existe só pra permitir simular outra data em
    #                  teste.py — a view real nunca passa esse parâmetro, sempre usa
    #                  a data de hoje de verdade.
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())
    filtros = filtros or {}

    vencimento_de = _parse_data_faixa(filtros.get('andamento_agenda__fim_ocorrencia_atual_min'))
    vencimento_ate = _parse_data_faixa(filtros.get('andamento_agenda__fim_ocorrencia_atual_max'))

    from agenda_videos.models import StatusManualAgenda

    candidatos = Produto.objects.filter(
        andamento_agenda__isnull=False, andamento_agenda__concluido=False,
        andamento_agenda__status_manual=StatusManualAgenda.ATIVO,
    ).select_related(
        'andamento_agenda', 'andamento_agenda__fase_atual', 'progresso_producao_video',
        'roadmap_agenda', 'snapshot_drive',
    ).prefetch_related('preparacoes_video')

    if busca:
        for termo in busca.split():
            candidatos = candidatos.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    if filtros.get('marcas'):
        candidatos = candidatos.filter(marca__in=filtros['marcas'])
    if filtros.get('status_manual'):
        candidatos = candidatos.filter(andamento_agenda__status_manual__in=filtros['status_manual'])
    if filtros.get('urgente'):
        candidatos = candidatos.filter(roadmap_agenda__urgente__in=[v == 'sim' for v in filtros['urgente']])
    if filtros.get('sem_video'):
        candidatos = candidatos.filter(roadmap_agenda__tem_video_reprovado__in=[v == 'sim' for v in filtros['sem_video']])
    if filtros.get('reestruturacao_manual'):
        candidatos = candidatos.filter(roadmap_agenda__reestruturacao_manual__in=[v == 'sim' for v in filtros['reestruturacao_manual']])
    if filtros.get('sincronizado_drive'):
        from django.utils import timezone as django_timezone
        limite_snapshot = django_timezone.now() - VALIDADE_SNAPSHOT_DRIVE
        condicao_sincronizado = Q(
            snapshot_drive__isnull=False, snapshot_drive__atualizado_em__gte=limite_snapshot,
        )
        valores = filtros['sincronizado_drive']
        if 'sim' in valores and 'nao' not in valores:
            candidatos = candidatos.filter(condicao_sincronizado)
        elif 'nao' in valores and 'sim' not in valores:
            candidatos = candidatos.exclude(condicao_sincronizado)
    if filtros.get('sincronizado_drive'):
        limite_snapshot = ultimo_dia_util_ou_hoje.__globals__['timezone'].now() - VALIDADE_SNAPSHOT_DRIVE if False else None
    if filtros.get('video_simples_status'):
        candidatos = candidatos.filter(progresso_producao_video__video_simples_status__in=filtros['video_simples_status'])
    if filtros.get('video_base_status'):
        candidatos = candidatos.filter(progresso_producao_video__video_base_status__in=filtros['video_base_status'])

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
        #                  é o mesmo template pros 2 modos. Aqui já vem escopado
        #                  certinho na ocorrência atual (postagem_atual acima),
        #                  diferente do status_postagem_recente da listagem
        #                  principal (que é o mais recente do produto inteiro).
        produto.status_postagem_recente = postagem_atual.status if postagem_atual else None
        calcular_indicadores_atraso(produto, andamento, data_referencia=hoje)

        if filtros.get('atrasado'):
            valores = filtros['atrasado']
            if 'sim' in valores and 'nao' not in valores and not produto.a_fazer_hoje_atrasado:
                continue
            if 'nao' in valores and 'sim' not in valores and produto.a_fazer_hoje_atrasado:
                continue
        if filtros.get('risco'):
            valores = filtros['risco']
            if 'sim' in valores and 'nao' not in valores and not produto.a_fazer_hoje_risco:
                continue
            if 'nao' in valores and 'sim' not in valores and produto.a_fazer_hoje_risco:
                continue
        if filtros.get('status_postagem') and produto.status_postagem_recente not in filtros['status_postagem']:
            continue
        if vencimento_de and produto.a_fazer_hoje_vencimento < vencimento_de:
            continue
        if vencimento_ate and produto.a_fazer_hoje_vencimento > vencimento_ate:
            continue

        if filtros.get('pendente_agora'):
            pendencias = calcular_pendencias_atuais_produto(produto, andamento, postagem_atual)
            if not pendencias.intersection(filtros['pendente_agora']):
                continue

        produto.pool_insuficiente_tipo = calcular_indicador_pool_insuficiente(produto, andamento)
        produto.divergencia_fase_concluida = calcular_indicador_divergencia_fase_concluida(produto, andamento)
        produto.diagnostico_drive = calcular_diagnostico_preparo_drive(produto)
        resultado.append(produto)

    # * [EXPLICAÇÃO] → Mesma prioridade da listagem principal (ver
    #                  prioridade_agenda_videos.py — versão Python, calculada aqui
    #                  por causa da janela de ocorrência):
    #                  1. Urgente  2. Atrasado  3. Sem vídeo (UP_HAS_SHORTS)  4. Resto.
    for produto in resultado:
        produto.prioridade_ordenacao = calcular_prioridade_produto(produto)
        produto.ordenacao_fase = calcular_ordem_fase_produto(produto)

    resultado.sort(key=lambda p: (p.prioridade_ordenacao, p.ordenacao_fase, p.a_fazer_hoje_vencimento))
    return resultado