# integracao_sysemp/servicos/selecao_nota_recente.py

# Função Objetivo: Dado o manifesto já filtrado por CFOP (1 linha por
# item), selecionar por produto (Código Barras) a nota mais recente — Data
# Entrada da Nota desc, NR NF desc como desempate. 1 produto sempre vem de
# 1 fornecedor (confirmado) — não precisa desempatar por fornecedor.

from datetime import datetime

CAMPO_CODIGO_PRODUTO = 'Código Barras'
CAMPO_NF = 'NR NF'
CAMPO_DATA_ENTRADA_NOTA = 'Data Entrada da Nota'


def _chave_de_ordenacao(linha: dict) -> tuple:
    data = linha.get(CAMPO_DATA_ENTRADA_NOTA)
    data_convertida = datetime.fromisoformat(data) if data else datetime.min
    return data_convertida, int(linha[CAMPO_NF])


def selecionar_nota_mais_recente_por_produto(linhas_filtradas: list[dict]) -> list[dict]:
    """Agrupa por Código Barras, mantém só a linha mais recente de cada
    produto."""
    mais_recente_por_produto: dict[str, dict] = {}
    for linha in linhas_filtradas:
        codigo = linha[CAMPO_CODIGO_PRODUTO]
        atual = mais_recente_por_produto.get(codigo)
        if atual is None or _chave_de_ordenacao(linha) > _chave_de_ordenacao(atual):
            mais_recente_por_produto[codigo] = linha
    return list(mais_recente_por_produto.values())