import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from mercado_livre.models import VariacaoAnuncioMercadoLivre
from mercado_livre.funcoes_auxiliares.comparador_dimensao_envio import SituacaoDimensaoEnvio

# ==== CONFIGURA AQUI ANTES DE RODAR ====
QTD_EXEMPLOS_POR_CATEGORIA = 5
CLASSIFICACOES_ACEITAS = ['simples', 'base']  # nunca 'catalogo' — filtro pedido pela outra conversa
# ========================================


# Função Objetivo: Classifica 1 variação divergente numa das 3 categorias de causa.
# Explicação em detalhe: mesma lógica de gerar_relatorio_divergencia_dimensao_envio.py —
# repetida aqui só pra manter este script autocontido (teste.py é sempre descartável).
def classificar_causa_divergencia(variacao, produto):
    dims_erp_com = [produto.altura_ordenada_cm, produto.largura_ordenada_cm, produto.comprimento_ordenada_cm]
    dims_ml = [variacao.altura_ordenada_cm, variacao.largura_ordenada_cm, variacao.comprimento_ordenada_cm]

    dims_erp_sem_brutas = [
        produto.altura_produto_sem_embalar, produto.largura_produto_sem_embalar,
        produto.comprimento_produto_sem_embalar,
    ]
    sem_embalar_tem_dado = any(valor != 0 for valor in dims_erp_sem_brutas) or produto.peso_produto_sem_embalar != 0
    dims_erp_sem_ordenadas = sorted(dims_erp_sem_brutas)

    bate_com_sem_embalar = (
        sem_embalar_tem_dado
        and dims_erp_sem_ordenadas == dims_ml
        and produto.peso_produto_sem_embalar == variacao.peso_declarado_kg
    )
    if bate_com_sem_embalar:
        return 'ML usa SEM EMBALAR do ERP (confirmado)'

    diferencas = [erp - ml for erp, ml in zip(dims_erp_com, dims_ml)]
    offset_uniforme = len(set(diferencas)) == 1 and diferencas[0] != 0
    if offset_uniforme:
        return 'Offset uniforme — outro padrão'

    return 'Sem padrão — divergência real'


variacoes_divergentes = list(
    VariacaoAnuncioMercadoLivre.objects
    .filter(
        situacao_dimensao_envio=SituacaoDimensaoEnvio.DIVERGENTE,
        anuncio__tipo_de_anuncio__classificacao_catalogo__in=CLASSIFICACOES_ACEITAS,
    )
    .select_related('produto', 'anuncio', 'anuncio__tipo_de_anuncio')
)
print(f'Total divergente (Simples/Base): {len(variacoes_divergentes)}')
print()

exemplos_por_categoria = {
    'ML usa SEM EMBALAR do ERP (confirmado)': [],
    'Offset uniforme — outro padrão': [],
    'Sem padrão — divergência real': [],
}

for variacao in variacoes_divergentes:
    categoria = classificar_causa_divergencia(variacao, variacao.produto)
    if len(exemplos_por_categoria[categoria]) < QTD_EXEMPLOS_POR_CATEGORIA:
        exemplos_por_categoria[categoria].append(variacao)

for categoria, exemplos in exemplos_por_categoria.items():
    print(f'=== {categoria} — {len(exemplos)} exemplo(s) ===')
    for variacao in exemplos:
        p = variacao.produto
        tipo = variacao.anuncio.tipo_de_anuncio
        print(f'  MLB: {variacao.anuncio.mlb} | Classificação: {tipo.get_classificacao_catalogo_display()}')
        print(f'    ERP c/ Embalagem: altura={p.altura_ordenada_cm} largura={p.largura_ordenada_cm} '
              f'comprimento={p.comprimento_ordenada_cm} peso={p.peso_produto_apos_embalado}')
        print(f'    ML Declarado atual: altura={variacao.altura_ordenada_cm} largura={variacao.largura_ordenada_cm} '
              f'comprimento={variacao.comprimento_ordenada_cm} peso={variacao.peso_declarado_kg}')
        print()
    print()