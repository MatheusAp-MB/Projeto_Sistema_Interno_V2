# impostos/funcoes_auxiliares/creditos_fiscais_para_precificacao.py

# Função Objetivo: Empacota os créditos fiscais de entrada já prontos pra
# a precificação consumir, sem calcular nada sozinha.
#
# A precificação nunca tem papel de calcular imposto de entrada — só usa
# o que este domínio já validou (ver "Migração da Precificação Real para
# Usar Impostos de Entrada Validados" no vault).

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from impostos.funcoes_auxiliares.conversao_valores_impostos import valor_por_unidade
from impostos.models import ImpostosECustosXMLEntradaProduto


@dataclass
class CreditosFiscaisEntradaParaPrecificacao:
    # Função Objetivo: Os 4 créditos que as fórmulas de marketplace
    # precisam, já por unidade e já com a regra de diferimento do ICMS ST
    # resolvida (ver "Hipótese de Diferimento do Crédito de ICMS Entrada
    # em Produtos ST" no vault).
    #
    # icms já é o valor certo pra usar no FIXO, seja o produto ST ou não —
    # quem consome nunca soma icms + "icms st" separadamente, isso
    # creditaria o mesmo imposto 2 vezes.
    #
    # Campo None significa dado insuficiente pra confiar no preço (nota
    # sem quantidade registrada, ou produto sem sincronizar) — quem
    # consome decide não precificar nesse caso, nunca finge um crédito
    # que não existe.

    icms: Decimal | None
    ipi: Decimal | None
    pis: Decimal | None
    cofins: Decimal | None


def _produto_tem_icms_st(impostos_entrada: ImpostosECustosXMLEntradaProduto) -> bool:
    # "É ST?" vem do próprio XML, nunca de cadastro manual — se a nota
    # trouxe base ou valor de ICMS ST maior que zero, o produto está sob
    # substituição tributária nesta entrada.
    return impostos_entrada.icms_st.valor > 0 or impostos_entrada.icms_st.base_calculo > 0


def _credito_icms_da_nota(impostos_entrada: ImpostosECustosXMLEntradaProduto) -> Decimal:
    # Produto sob ICMS ST: o crédito de ICMS normal já foi absorvido
    # dentro do cálculo líquido do ST (diferimento) — usa o líquido
    # (bruto do ST menos o ICMS normal), nunca os 2 separados.
    #
    # Produto sem ICMS ST: crédito normal, sem ajuste nenhum.
    if _produto_tem_icms_st(impostos_entrada):
        return impostos_entrada.icms_st.valor - impostos_entrada.icms.valor

    return impostos_entrada.icms.valor


def montar_creditos_fiscais_para_precificacao(
    impostos_entrada: ImpostosECustosXMLEntradaProduto,
) -> CreditosFiscaisEntradaParaPrecificacao:
    quantidade_nota = impostos_entrada.quantidade_nota

    return CreditosFiscaisEntradaParaPrecificacao(
        icms=valor_por_unidade(_credito_icms_da_nota(impostos_entrada), quantidade_nota),
        ipi=valor_por_unidade(impostos_entrada.ipi.valor, quantidade_nota),
        pis=valor_por_unidade(impostos_entrada.pis.valor, quantidade_nota),
        cofins=valor_por_unidade(impostos_entrada.cofins.valor, quantidade_nota),
    )