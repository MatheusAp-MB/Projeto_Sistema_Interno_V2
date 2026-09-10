# scripts_exploracao_ERP/duble_precificacao_ml.py

# Função Objetivo: Passo a passo didático de como cada valor da precificação
# ML é obtido — Produto → Dimensões → Custo Unitário → Impostos → Custo
# Final → Coleta → Armazenagem → FIXO → Taxa/Denominador → Preço Final. Só
# leitura no banco, nenhuma escrita. A Etapa 4 é o ÚNICO lugar que CALCULA
# cada imposto (ICMS, ICMS ST, IPI, PIS, COFINS) — tudo depois dela só
# CONSOME esses valores já prontos, nunca recalcula. PIS e COFINS seguem
# separados até o fim (decisão definitiva, não mais "em aberto").

import json
import os
import sys
from dataclasses import dataclass, fields
from decimal import Decimal

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
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from produtos.funcoes_auxiliares.dimensoes_fisicas import (
    metro_cubico_de_dimensoes, selecionar_faixa_por_dimensao,
)
from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_por_margem
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem
from mercado_livre.models import FreteML, TipoDeAnuncioMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre
from integracao_sysemp.servicos.dados_xml_nf import Custos, IcmsSt, Icms, Ipi, Pis, Cofins
from integracao_sysemp.servicos.arquivos_retorno_api import ler_json, NOME_ARQUIVO_NOTAS_MAIS_RECENTES

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')

EAN_TESTADO = '7908050719121'

console = Console(record=True)


# Função Objetivo: Imprime qualquer dataclass simples como tabela Rich —
# 1 linha por campo, reaproveitada pelas Etapas 1, 2 e 3.
def _imprimir_etapa(titulo, dado):
    tabela = Table(title=titulo)
    tabela.add_column('Campo', style='cyan', no_wrap=True)
    tabela.add_column('Valor', style='green')
    for campo in fields(dado):
        tabela.add_row(campo.name, str(getattr(dado, campo.name)))
    console.print(tabela)


# ========== Etapa 1 — Qual é o produto? (banco real) ==========

@dataclass(frozen=True)
class IdentificacaoProdutoBanco:
    ean: str
    cod_fabricante: str
    codigo_auxiliar: str
    titulo: str
    marca: str

    @classmethod
    def a_partir_do_produto(cls, produto) -> 'IdentificacaoProdutoBanco':
        return cls(
            ean=produto.ean,
            cod_fabricante=produto.cod_fabricante,
            codigo_auxiliar=produto.sku,
            titulo=produto.titulo,
            marca=produto.marca,
        )


produto = Produto.objects.get(ean=EAN_TESTADO)
identificacao = IdentificacaoProdutoBanco.a_partir_do_produto(produto)
_imprimir_etapa('Etapa 1 — Qual é o produto? (banco real)', identificacao)


# ========== Etapa 2 — Quais são as dimensões desse produto? (banco real) ==========

@dataclass(frozen=True)
class DimensoesDoProduto:
    altura: float
    largura: float
    comprimento: float
    peso: float
    origem: str

    @classmethod
    def a_partir_do_produto(cls, produto) -> 'DimensoesDoProduto':
        dim = resolver_dimensoes_efetivas(produto, variacao=None)
        return cls(
            altura=float(dim.altura), largura=float(dim.largura),
            comprimento=float(dim.comprimento), peso=float(dim.peso),
            origem=dim.origem.value,
        )


dimensoes = DimensoesDoProduto.a_partir_do_produto(produto)
_imprimir_etapa('Etapa 2 — Quais são as dimensões desse produto? (banco real)', dimensoes)


# ========== Etapa 3 — Qual é o custo unitário desse produto? (XML) ==========

