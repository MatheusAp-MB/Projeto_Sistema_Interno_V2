# mercado_livre/models/coleta_vendas.py
#
# Função Objetivo: Registro de cada COLETA de pedidos que alguém disparou pela tela de vendas (1 linha por clique). Serve para a tela
# dizer, para cada SKU, "tenho dados de X a Y, atualizados em Z" e para NÃO prometer dado que ninguém puxou: na tela, dia sem venda
# dentro do período coberto é zero de verdade; dia fora do período coberto é "sem dado" (ausente não é zero).
#
# * [EXPLICAÇÃO] → As coletas são GRANULARES (decisão do Matheus, 11/10/2026): 1 MLB, 1 dia da conta inteira ou um período da conta
#                  inteira. O botão "Atualizar produto" não tem escopo próprio: ele registra 1 coleta 'mlb' por MLB do SKU (o campo
#                  `sku` guarda só quem pediu). Cada escopo cobre um pedaço diferente:
#                    - 'dia' e 'periodo' cobrem a CONTA toda (todos os SKUs) nas datas dele;
#                    - 'mlb' cobre só aquele MLB (o SKU só fica coberto quando TODOS os MLBs dele têm o período).
#                  A conta de cobertura mora em gestao_vendas.funcoes_auxiliares.vendas_ml (cobertura_do_sku).

from django.db import models


class ColetaVendasMercadoLivre(models.Model):
    class Escopo(models.TextChoices):
        MLB     = 'mlb',     'Um MLB'
        DIA     = 'dia',     'Um dia da conta toda'
        PERIODO = 'periodo', 'Um período da conta toda'

    class Status(models.TextChoices):
        CONCLUIDA = 'concluida', 'Concluída'
        PARCIAL   = 'parcial',   'Parcial (interrompida; data_de/data_ate mostram só o que ficou completo)'
        FALHA     = 'falha',     'Falhou (nada conta como coberto)'

    escopo = models.CharField(max_length=10, choices=Escopo.choices)
    mlb    = models.CharField(max_length=20, blank=True)
    sku    = models.CharField(max_length=40, blank=True)   # só em coleta 'mlb' pedida pelo "Atualizar produto": o SKU que pediu

    # * [EXPLICAÇÃO] → Datas INCLUSIVAS (dia de Brasília): data_de 01/10 e data_ate 03/10 cobrem os dias 1, 2 e 3. Em coleta PARCIAL
    #                  guardam só o trecho que terminou por completo. Em FALHA guardam o que foi pedido, mas não contam como cobertura.
    data_de  = models.DateField()
    data_ate = models.DateField()

    status = models.CharField(max_length=10, choices=Status.choices)

    pedidos_lidos  = models.PositiveIntegerField(default=0)
    itens_gravados = models.PositiveIntegerField(default=0)
    chamadas       = models.PositiveIntegerField(default=0)
    erros_429      = models.PositiveIntegerField(default=0)
    # * [EXPLICAÇÃO] → O texto da coleta + a lista COMPLETA dos avisos (título "Avisos desta coleta", um por linha; até 20). A tela mostra só o 1º aviso.
    mensagem       = models.TextField(blank=True)
    usuario        = models.CharField(max_length=150, blank=True)

    iniciado_em  = models.DateTimeField()
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = 'Coleta de vendas do Mercado Livre'
        verbose_name_plural = 'Coletas de vendas do Mercado Livre'
        ordering = ['-iniciado_em']
        indexes = [
            models.Index(fields=['escopo', 'status', 'data_ate'], name='coletav_escopo_status_idx'),
            models.Index(fields=['sku', 'status'], name='coletav_sku_status_idx'),
            models.Index(fields=['mlb', 'status'], name='coletav_mlb_status_idx'),
        ]

    def __str__(self):
        alvo = self.mlb or self.sku or 'conta'
        return f'{self.get_escopo_display()} · {alvo} · {self.data_de:%d/%m/%Y}–{self.data_ate:%d/%m/%Y} · {self.get_status_display()}'
