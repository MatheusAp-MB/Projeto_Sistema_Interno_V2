# scripts_exploracao_ERP/duble_precificacao.py

# Função Objetivo: Duble de Precificação — passo a passo didático, só leitura, cobrindo
# os 6 marketplaces (Mercado Livre, Raia, Magalu, Shopee, TikTok, Amazon) e todas as
# variações internas reais de cada um (ML: Clássico/Premium; TikTok: Sem Afiliado/Com
# Afiliado; Amazon: DBA/FBA; Raia/Magalu/Shopee: nenhuma), nas 4 margens (Mínima/Padrão/
# Máxima/Competição), pros produtos de EANS_TESTE. Substitui o antigo
# duble_precificacao_ml.py (quebrado desde 16/08 — produto.pis_cofins removido — e cobria
# só ML/Clássico/Padrão). Não reimplementa nenhuma conta: instancia as 6 classes de
# fórmula de PRODUÇÃO (as mesmas usadas pelos calcular_grade_precificacao_*) e usa os
# métodos de auditoria delas (formula_abstrata/formula_preenchida/passos/entrada/
# intermediarios/saida) — o que este script mostra é EXATAMENTE o que o sistema real
# calculou, nunca uma conta paralela. Erro de assert numa combinação não derruba o
# script inteiro — é capturado, registrado no resumo, e o Duble segue pras próximas.
# Só leitura no banco, nenhuma escrita.

import os
import sys
from dataclasses import fields as dataclass_fields
from datetime import datetime


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from produtos.models import Produto
from precificacao.models import (
    ConfiguracaoOperacional, FaixaArmazenagem, TabelaComissaoShopee, TabelaComissaoTiktok,
    FreteAmazon, TaxaKgAdicionalAmazon,
)

from mercado_livre.models import (
    FreteML, TipoDeAnuncioMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre,
)
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from precificacao.funcoes_auxiliares.mercado_livre.formula_precificacao import FormulaPrecificacao

from raia.models import ConfiguracaoRaia
from precificacao.funcoes_auxiliares.raia.formula_precificacao_raia import FormulaPrecificacaoRaia

from magalu.models import ConfiguracaoMagalu, FreteMagalu
from precificacao.funcoes_auxiliares.magalu.formula_precificacao_magalu import FormulaPrecificacaoMagalu

from shopee.models import ConfiguracaoShopee
from precificacao.funcoes_auxiliares.shopee.formula_precificacao_shopee import FormulaPrecificacaoShopee

from tiktok.models import ConfiguracaoTiktok, FreteTiktok
from precificacao.funcoes_auxiliares.tiktok.formula_precificacao_tiktok import FormulaPrecificacaoTiktok

from amazon.models import ConfiguracaoAmazon
from precificacao.funcoes_auxiliares.amazon.formula_precificacao_amazon import FormulaPrecificacaoAmazon


# ========== Configuração do Duble ==========

EANS_TESTE = [
    '7908050719121',  # pulverizador — produto de referência, usado desde o Duble antigo
    '7909436926904',  # CONJUNTO REP. MOTOR 1.0 CV 127V — 1 dos 2 SKUs com erro de assert em Raia/Magalu
    '7891988014072',  # PARTE APARELHO MECANICO/KIT DA BARRA... — o outro SKU problemático
]

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')

console = Console(record=True)

resumo_geral = []  # 1 dict por combinação (produto, marketplace, variação, margem) — vira a tabela final


# ========== Helpers de impressão (Rich) — reaproveitados por todos os marketplaces ==========

# Função Objetivo: Imprime qualquer dataclass de auditoria (Entrada/Intermediarios/Saida)
# como tabela — 1 linha por campo, igual foi de fato usado/calculado naquela margem.
def _imprimir_dataclass(titulo, dado):
    tabela = Table(title=titulo)
    tabela.add_column('Campo', style='cyan', no_wrap=True)
    tabela.add_column('Valor', style='green')
    for campo in dataclass_fields(dado):
        tabela.add_row(campo.name, str(getattr(dado, campo.name)))
    console.print(tabela)


# Função Objetivo: Imprime passos() — o passo a passo real da fórmula, na ordem certa.
def _imprimir_passos(passos):
    tabela = Table(title='Passo a Passo (auditoria real da fórmula)', show_lines=True)
    tabela.add_column('#', justify='right', width=3)
    tabela.add_column('Rótulo', style='cyan')
    tabela.add_column('Fórmula (valores reais)')
    tabela.add_column('Resultado', style='bold green', justify='right')
    for passo in passos:
        tabela.add_row(str(passo['ordem']), passo['rotulo'], passo['formula'], str(passo['resultado']))
    console.print(tabela)