def _carregar_registro_xml(ean):
    # * [EXPLICAÇÃO] → o json de "notas mais recentes por produto" é
    #                  gravado como LISTA (1 dict por produto), não como
    #                  dict indexado por EAN — procura na lista pela chave
    #                  real do manifesto (Código Barras).
    registros = ler_json(NOME_ARQUIVO_NOTAS_MAIS_RECENTES, padrao=[])
    for registro in registros:
        if registro.get('Código Barras') == ean:
            return registro

    raise RuntimeError(
        f'Produto {ean} não encontrado em {NOME_ARQUIVO_NOTAS_MAIS_RECENTES} '
        f'(rode manage.py sincronizar_impostos_entrada antes).'
    )


@dataclass(frozen=True)
class CustoUnitarioDoXML:
    custo_total_nota: float
    quantidade_nota: float
    custo_unitario: float

    @classmethod
    def a_partir_do_registro(cls, registro) -> 'CustoUnitarioDoXML':
        custos = Custos.a_partir_do_registro(registro)
        return cls(
            custo_total_nota=custos.total,
            quantidade_nota=float(registro['Qtde']),
            custo_unitario=custos.unitario,
        )


registro_xml = _carregar_registro_xml(EAN_TESTADO)
custo_unitario_xml = CustoUnitarioDoXML.a_partir_do_registro(registro_xml)
_imprimir_etapa('Etapa 3 — Qual é o custo unitário desse produto? (XML)', custo_unitario_xml)


# ========== Etapa 4 — Impostos, imposto por imposto (didático) ==========
# * [EXPLICAÇÃO] → Único lugar que CALCULA imposto. Tudo depois consome
#                   os `valor` devolvidos aqui — nunca recalcula.

@dataclass(frozen=True)
class EntradaUsada:
    campo: str
    valor: str
    origem: str


@dataclass(frozen=True)
class PassoDeCalculo:
    etapa: int
    formula_abstrata: str
    formula_real: str
    resultado: str


def _imprimir_entradas_usadas(entradas):
    tabela = Table(title='Entradas Usadas')
    tabela.add_column('Campo', style='cyan')
    tabela.add_column('Valor')
    tabela.add_column('De onde veio', style='dim')
    for entrada in entradas:
        tabela.add_row(entrada.campo, entrada.valor, entrada.origem)
    console.print(tabela)


def _imprimir_processamento(titulo, passos):
    tabela = Table(title=titulo)
    tabela.add_column('Etapa', justify='right')
    tabela.add_column('Fórmula (abstrata)')
    tabela.add_column('Fórmula (valores reais)')
    tabela.add_column('Resultado', style='bold')
    for passo in passos:
        tabela.add_row(str(passo.etapa), passo.formula_abstrata, passo.formula_real, passo.resultado)
    console.print(tabela)


def _imprimir_resultado_final(rotulo, valor):
    console.print(Panel(f'[bold green]R$ {valor:.2f}[/bold green]', title=rotulo, border_style='green'))


