# precificacao/funcoes_auxiliares/amazon/formula_precificacao_amazon.py

# Função Objetivo: Representa 1 margem candidata da Amazon já resolvida, com auditoria.
# Explicação em detalhe: motor 100% independente — busca de frete própria, sem reaproveitar
# nenhuma função de resolução do mercado_livre (só arredondar_para_90, regra matemática
# neutra usada por todos). Comissão é FLAT (13%, confirmado), diferente de Shopee/TikTok —
# quem varia por faixa de preço aqui é o FRETE, não a comissão (mesma ideia do ML original,
# implementação nova). "Tipo" (DBA/FBA) tem o mesmo papel de Clássico/Premium.
#
# Créditos fiscais de entrada (ICMS/IPI/PIS/COFINS) vêm prontos de impostos_entrada, via
# montar_creditos_fiscais_para_precificacao — já por unidade, já com o diferimento de ICMS
# ST resolvido internamente. Esta classe nunca reinterpreta esse valor, só consome.

import math
from dataclasses import dataclass, asdict
from decimal import Decimal
from django.core.exceptions import ObjectDoesNotExist
from precificacao.funcoes_auxiliares.goal_seek import arredondar_para_90
from produtos.funcoes_auxiliares.dimensoes_fisicas import (
    metro_cubico_de_dimensoes, selecionar_faixa_por_dimensao, resolver_dimensao_produto,
)
from impostos.funcoes_auxiliares.creditos_fiscais_para_precificacao import (
    montar_creditos_fiscais_para_precificacao,
)


@dataclass
class DadosEntrada:
    sku: str
    ean: str
    margem_alvo_percentual: Decimal
    tipo: str  # 'dba' ou 'fba'

    custo: Decimal
    custo_com_boni: Decimal
    frete_cif_fob_percentual: Decimal
    icms_saida_percentual: Decimal
    pis_saida_percentual: Decimal
    cofins_saida_percentual: Decimal
    comissao_percentual: Decimal

    armazenagem_planilha: Decimal | None
    origem_dados_fiscais: str

    altura: Decimal
    largura: Decimal
    comprimento: Decimal
    peso: Decimal
    origem_dimensao: str

    fator_coleta: Decimal
    periodo_armazenagem: Decimal


@dataclass
class DadosIntermediarios:
    custo_final: Decimal
    ipi_valor: Decimal
    frete_cif_fob_valor: Decimal
    metro_cubico: Decimal
    coleta: Decimal
    armazenagem_origem: str
    armazenagem: Decimal
    credito_icms_entrada: Decimal
    credito_pis: Decimal
    credito_cofins: Decimal
    pis_saida_valor: Decimal
    cofins_saida_valor: Decimal
    icms_saida_valor: Decimal
    comissao_valor: Decimal
    fixo: Decimal
    taxa_percentual: Decimal
    denominador: Decimal
    margem_alvo_valor: Decimal
    faixa_preco_min: Decimal
    faixa_preco_max: Decimal | None
    peso_min_usado: Decimal | None
    peso_max_usado: Decimal | None
    preco_exato_antes_arredondar: Decimal


@dataclass
class DadosSaida:
    preco_final: Decimal
    frete_usado: Decimal
    margem_valor: Decimal
    margem_percentual_obtida: Decimal
    margem_exata_percentual: Decimal
    margem_exata_valor: Decimal