# Função Objetivo: Painel de destaque com o resultado final — preço, frete, margem obtida
# vs meta (com alerta visual se ficar abaixo), e margem exata antes do RoundUp90.
def _imprimir_resultado_final(formula, margem_alvo_percentual):
    margem_obtida = formula.saida.margem_percentual_obtida
    margem_ok = margem_obtida >= margem_alvo_percentual
    cor = 'green' if margem_ok else 'red'
    alerta = '' if margem_ok else '  ⚠ MARGEM ABAIXO DA META'

    linhas = [
        f'[bold {cor}]Preço Final: R$ {formula.saida.preco_final:.2f}[/bold {cor}]',
        f'Frete usado: R$ {formula.saida.frete_usado:.2f}',
        f'Margem obtida: {margem_obtida:.2f}%  (meta: {margem_alvo_percentual:.2f}%){alerta}',
        f'Margem exata (antes do RoundUp90): {formula.saida.margem_exata_percentual:.2f}%',
    ]
    preco_de_exibicao = getattr(formula.saida, 'preco_de_exibicao', None)
    if preco_de_exibicao is not None:
        linhas.append(f'Preço de exibição (decorativo): R$ {preco_de_exibicao:.2f}')

    console.print(Panel('\n'.join(linhas), border_style=cor))


# Função Objetivo: Guarda 1 linha da combinação (produto, marketplace, variação, margem)
# no resumo geral — sempre, mesmo em erro/sem-cálculo, pra aparecer na tabela final.
def _registrar_resumo(produto, marketplace, variacao, margem_chave, status, formula=None, margem_alvo=None, detalhe=''):
    resumo_geral.append({
        'produto': f'{produto.ean} — {produto.titulo[:40]}',
        'marketplace': marketplace,
        'variacao': variacao or '—',
        'margem': margem_chave,
        'status': status,
        'preco_final': f'R$ {formula.saida.preco_final:.2f}' if formula and formula.resolvida else '—',
        'margem_obtida': f'{formula.saida.margem_percentual_obtida:.2f}%' if formula and formula.resolvida else '—',
        'margem_meta': f'{margem_alvo:.2f}%' if margem_alvo is not None else '—',
        'detalhe': detalhe,
    })


# Função Objetivo: Roda 1 combinação (produto, marketplace, variação, margem) por
# completo — instancia a fórmula real (via construir_formula, sem calcular ainda),
# chama .calcular(), imprime Entrada/Intermediários/Passos/Saída/Resultado, e sempre
# registra no resumo geral. Erro de assert é capturado aqui — não derruba o script.
def _rodar_e_exibir(produto, marketplace, variacao_rotulo, margem_chave, margem_alvo_percentual, construir_formula):
    rotulo_variacao = f' — {variacao_rotulo}' if variacao_rotulo else ''
    console.rule(f'[bold]{marketplace}{rotulo_variacao} | margem {margem_chave} ({margem_alvo_percentual}%) | {produto.ean}[/bold]')

    try:
        formula = construir_formula().calcular()
    except AssertionError as e:
        console.print(Panel(f'[bold red]ERRO DE ASSERT[/bold red]\n{e}', border_style='red'))
        console.print()
        _registrar_resumo(produto, marketplace, variacao_rotulo, margem_chave, 'ERRO DE ASSERT', margem_alvo=margem_alvo_percentual, detalhe=str(e))
        return

    if not formula.resolvida:
        motivo = (
            'Sem crédito fiscal de entrada (impostos_entrada ausente/incompleto)'
            if getattr(formula, '_creditos', None) is None
            else 'Nenhuma faixa gerou solução consistente (meta de margem inatingível)'
        )
        console.print(Panel(f'[bold yellow]SEM CÁLCULO POSSÍVEL[/bold yellow]\n{motivo}', border_style='yellow'))
        console.print()
        _registrar_resumo(produto, marketplace, variacao_rotulo, margem_chave, 'SEM CÁLCULO', margem_alvo=margem_alvo_percentual, detalhe=motivo)
        return

    _imprimir_dataclass('Entrada (dado cru — banco/planilha/config)', formula.entrada)
    console.print()
    _imprimir_dataclass('Intermediários (cada pedaço calculado)', formula.intermediarios)
    console.print()
    console.print(f'[dim]{formula.formula_abstrata()}[/dim]')
    console.print(f'[dim]{formula.formula_preenchida()}[/dim]')
    console.print()
    _imprimir_passos(formula.passos())
    console.print()
    _imprimir_dataclass('Saída (resultado)', formula.saida)
    _imprimir_resultado_final(formula, margem_alvo_percentual)
    console.print()

    status = 'OK' if formula.saida.margem_percentual_obtida >= margem_alvo_percentual else 'MARGEM ABAIXO DA META'
    _registrar_resumo(produto, marketplace, variacao_rotulo, margem_chave, status, formula=formula, margem_alvo=margem_alvo_percentual)


