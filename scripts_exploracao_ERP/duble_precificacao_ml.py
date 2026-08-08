# scripts_exploracao_ERP/duble_precificacao_ml.py

# Função Objetivo: "Dublê" da FormulaPrecificacao real do Mercado Livre,
# construído de baixo pra cima (Etapa 1 → 10, ver "Plano em Etapas do Duble
# de Precificacao ML" no vault). Só leitura no banco, nenhuma escrita.
# 3 pontos que estavam "em aberto" no plano foram resolvidos aqui com uma
# escolha explícita, marcada em comentário — ainda precisam de validação:
#   Etapa 7: redução de ICMS/ICMS ST usada como vem da API, sem confirmar
#            empiricamente com produto real ≠ 0 (só PIS/COFINS validados).
#   Etapa 8: PIS e COFINS entram como 2 créditos SEPARADOS no FIXO (não
#            combinados) — escolha, não decisão fechada com o usuário.
#   Etapa 9: ICMS/PIS-COFINS de SAÍDA continuam vindo direto do Produto
#            real (banco) — o manifesto de entrada não cobre isso.

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

from produtos.models import Produto
from produtos.funcoes_auxiliares.dimensoes_fisicas import metro_cubico_de_dimensoes, selecionar_faixa_por_dimensao
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem
from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_por_margem
from dados_xml_nf import (
    IdentificacaoNF, DadosNF, Custos, IdentificadorRegra, IcmsSt, Icms, IcmsRet, Ipi, Pis, Cofins,
)

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')
NOME_ARQUIVO_ENTRADA_XML = 'nota_mais_recente_por_produto.json'

EAN_TESTADO = '7908050719121'

console = Console()


# Função Objetivo: Imprime qualquer dataclass do dublê como tabela Rich —
# 1 linha por campo, reaproveitada por todas as etapas.
def _imprimir_etapa(titulo, dado):
    tabela = Table(title=titulo)
    tabela.add_column('Campo', style='cyan', no_wrap=True)
    tabela.add_column('Valor', style='green')
    for campo in fields(dado):
        tabela.add_row(campo.name, str(getattr(dado, campo.name)))
    console.print(tabela)


# ========== Etapa 1 — Identificação do Produto (banco real, sem XML) ==========

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
_imprimir_etapa('Etapa 1 — Identificação do Produto (banco real)', identificacao)


# ========== Etapa 2 — Custo de Coleta (banco/config real, sem XML) ==========

@dataclass(frozen=True)
class CustoDeColeta:
    altura: Decimal
    largura: Decimal
    comprimento: Decimal
    peso: Decimal
    origem_dimensao: str
    metro_cubico: Decimal
    fator_coleta: Decimal
    coleta: Decimal

    @classmethod
    def a_partir_do_produto(cls, produto) -> 'CustoDeColeta':
        dim = resolver_dimensoes_efetivas(produto, variacao=None)
        config_geral = ConfiguracaoOperacional.obter()
        metro_cubico = metro_cubico_de_dimensoes(dim.altura, dim.largura, dim.comprimento)
        coleta = metro_cubico * config_geral.fator_coleta
        return cls(
            altura=dim.altura, largura=dim.largura, comprimento=dim.comprimento, peso=dim.peso,
            origem_dimensao=dim.origem.value,
            metro_cubico=metro_cubico, fator_coleta=config_geral.fator_coleta, coleta=coleta,
        )


custo_coleta = CustoDeColeta.a_partir_do_produto(produto)
_imprimir_etapa('Etapa 2 — Custo de Coleta (banco/config real)', custo_coleta)


# ========== Etapa 3 — Custo de Armazenagem (banco/config real, sem XML) ==========

@dataclass(frozen=True)
class CustoDeArmazenagem:
    origem: str
    periodo_armazenagem: Decimal
    armazenagem: Decimal

    @classmethod
    def a_partir_do_produto(cls, produto, custo_coleta) -> 'CustoDeArmazenagem':
        config_geral = ConfiguracaoOperacional.obter()

        if produto.armazenagem_planilha is not None:
            return cls(
                origem='planilha',
                periodo_armazenagem=config_geral.periodo_armazenagem,
                armazenagem=produto.armazenagem_planilha,
            )

        faixas = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))
        faixa_usada = selecionar_faixa_por_dimensao(
            custo_coleta.altura, custo_coleta.largura, custo_coleta.comprimento, faixas
        )
        armazenagem = (
            faixa_usada.valor_diario * config_geral.periodo_armazenagem
            if faixa_usada else Decimal('0')
        )
        return cls(
            origem='faixa_dimensao',
            periodo_armazenagem=config_geral.periodo_armazenagem,
            armazenagem=armazenagem,
        )


