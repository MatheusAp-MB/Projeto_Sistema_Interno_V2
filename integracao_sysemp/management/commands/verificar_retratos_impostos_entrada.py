# integracao_sysemp/management/commands/verificar_retratos_impostos_entrada.py

# Função Objetivo: Acha (e, com --apagar, remove) os retratos de impostos de
# entrada em que NÃO se pode confiar:
#
#   1) INCOMPLETOS — o guarda-chuva existe, mas falta alguma das 6 tabelas de
#      imposto (ICMS, ICMS ST, ICMS Retido, IPI, PIS, COFINS). Sobra de uma
#      sincronização que falhou no meio quando a transação abria no banco
#      errado (corrigido em 09/10/2026, ver sincronizacao_impostos_entrada.py).
#      A precificação já trata esses retratos como "sem dado fiscal" (o produto
#      só não ganha preço), mas outras telas ainda podem tropeçar neles.
#
#   2) COM PENDÊNCIA — o produto está na lista de pendências da última
#      sincronização (XML_Manifesto_NF_Erros.json). Se a falha foi no meio da
#      gravação (antes da correção acima), o retrato pode estar MISTURADO:
#      cabeçalho da nota nova com impostos da nota antiga. Completo, mas
#      mentiroso — por isso aparece aqui também.
#
# Sem --apagar só lista (nada é alterado). Com --apagar remove os INCOMPLETOS
# (inúteis: a precificação já os ignora). Os COM PENDÊNCIA só saem com
# --incluir-pendencias, porque pode ser um retrato antigo e válido (falha
# DEPOIS da correção desfaz a gravação e preserva o retrato anterior) — quem
# decide é o Matheus, olhando a lista.
#
# Apagar o retrato deixa o produto "sem retrato" (honesto); a próxima
# sincronização recria o retrato correto, desde que a nota dele caia na janela
# buscada (por isso o comando sugere o --desde certo no final).

from django.core.exceptions import ObjectDoesNotExist
from django.db import router, transaction
from django.db.models import Q
from rich.console import Console
from rich.table import Table

from core.management.commands._base_empresa import ComandoComEmpresa
from impostos.descritores_impostos import DESCRITORES_IMPOSTOS
from impostos.models import ImpostosECustosXMLEntradaProduto
from integracao_sysemp.servicos.arquivos_retorno_api import NOME_ARQUIVO_ERROS, ler_json


# Função Objetivo: Nomes (como aparecem na tela) das tabelas de imposto que 1 retrato NÃO tem.
def _tabelas_que_faltam(retrato: ImpostosECustosXMLEntradaProduto) -> list[str]:
    faltando = []
    for descritor in DESCRITORES_IMPOSTOS:
        try:
            getattr(retrato, descritor.nome_do_related_name_no_banco)
        except ObjectDoesNotExist:
            faltando.append(descritor.nome_para_exibicao)
    return faltando


