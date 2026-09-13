# impostos/funcoes_auxiliares/conversao_valores_impostos.py

# Função Objetivo: Converte um valor TOTAL da nota fiscal pra valor POR
# UNIDADE — única fonte desta conta em todo o domínio de impostos de
# entrada (exibição no modal e créditos pra precificação usam a mesma
# regra).

from __future__ import annotations

from decimal import Decimal


def valor_por_unidade(valor_da_nota: Decimal | None, quantidade_nota: Decimal | None) -> Decimal | None:
    # Função Objetivo: Divide valor_da_nota por quantidade_nota, sem
    # fingir um número quando falta dado.
    #
    # None quando quantidade_nota é None/zero (produto sincronizado antes
    # desse campo existir) ou quando valor_da_nota já é None.
    if valor_da_nota is None or not quantidade_nota:
        return None

    return valor_da_nota / quantidade_nota