custo_armazenagem = CustoDeArmazenagem.a_partir_do_produto(produto, custo_coleta)
_imprimir_etapa('Etapa 3 — Custo de Armazenagem (banco/config real)', custo_armazenagem)


# ========== Carrega o registro do XML (Sysemp) — base das Etapas 4, 5, 6 ==========

def _carregar_registro_xml(ean):
    caminho = os.path.join(PASTA_SAIDAS, NOME_ARQUIVO_ENTRADA_XML)
    with open(caminho, encoding='utf-8') as arquivo:
        produtos_sysemp = json.load(arquivo)

    registro = produtos_sysemp.get(ean)
    if registro is None:
        raise RuntimeError(f'Produto {ean} não encontrado em {caminho}')

    return registro


registro_xml = _carregar_registro_xml(EAN_TESTADO)
qtde_nota = float(registro_xml['Qtde'])


# ========== Etapa 4 — Identificação da Nota Fiscal (XML) ==========

identificacao_nf = IdentificacaoNF.a_partir_do_registro(registro_xml)
dados_nf = DadosNF.a_partir_do_registro(registro_xml)
_imprimir_etapa('Etapa 4 — Identificação da Nota Fiscal (XML)', identificacao_nf)
_imprimir_etapa('Etapa 4 — Dados da Nota Fiscal (XML)', dados_nf)


# ========== Etapa 5 — Custo vindo do XML ==========

custos_xml = Custos.a_partir_do_registro(registro_xml)
_imprimir_etapa('Etapa 5 — Custo vindo do XML', custos_xml)


# ========== Etapa 6 — Impostos vindos do XML, brutos ==========

identificador_regra = IdentificadorRegra.a_partir_do_registro(registro_xml)
icms_st = IcmsSt.a_partir_do_registro(registro_xml)
icms = Icms.a_partir_do_registro(registro_xml)
icms_ret = IcmsRet.a_partir_do_registro(registro_xml)
ipi = Ipi.a_partir_do_registro(registro_xml)
pis = Pis.a_partir_do_registro(registro_xml, custos_xml.total)
cofins = Cofins.a_partir_do_registro(registro_xml, custos_xml.total)

_imprimir_etapa('Etapa 6 — Identificador de Regra (XML)', identificador_regra)
_imprimir_etapa('Etapa 6 — ICMS ST (XML, bruto)', icms_st)
_imprimir_etapa('Etapa 6 — ICMS (XML, bruto)', icms)
_imprimir_etapa('Etapa 6 — ICMS RET (XML, bruto)', icms_ret)
_imprimir_etapa('Etapa 6 — IPI (XML, bruto)', ipi)
_imprimir_etapa('Etapa 6 — PIS (XML, bruto)', pis)
_imprimir_etapa('Etapa 6 — COFINS (XML, bruto)', cofins)


# ========== Etapa 7 — Cálculo individual de cada imposto, por unidade ==========

@dataclass(frozen=True)
class ImpostoPorUnidade:
    nome: str
    base_calculo: Decimal
    aliquota: Decimal
    reducao: Decimal
    valor: Decimal

    @classmethod
    def calcular(cls, nome, aliquota, reducao, custo_unitario) -> 'ImpostoPorUnidade':
        # * [EXPLICAÇÃO] → base_calculo derivada do custo_unitário + redução
        # (algebricamente igual a dividir a base bruta do XML pela Qtde da
        # nota — ver "Calculo de Reducao PIS e COFINS..." no vault). Pra
        # ICMS/ICMS ST a redução vem direto da API, ainda sem validação
        # empírica com produto real ≠ 0.
        custo = Decimal(str(custo_unitario))
        aliquota_dec = Decimal(str(aliquota))
        reducao_dec = Decimal(str(reducao))
        base_calculo = custo * (Decimal('1') - reducao_dec / 100)
        valor = base_calculo * aliquota_dec / 100
        return cls(nome=nome, base_calculo=base_calculo, aliquota=aliquota_dec, reducao=reducao_dec, valor=valor)


