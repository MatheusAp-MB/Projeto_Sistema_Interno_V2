from django.db import models


class ConfiguracaoOperacional(models.Model):
    # * [EXPLICAÇÃO] → Movido de mercado_livre/ConfiguracaoMercadoLivre (17/07) —
    #                  fator_coleta/periodo_armazenagem são custo FÍSICO de
    #                  coleta/armazém, compartilhado por todos os marketplaces
    #                  (confirmado analisando a planilha de precificação: essas
    #                  colunas ficam ANTES de qualquer bloco de marketplace,
    #                  usadas 1x só, reaproveitadas em todos os canais). Nunca
    #                  deveria ter sido nomeado/hospedado como se fosse
    #                  exclusivo do ML. Singleton — só deve existir 1 linha.

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
        verbose_name = 'Configuração Operacional'
        verbose_name_plural = 'Configuração Operacional'

    def __str__(self):
        return 'Configuração Operacional'

    @classmethod
    def obter(cls):
        """Busca a única configuração existente, criando com valores
        padrão se ainda não existir — evita quebrar o cálculo caso
        alguém rode o sistema antes do seed inicial."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config