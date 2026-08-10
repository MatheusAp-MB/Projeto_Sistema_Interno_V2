import json
import os
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from api_sysemp import ApiSysemp

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))

DATA_INICIAL = '2020-05-01'
DATA_FINAL = '2021-01-01'


console = Console()
api = ApiSysemp()

with Progress(
    SpinnerColumn(),
    TextColumn('[bold]{task.description}'),
    TimeElapsedColumn(),
    console=console,
) as progress:
    tarefa = progress.add_task('Buscando notas...', total=None)

    def _mostrar_progresso(numero_da_pagina, registros_na_pagina, total_acumulado):
        progress.update(
            tarefa,
            description=f'Página {numero_da_pagina} — +{registros_na_pagina} registros (total: {total_acumulado})',
        )

    resultado = api.impostos_entrada.listar_periodo_completo(
        DATA_INICIAL, DATA_FINAL, ao_avancar_pagina=_mostrar_progresso
    )

os.makedirs(os.path.join(_PASTA_ATUAL, 'saidas'), exist_ok=True)
caminho_saida = os.path.join(_PASTA_ATUAL, 'saidas', f'manifesto_nota_entrada_{datetime.now():%Y%m%d_%H%M%S}.json')
with open(caminho_saida, 'w', encoding='utf-8') as arquivo:
    json.dump(resultado, arquivo, ensure_ascii=False, indent=2)

console.print(f'[green]Resposta salva em:[/green] {caminho_saida}')
console.print(f'[green]Total de registros:[/green] {len(resultado["retorno"])}')