# ========== Carga de configuração (1x, fora do loop de produtos) ==========

console.print(Panel('[bold]Duble de Precificação — carregando configuração real do banco...[/bold]', border_style='blue'))

config_geral = ConfiguracaoOperacional.obter()
faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
configs_ml = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}
frete_todas_ml = list(FreteML.objects.all())

config_raia = ConfiguracaoRaia.obter()

config_magalu = ConfiguracaoMagalu.obter()
frete_todas_magalu = list(FreteMagalu.objects.all())

config_shopee = ConfiguracaoShopee.obter()
faixas_comissao_shopee = list(TabelaComissaoShopee.objects.all().order_by('preco_min'))

config_tiktok = ConfiguracaoTiktok.obter()
faixas_comissao_tiktok = list(TabelaComissaoTiktok.objects.all().order_by('preco_min'))
frete_todas_tiktok = list(FreteTiktok.objects.all())

config_amazon = ConfiguracaoAmazon.obter()
fretes_amazon = list(FreteAmazon.objects.all())
taxas_kg_adicional = list(TaxaKgAdicionalAmazon.objects.all())

# * [EXPLICAÇÃO] → Raia/Magalu/Shopee/TikTok/Amazon usam margem FIXA, hardcoded no
#                  próprio calcular_grade_precificacao_* (não vem de config) — copiado
#                  literal daqui pra manter o Duble fiel ao que roda de verdade.
MARGENS_PADRAO = [('minima', 10), ('padrao', 15), ('maxima', 20), ('competicao', 5)]


# Função Objetivo: ML é o único marketplace que lê as 4 margens de uma Configuração
# real por tipo de anúncio (Clássico/Premium têm margens próprias, não fixas).
def _margens_do_tipo_ml(config):
    return [
        ('minima', config.margem_minima), ('padrao', config.margem_padrao),
        ('maxima', config.margem_maxima), ('competicao', config.margem_competicao),
    ]


# ========== 1 função por marketplace — mesmo padrão dos calcular_grade_precificacao_* ==========

def _processar_mercado_livre(produto):
    dim = resolver_dimensoes_efetivas(produto, variacao=None)
    for tipo, tipo_rotulo in [(TipoAnuncio.CLASSICO, 'Clássico'), (TipoAnuncio.PREMIUM, 'Premium')]:
        config_tipo = configs_ml.get(tipo)
        if not config_tipo:
            console.print(f'[yellow]Sem ConfiguracaoTipoAnuncioMercadoLivre para {tipo_rotulo} — pulado.[/yellow]')
            continue
        for margem_chave, margem_valor in _margens_do_tipo_ml(config_tipo):
            _rodar_e_exibir(
                produto, 'Mercado Livre', tipo_rotulo, margem_chave, margem_valor,
                lambda config_tipo=config_tipo, margem_valor=margem_valor: FormulaPrecificacao(
                    produto=produto, dimensoes_efetivas=dim, config_tipo=config_tipo,
                    config_geral=config_geral, margem_alvo_percentual=margem_valor,
                    frete_todas=frete_todas_ml, faixas_armazenagem=faixas_armazenagem,
                )
            )


def _processar_raia(produto):
    for margem_chave, margem_valor in MARGENS_PADRAO:
        _rodar_e_exibir(
            produto, 'Raia', None, margem_chave, margem_valor,
            lambda margem_valor=margem_valor: FormulaPrecificacaoRaia(
                produto=produto, config_raia=config_raia, config_geral=config_geral,
                margem_alvo_percentual=margem_valor, faixas_armazenagem=faixas_armazenagem,
            )
        )


def _processar_magalu(produto):
    for margem_chave, margem_valor in MARGENS_PADRAO:
        _rodar_e_exibir(
            produto, 'Magalu', None, margem_chave, margem_valor,
            lambda margem_valor=margem_valor: FormulaPrecificacaoMagalu(
                produto=produto, config_magalu=config_magalu, config_geral=config_geral,
                margem_alvo_percentual=margem_valor, frete_todas=frete_todas_magalu,
                faixas_armazenagem=faixas_armazenagem,
            )
        )


def _processar_shopee(produto):
    for margem_chave, margem_valor in MARGENS_PADRAO:
        _rodar_e_exibir(
            produto, 'Shopee', None, margem_chave, margem_valor,
            lambda margem_valor=margem_valor: FormulaPrecificacaoShopee(
                produto=produto, config_shopee=config_shopee, config_geral=config_geral,
                margem_alvo_percentual=margem_valor, faixas_comissao=faixas_comissao_shopee,
                faixas_armazenagem=faixas_armazenagem,
            )
        )


