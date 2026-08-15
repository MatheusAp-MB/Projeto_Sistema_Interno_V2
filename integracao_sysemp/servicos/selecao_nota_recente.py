# integracao_sysemp/servicos/selecao_nota_recente.py

# Função Objetivo: Dado o manifesto já filtrado por CFOP (1 linha por
# item), selecionar por produto (Código Barras) a nota mais recente — Data
# Entrada da Nota desc, NR NF desc como desempate. 1 produto sempre vem de
# 1 fornecedor (confirmado) — não precisa desempatar por fornecedor.
#
# Atualizado (15/08/2026): a validação de data/NF antes só rodava na hora
# de COMPARAR duas notas do mesmo produto — como a comparação usava um
# "or" com curto-circuito, a 1ª nota de cada produto nunca era validada
# (dado ruim passava direto pro resultado), e a partir da 2ª nota, dado
# ruim derrubava a seleção inteira. Agora a chave de ordenação é calculada
# e validada ANTES de qualquer comparação, por linha — linha inválida
# nunca entra na disputa, e nunca derruba as outras. Esta função continua
# sem saber de disco (ver arquivos_retorno_api.py: "nenhuma função de
# negócio sabe de disco por conta própria") — devolve os erros como dado;
# quem registra a pendência de verdade é o orquestrador.

from datetime import datetime

CAMPO_CODIGO_PRODUTO = 'Código Barras'
CAMPO_NF = 'NR NF'
CAMPO_DATA_ENTRADA_NOTA = 'Entrada NF'

_IDENTIFICADOR_SEM_CODIGO_BARRAS = 'produto sem Código Barras identificável'


def _tentar_calcular_chave_de_ordenacao(linha: dict, identificador: str, erros: list[dict]) -> tuple | None:
    """Calcula (data, número da NF) pra comparar duas notas do mesmo
    produto. Devolve None (e acrescenta o erro na lista) se a linha
    estiver malformada — data num formato que não dá pra converter, ou NF
    ausente/não numérico — em vez de deixar a exceção subir e derrubar a
    seleção inteira."""
    try:
        data = linha.get(CAMPO_DATA_ENTRADA_NOTA)
        data_convertida = datetime.fromisoformat(data) if data else datetime.min
        return data_convertida, int(linha[CAMPO_NF])
    except (KeyError, ValueError, TypeError) as erro:
        erros.append({'identificador': identificador, 'mensagem': str(erro)})
        return None


def selecionar_nota_mais_recente_por_produto(linhas_filtradas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Agrupa por Código Barras, mantém só a linha mais recente de cada
    produto. Devolve (selecionados, erros) — cada linha tem a chave de
    ordenação calculada e validada antes de entrar na disputa, então uma
    linha malformada nunca vira "mais recente" por engano nem derruba as
    outras do mesmo produto."""
    mais_recente_por_produto: dict[str, dict] = {}
    melhor_chave_por_produto: dict[str, tuple] = {}
    erros: list[dict] = []
    for linha in linhas_filtradas:
        try:
            codigo = linha[CAMPO_CODIGO_PRODUTO]
        except KeyError as erro:
            erros.append({'identificador': _IDENTIFICADOR_SEM_CODIGO_BARRAS, 'mensagem': str(erro)})
            continue
        chave = _tentar_calcular_chave_de_ordenacao(linha, codigo, erros)
        if chave is None:
            continue
        melhor_chave_atual = melhor_chave_por_produto.get(codigo)
        if melhor_chave_atual is None or chave > melhor_chave_atual:
            mais_recente_por_produto[codigo] = linha
            melhor_chave_por_produto[codigo] = chave
    return list(mais_recente_por_produto.values()), erros