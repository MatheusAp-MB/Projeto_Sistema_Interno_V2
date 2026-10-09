# integracao_sysemp/management/commands/sincronizar_impostos_entrada.py

import argparse
from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from core.management.commands._base_empresa import ComandoComEmpresa
from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada
from integracao_sysemp.servicos.orquestrador import sincronizar_impostos_entrada_xml

def _data_iso(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f'"{texto}" não é uma data válida — use o formato AAAA-MM-DD (ex: 2026-01-01).')


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

    def adicionar_argumentos(self, parser):
        # * [EXPLICAÇÃO] → Sem isso, só dá pra reconsultar a API depois de
        #                  MARGEM_DE_SEGURANCA_DIAS de "descanso" desde a
        #                  última sincronização — bom pra rotina automática,
        #                  ruim quando se sabe que um dado específico mudou
        #                  fora do ritmo normal (achado real de 19/08/2026
        #                  com a marca HIDROLIGHT) e precisa reconsultar na
        #                  hora, sem esperar o prazo.
        parser.add_argument(
            '--forcar', action='store_true',
            help='Ignora a checagem de "já atualizado" e busca de novo a janela recente '
                 '(cobertura - margem até hoje), mesmo que a última sincronização tenha sido há poucos dias.',
        )
        # * [EXPLICAÇÃO] → Preenche o espelho da NF (botão "Ver NF" da grade de
        #                  precificação) de notas mais antigas que a janela
        #                  normal. Já implica --forcar. Nunca encurta a janela
        #                  normal — só estica pra trás quando a data pedida é
        #                  mais antiga que o início dela.
        parser.add_argument(
            '--desde', type=_data_iso, default=None, metavar='AAAA-MM-DD',
            help='Busca a partir desta data (se for anterior ao início da janela normal) — '
                 'preenche o espelho de NFs antigas. Implica --forcar.',
        )

    def handle(self, *args, **options):
        console = Console()
        empresa = options['empresa']
        forcar = options['forcar']
        desde = options['desde']

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

        if forcar or desde is not None or registro_watermark.esta_desatualizada():
            data_inicial_busca, data_final_busca = registro_watermark.calcular_janela_da_proxima_busca()
            if desde is not None and desde < data_inicial_busca:
                data_inicial_busca = desde
            rotulo_forcado = (
                ' [yellow](forçado com --forcar/--desde)[/yellow]'
                if (forcar or desde is not None) and not registro_watermark.esta_desatualizada() else ''
            )
            console.print(
                f'Buscando agora{rotulo_forcado}: '
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
                informar_fase=_informar_fase, informar_pagina=_informar_pagina, forcar=forcar, desde=desde,
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
            f'[bold]Com erro[/bold]             {relatorio.produtos_com_erro}\n'
            f'[bold]NFs completas gravadas[/bold] {relatorio.notas_completas_gravadas}\n'
            f'[bold]NFs completas com erro[/bold] {relatorio.notas_completas_com_erro}'
        )
        console.print(Panel(resumo, title=f'Sincronização concluída — {empresa}', border_style='green'))