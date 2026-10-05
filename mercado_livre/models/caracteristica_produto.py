# mercado_livre/models/caracteristica_produto.py
from django.db import models


class CaracteristicaProdutoMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → O valor que o USUÁRIO preencheu na tela de
    #                  Características dos anúncios: 1 linha por produto +
    #                  característica (nunca por MLB — regra de negócio:
    #                  todos os MLBs de 1 produto recebem exatamente os
    #                  mesmos dados). Cada MLB recebe só o subconjunto que
    #                  a categoria dele pede (ver AtributoCategoriaMercadoLivre).
    #                  Campo sem valor = linha não existe. A Marca NÃO
    #                  entra aqui: continua vindo de Produto.marca (ERP).

    class Situacao(models.TextChoices):
        RASCUNHO = 'rascunho', 'Rascunho'
        ENVIADO = 'enviado', 'Enviado'

    produto = models.ForeignKey(
        'produtos.Produto',
        on_delete=models.CASCADE,
        related_name='caracteristicas_mercado_livre'
    )

    # * [EXPLICAÇÃO] → Mesmo "ID na API" de AtributoCategoriaMercadoLivre
    #                  (ex.: "MODEL"). Não é ForeignKey de propósito: o
    #                  valor é do produto e vale para qualquer categoria
    #                  que peça aquele mesmo ID.
    atributo_id = models.CharField(max_length=60)

    # * [EXPLICAÇÃO] → Os 4 campos abaixo cobrem todos os tipos de campo:
    #                  lista usa valor_id + valor_nome; texto usa só
    #                  valor_nome; número com unidade usa valor_numero +
    #                  unidade. O jeito exato de gravar cada tipo (inclusive
    #                  Sim/Não) é confirmado com a documentação oficial na
    #                  Etapa 2.
    valor_id = models.CharField(max_length=60, blank=True, null=True)
    valor_nome = models.CharField(max_length=255, blank=True, null=True)
    valor_numero = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
    unidade = models.CharField(max_length=30, blank=True, null=True)

    # * [EXPLICAÇÃO] → Rascunho = salvo aqui, ainda não confirmado no ML.
    #                  Enviado = foi enviado ao ML. Se o usuário alterar um
    #                  valor já enviado, volta para Rascunho. A situação REAL
    #                  de cada MLB (igual / diferente / em branco) não mora
    #                  aqui: é calculada comparando este valor com o que a
    #                  última leitura do ML trouxe.
    situacao = models.CharField(
        max_length=10,
        choices=Situacao.choices,
        default=Situacao.RASCUNHO,
    )

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together     = ['produto', 'atributo_id']
        verbose_name        = 'Característica de Produto Mercado Livre'
        verbose_name_plural = 'Características de Produto Mercado Livre'
        ordering            = ['atributo_id']

    def __str__(self):
        valor = self.valor_nome or self.valor_numero
        return f'{self.produto.sku} — {self.atributo_id}: {valor}'
