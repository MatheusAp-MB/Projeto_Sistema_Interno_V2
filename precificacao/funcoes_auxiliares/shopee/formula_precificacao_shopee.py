# precificacao/funcoes_auxiliares/shopee/formula_precificacao_shopee.py

# Função Objetivo: Representa 1 margem candidata da Shopee já resolvida, com auditoria.
# Explicação em detalhe: comissão + adicional fixo variam JUNTOS por faixa de PREÇO
# (confirmado por print oficial da Shopee) — resolvida via resolver_preco_por_faixa_comissao
# (busca com auto-consistência, mesma mecânica do ML, só invertida: aqui o frete é fixo e a
# taxa/adicional variam). Calcula também preco_de_exibicao (preço ÷ 0,80) — decorativo,
# nunca usado em conta de margem.
#
# Créditos fiscais de entrada (ICMS/IPI/PIS/COFINS) vêm prontos de impostos_entrada, via
# montar_creditos_fiscais_para_precificacao — já por unidade, já com o diferimento de ICMS
# ST resolvido internamente. Esta classe nunca reinterpreta esse valor, só consome.

from dataclasses import dataclass, asdict
from decimal import Decimal
from django.core.exceptions import ObjectDoesNotExist
from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_por_faixa_comissao
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

    custo: Decimal
    custo_com_boni: Decimal
    frete_cif_fob_percentual: Decimal
    icms_saida_percentual: Decimal
    pis_saida_percentual: Decimal
    cofins_saida_percentual: Decimal
    comissao_percentual: Decimal  # resolvida pela busca de faixa — guardada aqui também, por conveniência do modal

    armazenagem_planilha: Decimal | None
    origem_dados_fiscais: str

    altura: Decimal
    largura: Decimal
    comprimento: Decimal
    peso: Decimal
    origem_dimensao: str

    fator_coleta: Decimal
    periodo_armazenagem: Decimal

    frete_configurado: Decimal
    desconto_vitrine_percentual: Decimal


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
    comissao_percentual: Decimal
    comissao_valor: Decimal
    adicional_fixo: Decimal
    fixo: Decimal
    taxa_percentual: Decimal
    denominador: Decimal
    margem_alvo_valor: Decimal
    faixa_comissao_preco_min: Decimal
    faixa_comissao_preco_max: Decimal | None
    preco_exato_antes_arredondar: Decimal


@dataclass
class DadosSaida:
    preco_final: Decimal
    frete_usado: Decimal
    margem_valor: Decimal
    margem_percentual_obtida: Decimal
    margem_exata_percentual: Decimal
    margem_exata_valor: Decimal
    preco_de_exibicao: Decimal


