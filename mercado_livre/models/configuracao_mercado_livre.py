from django.db import models
from .tipo_de_anuncio import TipoDeAnuncioMercadoLivre


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