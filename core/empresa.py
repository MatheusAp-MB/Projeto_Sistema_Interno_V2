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

# Direção inversa do dict acima — única fonte de verdade pro valor que o
# usuário digita em --empresa (sempre minúsculo: 'magazine'/'samvale') e
# pra tradução de volta pra constante interna (EMPRESA_MAGAZINE/EMPRESA_SAMVALE).
# Antes desse padrão (27/09/2026), cada comando de management duplicava seu
# próprio dict local com o mesmo mapeamento — 4 cópias (_base_empresa.py +
# 3 comandos do ML), risco de divergir se uma empresa nova entrar.
EMPRESA_POR_ALIAS_BANCO = {
    alias: empresa for empresa, alias in ALIAS_BANCO_POR_EMPRESA.items()
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


class EmpresaNaoDefinidaError(RuntimeError):
    """
    Nenhuma empresa ativa nesta thread (definir_empresa_ativa() nunca foi
    chamado). Decisão explícita (Matheus, 27/09/2026): nunca cair em
    silêncio pro banco default (Magazine) — todo comando/script/shell que
    toca dado de empresa precisa setar a empresa ativa primeiro, ou falha
    na hora, alto e claro.
    """
    pass


def obter_alias_banco_ativo():
    empresa = obter_empresa_ativa()
    if empresa is None:
        raise EmpresaNaoDefinidaError(
            'Nenhuma empresa ativa — chame definir_empresa_ativa(EMPRESA_MAGAZINE '
            'ou EMPRESA_SAMVALE) antes de ler/escrever qualquer dado de empresa. '
            'Comandos de management usam --empresa explícito (obrigatório); scripts '
            'avulsos chamam definir_empresa_ativa() logo no início.'
        )
    return ALIAS_BANCO_POR_EMPRESA[empresa]



# Prefixo já usado nas variáveis de .env de integrações externas (Sysemp,
# Mercado Livre), criado antes da decisão de nomes de hoje — mantém o
# padrão curto já validado em produção (MB_CLIENT_ID, SV_ACCESS_TOKEN etc.)
# em vez de renomear tudo no .env sob pressão de hoje à noite.
PREFIXO_ENV_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'MB',
    EMPRESA_SAMVALE: 'SV',
}