@dataclass(frozen=True)
class IcmsRetPorUnidade:
    base: Decimal
    valor: Decimal

    @classmethod
    def calcular(cls, icms_ret, qtde) -> 'IcmsRetPorUnidade':
        # * [EXPLICAÇÃO] → ICMS RET não tem aliquota/redução no nosso
        # modelo — divide direto pela Qtde da nota, sem passar pela fórmula
        # de base_calculo × aliquota usada nos outros impostos.
        qtde_dec = Decimal(str(qtde))
        return cls(base=Decimal(str(icms_ret.base)) / qtde_dec, valor=Decimal(str(icms_ret.valor)) / qtde_dec)


icms_st_unitario = ImpostoPorUnidade.calcular('ICMS ST', icms_st.aliquota, icms_st.reducao, custos_xml.unitario)
icms_unitario = ImpostoPorUnidade.calcular('ICMS', icms.aliquota, icms.reducao, custos_xml.unitario)
ipi_unitario = ImpostoPorUnidade.calcular('IPI', ipi.aliquota, 0, custos_xml.unitario)
pis_unitario = ImpostoPorUnidade.calcular('PIS', pis.aliquota, pis.reducao, custos_xml.unitario)
cofins_unitario = ImpostoPorUnidade.calcular('COFINS', cofins.aliquota, cofins.reducao, custos_xml.unitario)
icms_ret_unitario = IcmsRetPorUnidade.calcular(icms_ret, qtde_nota)

_imprimir_etapa('Etapa 7 — ICMS ST por unidade', icms_st_unitario)
_imprimir_etapa('Etapa 7 — ICMS por unidade', icms_unitario)
_imprimir_etapa('Etapa 7 — IPI por unidade', ipi_unitario)
_imprimir_etapa('Etapa 7 — PIS por unidade', pis_unitario)
_imprimir_etapa('Etapa 7 — COFINS por unidade', cofins_unitario)
_imprimir_etapa('Etapa 7 — ICMS RET por unidade', icms_ret_unitario)


# ========== Etapa 8 — Cálculo do FIXO ==========

@dataclass(frozen=True)
class CalculoFixo:
    custo_unitario: Decimal
    ipi_valor: Decimal
    frete_cif_fob_percentual: Decimal
    frete_cif_fob_valor: Decimal
    st_valor: Decimal
    custo_final: Decimal
    coleta: Decimal
    armazenagem: Decimal
    credito_icms_entrada: Decimal
    credito_pis: Decimal
    credito_cofins: Decimal
    fixo: Decimal

    @classmethod
    def calcular(cls, produto, custos_xml, ipi_unitario, icms_st_unitario, icms_unitario,
                 pis_unitario, cofins_unitario, custo_coleta, custo_armazenagem) -> 'CalculoFixo':
        custo_unitario = Decimal(str(custos_xml.unitario))
        frete_cif_fob_percentual = produto.frete_cif_fob or Decimal('0')  # * [REAL] não vem do Sysemp Entrada
        frete_cif_fob_valor = custo_unitario * (frete_cif_fob_percentual / 100)

        custo_final = custo_unitario + ipi_unitario.valor + frete_cif_fob_valor + icms_st_unitario.valor

        # * [EXPLICAÇÃO] → escolha (etapa 8 "em aberto"): PIS e COFINS
        # entram como 2 créditos SEPARADOS, não combinados — a confirmar.
        fixo = (
            custo_coleta.coleta + custo_armazenagem.armazenagem + custo_final
            - (icms_unitario.valor + pis_unitario.valor + cofins_unitario.valor)
        )

        return cls(
            custo_unitario=custo_unitario, ipi_valor=ipi_unitario.valor,
            frete_cif_fob_percentual=frete_cif_fob_percentual, frete_cif_fob_valor=frete_cif_fob_valor,
            st_valor=icms_st_unitario.valor, custo_final=custo_final,
            coleta=custo_coleta.coleta, armazenagem=custo_armazenagem.armazenagem,
            credito_icms_entrada=icms_unitario.valor, credito_pis=pis_unitario.valor,
            credito_cofins=cofins_unitario.valor, fixo=fixo,
        )


