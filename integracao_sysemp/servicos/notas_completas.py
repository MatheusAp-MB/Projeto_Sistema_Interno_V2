# integracao_sysemp/servicos/notas_completas.py

# Função Objetivo: Do manifesto bruto (1 registro por item de nota), separa as
# linhas por nota (Chave de acesso) — sem filtrar por CFOP — pra que o
# orquestrador consiga gravar o espelho da nota INTEIRA (todos os itens) de
# cada nota que um produto do sistema usa como base. Só agrupa; continua sem
# saber de disco nem de banco (ver arquivos_retorno_api.py: "nenhuma função
# de negócio sabe de disco por conta própria").

from .filtro_cfop import achatar_manifesto_em_linhas

CAMPO_CHAVE = 'Chave'


def agrupar_manifesto_por_chave(notas_brutas: list[dict]) -> dict[str, list[dict]]:
    """Devolve {chave da nota: [linhas dessa nota]} a partir de bruto['retorno'].
    Linha sem Chave (ou que nem é dicionário) fica de fora — não tem como
    saber a qual nota pertence, e o filtro de CFOP já reporta registros
    malformados como pendência."""
    linhas_por_chave: dict[str, list[dict]] = {}
    for linha in achatar_manifesto_em_linhas(notas_brutas):
        chave = linha.get(CAMPO_CHAVE) if isinstance(linha, dict) else None
        if not chave:
            continue
        linhas_por_chave.setdefault(chave, []).append(linha)
    return linhas_por_chave
