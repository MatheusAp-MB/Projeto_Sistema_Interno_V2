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

from impostos.models import ImpostosECustosXMLEntradaProduto

PIS_SAIDA_REDUZIDO = 'PIS SAÍDA REDUZIDO'
PIS_SAIDA_INTEGRAL = 'PIS SAÍDA INTEGRAL'
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
        return BadgesFiscaisProduto(
            pis_rotulo=PIS_SAIDA_INTEGRAL, pis_classe='badge-fiscal-integral',
            cofins_rotulo=COFINS_SAIDA_INTEGRAL, cofins_classe='badge-fiscal-integral',
            icms_rotulo=ICMS_ENTRADA_INTEGRAL, icms_classe='badge-fiscal-integral',
        )

    pis_reduzido = impostos_entrada.pis.reducao > 0
    cofins_reduzido = impostos_entrada.cofins.reducao > 0

    if _produto_tem_icms_st(impostos_entrada):
        icms_rotulo, icms_classe = ICMS_ENTRADA_ST, 'badge-fiscal-st'
    elif impostos_entrada.icms.reducao > 0:
        icms_rotulo, icms_classe = ICMS_ENTRADA_REDUZIDO, 'badge-fiscal-reduzido'
    else:
        icms_rotulo, icms_classe = ICMS_ENTRADA_INTEGRAL, 'badge-fiscal-integral'

    return BadgesFiscaisProduto(
        pis_rotulo=PIS_SAIDA_REDUZIDO if pis_reduzido else PIS_SAIDA_INTEGRAL,
        pis_classe='badge-fiscal-reduzido' if pis_reduzido else 'badge-fiscal-integral',
        cofins_rotulo=COFINS_SAIDA_REDUZIDO if cofins_reduzido else COFINS_SAIDA_INTEGRAL,
        cofins_classe='badge-fiscal-reduzido' if cofins_reduzido else 'badge-fiscal-integral',
        icms_rotulo=icms_rotulo, icms_classe=icms_classe,
    )