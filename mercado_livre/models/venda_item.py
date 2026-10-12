# mercado_livre/models/venda_item.py
#
# Função Objetivo: Guarda cada ITEM VENDIDO nos pedidos do Mercado Livre (GET /orders/search), já limpo e tipado. É a ÚNICA origem do
# histórico de vendas por produto, por MLB, por Código ML e por origem (Full ou fora do Full). A tela de vendas e qualquer cálculo
# futuro (ritmo, previsão de ruptura) leem SÓ daqui: nunca de JSON, nunca de uma chamada ao vivo feita pela tela. Quem grava é o
# coletor (coletar_vendas_ml), sempre por clique de botão.
#
# Contexto: o endpoint de operações do Full foi abandonado em 10/10/2026 (429 mesmo com 1 SKU). O /orders/search entrega o pedido com
# SKU, MLB, quantidade, data, status e origem do estoque na mesma resposta (medido em 10/10/2026, conta Magazine, 160 pedidos de 1 dia).

from django.db import models


class VendaItemMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Um pedido pode ter vários itens; cada item vira 1 linha. A chave natural é (order_id, posicao): reler o mesmo
    #                  período NÃO duplica nada, só atualiza a linha (é assim que um cancelamento feito depois entra no banco).
    #                  Nos 160 pedidos medidos em 10/10/2026 todos tinham 1 item, mas a doc permite mais.
    order_id = models.BigIntegerField()
    posicao  = models.PositiveSmallIntegerField(default=0)

    # * [EXPLICAÇÃO] → item.id do pedido (o MLB) e item.seller_sku (o SKU do produto, igual ao Produto.sku do sistema; veio em
    #                  160 de 160 itens medidos). item.seller_custom_field NÃO é usado: só veio em metade dos itens.
    mlb        = models.CharField(max_length=20)
    seller_sku = models.CharField(max_length=40, blank=True)

    # * [EXPLICAÇÃO] → item.variation_id (vazio na maioria). Serve para ligar o MLB ao Código ML (inventory_id) da variação certa
    #                  quando o MLB tem mais de um Código.
    variation_id = models.CharField(max_length=30, blank=True)

    # * [EXPLICAÇÃO] → quantity do item: o ritmo de vendas usa UNIDADES, não número de pedidos (160 pedidos = 170 unidades em
    #                  09/10/2026). Nunca 0: pedido sem quantidade não é gravado (ausente não é zero).
    quantidade = models.PositiveIntegerField()

    # * [EXPLICAÇÃO] → unit_price e sale_fee do item, na moeda do pedido (BRL). Podem faltar (null): aí a tela não soma faturamento
    #                  daquele item em vez de inventar 0. listing_type_id = tipo do anúncio (gold_special, gold_pro...).
    preco_unitario = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    taxa_venda     = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tipo_anuncio   = models.CharField(max_length=30, blank=True)

    # * [EXPLICAÇÃO] → Status do pedido como o ML manda (paid, cancelled...). A busca do vendedor TRAZ os cancelados (medido em
    #                  10/10/2026: 158 paid + 2 cancelled). Regra de negócio do Matheus: venda cancelada NÃO conta no dia da venda
    #                  original. Por isso o status é guardado e a tela só soma o que não é 'cancelled'.
    status = models.CharField(max_length=30)

    # * [EXPLICAÇÃO] → date_created e date_closed do pedido. A API manda TODAS as datas com fuso -04:00, mas Brasília é -03:00: o
    #                  coletor lê a data completa com o fuso e converte (nunca corta os 10 primeiros caracteres). O dia da venda é
    #                  date_created (decisão de 10/10/2026: é quando o cliente comprou; 159 de 160 pedidos tiveram o mesmo dia nas
    #                  duas datas, e o que trocou foi criado 09/10 e fechado 10/10 às 10:37).
    criado_em_ml  = models.DateTimeField()
    fechado_em_ml = models.DateTimeField(null=True, blank=True)

    # * [EXPLICAÇÃO] → O DIA e a HORA da venda no horário de Brasília, calculados UMA vez na gravação a partir de criado_em_ml.
    #                  Existem para somar por dia no banco sem depender das tabelas de fuso horário do MySQL. Se a regra do dia da
    #                  venda mudar, é só recalcular a partir de criado_em_ml.
    dia_venda  = models.DateField()
    hora_venda = models.PositiveSmallIntegerField()

    # * [EXPLICAÇÃO] → De onde o estoque saiu (order_items[].stock): node_id é o nó (BRSP11, BRPE01... = centro do Full; "BRP" + código do vendedor
    #                  + "1" = o estoque próprio, fora do Full) e store_id só vem preenchido no estoque próprio (a partir de ~25/03/2026). Antes de
    #                  26/03/2026 o ML mandava o pedido de Coleta SEM stock (node_id e store_id vazios; o envio também não tem origin.node). Medido
    #                  em 10 e 11/10/2026 com 80 envios: nó de centro = fulfillment; nó próprio, loja e Coleta sem origem = cross_docking. Quem
    #                  separa Full de fora do Full é a função classificar_origem (em gestao_vendas), em 1 lugar só.
    node_id  = models.CharField(max_length=30, blank=True)
    store_id = models.CharField(max_length=30, blank=True)

    # * [EXPLICAÇÃO] → Ligações do pedido: pack (carrinho) e envio. Sem dado de comprador: o coletor nunca grava nada do buyer.
    pack_id     = models.BigIntegerField(null=True, blank=True)
    shipping_id = models.BigIntegerField(null=True, blank=True)

    # * [EXPLICAÇÃO] → Tags do pedido que já valem a pena guardar: venda por catálogo ("catalog") e pedido com desconto
    #                  ("order_has_discount"). Em 09/10/2026: 112 e 119 de 160 pedidos.
    catalogo     = models.BooleanField(default=False)
    com_desconto = models.BooleanField(default=False)

    # Quando NÓS gravamos/atualizamos a linha pela última vez (não é data do ML).
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Item vendido no Mercado Livre'
        verbose_name_plural = 'Itens vendidos no Mercado Livre'
        constraints = [
            models.UniqueConstraint(fields=['order_id', 'posicao'], name='vendaitem_pedido_posicao_uniq'),
            models.CheckConstraint(condition=models.Q(quantidade__gte=1), name='vendaitem_quantidade_maior_que_zero'),
        ]
        indexes = [
            # Histórico de 1 SKU por dia (a consulta principal da tela).
            models.Index(fields=['seller_sku', 'dia_venda'], name='vi_sku_dia_idx'),
            # Histórico de 1 MLB por dia (botão "Atualizar" e nível por MLB).
            models.Index(fields=['mlb', 'dia_venda'], name='vi_mlb_dia_idx'),
            # Conta toda por dia.
            models.Index(fields=['dia_venda'], name='vi_dia_idx'),
        ]

    def __str__(self):
        return f'{self.order_id} · {self.mlb} · {self.quantidade} un · {self.dia_venda:%d/%m/%Y}'
