# integracao_sysemp/servicos/filtro_cfop.py

# Função Objetivo: Filtrar o manifesto bruto (nota + itens_nf, cru da API)
# por CFOP relevante pra custo/imposto de entrada, achatando pra 1 linha =
# 1 item. Mesma lista de CFOP já validada em reunião com o superior (ver
# "Lista de CFOP Relevantes para Precificacao" no vault) — só aplica a
# decisão, não a redefine.

CAMPO_ITENS_NF = 'itens_nf'

CFOPS_PARA_MANTER = (
    '1.102', '2.102',  # compra para revenda
    '1.403', '2.403',  # compra para revenda sob substituição tributária (ICMS-ST)
    '1.910', '2.910',  # bonificação, doação ou brinde (sem custo real de aquisição)
)


def _achatar_em_linhas(notas: list[dict]) -> list[dict]:
    """1 nota com N itens em itens_nf vira N linhas — cada linha junta os
    campos da nota (NF, Emissão, Fornecedor...) com os campos do item."""
    linhas = []
    for nota in notas:
        campos_da_nota = {chave: valor for chave, valor in nota.items() if chave != CAMPO_ITENS_NF}
        for item in nota.get(CAMPO_ITENS_NF, []):
            linhas.append({**campos_da_nota, **item})
    return linhas


def filtrar_por_cfop(notas_brutas: list[dict]) -> list[dict]:
    """Recebe a lista de notas cruas (bruto['retorno']) e devolve só os
    itens com CFOP relevante, achatados em 1 linha por item."""
    linhas = _achatar_em_linhas(notas_brutas)
    return [linha for linha in linhas if linha.get('CFOP') in CFOPS_PARA_MANTER]