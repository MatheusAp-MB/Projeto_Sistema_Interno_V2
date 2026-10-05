# mercado_livre/models/varredura_caracteristicas.py
from django.db import models


class VarreduraCaracteristicasMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Histórico de cada "Fazer varredura completa" da tela
    #                  de Características dos anúncios: quando começou,
    #                  quando terminou, quantos anúncios e categorias foram
    #                  lidos e o que falhou. Existe para a tela mostrar
    #                  "Última varredura completa: ..." sem precisar chamar
    #                  a API, e para sobrar um rastro do que aconteceu se a
    #                  varredura quebrar no meio. O "Atualizar" de um produto
    #                  NÃO gera linha aqui — a data de cada anúncio já fica em
    #                  AnuncioMercadoLivre.atributos_ml_lido_em.

    class Situacao(models.TextChoices):
        RODANDO    = 'rodando',    'Rodando'
        CONCLUIDA  = 'concluida',  'Concluída'
        COM_FALHAS = 'com_falhas', 'Concluída com falhas'
        ERRO       = 'erro',       'Interrompida por erro'

    iniciada_em  = models.DateTimeField(auto_now_add=True)
    concluida_em = models.DateTimeField(blank=True, null=True)
    situacao     = models.CharField(max_length=12, choices=Situacao.choices, default=Situacao.RODANDO)

    # * [EXPLICAÇÃO] → Quem apertou o botão (nome de usuário do Django).
    usuario = models.CharField(max_length=150, blank=True)

    total_anuncios   = models.PositiveIntegerField(default=0)
    anuncios_lidos   = models.PositiveIntegerField(default=0)
    total_categorias = models.PositiveIntegerField(default=0)
    categorias_lidas = models.PositiveIntegerField(default=0)

    # * [EXPLICAÇÃO] → Lista de {"tipo", "id", "erro"} do que não foi lido
    #                  (limitada às primeiras ocorrências — o objetivo é
    #                  diagnosticar, não arquivar tudo).
    falhas = models.JSONField(blank=True, null=True)

    class Meta:
        verbose_name        = 'Varredura de Características Mercado Livre'
        verbose_name_plural = 'Varreduras de Características Mercado Livre'
        ordering            = ['-iniciada_em']

    def __str__(self):
        return f'Varredura de {self.iniciada_em:%d/%m/%Y %H:%M} — {self.get_situacao_display()}'
