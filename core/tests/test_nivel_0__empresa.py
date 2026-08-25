# core/tests/test_nivel_0__empresa.py

# Função Objetivo: Testa core/empresa.py isolado — Nível 0, funções puras,
# sem banco, sem Django request nenhum. Esse módulo nunca teve teste próprio
# (só era exercitado de forma indireta pelas suítes de middleware) — cobre as
# 2 funções de thread-local (definir/obter empresa ativa) e o único ramo que
# faltava em 25/08: obter_alias_banco_ativo() quando NINGUÉM setou a empresa
# ainda (comando de terminal/migration/thread nova, sem requisição web no
# meio — ver comentário de obter_empresa_ativa() no próprio módulo).
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest

from core import empresa
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — core.empresa (funções puras de thread-local, sem banco)'


@pytest.fixture(autouse=True)
def _resetar_empresa_ativa():
    # Função Objetivo: threading.local() persiste entre testes do mesmo
    # processo/thread (é o pytest inteiro rodando na mesma thread) — sem
    # resetar, "sem empresa ativa" só passaria se rodasse 1º de todos,
    # dependendo de ordem em vez de testar o cenário de verdade.
    if hasattr(empresa._armazenamento_local, 'empresa'):
        del empresa._armazenamento_local.empresa
    yield
    if hasattr(empresa._armazenamento_local, 'empresa'):
        del empresa._armazenamento_local.empresa


def test_obter_empresa_ativa_sem_nada_definido_devolve_none(tabela_resultados):
    # Exercise:
    resultado = empresa.obter_empresa_ativa()

    # Assert:
    passou = resultado is None
    registrar_resultado(
        tabela_resultados, teste='obter_empresa_ativa() sem nenhum definir_empresa_ativa() antes',
        entrada='thread-local limpo (fixture reseta antes de cada teste)', esperado='None',
        motivo='Comando de terminal/migration/thread nova não passa pelo EmpresaMiddleware — não pode quebrar, só devolver None',
        obtido=f'resultado={resultado!r}',
        passou=passou,
    )
    assert passou


def test_definir_e_obter_empresa_ativa_magazine(tabela_resultados):
    # Exercise:
    empresa.definir_empresa_ativa(empresa.EMPRESA_MAGAZINE)
    resultado = empresa.obter_empresa_ativa()

    # Assert:
    passou = resultado == empresa.EMPRESA_MAGAZINE
    registrar_resultado(
        tabela_resultados, teste='definir_empresa_ativa(MAGAZINE) + obter_empresa_ativa()',
        entrada='definir_empresa_ativa("MAGAZINE")', esperado='"MAGAZINE"',
        motivo='Caminho feliz mais básico do thread-local — sem isso nada no resto do multi-empresa funciona',
        obtido=f'resultado={resultado!r}',
        passou=passou,
    )
    assert passou


def test_definir_e_obter_empresa_ativa_samvale(tabela_resultados):
    # Exercise:
    empresa.definir_empresa_ativa(empresa.EMPRESA_SAMVALE)
    resultado = empresa.obter_empresa_ativa()

    # Assert:
    passou = resultado == empresa.EMPRESA_SAMVALE
    registrar_resultado(
        tabela_resultados, teste='definir_empresa_ativa(SAMVALE) + obter_empresa_ativa()',
        entrada='definir_empresa_ativa("SAMVALE")', esperado='"SAMVALE"',
        motivo='Espelha o teste da Magazine — prova que a troca não fica "preso" num valor fixo',
        obtido=f'resultado={resultado!r}',
        passou=passou,
    )
    assert passou


def test_obter_alias_banco_ativo_com_magazine_ativa(tabela_resultados):
    # Setup:
    empresa.definir_empresa_ativa(empresa.EMPRESA_MAGAZINE)

    # Exercise:
    resultado = empresa.obter_alias_banco_ativo()

    # Assert:
    passou = resultado == 'magazine'
    registrar_resultado(
        tabela_resultados, teste='obter_alias_banco_ativo() com MAGAZINE ativa',
        entrada='empresa ativa = MAGAZINE', esperado="'magazine'",
        motivo='É esse alias que o database_router usa pra rotear a query pro banco certo',
        obtido=f'resultado={resultado!r}',
        passou=passou,
    )
    assert passou