# Função Objetivo: Mostra o cálculo de 1 imposto por completo, na ordem em
# que os dados de fato aparecem: primeiro TODAS as entradas usadas (cru,
# com origem — incluindo Base de Cálculo/Custo Total quando a redução for
# calculada por nós), depois o cálculo da redução (se houver), depois o
# processamento do imposto em si, depois o resultado final.
def _exibir_calculo_didatico_do_imposto(
    nome_imposto, aliquota, reducao, origem_reducao, custo_unitario, calculo_da_reducao=None,
):
    console.rule(f'[bold]{nome_imposto}[/bold]')

    entradas = [
        EntradaUsada('Custo Unitário', f'R$ {custo_unitario:.2f}', 'XML — Custo Unitário da nota mais recente'),
        EntradaUsada('Alíquota', f'{aliquota:.2f}%', 'XML — direto da nota'),
    ]
    if calculo_da_reducao is not None:
        base_calculo_bruta, custo_total_nota = calculo_da_reducao
        entradas.append(EntradaUsada(
            f'Base de Cálculo {nome_imposto} (nota)', f'R$ {base_calculo_bruta:.2f}',
            f'XML — Base de Cálculo {nome_imposto} da nota',
        ))
        entradas.append(EntradaUsada('Custo Total (nota)', f'R$ {custo_total_nota:.2f}', 'XML — Custo Total da nota'))
    entradas.append(EntradaUsada('Redução', f'{reducao:.2f}%', origem_reducao))

    _imprimir_entradas_usadas(entradas)
    console.print()

    if calculo_da_reducao is not None:
        _imprimir_processamento('Como a Redução foi calculada', [
            PassoDeCalculo(
                1, 'Redução = (1 − Base de Cálculo ÷ Custo Total) × 100',
                f'(1 − R$ {base_calculo_bruta:.2f} ÷ R$ {custo_total_nota:.2f}) × 100',
                f'{reducao:.2f}%',
            ),
        ])
        console.print()

    base_calculo = custo_unitario * (1 - reducao / 100)
    valor = base_calculo * aliquota / 100

    _imprimir_processamento('Processamento', [
        PassoDeCalculo(1, 'Base = Custo Unitário', f'Base = R$ {custo_unitario:.2f}', f'R$ {custo_unitario:.2f}'),
        PassoDeCalculo(
            2, 'Base reduzida = Base × (1 − Redução)',
            f'R$ {custo_unitario:.2f} × (1 − {reducao:.2f}%)', f'R$ {base_calculo:.2f}',
        ),
        PassoDeCalculo(
            3, 'Valor = Base reduzida × Alíquota',
            f'R$ {base_calculo:.2f} × {aliquota:.2f}%', f'R$ {valor:.2f}',
        ),
    ])

    _imprimir_resultado_final(f'Valor {nome_imposto} a pagar (por unidade)', valor)
    console.print()

    return valor


# Função Objetivo: ICMS ST não segue o mesmo padrão dos outros impostos —
# a base não é derivável do custo unitário (o fornecedor já embute margem
# agregada/MVA antes da redução) e o valor não é base × alíquota isolado,
# é líquido do ICMS normal (lógica de substituição tributária). Por isso
# usa o campo bruto da nota como base, e recebe o valor do ICMS normal já
# calculado como parâmetro — dependência explícita, não recalculada por
# fora. [EXPLICAÇÃO] Validado com produto real de alíquota ≠ 0 (08/08) —
# aguardando validação do tributário/superior mesmo assim.
def _exibir_calculo_didatico_icms_st(icms_st, quantidade_nota, valor_icms_normal_unitario):
    console.rule('[bold]ICMS ST[/bold]')

    # * [EXPLICAÇÃO] → Bug encontrado em 09/08 comparando com a planilha real:
    #                   quando a nota NÃO tem ICMS ST (produto não é substituição
    #                   tributária), Base de Cálculo ICMS ST = 0. Sem essa guarda,
    #                   a fórmula abaixo calculava valor_bruto=0 e ainda subtraía
    #                   o ICMS normal (valor_liquido = 0 − valor_icms_normal),
    #                   virando um crédito negativo fantasma que reduzia o Custo
    #                   Final indevidamente. Mesmo critério de "é ST?" da Etapa 8.
    if not (icms_st.valor > 0 or icms_st.base_calculo > 0):
        console.print('[dim]Nota sem ICMS ST (Base de Cálculo = 0) — produto não está sob substituição tributária nesta nota.[/dim]')
        console.print()
        _imprimir_resultado_final('Valor ICMS ST a pagar (por unidade)', 0.0)
        console.print()
        return 0.0

    entradas = [
        EntradaUsada(
            'Base de Cálculo ICMS ST (nota)', f'R$ {icms_st.base_calculo:.2f}',
            'XML — Base de Cálculo ICMS ST da nota (já reduzida pelo fornecedor)',
        ),
        EntradaUsada('Quantidade (nota)', f'{quantidade_nota:.2f}', 'XML — Qtde da nota'),
        EntradaUsada('Alíquota ICMS ST', f'{icms_st.aliquota:.2f}%', 'XML — direto da nota'),
        EntradaUsada(
            'Redução ICMS ST (informativo)', f'{icms_st.reducao:.2f}%',
            'XML — já aplicada na Base de Cálculo acima, não recalculamos',
        ),
        EntradaUsada(
            'Valor ICMS (normal, por unidade)', f'R$ {valor_icms_normal_unitario:.2f}',
            'Calculado na etapa anterior (ICMS normal desta mesma nota)',
        ),
    ]
    _imprimir_entradas_usadas(entradas)
    console.print()

    base_unitaria = icms_st.base_calculo / quantidade_nota
    valor_bruto = base_unitaria * icms_st.aliquota / 100
    valor_liquido = valor_bruto - valor_icms_normal_unitario

    _imprimir_processamento('Processamento', [
        PassoDeCalculo(
            1, 'Base (unitária) = Base de Cálculo ICMS ST (nota) ÷ Quantidade',
            f'R$ {icms_st.base_calculo:.2f} ÷ {quantidade_nota:.2f}', f'R$ {base_unitaria:.2f}',
        ),
        PassoDeCalculo(
            2, 'Valor bruto = Base × Alíquota',
            f'R$ {base_unitaria:.2f} × {icms_st.aliquota:.2f}%', f'R$ {valor_bruto:.2f}',
        ),
        PassoDeCalculo(
            3, 'Valor líquido = Valor bruto − Valor ICMS (normal)',
            f'R$ {valor_bruto:.2f} − R$ {valor_icms_normal_unitario:.2f}', f'R$ {valor_liquido:.2f}',
        ),
    ])

    _imprimir_resultado_final('Valor ICMS ST a pagar (por unidade)', valor_liquido)
    console.print()

    return valor_liquido


