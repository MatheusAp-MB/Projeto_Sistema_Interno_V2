# integracao_sysemp/management/commands/reprocessar_impostos_entrada_de_json.py

# Função Objetivo: Repersiste no banco os impostos de entrada a partir do
# json JÁ SALVO em disco (XML_Manifesto_NF_notas_mais_recentes_por_produto.json)
# — não chama a API, não toca o watermark. Uso real: reprocessar produtos já
# sincronizados quando um campo novo é adicionado ao modelo (ex:
# quantidade_nota/custo_unitario, 10/08/2026) e precisa ser preenchido pra
# quem já tinha dado sincronizado antes do campo existir — sem gastar uma
# chamada nova na API (cara/lenta).

from django.core.management.base import CommandError
from core.management.commands._base_empresa import ComandoComEmpresa
from rich.console import Console
from rich.table import Table

from integracao_sysemp.servicos.arquivos_retorno_api import NOME_ARQUIVO_NOTAS_MAIS_RECENTES, ler_json
from integracao_sysemp.servicos.orquestrador import RelatorioDeSincronizacao, persistir_selecionados_no_banco


class Command(ComandoComEmpresa):
    help = (
        'Repersiste no banco os impostos de entrada a partir do json já salvo em disco '
        '(XML_Manifesto_NF_notas_mais_recentes_por_produto.json) — não chama a API, não toca o watermark.'
    )

    def handle(self, *args, **options):
        console = Console()

        selecionados = ler_json(NOME_ARQUIVO_NOTAS_MAIS_RECENTES)
        if not selecionados:
            raise CommandError(
                f'Arquivo "{NOME_ARQUIVO_NOTAS_MAIS_RECENTES}" não encontrado ou vazio — nada pra reprocessar.',
            )

        relatorio = RelatorioDeSincronizacao()
        relatorio.produtos_selecionados = len(selecionados)

        console.print(f'{len(selecionados)} produtos selecionados no json — persistindo no banco...')
        persistir_selecionados_no_banco(selecionados, relatorio)

        tabela = Table(title='Reprocessamento a partir do JSON — Resultado')
        tabela.add_column('Campo')
        tabela.add_column('Valor', justify='right')
        tabela.add_row('Produtos selecionados', str(relatorio.produtos_selecionados))
        tabela.add_row('Produtos sincronizados', str(relatorio.produtos_sincronizados))
        tabela.add_row('Sem Produto correspondente', str(relatorio.produtos_sem_correspondencia))
        tabela.add_row('Com erro (foram pros erros)', str(relatorio.produtos_com_erro))
        console.print(tabela)

        self.stdout.write(self.style.SUCCESS('Reprocessamento concluído.'))