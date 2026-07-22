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

    # * [EXPLICAÇÃO] → Mesmos valores de cima (_apos_embalado), só que ORDENADOS
    #                  (menor → maior) — "altura/largura/comprimento" aqui é só
    #                  rótulo de posição no ranking de tamanho, não eixo físico
    #                  real. Única fonte usada por qualquer cálculo que precise
    #                  de eixos consistentes (frete, armazenagem, peso cúbico) —
    #                  os campos "_apos_embalado" acima agora são 100% brutos,
    #                  nunca mais usados direto em cálculo. Calculados por
    #                  obter_dimensoes_envio(), persistidos pelo comando
    #                  organizar_e_verificar_divergencias_dimensoes_envio.
    altura_ordenada_cm = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    largura_ordenada_cm = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    comprimento_ordenada_cm = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)

    # * [EXPLICAÇÃO] → Mesmos valores de cima (_apos_embalado), só que ORDENADOS
    #                  (menor → maior) — "altura/largura/comprimento" aqui é só
    #                  rótulo de posição no ranking de tamanho, não eixo físico
    #                  real. Existem pra comparar com o lado ML (VariacaoAnuncioML)
    #                  sem depender de qual rótulo cada API/planilha usou pro
    #                  mesmo eixo físico. Calculados por obter_dimensoes_envio(),
    #                  persistidos pelo comando verificar_divergencias_de_dimensoes.
    altura_ordenada_cm = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    largura_ordenada_cm = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    comprimento_ordenada_cm = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)

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

    # Função Objetivo: Devolve as dimensões de envio deste produto, já ordenadas.
    # Explicação em detalhe: usa sempre os campos "_apos_embalado" (embalagem real
    # enviada, nunca o produto sem embalar) — mesma regra já aplicada em frete e
    # armazenagem. Não persiste nada, só calcula e devolve.
    def obter_dimensoes_envio(self):
        from core.funcoes_auxiliares.dimensoes_envio import montar_dimensoes_envio

        # * [EXPLICAÇÃO] → Convenção real do ERP (confirmada 21/07): "0" nesses 4
        #                  campos significa "nunca foi cadastrado", não "o produto
        #                  mede zero". Tratar como ausente aqui, não em
        #                  montar_dimensoes_envio (que é neutra e não deveria saber
        #                  dessa convenção específica do ERP).
        def _valor_ou_none(valor):
            if valor is None or valor == 0:
                return None
            return valor

        return montar_dimensoes_envio(
            altura=_valor_ou_none(self.altura_produto_apos_embalado),
            largura=_valor_ou_none(self.largura_produto_apos_embalado),
            comprimento=_valor_ou_none(self.comprimento_produto_apos_embalado),
            peso=_valor_ou_none(self.peso_produto_apos_embalado),
        )



    class Meta:
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'
        ordering = ['titulo']

    def __str__(self):
        return f'{self.ean} — {self.titulo}'