class FormulaPrecificacaoShopee:

    def __init__(self, produto, config_shopee, config_geral, margem_alvo_percentual,
                 faixas_comissao, faixas_armazenagem=None):
        self.produto = produto
        self.config_shopee = config_shopee
        self.config_geral = config_geral
        self.margem_alvo_percentual = Decimal(str(margem_alvo_percentual))
        self.faixas_comissao = faixas_comissao
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

    # * [EXPLICAÇÃO] → ICMS saída + PIS + COFINS somam na taxa igual todo
    #                  o resto do sistema — são impostos de governo,
    #                  dependem do regime tributário da empresa, não da
    #                  plataforma. "Comissão já contempla a taxa de
    #                  transação" (texto oficial da Shopee) é sobre uma
    #                  taxa DA PRÓPRIA SHOPEE, não sobre imposto — não
    #                  tem relação com ICMS/PIS/COFINS, que continuam somando.
    def resolver_preco(self):
        produto = self.produto
        self._icms_saida_percentual = produto.icms_saida_media or Decimal('0')
        self._pis_saida_percentual = produto.pis_percentual or Decimal('0')
        self._cofins_saida_percentual = produto.cofins_percentual or Decimal('0')
        taxa_extra_fracao = (
            self._icms_saida_percentual + self._pis_saida_percentual + self._cofins_saida_percentual
        ) / 100

        frete = self.config_shopee.frete_padrao

        resultado = resolver_preco_por_faixa_comissao(
            fixo=self._fixo,
            margem_alvo_fracao=self.margem_alvo_percentual / 100,
            custo_produto=produto.custo,
            frete=frete,
            faixas_comissao_candidatas=self.faixas_comissao,
            taxa_extra_fracao=taxa_extra_fracao,
        )

        if resultado is None:
            self.resolvida = False
            return

        self.resolvida = True
        detalhamento = resultado['detalhamento']

        self._preco_final = resultado['preco_calculado']
        self._frete_usado = resultado['frete_usado']
        self._margem_valor = detalhamento['margem_valor']
        self._margem_percentual_obtida = resultado['margem_percentual_obtida']
        self._preco_exato_antes_arredondar = detalhamento['preco_exato_antes_arredondar']

        self._comissao_percentual = detalhamento['comissao_percentual']
        self._taxa_percentual_fracao = detalhamento['taxa_percentual'] / 100
        self._adicional_fixo = detalhamento['adicional_fixo']
        self._faixa_comissao_preco_min = detalhamento['faixa_preco_min']
        self._faixa_comissao_preco_max = detalhamento['faixa_preco_max']

        self._margem_exata_valor = (
            self._preco_exato_antes_arredondar * (1 - self._taxa_percentual_fracao)
            - self._fixo - self._frete_usado - self._adicional_fixo
        )
        self._margem_exata_percentual = (self._margem_exata_valor / self._preco_exato_antes_arredondar) * 100

        self._comissao_valor = self._preco_final * self._taxa_percentual_fracao
        self._margem_alvo_valor = self._preco_final * (self.margem_alvo_percentual / 100)

        # * [EXPLICAÇÃO] → "De" decorativo — preço ÷ (1 − desconto configurado),
        #                  pra sempre mostrar o desconto configurado na vitrine
        #                  (editável na tela, hoje 20%). NUNCA usado em nenhuma
        #                  conta de margem/FIXO.
        fator_vitrine = Decimal('1') - (Decimal(str(self.config_shopee.desconto_vitrine_percentual)) / 100)
        self._preco_de_exibicao = (self._preco_final / fator_vitrine).quantize(Decimal('0.01'))

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
            margem_alvo_percentual=self.margem_alvo_percentual,
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
            frete_configurado=self.config_shopee.frete_padrao,
            desconto_vitrine_percentual=self.config_shopee.desconto_vitrine_percentual,
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
            comissao_percentual=self._comissao_percentual, comissao_valor=self._comissao_valor,
            adicional_fixo=self._adicional_fixo, fixo=self._fixo,
            taxa_percentual=self._taxa_percentual_fracao * 100, denominador=(
                Decimal('1') - self._taxa_percentual_fracao - (self.margem_alvo_percentual / 100)
            ),
            margem_alvo_valor=self._margem_alvo_valor,
            faixa_comissao_preco_min=self._faixa_comissao_preco_min,
            faixa_comissao_preco_max=self._faixa_comissao_preco_max,
            preco_exato_antes_arredondar=self._preco_exato_antes_arredondar,
        )

    def _montar_dados_saida(self):
        self.saida = DadosSaida(
            preco_final=self._preco_final, frete_usado=self._frete_usado,
            margem_valor=self._margem_valor, margem_percentual_obtida=self._margem_percentual_obtida,
            margem_exata_percentual=self._margem_exata_percentual, margem_exata_valor=self._margem_exata_valor,
            preco_de_exibicao=self._preco_de_exibicao,
        )

    def para_dict_auditoria(self):
        return {
            'entrada': asdict(self.entrada),
            'intermediarios': asdict(self.intermediarios),
            'saida': asdict(self.saida),
        }