# impostos/views/__init__.py

# Reexporta as 8 views (2 de entrada, 6 de saída) num namespace só --
# impostos/urls.py continua fazendo `from . import views` e
# `views.view_xxx`, sem precisar saber que virou um pacote (mesmo padrão
# de precificacao/views/__init__.py, o único outro pacote de views do
# projeto). Separação decidida em 13/09/2026 (Passo 3 do plano no vault,
# escopo revisado pra não incluir templates/static -- ver Decisão) --
# mesma divisão entrada/saida que impostos/models/ e
# impostos/funcoes_auxiliares/ já têm.

from impostos.views.entrada import (
    view_resumo_impostos_entrada,
    view_exportar_resumo_impostos_entrada,
)
from impostos.views.saida import (
    view_auditoria_fiscal,
    view_tabela_icms_por_ncm,
    view_calcular_icms_por_ncm,
    view_tabela_pis_cofins_por_ncm_cst,
    view_csts_disponiveis_pis_cofins_ncm_cst,
    view_calcular_pis_cofins_por_ncm_cst,
)
