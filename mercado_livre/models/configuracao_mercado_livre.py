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
    # * [EXPLICAÇÃO] → 1 linha por tipo_anuncio (Clássico/Premium) — 2
    #                  no total. Simplificado em 27/07: confirmado com
    #                  o usuário/superior que logística (FULL/Coleta)
    #                  e classificação (Simples/Base/Catálogo) NÃO
    #                  afetam comissão nem margem — só o tipo de
    #                  anúncio importa pra precificação. As 8 linhas
    #                  antigas (mantidas "pra controle fino futuro")
    #                  foram abandonadas de propósito, não são mais
    #                  necessárias.

    tipo_anuncio = models.CharField(
        max_length=20, choices=TipoDeAnuncioMercadoLivre.TipoAnuncio.choices, unique=True)

    comissao = models.DecimalField(max_digits=5, decimal_places=2)

    margem_minima = models.DecimalField(max_digits=5, decimal_places=2)
    margem_padrao = models.DecimalField(max_digits=5, decimal_places=2)
    margem_maxima = models.DecimalField(max_digits=5, decimal_places=2)

    # * [EXPLICAÇÃO] → Piso de margem quando o objetivo é "ganhar a
    #                  todo custo" (ex: vencer catálogo) — mais baixo
    #                  que margem_minima de propósito. Continua existindo
    #                  aqui (usado pela Grade, que gera o preço pra essa
    #                  meta também) — mas QUAL margem usar como piso em
    #                  cada situação (Catálogo vs Simples/Base) é decidido
    #                  na Recomendação/Hub, não aqui.
    margem_competicao = models.DecimalField(max_digits=5, decimal_places=2)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração de Tipo de Anúncio ML'
        verbose_name_plural = 'Configurações de Tipo de Anúncio ML'
        ordering = ['tipo_anuncio']

    def __str__(self):
        return self.get_tipo_anuncio_display()

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