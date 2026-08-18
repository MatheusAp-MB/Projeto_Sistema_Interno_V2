# integracao_sysemp/management/commands/sincronizar_impostos_entrada.py

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from core.management.commands._base_empresa import ComandoComEmpresa
from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada
from integracao_sysemp.servicos.orquestrador import sincronizar_impostos_entrada_xml

FASES_EM_ORDEM = (
    'busca_api', 'salvar_bruto', 'filtro_cfop', 'salvar_filtrado',
    'selecao_nota_recente', 'salvar_selecionados', 'persistencia_no_banco', 'total',
)

NOME_EXIBICAO_FASE = {
    'busca_api': 'Busca na API',
    'salvar_bruto': 'Salvar bruto',
    'filtro_cfop': 'Filtro CFOP',
    'salvar_filtrado': 'Salvar filtrado',
    'selecao_nota_recente': 'Seleção nota mais recente',
    'salvar_selecionados': 'Salvar selecionados',
    'persistencia_no_banco': 'Persistência no banco',
    'total': 'Total',
}


class Command(ComandoComEmpresa):
    help = 'Sincroniza os impostos/custos de entrada a partir do manifesto XML do Sysemp.'

    def handle(self, *args, **options):
        console = Console()
        empresa = options['empresa']

        registro_watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
        console.print(f'[bold]Empresa[/bold] {empresa}')
        if registro_watermark.data_final_cobertura is not None:
            console.print(
                f'Cobertura atual no banco: '
                f'[green]{registro_watermark.data_inicial_cobertura:%d/%m/%Y}[/green] → '
                f'[green]{registro_watermark.data_final_cobertura:%d/%m/%Y}[/green]',
            )
        else:
            console.print('[yellow]Nenhuma sincronização anterior registrada — primeira carga.[/yellow]')

        if registro_watermark.esta_desatualizada():
            data_inicial_busca, data_final_busca = registro_watermark.calcular_janela_da_proxima_busca()
            console.print(
                f'Buscando agora: '
                f'[cyan]{data_inicial_busca:%d/%m/%Y}[/cyan] → [cyan]{data_final_busca:%d/%m/%Y}[/cyan]',
            )
        else:
            console.print('[green]Dados já atualizados — nada a fazer.[/green]')

        with Progress(
            SpinnerColumn(), TextColumn('[bold]{task.description}'), TimeElapsedColumn(), console=console,
        ) as progress:
            tarefa = progress.add_task('Iniciando sincronização...', total=None)

            def _informar_fase(mensagem: str) -> None:
                progress.update(tarefa, description=mensagem)

            def _informar_pagina(numero_da_pagina, registros_na_pagina, total_acumulado):
                progress.update(
                    tarefa,
                    description=(
                        f'Buscando na API — página {numero_da_pagina} '
                        f'(+{registros_na_pagina}, total {total_acumulado})'
                    ),
                )

            relatorio = sincronizar_impostos_entrada_xml(
                informar_fase=_informar_fase, informar_pagina=_informar_pagina,
            )

        if relatorio.contagem_por_cfop:
            tabela_cfop = Table(title='CFOPs mantidos no filtro')
            tabela_cfop.add_column('CFOP')
            tabela_cfop.add_column('Descrição')
            tabela_cfop.add_column('Notas', justify='right')
            for cfop, descricao, contagem in relatorio.contagem_por_cfop:
                tabela_cfop.add_row(cfop, descricao, str(contagem))
            console.print(tabela_cfop)

        tabela_tempo = Table(title='Sincronização de Impostos de Entrada — Tempo por Fase')
        tabela_tempo.add_column('Fase')
        tabela_tempo.add_column('Tempo (s)', justify='right')
        for fase in FASES_EM_ORDEM:
            valor = getattr(relatorio, fase)
            if valor is not None:
                tabela_tempo.add_row(NOME_EXIBICAO_FASE[fase], f'{valor:.3f}')
        console.print(tabela_tempo)

        resumo = (
            f'[bold]Selecionados[/bold]        {relatorio.produtos_selecionados}\n'
            f'[bold]Sincronizados[/bold]        {relatorio.produtos_sincronizados}\n'
            f'[yellow]Sem produto no ERP[/yellow]  {relatorio.produtos_sem_correspondencia}\n'
            f'[bold]Com erro[/bold]             {relatorio.produtos_com_erro}'
        )
        console.print(Panel(resumo, title=f'Sincronização concluída — {empresa}', border_style='green'))