from django.db import models


class FaixaArmazenagem(models.Model):
    # * [EXPLICAÇÃO] → Movido de mercado_livre/FaixaArmazenagemMercadoLivre
    #                  (17/07) — mesma razão do ConfiguracaoOperacional: é
    #                  faixa de custo de armazém por dimensão física, não
    #                  regra de negócio de nenhum marketplace específico.
    #                  Usada quando o Produto ainda não tem
    #                  armazenagem_planilha. Itera em ordem crescente,
    #                  primeira faixa onde TODAS as dimensões cabem; se
    #                  nenhuma comportar, usa a maior (fallback).

    nome = models.CharField(max_length=50)
    valor_diario = models.DecimalField(max_digits=8, decimal_places=4)
    max_altura = models.DecimalField(max_digits=6, decimal_places=2)
    max_largura = models.DecimalField(max_digits=6, decimal_places=2)
    max_profundidade = models.DecimalField(max_digits=6, decimal_places=2)
    ordem = models.PositiveIntegerField(default=1)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Faixa de Armazenagem'
        verbose_name_plural = 'Faixas de Armazenagem'
        ordering = ['ordem']

    def __str__(self):
        return f'{self.nome} (R$ {self.valor_diario}/dia)'