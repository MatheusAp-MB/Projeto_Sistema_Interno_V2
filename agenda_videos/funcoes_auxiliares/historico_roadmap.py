# agenda_videos/funcoes_auxiliares/historico_roadmap.py

# Função Objetivo: Monta os dados de histórico de 1 produto — usado tanto pelo
# modal individual (Formato A) quanto pela tela de relatório geral agrupada
# por produto (Formato B). 1 função só constrói o histórico, os 2 formatos
# reaproveitam ela — nunca duplicada.
# Reestruturação completa (30/07) — antes precisava juntar 3 tabelas
# (progresso/preparação por fase/postagem) pra montar a linha do tempo; agora
# cada CicloVideo já carrega, numa linha só, todos os timestamps do ciclo
# inteiro dele. O conceito de "gap" (marco concluído sem data) deixa de
# existir — não tem mais "fase pulada automaticamente" no agendamento, então
# toda etapa concluída sempre tem timestamp real, por construção.

from django.db.models import Q
from produtos.models import Produto
from agenda_videos.models import CicloVideo, StatusPostagem
from agenda_videos.funcoes_auxiliares.roadmap_produto import rotulo_rodada
from agenda_videos.funcoes_auxiliares.badges_agenda import BADGES_STATUS_POSTAGEM, BADGES_ETAPA, badge_de


# Função Objetivo: Monta a linha do tempo COMPLETA e ÚNICA de 1 produto —
# desde "Entrou na Agenda" até o evento mais recente, tudo misturado em
# ordem cronológica. Cada CicloVideo contribui com até 6 eventos (Base/
# Roteiro/Completo concluídos, Postado, Aprovado-ou-Recusado, Replicado).
def montar_linha_do_tempo_produto(produto):
    eventos = []

    participacao = getattr(produto, 'participacao_agenda', None)
    if participacao and participacao.agendado_em:
        eventos.append({
            'timestamp': participacao.agendado_em, 'label': 'Entrou na Agenda de Vídeos',
            'tipo': 'marco', 'icone': 'fa-calendar-check',
        })

    for ciclo in produto.ciclos_video.all():
        rotulo_base = rotulo_rodada(ciclo.fase, ciclo.numero_ocorrencia)

        if ciclo.base_concluido_em:
            eventos.append({
                'timestamp': ciclo.base_concluido_em, 'label': f'Base concluída ({rotulo_base})',
                'tipo': 'marco', 'icone': 'fa-video',
            })
        if ciclo.roteiro_concluido_em:
            eventos.append({
                'timestamp': ciclo.roteiro_concluido_em, 'label': f'Roteiro concluído ({rotulo_base})',
                'tipo': 'marco', 'icone': 'fa-pen',
            })
        if ciclo.completo_concluido_em:
            eventos.append({
                'timestamp': ciclo.completo_concluido_em, 'label': f'Completo concluído ({rotulo_base})',
                'tipo': 'marco', 'icone': 'fa-film',
            })
        if ciclo.aguardando_aprovacao_em:
            eventos.append({
                'timestamp': ciclo.aguardando_aprovacao_em, 'label': f'{rotulo_base} — Postado',
                'tipo': 'aguardando_aprovacao', 'icone': 'fa-upload',
            })
        if ciclo.aprovado_ou_recusado_em:
            if ciclo.status == StatusPostagem.RECUSADO:
                tipo, acao = 'recusado', 'Recusado'
            else:
                tipo, acao = 'aprovado', 'Aprovado'
            eventos.append({
                'timestamp': ciclo.aprovado_ou_recusado_em, 'label': f'{rotulo_base} — {acao}',
                'tipo': tipo, 'icone': 'fa-gavel',
            })
        if ciclo.replicado_em:
            eventos.append({
                'timestamp': ciclo.replicado_em, 'label': f'{rotulo_base} — Replicado',
                'tipo': 'replicado', 'icone': 'fa-copy',
                'mlbs_replicados': ciclo.mlbs_replicados, 'mlbs_nao_encontrados': ciclo.mlbs_nao_encontrados,
            })

    eventos.sort(key=lambda evento: evento['timestamp'])
    return {'eventos': eventos, 'aviso_gap': None}


# Função Objetivo: Monta o histórico completo (todas as fases/ocorrências) de
# 1 produto — SEMPRE completo, nunca filtrado, mesmo quando chamado a partir
# da tela com filtro ativo (o filtro estreita QUAIS produtos aparecem no
# relatório, nunca esconde ciclo de dentro de um produto já mostrado).
def montar_historico_produto(produto):
    ciclos = list(CicloVideo.objects.filter(produto=produto).order_by('-criado_em'))

    contagem_por_etapa = {}
    for ciclo in ciclos:
        etapa = ciclo.etapa_atual()
        # * [EXPLICAÇÃO] → Badge de status (Aguardando/Aprovado/Recusado/
        #                  Replicado) quando já tem status; senão, badge da
        #                  etapa de produção (Base/Roteiro/Completo).
        ciclo.badge = badge_de(BADGES_STATUS_POSTAGEM, ciclo.status) if ciclo.status else badge_de(BADGES_ETAPA, etapa)
        contagem_por_etapa[etapa] = contagem_por_etapa.get(etapa, 0) + 1

    resumo = [
        {
            'valor': etapa_valor,
            'label': BADGES_ETAPA[etapa_valor]['label'],
            'classe': BADGES_ETAPA[etapa_valor]['classe'],
            'quantidade': quantidade,
        }
        for etapa_valor, quantidade in contagem_por_etapa.items()
    ]

    linha_do_tempo = montar_linha_do_tempo_produto(produto)

    return {
        'produto': produto,
        'postagens': ciclos,  # nome mantido — o template ainda espera essa chave (Frente 4 renomeia)
        'total': len(ciclos),
        'resumo': resumo,
        'eventos': linha_do_tempo['eventos'],
        'aviso_gap': linha_do_tempo['aviso_gap'],
    }


# Função Objetivo: Busca de PRODUTOS que têm pelo menos 1 CicloVideo batendo
# com os filtros (fase/status/intervalo de data) + busca por nome/EAN/SKU.
# Devolve só os PRODUTOS — o conteúdo de cada um vem de
# montar_historico_produto, sempre completo.
def listar_produtos_com_historico(busca=None, filtros=None):
    filtros = filtros or {}

    ciclos = CicloVideo.objects.all()
    if filtros.get('fase'):
        ciclos = ciclos.filter(fase__in=filtros['fase'])
    if filtros.get('status'):
        ciclos = ciclos.filter(status__in=filtros['status'])
    if filtros.get('data_de'):
        ciclos = ciclos.filter(criado_em__date__gte=filtros['data_de'])
    if filtros.get('data_ate'):
        ciclos = ciclos.filter(criado_em__date__lte=filtros['data_ate'])

    ids_produtos = ciclos.values_list('produto_id', flat=True).distinct()
    produtos = Produto.objects.filter(id__in=ids_produtos)

    if filtros.get('urgente'):
        produtos = produtos.filter(participacao_agenda__urgente__in=[v == 'sim' for v in filtros['urgente']])
    if filtros.get('marcas'):
        produtos = produtos.filter(marca__in=filtros['marcas'])
    if filtros.get('status_manual'):
        produtos = produtos.filter(indicadores_agenda__status_manual__in=filtros['status_manual'])

    if busca:
        for termo in busca.split():
            produtos = produtos.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    return produtos.order_by('titulo')