icms_st = IcmsSt.a_partir_do_registro(registro_xml)
icms = Icms.a_partir_do_registro(registro_xml)
ipi = Ipi.a_partir_do_registro(registro_xml)
pis = Pis.a_partir_do_registro(registro_xml, custo_unitario_xml.custo_total_nota)
cofins = Cofins.a_partir_do_registro(registro_xml, custo_unitario_xml.custo_total_nota)

console.print('[bold]Etapa 4 — Impostos, imposto por imposto[/bold]\n')

valor_icms = _exibir_calculo_didatico_do_imposto(
    'ICMS', icms.aliquota, icms.reducao, 'XML — direto da nota (Redução ICMS)', custo_unitario_xml.custo_unitario
)
valor_icms_st = _exibir_calculo_didatico_icms_st(
    icms_st, custo_unitario_xml.quantidade_nota, valor_icms
)

valor_ipi = _exibir_calculo_didatico_do_imposto(
    'IPI', ipi.aliquota, 0, 'Não existe esse campo na API — assumido 0%', custo_unitario_xml.custo_unitario
)
valor_pis = _exibir_calculo_didatico_do_imposto(
    'PIS', pis.aliquota, pis.reducao,
    'Calculado — ver cálculo abaixo', custo_unitario_xml.custo_unitario,
    calculo_da_reducao=(pis.base_calculo, custo_unitario_xml.custo_total_nota),
)
valor_cofins = _exibir_calculo_didatico_do_imposto(
    'COFINS', cofins.aliquota, cofins.reducao,
    'Calculado — ver cálculo abaixo', custo_unitario_xml.custo_unitario,
    calculo_da_reducao=(cofins.base_calculo, custo_unitario_xml.custo_total_nota),
)


