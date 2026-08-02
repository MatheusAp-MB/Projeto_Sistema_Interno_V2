# agenda_videos/tests/conftest.py

import pytest
from rich.console import Console
from rich.table import Table

_console = Console()


@pytest.fixture(scope='module')
def tabela_resultados(request):
    titulo = getattr(request.module, 'TITULO_CAMADA', request.module.__name__)
    tabela = Table(title=titulo)
    tabela.add_column('Teste')
    tabela.add_column('Entrada')
    tabela.add_column('Esperado')
    tabela.add_column('Obtido')
    tabela.add_column('Status')
    yield tabela
    _console.rule('[bold cyan]NOSSOS TESTES — RESULTADO REAL[/bold cyan]')
    _console.print(tabela)
    _console.rule()