calculo_fixo = CalculoFixo.calcular(
    produto, custos_xml, ipi_unitario, icms_st_unitario, icms_unitario,
    pis_unitario, cofins_unitario, custo_coleta, custo_armazenagem,
)
_imprimir_etapa('Etapa 8 — Cálculo do FIXO', calculo_fixo)


# ========== Etapa 9 — Cálculo do Denominador ==========

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
config_tipo = ConfiguracaoTipoAnuncioMercadoLivre.objects.get(tipo_anuncio=TipoAnuncio.CLASSICO)
MARGEM_ALVO_TESTADA = config_tipo.margem_padrao


@dataclass(frozen=True)
class CalculoDenominador:
    comissao_percentual: Decimal
    icms_saida_percentual: Decimal
    pis_cofins_saida_percentual: Decimal
    taxa_percentual: Decimal
    margem_alvo_percentual: Decimal
    denominador: Decimal

    @classmethod
    def calcular(cls, produto, config_tipo, margem_alvo_percentual) -> 'CalculoDenominador':
        # * [EXPLICAÇÃO] → ICMS/PIS-COFINS de SAÍDA continuam vindo do
        # Produto real (banco) — o manifesto de entrada não cobre saída.
        comissao_percentual = config_tipo.comissao
        icms_saida_percentual = produto.icms_saida_media or Decimal('0')
        pis_cofins_saida_percentual = produto.pis_cofins or Decimal('0')

        taxa_fracao = (comissao_percentual + icms_saida_percentual + pis_cofins_saida_percentual) / 100
        margem_dec = Decimal(str(margem_alvo_percentual))
        denominador = Decimal('1') - taxa_fracao - (margem_dec / 100)

        return cls(
            comissao_percentual=comissao_percentual, icms_saida_percentual=icms_saida_percentual,
            pis_cofins_saida_percentual=pis_cofins_saida_percentual, taxa_percentual=taxa_fracao * 100,
            margem_alvo_percentual=margem_dec, denominador=denominador,
        )


calculo_denominador = CalculoDenominador.calcular(produto, config_tipo, MARGEM_ALVO_TESTADA)
_imprimir_etapa('Etapa 9 — Cálculo do Denominador', calculo_denominador)


# ========== Etapa 10 — Resto do fluxo real (frete + goal-seek) ==========

@dataclass(frozen=True)
class ResultadoFinal:
    preco_final: Decimal
    frete_usado: Decimal
    margem_valor: Decimal
    margem_percentual_obtida: Decimal

    @classmethod
    def calcular(cls, fixo, denominador, custo_coleta, custos_xml) -> 'ResultadoFinal':
        frete_todas = list(FreteML.objects.all())
        peso = custo_coleta.peso
        faixas_candidatas = sorted(
            (f for f in frete_todas if f.peso_min <= peso and (f.peso_max is None or f.peso_max >= peso)),
            key=lambda f: f.preco_min,
        )

        resultado = resolver_preco_por_margem(
            fixo=fixo.fixo,
            taxa_percentual=denominador.taxa_percentual / 100,
            margem_alvo_fracao=denominador.margem_alvo_percentual / 100,
            custo_produto=Decimal(str(custos_xml.unitario)),
            faixas_frete_candidatas=faixas_candidatas,
            rebate_valor=Decimal('0'),
        )

        if resultado is None:
            raise RuntimeError('Meta de margem inatingível com os dados atuais — sem cálculo possível.')

        return cls(
            preco_final=resultado['preco_calculado'],
            frete_usado=resultado['frete_usado'],
            margem_valor=resultado['detalhamento']['margem_valor'],
            margem_percentual_obtida=resultado['margem_percentual_obtida'],
        )


resultado_final = ResultadoFinal.calcular(calculo_fixo, calculo_denominador, custo_coleta, custos_xml)
_imprimir_etapa(f'Etapa 10 — Resultado Final (margem-alvo {MARGEM_ALVO_TESTADA}%, Clássico)', resultado_final)