# ========== Etapa 5 — Custo Final (por unidade) ==========
# * [EXPLICAÇÃO] → custo_com_boni foi abandonado (decisão do usuário,
#                   09/08) — não faz sentido precificar com custo 0. Usa
#                   custo_unitário direto no lugar. Frete CIF/FOB segue
#                   vindo do banco/planilha (fora do escopo desta troca,
#                   ver [[Escopo Final]] no vault) — IPI e ICMS ST vêm
#                   já calculados da Etapa 4.
def _exibir_custo_final(custo_unitario, valor_ipi, valor_icms_st, frete_cif_fob_percentual):
    console.rule('[bold]Etapa 5 — Custo Final (por unidade)[/bold]')

    entradas = [
        EntradaUsada('Custo Unitário', f'R$ {custo_unitario:.2f}', 'XML — Etapa 3'),
        EntradaUsada('Valor IPI', f'R$ {valor_ipi:.2f}', 'XML — Etapa 4, já calculado'),
        EntradaUsada('Valor ICMS ST', f'R$ {valor_icms_st:.2f}', 'XML — Etapa 4, já calculado (líquido do ICMS normal)'),
        EntradaUsada('Frete CIF/FOB (%)', f'{frete_cif_fob_percentual:.2f}%', 'Banco/planilha — segue como está, fora do escopo desta troca'),
    ]
    _imprimir_entradas_usadas(entradas)
    console.print()

    frete_cif_fob_valor = custo_unitario * frete_cif_fob_percentual / 100
    custo_final = custo_unitario + valor_ipi + frete_cif_fob_valor + valor_icms_st

    _imprimir_processamento('Processamento', [
        PassoDeCalculo(
            1, 'Frete CIF/FOB = Custo Unitário × Frete CIF/FOB %',
            f'R$ {custo_unitario:.2f} × {frete_cif_fob_percentual:.2f}%', f'R$ {frete_cif_fob_valor:.2f}',
        ),
        PassoDeCalculo(
            2, 'Custo Final = Custo Unitário + IPI + Frete CIF/FOB + ICMS ST',
            f'R$ {custo_unitario:.2f} + R$ {valor_ipi:.2f} + R$ {frete_cif_fob_valor:.2f} + R$ {valor_icms_st:.2f}',
            f'R$ {custo_final:.2f}',
        ),
    ])
    _imprimir_resultado_final('Custo Final (por unidade)', custo_final)
    console.print()
    return custo_final


custo_final = _exibir_custo_final(
    custo_unitario_xml.custo_unitario, valor_ipi, valor_icms_st, float(produto.frete_cif_fob or 0)
)


# ========== Etapa 6 — Custo de Coleta ==========
# * [EXPLICAÇÃO] → Sem dado fiscal, real 100%: dimensões (Etapa 2) ×
#                   fator_coleta (Configuração Operacional real).
def _exibir_coleta(dimensoes, config_geral):
    console.rule('[bold]Etapa 6 — Custo de Coleta[/bold]')

    fator_coleta = float(config_geral.fator_coleta)
    entradas = [
        EntradaUsada('Altura', f'{dimensoes.altura:.2f} cm', 'Banco — Etapa 2'),
        EntradaUsada('Largura', f'{dimensoes.largura:.2f} cm', 'Banco — Etapa 2'),
        EntradaUsada('Comprimento', f'{dimensoes.comprimento:.2f} cm', 'Banco — Etapa 2'),
        EntradaUsada('Fator de Coleta', f'R$ {fator_coleta:.2f}/m³', 'Configuração Operacional real'),
    ]
    _imprimir_entradas_usadas(entradas)
    console.print()

    metro_cubico = float(metro_cubico_de_dimensoes(dimensoes.altura, dimensoes.largura, dimensoes.comprimento))
    coleta = metro_cubico * fator_coleta

    _imprimir_processamento('Processamento', [
        PassoDeCalculo(
            1, 'Metro Cúbico = (Altura÷100) × (Largura÷100) × (Comprimento÷100)',
            f'({dimensoes.altura:.2f}÷100) × ({dimensoes.largura:.2f}÷100) × ({dimensoes.comprimento:.2f}÷100)',
            f'{metro_cubico:.4f} m³',
        ),
        PassoDeCalculo(
            2, 'Coleta = Metro Cúbico × Fator de Coleta',
            f'{metro_cubico:.4f} × R$ {fator_coleta:.2f}', f'R$ {coleta:.2f}',
        ),
    ])
    _imprimir_resultado_final('Custo de Coleta (por unidade)', coleta)
    console.print()
    return coleta


