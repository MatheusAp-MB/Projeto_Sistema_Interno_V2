# mercado_livre/funcoes_auxiliares/comparador_dimensao_envio.py

# Função Objetivo: Define os estados possíveis da comparação de dimensão de envio ERP vs ML.
# Explicação em detalhe: ERP é sempre a fonte da verdade (decisão de negócio confirmada) — este
# campo só sinaliza onde o ML está desalinhado do ERP, nunca corrige nada sozinho. Usado como
# choices do campo VariacaoAnuncioMercadoLivre.situacao_dimensao_envio.
from django.db import models


class SituacaoDimensaoEnvio(models.TextChoices):
    IGUAIS               = 'iguais',               'Dimensões de envio iguais'
    DIVERGENTE           = 'divergente',            'Divergência nas dimensões de envio'
    NAO_REFLETIDA_ML     = 'nao_refletida_ml',      'Dimensão de envio não refletida no ML'
    NAO_SALVA_ERP        = 'nao_salva_erp',         'Dimensão de envio não salva no ERP'
    SEM_DADO_NENHUM_LADO = 'sem_dado_nenhum_lado',  'Sem dado de envio em nenhum dos 2 lados'
    SEM_PRODUTO_VINCULADO = 'sem_produto_vinculado', 'Sem produto vinculado no ERP'


# Função Objetivo: Compara as dimensões de envio do ERP com as do ML e devolve a situação.
# Explicação em detalhe: função pura — recebe 2 DimensoesEnvio já prontos (montados por
# Produto.obter_dimensoes_envio() e VariacaoAnuncioMercadoLivre.obter_dimensoes_envio()),
# nunca acessa banco. Completude é checada primeiro (existe dos 2 lados / só 1 lado / nenhum);
# só quando os 2 lados estão completos entra a comparação valor-a-valor (dimensões já vêm
# ordenadas dos 2 dataclasses, então compara posição-com-posição, sem se importar com rótulo
# de eixo original) + peso bruto-com-bruto. Igualdade exata em TODOS os 4 valores — qualquer
# diferença, mesmo mínima, já é divergência.
def comparar_dimensoes_envio(dimensoes_erp, dimensoes_ml):
    if not dimensoes_erp.completo and not dimensoes_ml.completo:
        return SituacaoDimensaoEnvio.SEM_DADO_NENHUM_LADO

    if dimensoes_erp.completo and not dimensoes_ml.completo:
        return SituacaoDimensaoEnvio.NAO_REFLETIDA_ML

    if not dimensoes_erp.completo and dimensoes_ml.completo:
        return SituacaoDimensaoEnvio.NAO_SALVA_ERP

    valores_batem = (
        dimensoes_erp.dimensao_menor == dimensoes_ml.dimensao_menor
        and dimensoes_erp.dimensao_media == dimensoes_ml.dimensao_media
        and dimensoes_erp.dimensao_maior == dimensoes_ml.dimensao_maior
        and dimensoes_erp.peso == dimensoes_ml.peso
    )

    if valores_batem:
        return SituacaoDimensaoEnvio.IGUAIS

    return SituacaoDimensaoEnvio.DIVERGENTE