def test_obter_alias_banco_ativo_com_samvale_ativa(tabela_resultados):
    # Setup:
    empresa.definir_empresa_ativa(empresa.EMPRESA_SAMVALE)

    # Exercise:
    resultado = empresa.obter_alias_banco_ativo()

    # Assert:
    passou = resultado == 'samvale'
    registrar_resultado(
        tabela_resultados, teste='obter_alias_banco_ativo() com SAMVALE ativa',
        entrada='empresa ativa = SAMVALE', esperado="'samvale'",
        motivo='Espelha o teste da Magazine pro lado Samvale',
        obtido=f'resultado={resultado!r}',
        passou=passou,
    )
    assert passou


def test_obter_alias_banco_ativo_sem_empresa_ativa_devolve_none(tabela_resultados):
    # Exercise: nenhum definir_empresa_ativa() antes (fixture garante isso).
    resultado = empresa.obter_alias_banco_ativo()

    # Assert:
    passou = resultado is None
    registrar_resultado(
        tabela_resultados, teste='obter_alias_banco_ativo() sem nenhuma empresa ativa',
        entrada='thread-local limpo', esperado='None',
        motivo='Linha que faltava cobrir em 25/08 — deixa o Router NÃO opinar, respeitando --database= nativo do Django',
        obtido=f'resultado={resultado!r}',
        passou=passou,
    )
    assert passou


def test_constantes_de_empresa_tem_os_valores_esperados(tabela_resultados):
    # Exercise/Assert: protege as 4 constantes/dicts que o resto do sistema
    # inteiro depende silenciosamente (middleware, router, templates,
    # cliente_api do agente local) — um typo aqui quebraria tudo sem
    # NENHUM erro óbvio na hora, só dado errado ou banco errado.
    passou = (
        empresa.EMPRESAS_VALIDAS == [empresa.EMPRESA_MAGAZINE, empresa.EMPRESA_SAMVALE]
        and empresa.EMPRESA_PADRAO == empresa.EMPRESA_MAGAZINE
        and empresa.ALIAS_BANCO_POR_EMPRESA == {empresa.EMPRESA_MAGAZINE: 'magazine', empresa.EMPRESA_SAMVALE: 'samvale'}
        and empresa.NOME_EXIBICAO_POR_EMPRESA[empresa.EMPRESA_MAGAZINE] == 'MAGAZINE BRASILEIRO'
        and empresa.NOME_EXIBICAO_POR_EMPRESA[empresa.EMPRESA_SAMVALE] == 'SAMVALE'
        and empresa.PREFIXO_ENV_POR_EMPRESA == {empresa.EMPRESA_MAGAZINE: 'MB', empresa.EMPRESA_SAMVALE: 'SV'}
    )
    registrar_resultado(
        tabela_resultados, teste='Constantes/dicts de core.empresa não sofreram regressão silenciosa',
        entrada='EMPRESAS_VALIDAS, EMPRESA_PADRAO, ALIAS_BANCO_POR_EMPRESA, NOME_EXIBICAO_POR_EMPRESA, PREFIXO_ENV_POR_EMPRESA',
        esperado='Magazine + Samvale, nos 2 sentidos, com os aliases/prefixos reais de produção',
        motivo='Typo num desses dicts não gera erro visível — só rotearia pro banco/prefixo errado em silêncio',
        obtido=f'EMPRESAS_VALIDAS={empresa.EMPRESAS_VALIDAS!r}, ALIAS_BANCO_POR_EMPRESA={empresa.ALIAS_BANCO_POR_EMPRESA!r}',
        passou=passou,
    )
    assert passou