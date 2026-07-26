# agenda_videos/funcoes_auxiliares/historico_postagens.py

# Função Objetivo: Monta os dados de histórico de Postagem — usado tanto pelo
# modal de 1 produto (Formato A) quanto pela tela de relatório geral agrupada
# por produto (Formato B). 1 função só constrói o histórico de 1 produto, os
# 2 formatos reaproveitam ela — nunca duplicada.

from django.db.models import Q
from produtos.models import Produto
from agenda_videos.models import Postagem
from agenda_videos.funcoes_auxiliares.badges_agenda import BADGES_STATUS_POSTAGEM, badge_de


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

    resumo = [
        {'label': BADGES_STATUS_POSTAGEM[status_valor]['label'], 'quantidade': quantidade}
        for status_valor, quantidade in contagem_por_status.items()
    ]

    return {
        'produto': produto,
        'postagens': postagens,
        'total': len(postagens),
        'resumo': resumo,
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

    if busca:
        for termo in busca.split():
            produtos = produtos.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    return produtos.order_by('titulo')