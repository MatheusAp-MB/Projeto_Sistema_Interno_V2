# * [RESUMO] → Model Produto — catálogo universal da empresa.
#              Independente de marketplace: o mesmo produto físico pode
#              ser vendido em qualquer um dos marketplaces trabalhados.

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from django.db import models


# Função Objetivo: Agrupa os dados de identificação/catálogo do Produto.
@dataclass
class DadosIdentificacaoProduto:
    ean: str
    sku: str
    cod_fabricante: str
    ncm: str
    titulo: str
    marca: str
    categoria: str
    curva: str
    imagem_url: str
    estoque: int
    ativo_no_erp: bool


# Função Objetivo: Agrupa os dados financeiros do Produto.
@dataclass
class DadosFinanceirosProduto:
    custo: Decimal
    custo_com_boni: Decimal


# Função Objetivo: Agrupa os dados fiscais do Produto.
@dataclass
class DadosFiscaisProduto:
    icms_saida_sp: Decimal
    icms_saida_media: Decimal
    pis_percentual: Decimal
    cofins_percentual: Decimal
    frete_cif_fob: Decimal


# Função Objetivo: Agrupa a dimensão do produto PURO, sem embalagem.
@dataclass
class DimensaoSemEmbalar:
    peso: Decimal
    altura: Decimal
    largura: Decimal
    comprimento: Decimal


# Função Objetivo: Agrupa a dimensão da embalagem REAL enviada (a que frete/armazenagem usam).
@dataclass
class DimensaoAposEmbalado:
    peso: Decimal
    altura: Decimal
    largura: Decimal
    comprimento: Decimal
    peso_cubado: Decimal
    # * [EXPLICAÇÃO] → Mesmos altura/largura/comprimento de cima, só que
    #                  ORDENADOS (menor→maior) — usados por qualquer cálculo
    #                  que precise de eixo consistente (frete/armazenagem).
    altura_ordenada: Decimal
    largura_ordenada: Decimal
    comprimento_ordenada: Decimal


# Função Objetivo: Agrupa os dados de controle/auditoria do Produto.
@dataclass
class DadosControleProduto:
    ultima_compra: datetime
    cadastrado_erp_em: datetime
    criado_em: datetime
    atualizado_em: datetime
    armazenagem_planilha: Decimal


# Função Objetivo: Representa 1 código do Produto numa plataforma específica.
@dataclass
class CodigoAssociado:
    marketplace: str
    rotulo: str
    codigo: str


# Função Objetivo: Representa a situação de anúncio manualmente marcada por marketplace.
@dataclass
class MarketplaceAnunciado:
    marketplace: str
    anunciado: bool


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

    # * [EXPLICAÇÃO] → Adicionado 15/08 — antes o sistema não tinha nenhum
    #                  jeito explícito de saber se um produto está ativo ou
    #                  inativo no ERP (isso ficava só implícito em qual
    #                  arquivo o produto vinha). Agora vem direto da coluna
    #                  real "Inativo" da planilha do ERP (ver
    #                  importar_produtos_erp.py) — nunca inferido do nome
    #                  do arquivo. Ver decisão "Produto Nasce Exclusivamente
    #                  do ERP" no vault.
    ativo_no_erp = models.BooleanField(default=True)

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

    # * [EXPLICAÇÃO] → Peso cúbico (volumétrico) — agora SEMPRE
    #                  calculado a partir do produto APÓS EMBALADO
    #                  (a caixa real enviada), nunca do produto puro.
    #                  Fórmula muda de arquivo (importadores), não
    #                  daqui — este campo só guarda o resultado.
    peso_cubado = models.DecimalField(
        max_digits=8, decimal_places=3, blank=True, null=True)

    icms_saida_sp = models.DecimalField(
        max_digits=6, decimal_places=2, default=0)
    icms_saida_media = models.DecimalField(
        max_digits=6, decimal_places=2, default=0)

    # Únicos campos de PIS/COFINS do Produto — sempre de saída. O crédito
    # de entrada vem de impostos_entrada (ver domínio `impostos`), nunca
    # daqui.
    pis_percentual = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    cofins_percentual = models.DecimalField(max_digits=6, decimal_places=2, default=0)

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
    # armazenagem. Não persiste nada, só calcula e devolve. Método de propósito
    # único (infraestrutura do comparador ERP x ML) — não faz parte dos 8
    # agrupamentos de consulta geral do Produto.
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

    # Função Objetivo: Devolve os dados de identificação/catálogo deste produto.
    def obter_dados_identificacao(self):
        return DadosIdentificacaoProduto(
            ean=self.ean, sku=self.sku, cod_fabricante=self.cod_fabricante, ncm=self.ncm,
            titulo=self.titulo, marca=self.marca, categoria=self.categoria, curva=self.curva,
            imagem_url=self.imagem_url, estoque=self.estoque, ativo_no_erp=self.ativo_no_erp,
        )

    # Função Objetivo: Devolve os dados financeiros deste produto.
    def obter_dados_financeiros(self):
        return DadosFinanceirosProduto(
            custo=self.custo, custo_com_boni=self.custo_com_boni,
        )

    # Função Objetivo: Devolve os dados fiscais deste produto.
    def obter_dados_fiscais(self):
        return DadosFiscaisProduto(
            icms_saida_sp=self.icms_saida_sp, icms_saida_media=self.icms_saida_media,
            pis_percentual=self.pis_percentual, cofins_percentual=self.cofins_percentual,
            frete_cif_fob=self.frete_cif_fob,
        )

    # Função Objetivo: Devolve a dimensão do produto puro, sem embalagem.
    def obter_dimensoes_sem_embalar(self):
        return DimensaoSemEmbalar(
            peso=self.peso_produto_sem_embalar, altura=self.altura_produto_sem_embalar,
            largura=self.largura_produto_sem_embalar,
            comprimento=self.comprimento_produto_sem_embalar,
        )

    # Função Objetivo: Devolve a dimensão da embalagem real enviada.
    def obter_dimensoes_apos_embalado(self):
        return DimensaoAposEmbalado(
            peso=self.peso_produto_apos_embalado, altura=self.altura_produto_apos_embalado,
            largura=self.largura_produto_apos_embalado,
            comprimento=self.comprimento_produto_apos_embalado,
            peso_cubado=self.peso_cubado,
            altura_ordenada=self.altura_ordenada_cm, largura_ordenada=self.largura_ordenada_cm,
            comprimento_ordenada=self.comprimento_ordenada_cm,
        )

    # Função Objetivo: Devolve os dados de controle/auditoria deste produto.
    def obter_dados_controle(self):
        return DadosControleProduto(
            ultima_compra=self.ultima_compra, cadastrado_erp_em=self.cadastrado_erp_em,
            criado_em=self.criado_em, atualizado_em=self.atualizado_em,
            armazenagem_planilha=self.armazenagem_planilha,
        )

    # Função Objetivo: Devolve todos os códigos associados deste produto, por marketplace.
    def obter_codigos_associados(self):
        return [
            CodigoAssociado(marketplace=c.marketplace, rotulo=c.rotulo, codigo=c.codigo)
            for c in self.codigos_associados.all()
        ]

    # Função Objetivo: Devolve a situação de anúncio (marcada manualmente) por marketplace.
    def obter_marketplaces_anunciados(self):
        return [
            MarketplaceAnunciado(marketplace=a.marketplace, anunciado=a.anunciado)
            for a in self.anuncios_marketplace.all()
        ]

    class Meta:
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'
        ordering = ['titulo']

    def __str__(self):
        return f'{self.ean} — {self.titulo}'