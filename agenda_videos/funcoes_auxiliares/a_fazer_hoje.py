# agenda_videos/funcoes_auxiliares/a_fazer_hoje.py

# Função Objetivo: Lista produtos "A Fazer Hoje" — pelo estado do CicloVideo
# mais recente de cada produto (ainda não concluído).
# Reestruturação completa (30/07) — antes precisava juntar 3 tabelas pra saber
# a pendência (progresso/preparação/andamento); agora é só o CicloVideo mais
# recente. "Pool insuficiente" e "Divergência de fase concluída" deixaram de
# existir (não tem mais pool reaproveitado pra ficar insuficiente).
#
# * [ATENÇÃO DE ESCALA] → Calculado em Python, não em SQL — mesma decisão de
# sempre (volume pequeno, dezenas de produtos ativos na Agenda).
#
# * [PENDENTE] → Diagnóstico do Drive (calcular_diagnostico_preparo_drive)
# removido daqui por enquanto (30/07) — a estrutura de pastas/nomes de
# arquivo no Drive ainda assume 1 vídeo por FASE, não por ocorrência. Precisa
# de conversa própria antes de reimplementar. produto.diagnostico_drive fica
# sempre None até lá.

from datetime import date, datetime
from django.db.models import Q
from produtos.models import Produto
from agenda_videos.models import StatusManualAgenda, VALIDADE_SNAPSHOT_DRIVE
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import adicionar_dias_uteis, ultimo_dia_util_ou_hoje
from agenda_videos.funcoes_auxiliares.prioridade_agenda_videos import (
    calcular_prioridade_produto, calcular_ordem_fase_produto,
)
from agenda_videos.funcoes_auxiliares.postagem_ciclica import ja_postou_hoje

DIAS_RISCO = 1  # "hoje e o próximo dia útil" — janela de risco de 1 dia útil à frente
ETAPAS_EM_PRODUCAO = {'base', 'roteiro', 'completo'}


def _parse_data_faixa(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


# Função Objetivo: Calcula os indicadores de 1 produto a partir do CicloVideo
# mais recente — atrasado, risco, vencimento e fase, tudo numa função só
# (antes vinham de 3 tabelas diferentes).
def calcular_indicadores_ciclo(produto, ciclo, data_referencia=None):
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())
    limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
    etapa = ciclo.etapa_atual()

    produto.a_fazer_hoje_atrasado = ciclo.esta_atrasado()
    # * [EXPLICAÇÃO] → Risco redefinido (30/07, pedido do usuário): não é mais
    #                  "a janela tá acabando" (não existe mais janela de
    #                  vários dias — toda fase agora é 1 dia exato, como a
    #                  Diária antiga) — é "a produção ainda não terminou e o
    #                  prazo pra postar tá perto". Avisa o pool não estar
    #                  pronto a tempo, antes de virar atraso de verdade.
    produto.a_fazer_hoje_risco = (
        not produto.a_fazer_hoje_atrasado
        and etapa in ETAPAS_EM_PRODUCAO
        and ciclo.data_devida <= limite_risco
    )
    produto.a_fazer_hoje_vencimento = ciclo.data_devida
    produto.a_fazer_hoje_fase = ciclo.fase
    return etapa


def listar_a_fazer_hoje(busca=None, filtros=None, data_referencia=None):
    # * [EXPLICAÇÃO] → "data_referencia" existe só pra permitir simular outra
    #                  data em teste — a view real nunca passa, sempre usa a
    #                  data de hoje de verdade.
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())
    filtros = filtros or {}

    vencimento_de = _parse_data_faixa(filtros.get('vencimento_min'))
    vencimento_ate = _parse_data_faixa(filtros.get('vencimento_max'))

    candidatos = Produto.objects.filter(
        ciclos_video__isnull=False,
    ).exclude(
        indicadores_agenda__status_manual__in=[StatusManualAgenda.PAUSADO, StatusManualAgenda.DESCONTINUADO],
    ).select_related(
        'participacao_agenda', 'indicadores_agenda', 'snapshot_drive',
    ).prefetch_related('ciclos_video').distinct()

    if busca:
        for termo in busca.split():
            candidatos = candidatos.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    if filtros.get('marcas'):
        candidatos = candidatos.filter(marca__in=filtros['marcas'])
    if filtros.get('status_manual'):
        candidatos = candidatos.filter(indicadores_agenda__status_manual__in=filtros['status_manual'])
    if filtros.get('urgente'):
        candidatos = candidatos.filter(participacao_agenda__urgente__in=[v == 'sim' for v in filtros['urgente']])
    if filtros.get('sem_video'):
        candidatos = candidatos.filter(
            indicadores_agenda__tem_video_reprovado__in=[v == 'sim' for v in filtros['sem_video']])
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

    resultado = []
    for produto in candidatos:
        ciclos = list(produto.ciclos_video.all())  # já ordenado por -criado_em (prefetch)
        ciclo_atual = ciclos[0] if ciclos else None
        if ciclo_atual is None or ciclo_atual.etapa_atual() == 'concluido':
            continue  # nada pendente nesse produto agora

        etapa = calcular_indicadores_ciclo(produto, ciclo_atual, data_referencia=hoje)

        # * [EXPLICAÇÃO] → "Postar" é a ÚNICA etapa com trava de data — Base/
        #                  Roteiro/Completo podem ser feitos com antecedência
        #                  (decisão confirmada), nunca escondidos por data.
        if etapa == 'postar' and hoje < ciclo_atual.data_devida:
            continue

        produto.pendencia_atual = etapa
        produto.ja_postou_hoje = ja_postou_hoje(produto, data_referencia=hoje)
        # * [EXPLICAÇÃO] → "1 vídeo por dia por produto" (28/07) — fonte única
        #                  usada pela tela humana e pela Postagem Automática.
        if etapa == 'postar' and produto.ja_postou_hoje:
            continue

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
        if filtros.get('pendente_agora') and etapa not in filtros['pendente_agora']:
            continue
        if vencimento_de and produto.a_fazer_hoje_vencimento < vencimento_de:
            continue
        if vencimento_ate and produto.a_fazer_hoje_vencimento > vencimento_ate:
            continue

        participacao = getattr(produto, 'participacao_agenda', None)
        produto.urgente = participacao is not None and participacao.urgente
        indicadores = getattr(produto, 'indicadores_agenda', None)
        produto.sem_video = indicadores is not None and indicadores.tem_video_reprovado

        # * [PENDENTE] → ver cabeçalho do arquivo.
        produto.diagnostico_drive = None

        resultado.append(produto)

    for produto in resultado:
        produto.prioridade_ordenacao = calcular_prioridade_produto(produto)
        produto.ordenacao_fase = calcular_ordem_fase_produto(produto)

    resultado.sort(key=lambda p: (p.prioridade_ordenacao, p.ordenacao_fase, p.a_fazer_hoje_vencimento))
    return resultado