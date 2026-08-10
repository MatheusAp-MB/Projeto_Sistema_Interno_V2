# integracao_sysemp/servicos/erros_sincronizacao.py

# Função Objetivo: Lista de pendências abertas de sincronização — 1
# entrada por Código Barras que falhou (parse do XML ou persistência).
# Não é log de execução: quando aquele mesmo produto sincronizar com
# sucesso numa rodada futura, a pendência sai da lista.

from datetime import datetime

from .arquivos_retorno_api import NOME_ARQUIVO_ERROS, ler_json, salvar_json


def _carregar_erros() -> dict:
    return ler_json(NOME_ARQUIVO_ERROS, padrao={})


def registrar_erro(codigo_barras: str, etapa: str, mensagem: str) -> None:
    erros = _carregar_erros()
    erros[codigo_barras] = {
        'etapa': etapa,
        'mensagem': mensagem,
        'quando': datetime.now().isoformat(),
    }
    salvar_json(erros, NOME_ARQUIVO_ERROS)


def remover_erro(codigo_barras: str) -> None:
    erros = _carregar_erros()
    if codigo_barras in erros:
        del erros[codigo_barras]
        salvar_json(erros, NOME_ARQUIVO_ERROS)