# impostos/funcoes_auxiliares/entrada/badges_fiscais_produto.py

# Função Objetivo: Classifica, por produto, as badges fiscais explícitas de
# PIS/COFINS de saída e ICMS de entrada — pedido de Matheus (21/09/2026) pra
# deixar visível, na tela de Produto (aba Impostos) e na Grade de
# Precificação ML, se cada produto está sendo calculado de forma reduzida
# ou integral.
#
# * [EXPLICAÇÃO] → PIS/COFINS SAÍDA (REDUZIDO/INTEGRAL): reflete a correção
#                  pontual de 21/09/2026 na planilha Busca Legal (ver
#                  preenchimento_impostos_saida.py::_aplicar_reducao_pis_cofins)
#                  — o percentual de redução vem de impostos_entrada.pis.reducao
#                  / .cofins.reducao (reducao > 0 = REDUZIDO). Produto sem
#                  nenhuma redução registrada (reducao == 0) é INTEGRAL.
#
# * [EXPLICAÇÃO] → PIS/COFINS SAÍDA ZERO (01/10/2026): CST de PIS/COFINS 02, 04 ou 06 no
#                  XML do fornecedor = tributo já pago antes, saída 0% (regra dona em
#                  pis_cofins_tributo_ja_pago.py, aplicada de fato em
#                  preenchimento_impostos_saida.py). ZERO vence REDUZIDO e INTEGRAL: se o
#                  percentual de saída é 0, mostrar "INTEGRAL" mentiria sobre o cálculo.
#                  Cada imposto (PIS e COFINS) olha o PRÓPRIO cst_xml.
#
# * [EXPLICAÇÃO] → ICMS ENTRADA (INTEGRAL/REDUZIDO/ST): é sobre a ENTRADA,
#                  não a saída — não existe conceito de redução de base de
#                  ICMS de saída neste sistema. Prioridade fixa: ST sempre
#                  vence (produto sob substituição tributária, crédito de
#                  ICMS normal já foi absorvido no líquido — ver
#                  creditos_fiscais_para_precificacao.py::_produto_tem_icms_st,
#                  mesma checagem reimplementada aqui por convenção do
#                  projeto — helper privado nunca é importado entre
#                  módulos), depois Redução, por último Integral.
#
# * [EXPLICAÇÃO] → Fallback (produto sem impostos_entrada sincronizado):
#                  todas as 3 badges caem em INTEGRAL — mesma regra já
#                  confirmada por Matheus pro cálculo de saída em si
#                  (preenchimento_impostos_saida.py, quando não há entrada
#                  pra consultar, mantém o percentual integral da planilha).

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from impostos.funcoes_auxiliares.entrada.pis_cofins_tributo_ja_pago import pis_cofins_tributo_ja_pago_pelo_fornecedor
from impostos.models import ImpostosECustosXMLEntradaProduto

PIS_SAIDA_ZERO = 'PIS SAÍDA ZERO'
PIS_SAIDA_REDUZIDO = 'PIS SAÍDA REDUZIDO'
PIS_SAIDA_INTEGRAL = 'PIS SAÍDA INTEGRAL'
COFINS_SAIDA_ZERO = 'COFINS SAÍDA ZERO'
COFINS_SAIDA_REDUZIDO = 'COFINS SAÍDA REDUZIDO'
COFINS_SAIDA_INTEGRAL = 'COFINS SAÍDA INTEGRAL'
ICMS_ENTRADA_INTEGRAL = 'ICMS ENTRADA INTEGRAL'
ICMS_ENTRADA_REDUZIDO = 'ICMS ENTRADA REDUZIDO'
ICMS_ENTRADA_ST = 'ICMS ENTRADA ST'


@dataclass(frozen=True)
class BadgesFiscaisProduto:
    pis_rotulo: str
    pis_classe: str
    cofins_rotulo: str
    cofins_classe: str
    icms_rotulo: str
    icms_classe: str


