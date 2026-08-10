# integracao_sysemp/management/commands/sincronizar_impostos_entrada.py

from django.core.management.base import BaseCommand
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from integracao_sysemp.servicos.orquestrador import sincronizar_impostos_entrada_xml

FASES_EM_ORDEM = (
    'busca_api', 'salvar_bruto', 'filtro_cfop', 'salvar_filtrado',
    'selecao_nota_recente', 'salvar_selecionados', 'persistencia_no_banco', 'total',
)


class Command(BaseCommand):
    help = 'Sincroniza os impostos/custos de entrada a partir do manifesto XML do Sysemp.'

    def handle(self, *args, **options):
        console = Console()

        with Progress(
            SpinnerColumn(), TextColumn('[bold]{task.description}'), TimeElapsedColumn(), console=console,
        ) as progress:
            tarefa = progress.add_task('Iniciando sincronização...', total=None)

            def _informar_fase(mensagem: str) -> None:
                progress.update(tarefa, description=mensagem)

            relatorio = sincronizar_impostos_entrada_xml(informar_fase=_informar_fase)

        tabela = Table(title='Sincronização de Impostos de Entrada — Tempo por Fase')
        tabela.add_column('Fase')
        tabela.add_column('Tempo (s)', justify='right')
        for fase in FASES_EM_ORDEM:
            valor = getattr(relatorio, fase)
            if valor is not None:
                tabela.add_row(fase, f'{valor:.3f}')
        console.print(tabela)

        console.print(f'Produtos selecionados: {relatorio.produtos_selecionados}')
        console.print(f'Produtos sincronizados: {relatorio.produtos_sincronizados}')
        console.print(f'Sem Produto correspondente: {relatorio.produtos_sem_correspondencia}')
        console.print(f'Com erro (foram pros erros): {relatorio.produtos_com_erro}')

        self.stdout.write(self.style.SUCCESS('Sincronização concluída.'))