# integracao_sysemp/management/commands/reprocessar_impostos_entrada_do_bruto.py

# Função Objetivo: Re-filtra e re-seleciona a partir do BRUTO já salvo em
# disco (XML_Manifesto_NF_Bruto.json) — não chama a API. Sobrescreve os
# jsons de filtrado/selecionados com o resultado correto e persiste no
# banco. Uso real: filtro_cfop.py tinha um bug (14/08/2026 — bruto num
# formato plano que o filtro não sabia processar, gerando 0 selecionados
# mesmo com dado real no bruto) e o bruto em disco continua válido — evita
# rechamar a API (cara/lenta). Diferente de reprocessar_impostos_entrada_de_json
# (que só relê o json de selecionados já correto, sem re-filtrar).

from django.core.management.base import CommandError
from core.management.commands._base_empresa import ComandoComEmpresa
from rich.console import Console
from rich.table import Table

from integracao_sysemp.servicos.arquivos_retorno_api import (
    NOME_ARQUIVO_BRUTO,
    NOME_ARQUIVO_FILTRADO,
    NOME_ARQUIVO_NOTAS_MAIS_RECENTES,
    ler_json,
    salvar_json,
)
from integracao_sysemp.servicos.filtro_cfop import filtrar_por_cfop
from integracao_sysemp.servicos.orquestrador import RelatorioDeSincronizacao, persistir_selecionados_no_banco
from integracao_sysemp.servicos.selecao_nota_recente import selecionar_nota_mais_recente_por_produto


class Command(ComandoComEmpresa):
    help = (
        'Re-filtra e re-seleciona a partir do bruto já salvo em disco '
        '(XML_Manifesto_NF_Bruto.json) e persiste no banco — não chama a API, não toca o watermark.'
    )

    def handle(self, *args, **options):
        console = Console()

        bruto = ler_json(NOME_ARQUIVO_BRUTO)
        if not bruto or not bruto.get('retorno'):
            raise CommandError(f'Arquivo "{NOME_ARQUIVO_BRUTO}" não encontrado ou vazio — nada pra reprocessar.')

        console.print(f'{len(bruto["retorno"])} notas brutas — filtrando por CFOP...')
        filtrado = filtrar_por_cfop(bruto['retorno'])
        salvar_json(filtrado, NOME_ARQUIVO_FILTRADO)

        console.print(f'{len(filtrado)} registros filtrados — selecionando a nota mais recente por produto...')
        selecionados = selecionar_nota_mais_recente_por_produto(filtrado)
        salvar_json(selecionados, NOME_ARQUIVO_NOTAS_MAIS_RECENTES)

        relatorio = RelatorioDeSincronizacao()
        relatorio.produtos_selecionados = len(selecionados)

        console.print(f'{len(selecionados)} produtos selecionados — persistindo no banco...')
        persistir_selecionados_no_banco(selecionados, relatorio)

        tabela = Table(title='Reprocessamento a partir do Bruto — Resultado')
        tabela.add_column('Campo')
        tabela.add_column('Valor', justify='right')
        tabela.add_row('Notas brutas', str(len(bruto['retorno'])))
        tabela.add_row('Registros filtrados (CFOP)', str(len(filtrado)))
        tabela.add_row('Produtos selecionados', str(relatorio.produtos_selecionados))
        tabela.add_row('Produtos sincronizados', str(relatorio.produtos_sincronizados))
        tabela.add_row('Sem Produto correspondente', str(relatorio.produtos_sem_correspondencia))
        tabela.add_row('Com erro (foram pros erros)', str(relatorio.produtos_com_erro))
        console.print(tabela)

        self.stdout.write(self.style.SUCCESS('Reprocessamento concluído.'))