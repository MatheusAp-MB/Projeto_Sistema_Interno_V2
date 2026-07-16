# * [RESUMO] → Model Produto — catálogo universal da empresa.
#              Independente de marketplace: o mesmo produto físico pode
#              ser vendido em qualquer um dos marketplaces trabalhados.

from django.db import models


class Produto(models.Model):
    ean = models.CharField(max_length=20, unique=True)
    sku = models.CharField(max_length=30, blank=True, null=True, unique=True)   
    cod_fabricante = models.CharField(max_length=50, blank=True, null=True)
    ncm = models.CharField(max_length=20, blank=True, null=True)

    titulo = models.CharField(max_length=255)
    marca = models.CharField(max_length=100, blank=True, null=True)
    categoria = models.CharField(max_length=100, blank=True, null=True)
    curva = models.CharField(max_length=5, blank=True, null=True)

    imagem_url = models.URLField(max_length=500, blank=True, null=True)

    estoque = models.IntegerField(default=0)

    custo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    custo_com_boni = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True)

    # * [EXPLICAÇÃO] → Renomeado (16/07) pra separar EXPLICITAMENTE
    #                  produto sem embalar (dimensão/peso do item
    #                  puro, sem caixa) de produto após embalado
    #                  (dimensão/peso da caixa REALMENTE enviada) —
    #                  descoberta real: o ERP tem os 2 conjuntos de
    #                  campos, e o cálculo de frete estava usando o
    #                  errado (produto puro, não a caixa). Frete
    #                  DEVE usar sempre "apos_embalado" — nunca
    #                  "sem_embalar" (regra confirmada com o usuário).
    peso_produto_sem_embalar = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    altura_produto_sem_embalar = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    largura_produto_sem_embalar = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    comprimento_produto_sem_embalar = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    peso_produto_apos_embalado = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    altura_produto_apos_embalado = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    largura_produto_apos_embalado = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    comprimento_produto_apos_embalado = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)

    # * [EXPLICAÇÃO] → Peso cúbico (volumétrico) — agora SEMPRE
    #                  calculado a partir do produto APÓS EMBALADO
    #                  (a caixa real enviada), nunca do produto puro.
    #                  Fórmula muda de arquivo (importadores), não
    #                  daqui — este campo só guarda o resultado.
    peso_cubado = models.DecimalField(
        max_digits=8, decimal_places=3, blank=True, null=True)

    mva = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True)
    st_valor = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True)
    icms_entrada = models.DecimalField(
        max_digits=6, decimal_places=2, default=0)
    icms_saida_sp = models.DecimalField(
        max_digits=6, decimal_places=2, default=0)
    icms_saida_media = models.DecimalField(
        max_digits=6, decimal_places=2, default=0)
    ipi = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    pis_cofins = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    frete_cif_fob = models.DecimalField(
        max_digits=6, decimal_places=2, default=0)

    # * [EXPLICAÇÃO] → Valor mensal de armazenagem importado direto da
    #                  coluna BH da planilha validada de precificação —
    #                  não é calculado por faixa/dimensão, porque a
    #                  planilha usa uma regra de atribuição inconsistente
    #                  (documentado: calcanheiras pequenas usam faixa
    #                  "grande", palmilhas longas usam faixa "pequena" —
    #                  parece depender de dimensão de embalagem ou
    #                  atribuição manual, nunca totalmente esclarecido).
    #                  Usar esse valor real é a única forma de bater
    #                  com o número validado, em vez de recalcular
    #                  por regra própria.
    armazenagem_planilha = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True)

    ultima_compra = models.DateTimeField(blank=True, null=True)
    cadastrado_erp_em = models.DateTimeField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'
        ordering = ['titulo']

    def __str__(self):
        return f'{self.ean} — {self.titulo}'