config_geral = ConfiguracaoOperacional.obter()
coleta = _exibir_coleta(dimensoes, config_geral)


# ========== Etapa 7 — Custo de Armazenagem ==========
# * [EXPLICAÇÃO] → Não vem mais de planilha (confirmado pelo usuário,
#                   09/08) — sistema já calcula por faixa dinâmica. Segue
#                   a mesma checagem do código real (produto.armazenagem_
#                   planilha is not None) só pra não quebrar produto
#                   legado que ainda tenha esse campo preenchido.
def _exibir_armazenagem(produto, dimensoes, config_geral, faixas_armazenagem):
    console.rule('[bold]Etapa 7 — Custo de Armazenagem[/bold]')

    if produto.armazenagem_planilha is not None:
        armazenagem = float(produto.armazenagem_planilha)
        _imprimir_entradas_usadas([
            EntradaUsada('Armazenagem (planilha)', f'R$ {armazenagem:.2f}', 'Banco — produto.armazenagem_planilha (legado)'),
        ])
        console.print()
        _imprimir_processamento('Processamento', [
            PassoDeCalculo(1, 'Armazenagem = valor direto da planilha (legado)', f'R$ {armazenagem:.2f}', f'R$ {armazenagem:.2f}'),
        ])
        origem = 'planilha (legado)'
    else:
        faixa = selecionar_faixa_por_dimensao(dimensoes.altura, dimensoes.largura, dimensoes.comprimento, faixas_armazenagem)
        valor_diario = float(faixa.valor_diario) if faixa else 0.0
        periodo = config_geral.periodo_armazenagem

        _imprimir_entradas_usadas([
            EntradaUsada('Altura/Largura/Comprimento', f'{dimensoes.altura:.2f} / {dimensoes.largura:.2f} / {dimensoes.comprimento:.2f} cm', 'Banco — Etapa 2'),
            EntradaUsada('Faixa selecionada', faixa.nome if faixa else 'nenhuma', 'Faixa de Armazenagem real (sistema, faixa dinâmica)'),
            EntradaUsada('Valor Diário da Faixa', f'R$ {valor_diario:.4f}', 'Faixa de Armazenagem real'),
            EntradaUsada('Período de Armazenagem', f'{periodo} dias', 'Configuração Operacional real'),
        ])
        console.print()

        armazenagem = valor_diario * periodo
        _imprimir_processamento('Processamento', [
            PassoDeCalculo(
                1, 'Armazenagem = Valor Diário da Faixa × Período',
                f'R$ {valor_diario:.4f} × {periodo}', f'R$ {armazenagem:.2f}',
            ),
        ])
        origem = 'faixa dinâmica'

    _imprimir_resultado_final(f'Custo de Armazenagem (por unidade — origem: {origem})', armazenagem)
    console.print()
    return armazenagem


faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))
armazenagem = _exibir_armazenagem(produto, dimensoes, config_geral, faixas_armazenagem)


