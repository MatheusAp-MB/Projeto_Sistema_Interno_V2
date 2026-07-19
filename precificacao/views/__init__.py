# precificacao/views/__init__.py

# Função Objetivo: Reexporta tudo — precificacao/urls.py continua fazendo
# "from . import views" e "views.view_xxx" sem precisar saber que virou um pacote.

from .comum import (
    Margem, MARGENS, MARGENS_CHAVES, MARGENS_POR_CHAVE, FiltrosGrade, FiltroPrecoExibido,
    LinhaMargemExibida, ColunaOrdenavel,
)
from .modal_comum import (
    LinhaPercentualValor, LinhaValorUnico, BlocoPisCofins, DimensaoUsada,
    PassoCustoFinal, PassoColeta, PassoArmazenagem, PassoFixo, PassoTaxa,
    PassoDenominador, PassoFaixaFrete, PassoPrecoExato, LinhaSaida,
)
from .grade_mercado_livre import (
    TIPO_GRADE_PARA_ML, TIPO_ML_PARA_GRADE, FAIXAS_PRECO_GRADE,
    CardMLB, ItemGradeProduto, AgrupadorLinhasGrade, ContextoGradePrecificacao,
    DetalheFormulaExibida, view_grade_precificacao_ml, view_grade_detalhe,
)
from .grade_magalu import (
    FAIXAS_PRECO_GRADE_MAGALU, ItemGradeMagaluProduto, AgrupadorLinhasGradeMagalu,
    DetalheFormulaExibidaMagalu, view_grade_precificacao_magalu, view_grade_detalhe_magalu,
)
from .grade_raia import (
    FAIXAS_PRECO_GRADE_RAIA, ItemGradeRaiaProduto, AgrupadorLinhasGradeRaia,
    DetalheFormulaExibidaRaia, view_grade_precificacao_raia, view_grade_detalhe_raia,
)
from .grade_shopee import (
    FAIXAS_PRECO_GRADE_SHOPEE, ItemGradeShopeeProduto, AgrupadorLinhasGradeShopee,
    DetalheFormulaExibidaShopee, view_grade_precificacao_shopee, view_grade_detalhe_shopee,
)
from .resumo_marketplaces import (
    COLUNAS_ORDENAVEIS, GrupoMarketplaceExibido, LinhaResumoMarketplace,
    view_resumo_marketplaces, view_resumo_linha,
)
from .configuracoes import view_configuracoes_operacionais
from .hub import view_precificacao_hub