def _processar_tiktok(produto):
    for tipo, tipo_rotulo in [('sem_afiliado', 'Sem Afiliado'), ('com_afiliado', 'Com Afiliado')]:
        for margem_chave, margem_valor in MARGENS_PADRAO:
            _rodar_e_exibir(
                produto, 'TikTok', tipo_rotulo, margem_chave, margem_valor,
                lambda tipo=tipo, margem_valor=margem_valor: FormulaPrecificacaoTiktok(
                    produto=produto, config_tiktok=config_tiktok, config_geral=config_geral,
                    margem_alvo_percentual=margem_valor, tipo=tipo,
                    faixas_comissao=faixas_comissao_tiktok, frete_todas=frete_todas_tiktok,
                    faixas_armazenagem=faixas_armazenagem,
                )
            )


def _processar_amazon(produto):
    for tipo, tipo_rotulo in [('dba', 'DBA'), ('fba', 'FBA')]:
        for margem_chave, margem_valor in MARGENS_PADRAO:
            _rodar_e_exibir(
                produto, 'Amazon', tipo_rotulo, margem_chave, margem_valor,
                lambda tipo=tipo, margem_valor=margem_valor: FormulaPrecificacaoAmazon(
                    produto=produto, config_amazon=config_amazon, config_geral=config_geral,
                    margem_alvo_percentual=margem_valor, tipo=tipo,
                    fretes_amazon=fretes_amazon, taxas_kg_adicional=taxas_kg_adicional,
                    faixas_armazenagem=faixas_armazenagem,
                )
            )


# ========== Execução — N produtos × 6 marketplaces × variações × 4 margens ==========

for ean in EANS_TESTE:
    try:
        produto = Produto.objects.get(ean=ean)
    except Produto.DoesNotExist:
        console.print(Panel(f'[bold red]Produto EAN {ean} não encontrado no banco — pulado.[/bold red]', border_style='red'))
        continue

    console.rule(f'[bold blue]PRODUTO: {produto.ean} — {produto.titulo}[/bold blue]', style='blue')
    console.print(f'SKU: {produto.sku}  |  Marca: {produto.marca}  |  Custo: R$ {produto.custo:.2f}')
    console.print()

    _processar_mercado_livre(produto)
    _processar_raia(produto)
    _processar_magalu(produto)
    _processar_shopee(produto)
    _processar_tiktok(produto)
    _processar_amazon(produto)


# ========== Resumo geral — 1 linha por combinação, pra ver o panorama de uma vez ==========

console.rule('[bold]RESUMO GERAL[/bold]')

tabela_resumo = Table(title='Todas as combinações rodadas neste Duble')
tabela_resumo.add_column('Produto', style='cyan', max_width=30)
tabela_resumo.add_column('Marketplace')
tabela_resumo.add_column('Variação')
tabela_resumo.add_column('Margem')
tabela_resumo.add_column('Status')
tabela_resumo.add_column('Preço Final', justify='right')
tabela_resumo.add_column('Margem Obtida', justify='right')
tabela_resumo.add_column('Meta', justify='right')

for linha in resumo_geral:
    cor_status = {
        'OK': 'green', 'ERRO DE ASSERT': 'bold red',
        'SEM CÁLCULO': 'yellow', 'MARGEM ABAIXO DA META': 'bold red',
    }.get(linha['status'], 'white')
    tabela_resumo.add_row(
        linha['produto'], linha['marketplace'], linha['variacao'], linha['margem'],
        f'[{cor_status}]{linha["status"]}[/{cor_status}]',
        linha['preco_final'], linha['margem_obtida'], linha['margem_meta'],
    )

console.print(tabela_resumo)

total = len(resumo_geral)
qtd_ok = sum(1 for l in resumo_geral if l['status'] == 'OK')
qtd_erro = sum(1 for l in resumo_geral if l['status'] == 'ERRO DE ASSERT')
qtd_sem_calculo = sum(1 for l in resumo_geral if l['status'] == 'SEM CÁLCULO')
qtd_margem_abaixo = sum(1 for l in resumo_geral if l['status'] == 'MARGEM ABAIXO DA META')

console.print(
    f'\nTotal de combinações: {total}  |  OK: {qtd_ok}  |  '
    f'Erros de assert: {qtd_erro}  |  Sem cálculo: {qtd_sem_calculo}  |  '
    f'Margem abaixo da meta (sem crashar): {qtd_margem_abaixo}'
)

os.makedirs(PASTA_SAIDAS, exist_ok=True)
carimbo = datetime.now().strftime('%Y%m%d_%H%M%S')
CAMINHO_LOG = os.path.join(PASTA_SAIDAS, f'duble_precificacao_{carimbo}.txt')
console.print(f'\n[dim]Log completo salvo em: {CAMINHO_LOG}[/dim]')
console.save_text(CAMINHO_LOG)