# ========== Etapa 8 — FIXO ==========
# * [EXPLICAÇÃO] → Só consome — Coleta/Armazenagem/Custo Final (5-7) e os
#                   3 créditos de imposto (Etapa 4) já vêm prontos. PIS e
#                   COFINS entram SEPARADOS (decisão definitiva, 09/08) —
#                   nunca mais somados num campo "pis_cofins" só.
def _exibir_fixo(coleta, armazenagem, custo_final, valor_icms, valor_pis, valor_cofins, eh_regime_st):
    console.rule('[bold]Etapa 8 — FIXO[/bold]')

    # * [EXPLICAÇÃO] → Hipótese de diferimento (09/08, não confirmada pelo
    #                   tributário/superior): produto com ICMS ST na nota
    #                   já teve o ICMS normal descontado POR DENTRO do
    #                   cálculo líquido do ST (Etapa 4) — dar esse crédito
    #                   de novo aqui seria creditar 2x o mesmo imposto.
    #                   Ver [[Hipotese de Diferimento do Credito de ICMS
    #                   Entrada em Produtos ST]] no vault.
    credito_icms_entrada = 0.0 if eh_regime_st else valor_icms
    origem_credito_icms = (
        'Zerado — regime ST detectado (hipótese de diferimento, aguardando validação do tributário)'
        if eh_regime_st else 'Etapa 4, já calculado'
    )

    entradas = [
        EntradaUsada('Coleta', f'R$ {coleta:.2f}', 'Etapa 6, já calculado'),
        EntradaUsada('Armazenagem', f'R$ {armazenagem:.2f}', 'Etapa 7, já calculado'),
        EntradaUsada('Custo Final', f'R$ {custo_final:.2f}', 'Etapa 5, já calculado'),
        EntradaUsada('Regime ST (nota)?', 'Sim' if eh_regime_st else 'Não', 'XML — Base/Valor ICMS ST da nota > 0'),
        EntradaUsada('Crédito ICMS (entrada)', f'R$ {credito_icms_entrada:.2f}', origem_credito_icms),
        EntradaUsada('Crédito PIS', f'R$ {valor_pis:.2f}', 'Etapa 4, já calculado'),
        EntradaUsada('Crédito COFINS', f'R$ {valor_cofins:.2f}', 'Etapa 4, já calculado'),
    ]
    _imprimir_entradas_usadas(entradas)
    console.print()

    creditos = credito_icms_entrada + valor_pis + valor_cofins
    fixo = coleta + armazenagem + custo_final - creditos

    _imprimir_processamento('Processamento', [
        PassoDeCalculo(
            1, 'Créditos = ICMS + PIS + COFINS',
            f'R$ {credito_icms_entrada:.2f} + R$ {valor_pis:.2f} + R$ {valor_cofins:.2f}', f'R$ {creditos:.2f}',
        ),
        PassoDeCalculo(
            2, 'FIXO = Coleta + Armazenagem + Custo Final − Créditos',
            f'R$ {coleta:.2f} + R$ {armazenagem:.2f} + R$ {custo_final:.2f} − R$ {creditos:.2f}',
            f'R$ {fixo:.2f}',
        ),
    ])
    _imprimir_resultado_final('FIXO (por unidade)', fixo)
    console.print()
    return fixo


eh_regime_st = icms_st.valor > 0 or icms_st.base_calculo > 0
fixo = _exibir_fixo(coleta, armazenagem, custo_final, valor_icms, valor_pis, valor_cofins, eh_regime_st)


