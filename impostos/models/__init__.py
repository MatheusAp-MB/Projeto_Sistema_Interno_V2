# impostos/models/__init__.py

# Reexporta tudo de entrada/ e saida/ num namespace só -- ninguém fora
# daqui precisa saber que a divisão existe. Separação decidida em
# 13/09/2026 (ver Decisão no vault): entrada e saída de impostos são
# domínios distintos (fontes de dado diferentes, times diferentes,
# nenhuma classe usada dos 2 lados) -- só moravam juntas por história, não
# por design.

from .entrada import (
    ImpostoComAliquota,
    ImpostosECustosXMLEntradaProduto,
    IcmsEntradaProduto,
    IcmsStEntradaProduto,
    IcmsRetEntradaProduto,
    IpiEntradaProduto,
    PisEntradaProduto,
    CofinsEntradaProduto,
)
from .saida import (
    IcmsNcmUf,
    PisCofinsNcmCst,
    IcmsNcmRejeitado,
    PisCofinsNcmCstRejeitado,
    IcmsSaidaMediaPorNcmCstOrigem,
)
