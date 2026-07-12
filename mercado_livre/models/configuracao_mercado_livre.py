from django.db import models
from .tipo_de_anuncio import TipoDeAnuncioMercadoLivre


# ================================================
# CONFIGURAÇÃO GERAL (singleton — 1 linha só)
# ================================================

class ConfiguracaoMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Parâmetros globais de logística do ML, usados na
    #                  fórmula de margem (calculo_margem.py). Singleton
    #                  — só deve existir 1 linha no sistema inteiro.

    fator_coleta = models.DecimalField(
        max_digits=8, decimal_places=2, default=72,
        help_text='Custo de coleta em R$ por m³.'
    )
    periodo_armazenagem = models.IntegerField(
        default=30,
        help_text='Dias considerados no cálculo mensal de armazenagem.'
    )

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração Mercado Livre'
        verbose_name_plural = 'Configuração Mercado Livre'

    def __str__(self):
        return 'Configuração Mercado Livre'

    @classmethod
    def obter(cls):
        """Busca a única configuração existente, criando com valores
        padrão se ainda não existir — evita quebrar o cálculo de margem
        caso alguém rode o sistema antes do seed inicial."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config


# ================================================
# CONFIGURAÇÃO POR TIPO DE ANÚNCIO (8 linhas)
# ================================================

class ConfiguracaoTipoAnuncioMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → 1 linha por combinação de (tipo_anuncio ×
    #                  tipo_logistico × catálogo) — 8 no total. Reaproveita
    #                  as mesmas TextChoices de TipoDeAnuncioMercadoLivre,
    #                  nunca duplicar essa lista em outro lugar.
    #                  Na prática (confirmado com o usuário), comissão só
    #                  varia por tipo_anuncio — as 8 linhas existem pra dar
    #                  controle fino no futuro, não porque a diferença já
    #                  seja usada hoje.

    tipo_anuncio = models.CharField(
        max_length=20, choices=TipoDeAnuncioMercadoLivre.TipoAnuncio.choices)
    tipo_logistico = models.CharField(
        max_length=20, choices=TipoDeAnuncioMercadoLivre.TipoLogistico.choices)
    catalogo = models.BooleanField(default=False)

    comissao = models.DecimalField(max_digits=5, decimal_places=2)

    # * [EXPLICAÇÃO] → % somado ao preço Clássico pra gerar o preço
    #                  Premium (Premium = RoundUpTo90(Clássico × (1 +
    #                  acrescimo_preco/100))) — regra de GERAÇÃO de
    #                  preço, não meta de margem. Hoje 8%, mas precisa
    #                  ser editável, não fixo em código.
    acrescimo_preco = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    margem_minima = models.DecimalField(max_digits=5, decimal_places=2)
    margem_padrao = models.DecimalField(max_digits=5, decimal_places=2)
    margem_maxima = models.DecimalField(max_digits=5, decimal_places=2)

    # * [EXPLICAÇÃO] → Piso de margem quando o objetivo é "ganhar a
    #                  todo custo" (ex: vencer catálogo) — mais baixo
    #                  que margem_minima de propósito.
    margem_competicao = models.DecimalField(max_digits=5, decimal_places=2)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração de Tipo de Anúncio ML'
        verbose_name_plural = 'Configurações de Tipo de Anúncio ML'
        unique_together = ['tipo_anuncio', 'tipo_logistico', 'catalogo']
        ordering = ['tipo_anuncio', 'tipo_logistico', 'catalogo']

    def __str__(self):
        nome_tipo = self.get_tipo_anuncio_display()
        nome_logistico = self.get_tipo_logistico_display()
        sufixo_catalogo = ' — Catálogo' if self.catalogo else ''
        return f'{nome_tipo} {nome_logistico}{sufixo_catalogo}'


# ================================================
# FAIXA DE ARMAZENAGEM (4 linhas, modo avançado)
# ================================================

class FaixaArmazenagemMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Seleção de custo de armazenagem por dimensão do
    #                  produto — usada quando NÃO existe
    #                  Produto.armazenagem_planilha (ex: produto sendo
    #                  precificado do zero, sem histórico na planilha).
    #                  Itera em ordem crescente e usa a primeira faixa
    #                  onde TODAS as dimensões cabem; se nenhuma
    #                  comportar, usa a maior (fallback).

    nome = models.CharField(max_length=50)
    valor_diario = models.DecimalField(max_digits=8, decimal_places=4)
    max_altura = models.DecimalField(max_digits=6, decimal_places=2)
    max_largura = models.DecimalField(max_digits=6, decimal_places=2)
    max_profundidade = models.DecimalField(max_digits=6, decimal_places=2)
    ordem = models.PositiveIntegerField(default=1)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Faixa de Armazenagem ML'
        verbose_name_plural = 'Faixas de Armazenagem ML'
        ordering = ['ordem']

    def __str__(self):
        return f'{self.nome} (R$ {self.valor_diario}/dia)'