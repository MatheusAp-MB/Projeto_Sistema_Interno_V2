# agenda_videos/funcoes_auxiliares/historico_roadmap.py

# Função Objetivo: Monta os dados de histórico de 1 produto — usado tanto pelo
# modal individual (Formato A) quanto pela tela de relatório geral agrupada
# por produto (Formato B). 1 função só constrói o histórico, os 2 formatos
# reaproveitam ela — nunca duplicada.
# Renomeado (26/07) de historico_postagens.py — o escopo cresceu pra linha do
# tempo completa (marcos de preparação + postagens), "postagens" ficou pequeno
# demais pro que o arquivo realmente faz.

from django.db.models import Q
from produtos.models import Produto
from agenda_videos.models import Postagem, StatusPostagem, StatusVideo
from agenda_videos.funcoes_auxiliares.badges_agenda import BADGES_STATUS_POSTAGEM, badge_de


# Função Objetivo: Monta a linha do tempo COMPLETA e ÚNICA de 1 produto —
# desde o Vídeo Simples até o fim do ciclo, tudo misturado em ordem
# cronológica (26/07, "toda ação feita é rastreada de ponta a ponta" — não é
# uma seção separada de marcos + outra de postagens, é 1 trilha só).
# Explicação em detalhe: cada Postagem contribui com ATÉ 3 linhas separadas
# (Postado/Aprovado-ou-Recusado/Replicado), cada uma com seu próprio horário
# — diferente do card agrupado que a tela ainda usa pro resumo de contagem.
# "Gap" (marco já concluído mas sem data) só conta pra quem JÁ aconteceu —
# uma etapa que o produto ainda nem chegou nunca gera aviso.
def montar_linha_do_tempo_produto(produto):
    eventos = []
    tem_gap = False
    marcos_presentes = 0

    def _adicionar_marco(ja_concluido, timestamp, label, icone):
        nonlocal tem_gap, marcos_presentes
        if not ja_concluido:
            return
        if timestamp:
            eventos.append({'timestamp': timestamp, 'label': label, 'tipo': 'marco', 'icone': icone})
            marcos_presentes += 1
        else:
            # * [EXPLICAÇÃO] → Sem timestamp mas já concluído = ou é dado
            #                  legado (marcado antes do rastreio existir), ou
            #                  foi uma fase PULADA no agendamento (marcado
            #                  automaticamente, nunca teve clique real) — nos
            #                  2 casos, nunca inventamos uma data.
            tem_gap = True

    progresso = getattr(produto, 'progresso_producao_video', None)
    if progresso:
        _adicionar_marco(
            progresso.video_simples_status == StatusVideo.GERADO,
            progresso.video_simples_marcado_em, 'Vídeo Simples gerado', 'fa-video',
        )
        _adicionar_marco(
            progresso.video_base_status == StatusVideo.GERADO,
            progresso.video_base_marcado_em, 'Vídeo Base gerado', 'fa-video',
        )

    for preparacao in produto.preparacoes_video.all():
        fase_label = preparacao.get_fase_display()
        _adicionar_marco(
            preparacao.roteiros_gerados,
            preparacao.roteiros_marcado_em, f'Roteiros gerados ({fase_label})', 'fa-pen',
        )
        _adicionar_marco(
            preparacao.completos_produzidos,
            preparacao.completos_marcado_em, f'Vídeos completos gerados ({fase_label})', 'fa-film',
        )

    andamento = getattr(produto, 'andamento_agenda', None)
    if andamento:
        _adicionar_marco(True, andamento.agendado_em, 'Entrou na Agenda de Vídeos', 'fa-calendar-check')

        if andamento.concluido:
            _adicionar_marco(
                True, andamento.concluido_marcado_em, 'Ciclo de divulgação encerrado (Otimizado)', 'fa-flag-checkered',
            )
    for postagem in Postagem.objects.filter(produto=produto):
        rotulo_base = f'{postagem.get_fase_display()} #{postagem.numero_ocorrencia}'

        if postagem.aguardando_aprovacao_em:
            eventos.append({
                'timestamp': postagem.aguardando_aprovacao_em,
                'label': f'{rotulo_base} — Postado', 'tipo': 'aguardando_aprovacao', 'icone': 'fa-upload',
            })

        if postagem.aprovado_ou_recusado_em:
            if postagem.status == StatusPostagem.RECUSADO:
                tipo, acao = 'recusado', 'Recusado'
            else:
                tipo, acao = 'aprovado', 'Aprovado'
            eventos.append({
                'timestamp': postagem.aprovado_ou_recusado_em,
                'label': f'{rotulo_base} — {acao}', 'tipo': tipo, 'icone': 'fa-gavel',
            })

        if postagem.replicado_em:
            eventos.append({
                'timestamp': postagem.replicado_em,
                'label': f'{rotulo_base} — Replicado', 'tipo': 'replicado', 'icone': 'fa-copy',
                'mlbs_replicados': postagem.mlbs_replicados,
                'mlbs_nao_encontrados': postagem.mlbs_nao_encontrados,
            })

    eventos.sort(key=lambda evento: evento['timestamp'])

    aviso_gap = None
    if tem_gap and marcos_presentes == 0:
        aviso_gap = 'Nenhuma etapa de preparação deste produto tem data registrada — aconteceram antes do rastreio existir.'
    elif tem_gap:
        aviso_gap = 'Algumas etapas deste produto aconteceram antes do rastreio existir — sem data registrada.'

    return {'eventos': eventos, 'aviso_gap': aviso_gap}


