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
    campos da nota (NF, Emissão, Fornecedor...) com os campos do item.
    Se a nota não tiver itens_nf (formato plano da API — 1 item = 1
    registro direto), a própria nota já É a linha, usada como está."""
    linhas = []
    for nota in notas:
        if CAMPO_ITENS_NF not in nota:
            linhas.append(nota)
            continue
        campos_da_nota = {chave: valor for chave, valor in nota.items() if chave != CAMPO_ITENS_NF}
        for item in nota.get(CAMPO_ITENS_NF, []):
            linhas.append({**campos_da_nota, **item})
    return linhas


def _cfop_relevante(linha: dict) -> bool:
    # * [EXPLICAÇÃO] → CFOP não é como os outros campos XML×Cadastro (NCM,
    #                  CST, Origem) — não é "qual lado tem o dado mais
    #                  atual", é "de qual lado da operação o código
    #                  descreve". O XML é escrito por quem EMITE a nota
    #                  (o fornecedor): pro lado dele, despachar mercadoria
    #                  é sempre "saída" (ex: 5102, 5916) — mesmo sendo, pra
    #                  nós, uma ENTRADA de compra. O Cadastro é a
    #                  classificação que o próprio Sysemp (nosso lado,
    #                  comprador) deu à operação (ex: 1.102, 1.910) — é
    #                  essa que corresponde a CFOPS_PARA_MANTER (só tem
    #                  código de entrada). Cadastro é sempre a fonte pra
    #                  este filtro, nunca XML primeiro — achado real
    #                  (14/08/2026): XML populado reprovava sistematicamente
    #                  toda nota emitida desde a remodelagem da API
    #                  (07-08/08/2026), porque "5102" nunca está na lista.
    cfop = linha.get('CFOP Cadastro') or linha.get('CFOP XML')
    return cfop in CFOPS_PARA_MANTER


def filtrar_por_cfop(notas_brutas: list[dict]) -> list[dict]:
    """Recebe a lista de notas cruas (bruto['retorno']) e devolve só os
    itens com CFOP relevante, achatados em 1 linha por item."""
    linhas = _achatar_em_linhas(notas_brutas)
    return [linha for linha in linhas if _cfop_relevante(linha)]