# Função Objetivo: "É ST?" — mesma checagem de creditos_fiscais_para_precificacao.py,
# reimplementada aqui por convenção do projeto (helper privado nunca é
# importado entre módulos).
def _produto_tem_icms_st(impostos_entrada: ImpostosECustosXMLEntradaProduto) -> bool:
    return impostos_entrada.icms_st.valor > 0 or impostos_entrada.icms_st.base_calculo > 0


# Função Objetivo: Monta as 3 badges fiscais (PIS saída, COFINS saída, ICMS
# entrada) de 1 produto, a partir do impostos_entrada RAW (não o objeto já
# formatado pra exibição) — evita ambiguidade dos valores já divididos por
# unidade.
def montar_badges_fiscais_produto(
    impostos_entrada: ImpostosECustosXMLEntradaProduto | None,
) -> BadgesFiscaisProduto:
    if impostos_entrada is None:
        return _badges_integrais()

    # * [EXPLICAÇÃO] → Retrato incompleto (sem alguma das tabelas de imposto filhas — ver
    #                  creditos_fiscais_para_precificacao.py) cai no mesmo fallback de
    #                  "sem retrato": a tela da grade não pode quebrar por causa dele.
    try:
        pis_rotulo, pis_classe = _badge_pis_cofins_saida(
            impostos_entrada.pis, PIS_SAIDA_ZERO, PIS_SAIDA_REDUZIDO, PIS_SAIDA_INTEGRAL,
        )
        cofins_rotulo, cofins_classe = _badge_pis_cofins_saida(
            impostos_entrada.cofins, COFINS_SAIDA_ZERO, COFINS_SAIDA_REDUZIDO, COFINS_SAIDA_INTEGRAL,
        )

        if _produto_tem_icms_st(impostos_entrada):
            icms_rotulo, icms_classe = ICMS_ENTRADA_ST, 'badge-fiscal-st'
        elif impostos_entrada.icms.reducao > 0:
            icms_rotulo, icms_classe = ICMS_ENTRADA_REDUZIDO, 'badge-fiscal-reduzido'
        else:
            icms_rotulo, icms_classe = ICMS_ENTRADA_INTEGRAL, 'badge-fiscal-integral'
    except ObjectDoesNotExist:
        return _badges_integrais()

    return BadgesFiscaisProduto(
        pis_rotulo=pis_rotulo, pis_classe=pis_classe,
        cofins_rotulo=cofins_rotulo, cofins_classe=cofins_classe,
        icms_rotulo=icms_rotulo, icms_classe=icms_classe,
    )


# Função Objetivo: Escolhe rótulo + classe CSS da badge de PIS ou COFINS de saída de 1 produto.
# Prioridade fixa: ZERO (tributo já pago, CST 02/04/06 no XML) > REDUZIDO (reducao > 0) > INTEGRAL.
# imposto_entrada é o PIS ou o COFINS do retrato (mesmos campos cst_xml e reducao nos 2).
def _badge_pis_cofins_saida(
    imposto_entrada: object, rotulo_zero: str, rotulo_reduzido: str, rotulo_integral: str,
) -> tuple[str, str]:
    if pis_cofins_tributo_ja_pago_pelo_fornecedor(imposto_entrada.cst_xml):
        return rotulo_zero, 'badge-fiscal-zero'

    if imposto_entrada.reducao > 0:
        return rotulo_reduzido, 'badge-fiscal-reduzido'

    return rotulo_integral, 'badge-fiscal-integral'


# Função Objetivo: As 3 badges "tudo integral" — fallback de produto sem retrato (ou com retrato incompleto).
def _badges_integrais() -> BadgesFiscaisProduto:
    return BadgesFiscaisProduto(
        pis_rotulo=PIS_SAIDA_INTEGRAL, pis_classe='badge-fiscal-integral',
        cofins_rotulo=COFINS_SAIDA_INTEGRAL, cofins_classe='badge-fiscal-integral',
        icms_rotulo=ICMS_ENTRADA_INTEGRAL, icms_classe='badge-fiscal-integral',
    )
