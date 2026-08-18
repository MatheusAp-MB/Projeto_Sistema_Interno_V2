# integracao_sysemp/servicos/filtro_cfop.py

# Função Objetivo: Filtrar o manifesto bruto (nota + itens_nf, cru da API)
# por CFOP relevante pra custo/imposto de entrada, achatando pra 1 linha =
# 1 item. Lista de CFOP documentada em "Lista de CFOP Relevantes para
# Precificacao" no vault — só aplica a decisão, não a redefine.
#
# Atualizado (15/08/2026): bonificação (1.910/2.910) removida da lista —
# "Dados Filtrados" passa a ser só CFOP de compra real (1.102/2.102,
# 1.403/2.403). Ver "Bonificacao Removida do Filtro de CFOP de Impostos
# de Entrada" no vault.
#
# Também atualizado (15/08/2026): 1 nota com itens_nf malformado (ex: null
# em vez de lista, ou item que não é dict) não derruba mais o lote
# inteiro — é pulada e devolvida como erro. Esta função continua sem
# saber de disco (ver arquivos_retorno_api.py: "nenhuma função de negócio
# sabe de disco por conta própria") — quem registra a pendência de
# verdade é o orquestrador, chamando registrar_erro() com o que esta
# função devolver.

CAMPO_ITENS_NF = 'itens_nf'
CAMPO_NF_DA_NOTA = 'NR NF'

CFOPS_PARA_MANTER = (
    '1.102', '2.102',  # compra para revenda
    '1.403', '2.403',  # compra para revenda sob substituição tributária (ICMS-ST)
)

DESCRICAO_POR_CFOP = {
    '1.102': 'Compra p/ revenda — mesmo estado',
    '2.102': 'Compra p/ revenda — outro estado',
    '1.403': 'Compra p/ revenda ST — mesmo estado',
    '2.403': 'Compra p/ revenda ST — outro estado',
}


def _identificador_da_nota(nota) -> str:
    if isinstance(nota, dict):
        return nota.get(CAMPO_NF_DA_NOTA, 'NF sem número identificável')
    return 'registro de nota malformado (não é um dicionário)'


def _achatar_em_linhas(notas: list[dict]) -> tuple[list[dict], list[dict]]:
    """1 nota com N itens em itens_nf vira N linhas — cada linha junta os
    campos da nota (NF, Emissão, Fornecedor...) com os campos do item.
    Se a nota não tiver itens_nf (formato plano da API — 1 item = 1
    registro direto), a própria nota já É a linha, usada como está.
    Devolve (linhas, erros) — 1 nota malformada (itens_nf nulo, item que
    não é dict, etc.) nunca derruba as outras, só vira 1 entrada em erros
    no lugar de virar linha."""
    linhas = []
    erros = []
    for nota in notas:
        try:
            if CAMPO_ITENS_NF not in nota:
                linhas.append(nota)
                continue
            campos_da_nota = {chave: valor for chave, valor in nota.items() if chave != CAMPO_ITENS_NF}
            for item in nota.get(CAMPO_ITENS_NF, []):
                linhas.append({**campos_da_nota, **item})
        except (TypeError, AttributeError) as erro:
            erros.append({'identificador': _identificador_da_nota(nota), 'mensagem': str(erro)})
            continue
    return linhas, erros


def _cfop_relevante(linha: dict) -> bool:
    # * [EXPLICAÇÃO] → CFOP não é como os outros campos XML×Cadastro (NCM,
    #                  CST, Origem) — não é "qual lado tem o dado mais
    #                  atual", é "de qual lado da operação o código
    #                  descreve". O XML é escrito por quem EMITE a nota
    #                  (o fornecedor): pro lado dele, despachar mercadoria
    #                  é sempre "saída" (ex: 5102), mesmo sendo, pra nós,
    #                  uma ENTRADA de compra. O Cadastro é a classificação
    #                  que o próprio Sysemp (nosso lado, comprador) deu à
    #                  operação (ex: 1.102) — é essa que corresponde a
    #                  CFOPS_PARA_MANTER (só tem código de entrada).
    #                  Cadastro é sempre a fonte pra este filtro, nunca
    #                  XML primeiro — achado real (14/08/2026): XML
    #                  populado reprovava sistematicamente toda nota
    #                  emitida desde a remodelagem da API (07-08/08/2026),
    #                  porque "5102" nunca está na lista. Ver "Por Que o
    #                  Filtro de CFOP Usa Cadastro e Nao XML" no vault
    #                  pra explicação completa (revisitada 15/08/2026).
    cfop = linha.get('CFOP Cadastro') or linha.get('CFOP XML')
    return cfop in CFOPS_PARA_MANTER


def filtrar_por_cfop(notas_brutas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Recebe a lista de notas cruas (bruto['retorno']) e devolve
    (linhas_filtradas, erros) — só os itens com CFOP relevante, achatados
    em 1 linha por item, mais a lista de notas puladas por erro."""
    linhas, erros = _achatar_em_linhas(notas_brutas)
    linhas_filtradas = [linha for linha in linhas if _cfop_relevante(linha)]
    return linhas_filtradas, erros


def contar_por_cfop(linhas_filtradas: list[dict]) -> list[tuple[str, str, int]]:
    """Quantas linhas já filtradas caem em cada CFOP mantido — não filtra
    de novo, só conta. Sempre devolve 1 tupla por CFOP de CFOPS_PARA_MANTER,
    na mesma ordem, incluindo CFOP com 0 ocorrência nesta execução
    (visibilidade total do que é possível aparecer, não só o que apareceu)."""
    contagem = {cfop: 0 for cfop in CFOPS_PARA_MANTER}
    for linha in linhas_filtradas:
        cfop = linha.get('CFOP Cadastro') or linha.get('CFOP XML')
        if cfop in contagem:
            contagem[cfop] += 1
    return [(cfop, DESCRICAO_POR_CFOP[cfop], contagem[cfop]) for cfop in CFOPS_PARA_MANTER]