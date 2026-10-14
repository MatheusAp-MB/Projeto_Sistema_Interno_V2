# gestao_apis/funcoes_auxiliares/verificador_demais_conexoes.py

# Função Objetivo: Leitura local (sem internet) das conexões que ainda NÃO têm teste real:
# Sysemp (MB e SV) e Agente de automação.
#
# * [REGRA] → Sem teste de verdade, o melhor estado possível é "Não verificada" — configuração
#   completa não prova que a conexão funciona.
# * [PENDÊNCIA] → Sysemp: falta identificar uma chamada LEVE da API (as que conhecemos —
#   impostos de entrada e análise de estoque do Full — carregam dados). Agente: falta o sistema
#   registrar o último contato autenticado do agente.

import os

from django.conf import settings

from core.empresa import PREFIXO_ENV_POR_EMPRESA, EMPRESA_MAGAZINE, EMPRESA_SAMVALE

from .estados import NAO_CONFIGURADA, NAO_VERIFICADA, Resultado

PREFIXO_POR_CONEXAO_SYSEMP = {
    'sysemp_mb': PREFIXO_ENV_POR_EMPRESA[EMPRESA_MAGAZINE],
    'sysemp_sv': PREFIXO_ENV_POR_EMPRESA[EMPRESA_SAMVALE],
}


def ler_local_sysemp(conexao_id):
    prefixo = PREFIXO_POR_CONEXAO_SYSEMP[conexao_id]
    nome_da_variavel = f'{prefixo}_SYSEMP_API_TOKEN'
    if not os.environ.get(nome_da_variavel):
        return Resultado(
            NAO_CONFIGURADA,
            f'A variável {nome_da_variavel} não está no .env.',
            como_resolver=f'Adicionar a linha {nome_da_variavel}=... no .env.',
        )
    # * [EXPLICAÇÃO] → Import dentro da função de propósito: se o pacote api_sysemp falhar ao
    #                  carregar, só os cartões do Sysemp mostram o erro — a tela abre igual.
    from api_sysemp import URL_BASE_PADRAO_POR_PREFIXO
    url_base = os.environ.get(f'{prefixo}_SYSEMP_API_URL_BASE') or URL_BASE_PADRAO_POR_PREFIXO[prefixo]
    return Resultado(
        NAO_VERIFICADA,
        'Token configurado. Ainda não existe teste de conexão para o Sysemp.',
        como_resolver='Identificar uma chamada leve da API do Sysemp para usar como teste.',
        evidencia=f'Endereço da API: {url_base}',
    )


def ler_local_agente():
    if not settings.AGENTE_TOKEN:
        return Resultado(
            NAO_CONFIGURADA,
            'A variável AGENTE_TOKEN não está no .env.',
            como_resolver='Definir AGENTE_TOKEN no .env do sistema e o mesmo valor no agente.',
        )
    return Resultado(
        NAO_VERIFICADA,
        'Chave configurada no sistema. O sistema ainda não registra o último contato do agente.',
        como_resolver='Registrar o último contato autenticado do agente para poder mostrar "Funcionando".',
    )

