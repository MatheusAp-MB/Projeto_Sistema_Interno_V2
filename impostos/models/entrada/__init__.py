# impostos/models/entrada/__init__.py

# Reexporta as tabelas de impostos de ENTRADA (1 produto, vindas do
# XML/Cadastro da nota fiscal via Sysemp) -- 1 arquivo por classe dentro
# desta pasta. `from impostos.models import X` continua funcionando
# idêntico em todo o resto do repo.

from .imposto_com_aliquota import ImpostoComAliquota
from .impostos_e_custos_xml_entrada_produto import ImpostosECustosXMLEntradaProduto
from .icms_entrada_produto import IcmsEntradaProduto
from .icms_st_entrada_produto import IcmsStEntradaProduto
from .icms_ret_entrada_produto import IcmsRetEntradaProduto
from .ipi_entrada_produto import IpiEntradaProduto
from .pis_entrada_produto import PisEntradaProduto
from .cofins_entrada_produto import CofinsEntradaProduto
