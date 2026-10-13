# impostos/funcoes_auxiliares/entrada/pis_cofins_tributo_ja_pago.py

# Função Objetivo: Dona ÚNICA da regra "PIS/COFINS com CST 02, 04 ou 06 no XML
# do fornecedor = tributo já pago antes (0% na entrada E na saída)". Quem
# precisa saber se a regra vale pra um produto (crédito de entrada pra
# precificação, preenchimento do PIS/COFINS de saída, badges fiscais) importa
# a função pública daqui — nenhum desses módulos reimplementa a lista de CSTs.
#
# * [EXPLICAÇÃO] → Regra confirmada por Matheus (01/10/2026): quando o CST de
#                  PIS/COFINS que o FORNECEDOR informou no XML (cst_xml, nunca
#                  o cst_cadastro do ERP) é 02, 04 ou 06, o produto NÃO tem
#                  crédito de PIS/COFINS na entrada e NÃO tem PIS/COFINS na
#                  saída — 0% nos dois lados, "independente do que vier do
#                  fornecedor" (alíquota/valor/redução do XML são ignorados
#                  pra esse fim). Motivo: o tributo já foi pago antecipadamente
#                  pelo fornecedor, então não há o que creditar na compra nem o
#                  que recolher na venda.
#
#                  Referência de como o CST de entrada se traduz na saída
#                  (usada só como explicação, o resultado numérico é 0 nos 3):
#                      XML fornecedor 02  →  saída 04
#                      XML fornecedor 04  →  saída 04
#                      XML fornecedor 06  →  saída 06
#
# * [EXPLICAÇÃO] → A regra olha só o CST do XML da ENTRADA. O Sistema continua
#                  espelhando o dado bruto da nota nas telas de NF/exportação
#                  (Pis.valor, Pis.aliquota etc. seguem como vieram do XML) —
#                  o zero é aplicado só onde o valor vira CÁLCULO DE PREÇO
#                  (montar_creditos_fiscais_para_precificacao e
#                  preencher_impostos_saida).
#
# * [EXPLICAÇÃO] → EXPLICITUDE (Matheus, 13/10/2026): a etapa de precificação não pode ter
#                  ambiguidade — nenhuma tela pode mostrar "0" como se fosse dado de tabela
#                  quando na verdade é esta regra. Onde o zero aparece (painel do Produto e
#                  auditoria da grade), a tela mostra o valor REAL que veio no XML E deixa
#                  claro "Valor considerado = 0 (zerado pela regra)", com o texto abaixo.
#                  O texto da regra mora SÓ aqui (TEXTO_REGRA_TRIBUTO_JA_PAGO) — as telas
#                  recebem pronto, nunca reescrevem a explicação.

from __future__ import annotations

CSTS_PIS_COFINS_TRIBUTO_JA_PAGO = frozenset({'02', '04', '06'})


def pis_cofins_tributo_ja_pago_pelo_fornecedor(cst_xml: object) -> bool:
    # Função Objetivo: True quando o CST de PIS ou COFINS do XML do
    # fornecedor é 02, 04 ou 06 (ver regra no topo do arquivo).
    #
    # Aceita str/None e tolera o zero à esquerda perdido ("4" → "04") — o
    # CST vem do XML como texto (ver _str_cst_ou_zero em dados_xml_nf.py), mas
    # a regra não pode errar o produto por causa de formatação. None/vazio
    # nunca dispara a regra (sem CST, o comportamento normal continua).
    if cst_xml is None:
        return False

    texto = str(cst_xml).strip()
    if not texto:
        return False

    return texto.zfill(2) in CSTS_PIS_COFINS_TRIBUTO_JA_PAGO


# Função Objetivo: O texto ÚNICO que explica a regra pro usuário, nas telas (ver nota de
# EXPLICITUDE no topo do arquivo). Painel do Produto e auditoria da grade só exibem esta string.
TEXTO_REGRA_TRIBUTO_JA_PAGO = (
    'CST de PIS/COFINS 02, 04 ou 06 no XML do fornecedor significa que o tributo já foi pago '
    'antecipadamente pelo fornecedor: não há crédito na entrada nem PIS/COFINS a recolher na saída. '
    'Por isso a precificação considera 0% nos dois lados, sempre, ignorando o valor que veio na nota.'
)


def saida_diverge_da_regra(cst_xml: object, percentual_saida_cadastro: object) -> bool:
    # Função Objetivo: True quando a regra manda a saída ser 0%, mas o percentual de saída que
    # está no cadastro (ou que a grade usou) NÃO é zero — sinal de que o preenchimento de
    # saída (preencher_impostos_saida) ainda não rodou depois da regra, e a precificação estaria
    # cobrando PIS/COFINS de um produto cujo tributo já foi pago.
    #
    # None (campo vazio) NÃO é divergência: a precificação lê vazio como 0%, que é exatamente o
    # que a regra manda. Só um percentual positivo contradiz a regra.
    if not pis_cofins_tributo_ja_pago_pelo_fornecedor(cst_xml):
        return False

    if percentual_saida_cadastro is None:
        return False

    return percentual_saida_cadastro != 0