class FormulaPrecificacaoAmazon:

    def __init__(self, produto, config_amazon, config_geral, margem_alvo_percentual, tipo,
                 fretes_amazon, taxas_kg_adicional, faixas_armazenagem=None):
        self.produto = produto
        self.config_amazon = config_amazon
        self.config_geral = config_geral
        self.margem_alvo_percentual = Decimal(str(margem_alvo_percentual))
        self.tipo = tipo
        self.fretes_amazon = [f for f in fretes_amazon if f.tipo == tipo]
        self.taxas_kg_adicional = [t for t in taxas_kg_adicional if t.tipo == tipo]
        self.faixas_armazenagem = faixas_armazenagem

        self.entrada = None
        self.intermediarios = None
        self.saida = None
        self.resolvida = False
        self._creditos = None

    def resolver_dimensao(self):
        self._altura, self._largura, self._comprimento, self._peso = resolver_dimensao_produto(self.produto)

    # Função Objetivo: Busca os créditos fiscais de entrada, já resolvidos e por unidade.
    def obter_creditos_fiscais(self):
        try:
            impostos_entrada = self.produto.impostos_entrada
        except ObjectDoesNotExist:
            self._creditos = None
            return

        creditos = montar_creditos_fiscais_para_precificacao(impostos_entrada)

        # Sem quantidade_nota (ou qualquer outro dado fiscal ausente),
        # nenhum dos 4 créditos existe — produto não precifica, nunca
        # finge um crédito parcial. Decisão: sem fallback.
        if None in (creditos.icms, creditos.ipi, creditos.pis, creditos.cofins):
            self._creditos = None
            return

        self._creditos = creditos

    def calcular_custo_final(self):
        produto = self.produto
        custo_com_boni = produto.custo_com_boni or produto.custo
        frete_cif_fob_percentual = produto.frete_cif_fob or Decimal('0')

        # IPI já vem em R$ pronto (dividido por unidade em impostos_entrada) —
        # nunca recalculado aqui a partir de percentual.
        ipi_valor = self._creditos.ipi
        frete_cif_fob_valor = custo_com_boni * (frete_cif_fob_percentual / 100)

        self._custo_com_boni = custo_com_boni
        self._frete_cif_fob_percentual = frete_cif_fob_percentual
        self._frete_cif_fob_valor = frete_cif_fob_valor
        self._ipi_valor = ipi_valor
        self._custo_final = custo_com_boni + ipi_valor + frete_cif_fob_valor

    def calcular_coleta(self):
        self._metro_cubico = metro_cubico_de_dimensoes(self._altura, self._largura, self._comprimento)
        self._coleta = self._metro_cubico * self.config_geral.fator_coleta

    def calcular_armazenagem(self):
        produto = self.produto

        if produto.armazenagem_planilha is not None:
            self._armazenagem_origem = 'planilha'
            self._armazenagem = produto.armazenagem_planilha
            return

        if self.faixas_armazenagem is not None:
            faixas = self.faixas_armazenagem
        else:
            from precificacao.models import FaixaArmazenagem
            faixas = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

        faixa_usada = selecionar_faixa_por_dimensao(self._altura, self._largura, self._comprimento, faixas)
        self._armazenagem_origem = 'faixa_dimensao'
        self._armazenagem = (faixa_usada.valor_diario * self.config_geral.periodo_armazenagem) if faixa_usada else Decimal('0')

    def calcular_fixo(self):
        creditos = self._creditos

        # creditos.icms já vem certo pra qualquer regime (líquido do
        # ST quando o produto é ST, normal quando não é) — nunca soma os 2.
        self._credito_icms_entrada = creditos.icms
        self._credito_pis = creditos.pis
        self._credito_cofins = creditos.cofins

        self._fixo = self._coleta + self._armazenagem + self._custo_final - (
            self._credito_icms_entrada + self._credito_pis + self._credito_cofins
        )

    def montar_taxa_e_denominador(self):
        produto = self.produto
        self._comissao_percentual = self.config_amazon.comissao_percentual
        self._icms_saida_percentual = produto.icms_saida_media or Decimal('0')
        self._pis_saida_percentual = produto.pis_percentual or Decimal('0')
        self._cofins_saida_percentual = produto.cofins_percentual or Decimal('0')

        self._taxa_percentual = (
            self._comissao_percentual + self._icms_saida_percentual
            + self._pis_saida_percentual + self._cofins_saida_percentual
        ) / 100
        self._denominador = Decimal('1') - self._taxa_percentual - (self.margem_alvo_percentual / 100)

    # Função Objetivo: Devolve as faixas de preço distintas da Amazon, pro tipo desta instância.
    def _faixas_preco_candidatas(self):
        combinacoes = {(f.preco_min, f.preco_max) for f in self.fretes_amazon}
        return sorted(combinacoes, key=lambda par: par[0])

    # Função Objetivo: Resolve o frete pra 1 faixa de preço candidata — 3 casos possíveis.
    # Explicação em detalhe: (1) faixa baixa (<R$79) — frete fixo, peso não importa;
    # (2) peso dentro da matriz — busca célula direta; (3) peso acima do teto da matriz
    # (~10kg) — usa a célula máxima + arredondar_pra_cima(peso-teto) × taxa de kg adicional.
    def _frete_para_faixa(self, preco_min, preco_max):
        linhas_da_faixa = [
            f for f in self.fretes_amazon if f.preco_min == preco_min and f.preco_max == preco_max
        ]

        linha_flat = next((f for f in linhas_da_faixa if f.peso_min is None), None)
        if linha_flat:
            return linha_flat.valor, None, None

        peso = self._peso
        linha_peso = next(
            (f for f in linhas_da_faixa if f.peso_min <= peso <= f.peso_max), None
        )
        if linha_peso:
            return linha_peso.valor, linha_peso.peso_min, linha_peso.peso_max

        if not linhas_da_faixa:
            return None, None, None

        linha_maxima = max(linhas_da_faixa, key=lambda f: f.peso_max)
        taxa_kg = next(
            (t for t in self.taxas_kg_adicional if t.preco_min == preco_min and t.preco_max == preco_max), None
        )
        if not taxa_kg:
            return None, None, None

        kg_extra = math.ceil(peso - linha_maxima.peso_max)
        valor = linha_maxima.valor + Decimal(kg_extra) * taxa_kg.valor_por_kg
        return valor, linha_maxima.peso_min, linha_maxima.peso_max

    # Função Objetivo: Testa cada faixa de preço candidata, aceita a primeira auto-consistente.
    def resolver_preco(self):
        for preco_min, preco_max in self._faixas_preco_candidatas():
            frete, peso_min_usado, peso_max_usado = self._frete_para_faixa(preco_min, preco_max)
            if frete is None:
                continue

            preco_exato = (frete + self._fixo) / self._denominador
            preco_90 = arredondar_para_90(preco_exato)

            dentro_piso = preco_90 >= preco_min
            dentro_teto = preco_max is None or preco_90 <= preco_max

            if not (dentro_piso and dentro_teto):
                continue

            margem_valor = preco_90 * (1 - self._taxa_percentual) - self._fixo - frete
            margem_percentual_obtida = (margem_valor / preco_90) * 100

            assert margem_percentual_obtida >= self.margem_alvo_percentual, (
                f'Margem obtida ({margem_percentual_obtida}%) ficou ABAIXO da margem-alvo '
                f'({self.margem_alvo_percentual}%) — RoundUp90 deveria garantir margem sempre '
                f'>= meta. Verificar a busca de faixa de frete da Amazon.'
            )

            self.resolvida = True
            self._preco_final = preco_90
            self._frete_usado = frete
            self._faixa_preco_min = preco_min
            self._faixa_preco_max = preco_max
            self._peso_min_usado = peso_min_usado
            self._peso_max_usado = peso_max_usado
            self._preco_exato_antes_arredondar = preco_exato
            self._margem_valor = margem_valor
            self._margem_percentual_obtida = margem_percentual_obtida

            self._margem_exata_valor = preco_exato * (1 - self._taxa_percentual) - self._fixo - frete
            self._margem_exata_percentual = (self._margem_exata_valor / preco_exato) * 100

            self._comissao_valor = preco_90 * self._comissao_percentual / 100
            self._margem_alvo_valor = preco_90 * (self.margem_alvo_percentual / 100)
            return

        self.resolvida = False

    def calcular(self):
        self.obter_creditos_fiscais()
        if self._creditos is None:
            self.resolvida = False
            return self

        self.resolver_dimensao()
        self.calcular_custo_final()
        self.calcular_coleta()
        self.calcular_armazenagem()
        self.calcular_fixo()
        self.montar_taxa_e_denominador()
        self.resolver_preco()

        if not self.resolvida:
            return self

        self._montar_dados_entrada()
        self._montar_dados_intermediarios()
        self._montar_dados_saida()
        return self

    def _montar_dados_entrada(self):
        produto = self.produto
        self.entrada = DadosEntrada(
            sku=produto.sku, ean=produto.ean,
            margem_alvo_percentual=self.margem_alvo_percentual, tipo=self.tipo,
            custo=produto.custo, custo_com_boni=self._custo_com_boni,
            frete_cif_fob_percentual=self._frete_cif_fob_percentual,
            icms_saida_percentual=self._icms_saida_percentual,
            pis_saida_percentual=self._pis_saida_percentual,
            cofins_saida_percentual=self._cofins_saida_percentual,
            comissao_percentual=self._comissao_percentual,
            armazenagem_planilha=produto.armazenagem_planilha,
            origem_dados_fiscais=(
                'planilha_precificacao' if produto.armazenagem_planilha is not None else 'erp_completo'
            ),
            altura=self._altura, largura=self._largura, comprimento=self._comprimento, peso=self._peso,
            origem_dimensao='produto_erp',
            fator_coleta=self.config_geral.fator_coleta,
            periodo_armazenagem=self.config_geral.periodo_armazenagem,
        )

    def _montar_dados_intermediarios(self):
        self.intermediarios = DadosIntermediarios(
            custo_final=self._custo_final, ipi_valor=self._ipi_valor,
            frete_cif_fob_valor=self._frete_cif_fob_valor, metro_cubico=self._metro_cubico,
            coleta=self._coleta, armazenagem_origem=self._armazenagem_origem, armazenagem=self._armazenagem,
            credito_icms_entrada=self._credito_icms_entrada, credito_pis=self._credito_pis,
            credito_cofins=self._credito_cofins,
            pis_saida_valor=self._preco_final * self._pis_saida_percentual / 100,
            cofins_saida_valor=self._preco_final * self._cofins_saida_percentual / 100,
            icms_saida_valor=self._preco_final * self._icms_saida_percentual / 100,
            comissao_valor=self._comissao_valor, fixo=self._fixo,
            taxa_percentual=self._taxa_percentual * 100, denominador=self._denominador,
            margem_alvo_valor=self._margem_alvo_valor,
            faixa_preco_min=self._faixa_preco_min, faixa_preco_max=self._faixa_preco_max,
            peso_min_usado=self._peso_min_usado, peso_max_usado=self._peso_max_usado,
            preco_exato_antes_arredondar=self._preco_exato_antes_arredondar,
        )

    def _montar_dados_saida(self):
        self.saida = DadosSaida(
            preco_final=self._preco_final, frete_usado=self._frete_usado,
            margem_valor=self._margem_valor, margem_percentual_obtida=self._margem_percentual_obtida,
            margem_exata_percentual=self._margem_exata_percentual, margem_exata_valor=self._margem_exata_valor,
        )

    def para_dict_auditoria(self):
        return {
            'entrada': asdict(self.entrada),
            'intermediarios': asdict(self.intermediarios),
            'saida': asdict(self.saida),
        }