# ========== Etapa 9 — Taxa, Denominador e Preço Final ==========
# * [EXPLICAÇÃO] → ICMS de saída e PIS/COFINS de saída seguem vindo do
#                   banco/planilha (fora do escopo desta troca — API de
#                   saída da Sysemp ainda não existe, ver [[Escopo Final]]
#                   no vault). Mostra só a margem PADRÃO do Clássico —
#                   Mínima/Máxima/Competição seria a mesma função com
#                   margem_alvo_percentual diferente.
def _exibir_denominador_e_resultado(fixo, custo_unitario, peso, config_tipo, produto, frete_todas):
    console.rule('[bold]Etapa 9 — Taxa, Denominador e Preço Final[/bold]')

    comissao_percentual = float(config_tipo.comissao)
    icms_saida_percentual = float(produto.icms_saida_media or 0)
    pis_cofins_saida_percentual = float(produto.pis_cofins or 0)
    margem_alvo_percentual = float(config_tipo.margem_padrao)

    entradas = [
        EntradaUsada('Comissão', f'{comissao_percentual:.2f}%', 'Configuração real do tipo de anúncio (Clássico)'),
        EntradaUsada('ICMS de Saída', f'{icms_saida_percentual:.2f}%', 'Banco/planilha — segue como está'),
        EntradaUsada('PIS/COFINS de Saída', f'{pis_cofins_saida_percentual:.2f}%', 'Banco/planilha — segue como está'),
        EntradaUsada('Margem-alvo (padrão)', f'{margem_alvo_percentual:.2f}%', 'Configuração real do tipo de anúncio'),
        EntradaUsada('FIXO', f'R$ {fixo:.2f}', 'Etapa 8, já calculado'),
    ]
    _imprimir_entradas_usadas(entradas)
    console.print()

    taxa_percentual_fracao = (comissao_percentual + icms_saida_percentual + pis_cofins_saida_percentual) / 100
    denominador = 1 - taxa_percentual_fracao - (margem_alvo_percentual / 100)

    _imprimir_processamento('Como a Taxa e o Denominador foram calculados', [
        PassoDeCalculo(
            1, 'Taxa = Comissão + ICMS Saída + PIS/COFINS Saída',
            f'{comissao_percentual:.2f}% + {icms_saida_percentual:.2f}% + {pis_cofins_saida_percentual:.2f}%',
            f'{taxa_percentual_fracao * 100:.2f}%',
        ),
        PassoDeCalculo(
            2, 'Denominador = 1 − Taxa − Margem-alvo',
            f'1 − {taxa_percentual_fracao * 100:.2f}% − {margem_alvo_percentual:.2f}%',
            f'{denominador:.4f}',
        ),
    ])
    console.print()

    faixas_candidatas = sorted(
        (f for f in frete_todas if f.peso_min <= peso and (f.peso_max is None or f.peso_max >= peso)),
        key=lambda f: f.preco_min,
    )

    resultado = resolver_preco_por_margem(
        fixo=fixo, taxa_percentual=Decimal(str(taxa_percentual_fracao)),
        margem_alvo_fracao=Decimal(str(margem_alvo_percentual / 100)),
        custo_produto=custo_unitario, faixas_frete_candidatas=faixas_candidatas,
    )

    if resultado is None:
        console.print('[bold red]Nenhuma faixa de frete gerou solução consistente — sem preço final.[/bold red]')
        return None

    d = resultado['detalhamento']
    _imprimir_processamento('Resolução do Preço (busca de faixa de frete real)', [
        PassoDeCalculo(1, 'Frete usado (faixa encontrada)', f'peso {peso:.2f}kg', f'R$ {d["frete_usado"]:.2f}'),
        PassoDeCalculo(
            2, 'Preço exato = (Frete + FIXO) ÷ Denominador',
            f'(R$ {d["frete_usado"]:.2f} + R$ {fixo:.2f}) ÷ {denominador:.4f}',
            f'R$ {d["preco_exato_antes_arredondar"]:.2f}',
        ),
        PassoDeCalculo(
            3, 'Preço Final = RoundUp90 (sempre pra cima)',
            f'R$ {d["preco_exato_antes_arredondar"]:.2f} → ,90', f'R$ {d["preco_calculado"]:.2f}',
        ),
    ])

    _imprimir_resultado_final('Preço Final (Clássico, margem padrão)', d['preco_calculado'])
    console.print(f'[dim]Margem obtida: {d["margem_percentual_obtida"]:.2f}% (meta: {margem_alvo_percentual:.2f}%)[/dim]')
    console.print()
    return resultado


config_tipo = ConfiguracaoTipoAnuncioMercadoLivre.objects.get(
    tipo_anuncio=TipoDeAnuncioMercadoLivre.TipoAnuncio.CLASSICO
)
frete_todas = list(FreteML.objects.all())
_exibir_denominador_e_resultado(fixo, custo_unitario_xml.custo_unitario, dimensoes.peso, config_tipo, produto, frete_todas)

CAMINHO_LOG = os.path.join(PASTA_SAIDAS, f'duble_{EAN_TESTADO}.txt')
os.makedirs(PASTA_SAIDAS, exist_ok=True)
console.print(f'\n[dim]Log completo salvo em: {CAMINHO_LOG}[/dim]')
console.save_text(CAMINHO_LOG)