# * [RESUMO] → Competição de catálogo — 1 registro por Anúncio de
#              Catálogo, guarda o resultado de price_to_win.
#
#              status: winning/competing/sharing_first_place são
#              documentados oficialmente pela API. listed/not_listed
#              foram confirmados só por observação de dado real +
#              painel visual do ML, não por texto oficial.
#
#              PENDÊNCIA: winner aparece quando status=winning ou
#              sharing_first_place (confirmado com dado real). Não
#              confirmado se aparece também em status=competing —
#              nenhum exemplo real desse caso foi encontrado ainda.

from django.db import models


class CompeticaoCatalogo(models.Model):

    class StatusCompeticao(models.TextChoices):
        GANHANDO      = 'winning', 'Ganhando'
        PERDENDO      = 'competing', 'Perdendo'
        EMPATADO      = 'sharing_first_place', 'Empatado em 1º'
        INELEGIVEL    = 'listed', 'Inelegível'
        FORA_CATALOGO = 'not_listed', 'Fora do catálogo'

    anuncio = models.OneToOneField(
        'mercado_livre.AnuncioMercadoLivre',
        on_delete=models.CASCADE,
        related_name='competicao'
    )

    status                 = models.CharField(max_length=30, choices=StatusCompeticao.choices, blank=True, null=True)
    current_price           = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    price_to_win              = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    currency_id                = models.CharField(max_length=10, blank=True, null=True)
    visit_share                 = models.CharField(max_length=20, blank=True, null=True)
    competitors_sharing_first_place = models.IntegerField(blank=True, null=True)
    consistent                   = models.BooleanField(blank=True, null=True)
    catalog_product_id            = models.CharField(max_length=30, blank=True, null=True)

    reason  = models.JSONField(blank=True, null=True)
    boosts  = models.JSONField(blank=True, null=True)
    winner  = models.JSONField(blank=True, null=True)

    http_status = models.IntegerField(blank=True, null=True)
    erro        = models.TextField(blank=True, null=True)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Competição de Catálogo'
        verbose_name_plural  = 'Competições de Catálogo'

    def __str__(self):
        return f'{self.anuncio.mlb} — {self.get_status_display() if self.status else "—"}'