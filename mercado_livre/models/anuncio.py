from django.db import models


class AnuncioMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Agrupador — dados confirmados como idênticos entre
    #                  todas as variações do mesmo MLB (validado com dado
    #                  real: título, status/tipo, catálogo, datas e
    #                  permalink não mudam entre variações de um MLB).
    mlb  = models.CharField(max_length=20, unique=True)

    titulo_anuncio = models.CharField(max_length=255, blank=True, null=True)

    tipo_de_anuncio = models.ForeignKey(
        'mercado_livre.TipoDeAnuncioMercadoLivre',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='anuncios'
    )

    catalog_product_id = models.CharField(max_length=30, blank=True, null=True)
    catalog_listing     = models.BooleanField(null=True, blank=True)
    item_relations      = models.JSONField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Espelho cru do array "pictures" da API (GET
    #                  /items?ids=), nível de anúncio — mesma natureza de
    #                  dado que item_relations acima. Dado de consumo,
    #                  sobrescrito por inteiro a cada reimportação — nunca
    #                  escrito por interação do usuário (ver Hub de Fotos,
    #                  checkpoint no vault).
    fotos = models.JSONField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Espelho cru do array "attributes" da API, nível de
    #                  anúncio — mesma natureza do campo fotos acima: dado
    #                  de consumo, sobrescrito por inteiro a cada leitura,
    #                  nunca escrito por interação do usuário. É o "Hoje no
    #                  Mercado Livre" da tela de Características dos
    #                  anúncios. atributos_ml_lido_em guarda QUANDO essa
    #                  leitura aconteceu (alimenta "Última leitura do ML" e
    #                  a auditoria pós-envio).
    atributos_ml = models.JSONField(blank=True, null=True)
    atributos_ml_lido_em = models.DateTimeField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Categoria e status que o ML informou NA HORA dessa
    #                  mesma leitura (crus, como a API devolveu). A categoria
    #                  aqui é a que define quais características o card
    #                  pede para este MLB — pode divergir da categoria
    #                  gravada na Variação se o ML mudou o anúncio de
    #                  categoria depois da última importação. O status
    #                  (active, paused, closed...) permite avisar na tela
    #                  quando o banco achava o anúncio ativo e o ML já o
    #                  encerrou. Texto simples (sem FK) para a leitura
    #                  nunca falhar por a categoria ainda não existir na
    #                  tabela de categorias.
    atributos_ml_categoria_id = models.CharField(max_length=30, blank=True, null=True)
    atributos_ml_status = models.CharField(max_length=20, blank=True, null=True)

    permalink  = models.URLField(max_length=500, blank=True, null=True)
    data_criacao_ml       = models.DateTimeField(blank=True, null=True)
    ultima_atualizacao_ml = models.DateTimeField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Identifica MLBs "fósseis" de uma migração antiga de
    #                  variações do próprio Mercado Livre (tag oficial
    #                  "variations_migration_source" no item bruto).
    #                  Confirmado com dado real: 100% dos casos com essa
    #                  tag estão com status=closed — são anúncios
    #                  encerrados carregando histórico de variações que
    #                  não representam nada vendável hoje. Excluídos do
    #                  Hub sempre, sem opção de exibir (não é dado
    #                  "acionável" como conexão com ERP, é só ruído).
    eh_fossil_migracao = models.BooleanField(default=False)

    class Meta:
        verbose_name        = 'Anúncio Mercado Livre'
        verbose_name_plural = 'Anúncios Mercado Livre'
        ordering            = ['mlb']

    def __str__(self):
        return f'{self.mlb} — {self.titulo_anuncio}'