class Command(ComandoComEmpresa):
    help = (
        'Lista os retratos de impostos de entrada incompletos (falta alguma tabela de imposto) '
        'ou de produtos com pendência de sincronização. Com --apagar, remove esses retratos.'
    )

    def adicionar_argumentos(self, parser):
        parser.add_argument(
            '--apagar', action='store_true',
            help='Remove os retratos INCOMPLETOS (os impostos filhos que existirem vão junto). '
                 'Sem este argumento o comando só lista, não altera nada.',
        )
        parser.add_argument(
            '--incluir-pendencias', action='store_true',
            help='Junto com --apagar: remove também os retratos de produtos com pendência de sincronização '
                 '(podem estar misturados — cabeçalho da nota nova com impostos da antiga).',
        )

    def handle(self, *args, **options):
        console = Console()
        empresa = options['empresa']
        apagar = options['apagar']
        incluir_pendencias = options['incluir_pendencias']

        nomes_dos_impostos = [d.nome_do_related_name_no_banco for d in DESCRITORES_IMPOSTOS]

        falta_algum_imposto = Q()
        for nome in nomes_dos_impostos:
            falta_algum_imposto |= Q(**{f'{nome}__isnull': True})

        incompletos = list(
            ImpostosECustosXMLEntradaProduto.objects
            .filter(falta_algum_imposto)
            .select_related('produto', *nomes_dos_impostos)
            .order_by('produto__sku')
        )

        pendencias = ler_json(NOME_ARQUIVO_ERROS, padrao={}) or {}
        ids_incompletos = {retrato.pk for retrato in incompletos}
        com_pendencia = list(
            ImpostosECustosXMLEntradaProduto.objects
            .filter(produto__ean__in=list(pendencias))
            .exclude(pk__in=ids_incompletos)
            .select_related('produto')
            .order_by('produto__sku')
        ) if pendencias else []

        total_de_retratos = ImpostosECustosXMLEntradaProduto.objects.count()
        console.print(f'[bold]Empresa[/bold] {empresa} — {total_de_retratos} retrato(s) de impostos de entrada no banco.')

        if not incompletos and not com_pendencia:
            console.print('[green]Nenhum retrato incompleto e nenhum com pendência. Nada a fazer.[/green]')
            return

        tabela = Table(title='Retratos em que não se pode confiar')
        tabela.add_column('SKU')
        tabela.add_column('EAN')
        tabela.add_column('NF')
        tabela.add_column('Emissão')
        tabela.add_column('Problema')

        for retrato in incompletos:
            tabela.add_row(
                str(retrato.produto.sku), str(retrato.produto.ean), str(retrato.nr_nf),
                f'{retrato.emissao:%d/%m/%Y}' if retrato.emissao else '—',
                f'INCOMPLETO — falta: {", ".join(_tabelas_que_faltam(retrato))}',
            )
        for retrato in com_pendencia:
            motivo = str(pendencias[retrato.produto.ean].get('mensagem', ''))[:70]
            tabela.add_row(
                str(retrato.produto.sku), str(retrato.produto.ean), str(retrato.nr_nf),
                f'{retrato.emissao:%d/%m/%Y}' if retrato.emissao else '—',
                f'PENDÊNCIA (última sincronização falhou; pode estar misturado) — {motivo}',
            )
        console.print(tabela)
        console.print(
            f'[bold]Incompletos[/bold] {len(incompletos)}   [bold]Com pendência[/bold] {len(com_pendencia)}',
        )

        if not apagar:
            console.print(
                '\n[yellow]Só listei — nada foi alterado.[/yellow] '
                'Pra remover os INCOMPLETOS, rode de novo com [bold]--apagar[/bold] '
                '(pra remover também os COM PENDÊNCIA: [bold]--apagar --incluir-pendencias[/bold]).',
            )
            return

        retratos_a_apagar = incompletos + (com_pendencia if incluir_pendencias else [])
        if not retratos_a_apagar:
            console.print(
                '\n[yellow]Não há retrato incompleto pra remover.[/yellow] Os listados acima têm só pendência — '
                'use [bold]--apagar --incluir-pendencias[/bold] se quiser removê-los também.',
            )
            return
        banco_da_empresa = router.db_for_write(ImpostosECustosXMLEntradaProduto)
        with transaction.atomic(using=banco_da_empresa):
            ImpostosECustosXMLEntradaProduto.objects.filter(
                pk__in=[retrato.pk for retrato in retratos_a_apagar],
            ).delete()

        console.print(f'\n[green]{len(retratos_a_apagar)} retrato(s) removido(s).[/green] Esses produtos agora estão "sem retrato".')
        if com_pendencia and not incluir_pendencias:
            console.print(f'[yellow]{len(com_pendencia)} retrato(s) com pendência foram mantidos (use --incluir-pendencias pra removê-los).[/yellow]')

        emissoes = [retrato.emissao for retrato in retratos_a_apagar if retrato.emissao]
        desde = f'{min(emissoes):%Y-%m-%d}' if emissoes else 'AAAA-MM-DD'
        console.print(
            'Pra recriar os retratos certos:\n'
            f'    python manage.py sincronizar_impostos_entrada --empresa {empresa} --desde {desde}\n'
            'Produtos com PENDÊNCIA só voltam a sincronizar depois que o dado da nota for corrigido no Sysemp — '
            'enquanto isso ficam sem preço (é o comportamento seguro).',
        )
