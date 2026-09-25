# mercado_livre/funcoes_auxiliares/recalcular_comissao_media.py
#
# Recalcula as médias de Comissão Real por Produto e por Categoria — sempre
# do zero (snapshot completo, nunca incremental), nunca via Django signal
# (decisão explícita: risco de loop/bug em cascata já visto antes nesse
# projeto). Quem chama isso decide o escopo (nunca recalcula "tudo" sozinho):
#   - buscar_comissao_real_ml.py chama no fim da execução, só pros
#     produto_ids/categoria_ids tocados durante aquele run.
#   - botão manual (ainda não implementado) vai chamar com o escopo
#     escolhido pelo usuário.
#
# As médias são só informativas — nunca entram no cálculo de precificação
# (que usa a comissão real por MLB, direto). Ver Checkpoint - Investigação
# da Comissão Real de Venda via API do Mercado Livre, seção 9.

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Avg, Count
from django.utils import timezone

from mercado_livre.models import VariacaoAnuncioMercadoLivre, CategoriaMercadoLivre
from produtos.models import Produto

CLASSICO = 'gold_special'
PREMIUM = 'gold_pro'

DUAS_CASAS = Decimal('0.01')


# Função Objetivo: Arredonda o resultado do Avg() pra 2 casas — o Avg do MySQL
# devolve mais casas decimais do que o campo comissao_real_percentual tem.
def _arredondar(valor):
    if valor is None:
        return None
    return Decimal(valor).quantize(DUAS_CASAS, rounding=ROUND_HALF_UP)


# Função Objetivo: Calcula média + amostra de Clássico e Premium pra 1 queryset
# de variações já filtrado (produto OU categoria — a lógica de agrupar por
# tipo_anuncio é idêntica nos 2 casos).
def _calcular_medias(queryset_base) -> dict:
    classico = queryset_base.filter(anuncio__tipo_de_anuncio__tipo_anuncio=CLASSICO) \
        .aggregate(media=Avg('comissao_real_percentual'), amostra=Count('id'))
    premium = queryset_base.filter(anuncio__tipo_de_anuncio__tipo_anuncio=PREMIUM) \
        .aggregate(media=Avg('comissao_real_percentual'), amostra=Count('id'))

    return {
        'comissao_media_classico': _arredondar(classico['media']),
        'comissao_media_classico_amostra': classico['amostra'] or None,
        'comissao_media_premium': _arredondar(premium['media']),
        'comissao_media_premium_amostra': premium['amostra'] or None,
    }


# Função Objetivo: Recalcula comissao_media_classico/premium de 1 produto, a partir
# de TODAS as variações dele com comissao_real_percentual preenchido — cross-categoria.
def _calcular_medias_produto(produto_sku: str) -> dict:
    base = VariacaoAnuncioMercadoLivre.objects.filter(
        produto_id=produto_sku,  # produto_id já É a sku (FK com to_field='sku')
        comissao_real_percentual__isnull=False,
    ).select_related('anuncio__tipo_de_anuncio')
    return _calcular_medias(base)


# Função Objetivo: Recalcula comissao_media_classico/premium de 1 categoria, a partir
# de TODAS as variações vinculadas a ela com comissao_real_percentual preenchido — cross-produto.
def _calcular_medias_categoria(categoria_id: str) -> dict:
    base = VariacaoAnuncioMercadoLivre.objects.filter(
        categoria_id=categoria_id,
        comissao_real_percentual__isnull=False,
    ).select_related('anuncio__tipo_de_anuncio')
    return _calcular_medias(base)


# Função Objetivo: Ponto único de entrada — recalcula só os produtos/categorias
# passados (nunca "tudo"), sempre snapshot completo. Usa .update() de propósito
# (não .save()) — não dispara auto_now de Produto.atualizado_em nem de
# CategoriaMercadoLivre.atualizado_em (campos de sincronização ERP/dump, sem
# relação com comissão — ver nota nos 2 models).
def recalcular_comissao_media(produto_ids=None, categoria_ids=None) -> dict:
    agora = timezone.now()
    produtos_atualizados = 0
    categorias_atualizadas = 0

    for produto_sku in set(produto_ids or []):
        medias = _calcular_medias_produto(produto_sku)
        Produto.objects.filter(sku=produto_sku).update(
            **medias, comissao_media_atualizado_em=agora,
        )
        produtos_atualizados += 1

    for categoria_id in set(categoria_ids or []):
        medias = _calcular_medias_categoria(categoria_id)
        CategoriaMercadoLivre.objects.filter(pk=categoria_id).update(
            **medias, comissao_media_atualizado_em=agora,
        )
        categorias_atualizadas += 1

    return {
        'produtos_atualizados': produtos_atualizados,
        'categorias_atualizadas': categorias_atualizadas,
    }