# core/empresa.py
import threading

_armazenamento_local = threading.local()

EMPRESA_MAGAZINE = 'MAGAZINE'
EMPRESA_SAMVALE = 'SAMVALE'

EMPRESA_PADRAO = EMPRESA_MAGAZINE

EMPRESAS_VALIDAS = [EMPRESA_MAGAZINE, EMPRESA_SAMVALE]

ALIAS_BANCO_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'magazine',
    EMPRESA_SAMVALE: 'samvale',
}

NOME_EXIBICAO_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'MAGAZINE BRASILEIRO',
    EMPRESA_SAMVALE: 'SAMVALE',
}


def definir_empresa_ativa(empresa):
    _armazenamento_local.empresa = empresa


def obter_empresa_ativa():
    # None = nenhuma requisição web setou isso ainda (comando de terminal,
    # migration, shell). Nesses casos o Router NÃO deve opinar — deixa o
    # Django respeitar o --database= nativo, sem interferência nossa.
    return getattr(_armazenamento_local, 'empresa', None)


def obter_alias_banco_ativo():
    empresa = obter_empresa_ativa()
    if empresa is None:
        return None
    return ALIAS_BANCO_POR_EMPRESA[empresa]