# arquivos_referencia/funcoes_auxiliares/consulta_ao_sistema.py

# Função Objetivo: Única porta da auditoria para o BANCO — e só de LEITURA. A auditoria da Busca Legal precisa saber,
# para cada EAN da planilha, se o produto existe no sistema da empresa e quais são o CST de saída e a Origem da
# Mercadoria dele (são esses 2 que, junto com o NCM, formam a chave de agrupamento do ICMS). Nada é gravado.
#
# * [DECISÃO, 15/10/2026] → A tela de arquivos NÃO altera nada do sistema nesta etapa, mas "EAN que não existe no
#   sistema" (decisão de 14/10) só dá para conferir olhando o banco. Então a auditoria LÊ o banco da empresa do
#   arquivo (Magazine ou Samvale), com consulta explícita `.using(alias)` — não depende de qual empresa está ativa na
#   sessão da pessoa — e nunca escreve.
# * [EXPLICAÇÃO] → A consulta é a MESMA que os importadores usam (Produto por EAN, com cst_saida e a Origem do
#   cadastro, via LEFT JOIN em impostos_entrada), em lotes para não montar um IN gigante.

TAMANHO_DO_LOTE = 500


# Função Objetivo: Devolve {ean: (cst_saida, origem_mercadoria_cadastro)} só dos EANs que existem como Produto no banco da
# empresa. EAN que não aparece no resultado não existe no sistema. CST/Origem podem ser None (produto ainda sem o dado).
# Importa os modelos aqui dentro para a tela abrir mesmo se este módulo nunca for usado.
def consultar_produtos_por_ean(empresa, eans):
    from core.empresa import ALIAS_BANCO_POR_EMPRESA
    from produtos.models import Produto

    alias = ALIAS_BANCO_POR_EMPRESA[empresa]
    lista = sorted(eans)
    encontrados = {}
    for inicio in range(0, len(lista), TAMANHO_DO_LOTE):
        lote = lista[inicio:inicio + TAMANHO_DO_LOTE]
        consulta = Produto.objects.using(alias).filter(ean__in=lote).values_list(
            'ean', 'cst_saida', 'impostos_entrada__origem_mercadoria_cadastro',
        )
        for ean, cst_saida, origem in consulta:
            encontrados[ean] = (cst_saida, origem)
    return encontrados
