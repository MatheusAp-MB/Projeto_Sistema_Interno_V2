# conftest.py (raiz)

from pathlib import Path

import pytest
from rich.console import Console
from rich.table import Table

_console = Console()

CAMINHO_LOG_TESTES = Path('resultados_testes.txt')


class RegistradorDeResultados:
    # Função Objetivo: Guarda cada resultado 2x — como linha de Table (pro
    # terminal) e como dict numa lista simples (pro log em texto, que não
    # tem largura fixa nem corta nada).
    def __init__(self, titulo):
        self.tabela = Table(title=titulo, show_lines=True)
        for coluna in ['Teste', 'Entrada', 'Esperado', 'Motivo', 'Obtido', 'Status']:
            self.tabela.add_column(coluna)
        self.linhas = []

    def adicionar(self, teste, entrada, esperado, motivo, obtido, passou, dado_bruto=None):
        status = '[green]✓ PASSOU[/green]' if passou else '[red]✗ FALHOU[/red]'
        self.tabela.add_row(teste, entrada, esperado, motivo, obtido, status)
        self.linhas.append({
            'teste': teste, 'entrada': entrada, 'esperado': esperado,
            'motivo': motivo, 'obtido': obtido, 'passou': passou,
            'dado_bruto': dado_bruto,
        })


@pytest.fixture(scope='session', autouse=True)
def _resetar_log_de_testes():
    # Setup: zera o arquivo 1x por sessão inteira de pytest — cada rodada
    # de "pytest -s" gera um log novo, nunca acumula histórico de rodadas
    # antigas.
    CAMINHO_LOG_TESTES.write_text('', encoding='utf-8')


@pytest.fixture(scope='module')
def tabela_resultados(request):
    titulo = getattr(request.module, 'TITULO_CAMADA', request.module.__name__)
    registrador = RegistradorDeResultados(titulo)
    yield registrador
    _console.rule('[bold cyan]NOSSOS TESTES — RESULTADO REAL[/bold cyan]')
    _console.print(registrador.tabela)
    _console.rule()

    with CAMINHO_LOG_TESTES.open('a', encoding='utf-8') as arquivo:
        arquivo.write(f'=== {titulo} ===\n\n')
        for linha in registrador.linhas:
            status = 'PASSOU' if linha['passou'] else 'FALHOU'
            arquivo.write(f"[{status}] {linha['teste']}\n")
            arquivo.write(f"  Entrada:  {linha['entrada']}\n")
            arquivo.write(f"  Esperado: {linha['esperado']}\n")
            arquivo.write(f"  Motivo:   {linha['motivo']}\n")
            arquivo.write(f"  Obtido:   {linha['obtido']}\n")
            if linha['dado_bruto'] is not None:
                arquivo.write(f"  Dado bruto: {linha['dado_bruto']!r}\n")
            arquivo.write('\n')


def pytest_collection_modifyitems(items):
    # Função Objetivo: Força a ordem de execução pela ordem alfabética do
    # caminho do arquivo — nunca confia na ordem "padrão" de coleta do
    # pytest, que pode variar por sistema de arquivos. É isso que garante
    # a hierarquia Nível 0 -> 2 -> 3 -> 4, sempre do menor problema pro maior.
    items.sort(key=lambda item: item.nodeid)

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    # Função Objetivo: Acrescenta ao mesmo log em texto o que só existia no
    # terminal até agora — o resumo final da sessão (quantos passaram,
    # falharam, xfailed) e o traceback COMPLETO de qualquer falha real. É o
    # "dado bruto" que a tabela Motivo/Entrada/Esperado não cobre, porque só
    # existe depois que TODOS os testes já rodaram.
    with CAMINHO_LOG_TESTES.open('a', encoding='utf-8') as arquivo:
        arquivo.write('=== RESUMO DA SESSÃO ===\n\n')
        for categoria in ('passed', 'failed', 'xfailed', 'skipped', 'error'):
            relatorios = [r for r in terminalreporter.stats.get(categoria, []) if r.when == 'call']
            if relatorios:
                arquivo.write(f'{categoria}: {len(relatorios)}\n')
        arquivo.write('\n')

        falhas = [r for r in terminalreporter.stats.get('failed', []) if r.when == 'call']
        if falhas:
            arquivo.write('=== DETALHE DAS FALHAS (traceback completo) ===\n\n')
            for relatorio in falhas:
                arquivo.write(f'--- {relatorio.nodeid} ---\n')
                arquivo.write(str(relatorio.longrepr))
                arquivo.write('\n\n')

        # Coverage: pytest-cov guarda o texto completo do relatório (o
        # mesmo que aparece no terminal — tabela + "HTML written to..." +
        # "JSON written to...") no buffer `cov_report` do próprio plugin.
        # Só existe se `--cov` foi passado nessa rodada.
        plugin_cov = terminalreporter.config.pluginmanager.getplugin('_cov')
        texto_cov = getattr(plugin_cov, 'cov_report', None)
        if texto_cov is not None and texto_cov.getvalue():
            arquivo.write('=== COVERAGE ===\n\n')
            arquivo.write(texto_cov.getvalue())
            arquivo.write('\n')