# Função Objetivo: Monta o histórico completo (todas as fases/ocorrências) de
# 1 produto — SEMPRE completo, nunca filtrado, mesmo quando chamado a partir
# da tela com filtro ativo. Decisão (26/07): o filtro estreita QUAIS produtos
# aparecem no relatório, nunca esconde postagem de dentro de um produto já
# mostrado — quem abrir o grupo vê o histórico real, inteiro.
def montar_historico_produto(produto):
    postagens = list(Postagem.objects.filter(produto=produto).order_by('-criado_em'))

    contagem_por_status = {}
    for postagem in postagens:
        # * [EXPLICAÇÃO] → Anexado aqui (não calculado no template) — mesmo
        #                  padrão já usado nas telas de config do ML.
        postagem.badge = badge_de(BADGES_STATUS_POSTAGEM, postagem.status)
        contagem_por_status[postagem.status] = contagem_por_status.get(postagem.status, 0) + 1

    # * [EXPLICAÇÃO] → "classe" incluída (26/07, redesenho visual) — o resumo
    #                  agora vira badge colorido, não só texto puro.
    resumo = [
        {
            'valor': status_valor,
            'label': BADGES_STATUS_POSTAGEM[status_valor]['label'],
            'classe': BADGES_STATUS_POSTAGEM[status_valor]['classe'],
            'quantidade': quantidade,
        }
        for status_valor, quantidade in contagem_por_status.items()
    ]

    linha_do_tempo = montar_linha_do_tempo_produto(produto)

    return {
        'produto': produto,
        'postagens': postagens,
        'total': len(postagens),
        'resumo': resumo,
        'eventos': linha_do_tempo['eventos'],
        'aviso_gap': linha_do_tempo['aviso_gap'],
    }


# Função Objetivo: Busca de PRODUTOS que têm pelo menos 1 Postagem batendo com
# os filtros (fase/status/intervalo de data) + busca por nome/EAN/SKU do
# produto. Devolve só os PRODUTOS — o conteúdo de cada um vem de
# montar_historico_produto, sempre completo.
def listar_produtos_com_historico(busca=None, filtros=None):
    filtros = filtros or {}

    postagens = Postagem.objects.all()
    if filtros.get('fase'):
        postagens = postagens.filter(fase__in=filtros['fase'])
    if filtros.get('status'):
        postagens = postagens.filter(status__in=filtros['status'])
    if filtros.get('data_de'):
        postagens = postagens.filter(criado_em__date__gte=filtros['data_de'])
    if filtros.get('data_ate'):
        postagens = postagens.filter(criado_em__date__lte=filtros['data_ate'])

    ids_produtos = postagens.values_list('produto_id', flat=True).distinct()
    produtos = Produto.objects.filter(id__in=ids_produtos)

    if filtros.get('urgente'):
        produtos = produtos.filter(roadmap_agenda__urgente__in=[v == 'sim' for v in filtros['urgente']])
    if filtros.get('marcas'):
        produtos = produtos.filter(marca__in=filtros['marcas'])
    if filtros.get('status_manual'):
        produtos = produtos.filter(andamento_agenda__status_manual__in=filtros['status_manual'])

    if busca:
        for termo in busca.split():
            produtos = produtos.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    return produtos.order_by('titulo')