# gestao_vendas/urls.py

from django.urls import path
from . import views_vendas

urlpatterns = [
    # * [EXPLICAÇÃO] → Tela "Vendas — Histórico de vendas" (11/10/2026): o ritmo de vendas de um produto (SKU), do Mercado Livre, em calendário
    #                  semana × dia da semana, com cartões-resumo e os 5 níveis (Produto, No Full, Fora do Full, Por MLB, Por Código ML).
    #                  Sem ?sku= ela mostra a LISTA de vendas (12/10/2026): uma linha por Produto (SKU), Anúncio (MLB) ou Código ML, com Full × fora, "vs. anterior"
    #                  e o link de cada linha para o calendário. A lista nasceu como substituta da busca simples + "Mais vendidos".
    #                  Só lê o banco. É a base da futura previsão de ruptura e da ordem de compra.
    path('', views_vendas.view_vendas, name='gestao_vendas_principal'),

    # * [EXPLICAÇÃO] → Botões de atualização (os ÚNICOS caminhos em que a tela chega ao Mercado Livre, sempre por clique), todos granulares:
    #                  "Atualizar" de um MLB (atualizar/mlb/; o "Atualizar produto" da tela primeiro pergunta o plano em planejar/ — só lê o banco,
    #                  diz o que falta — e depois chama atualizar/mlb/ uma vez por trecho curto, vários ao mesmo tempo; o botão "Atualizar este item" da tela
    #                  "Previsão de Ruptura de estoque" usa os MESMOS endereços, pelo mesmo orquestrador JS, atualizador_de_vendas.js),
    #                  "Atualizar dia" de um dia da conta toda (atualizar/dia/) e "Coletar período da conta" (periodo/iniciar/, com o andamento
    #                  em periodo/status/ e o botão Parar em periodo/parar/).
    path('planejar/', views_vendas.view_vendas_planejar, name='gestao_vendas_planejar'),

    # * [EXPLICAÇÃO] → Painel do dia: os pedidos de 1 dia (só lê o banco), buscados quando a pessoa abre o bloco "Pedidos e cancelamentos".
    path('pedidos-do-dia/', views_vendas.view_vendas_pedidos_dia, name='gestao_vendas_pedidos_dia'),
    path('atualizar/mlb/', views_vendas.view_vendas_atualizar_mlb, name='gestao_vendas_atualizar_mlb'),
    path('atualizar/dia/', views_vendas.view_vendas_atualizar_dia, name='gestao_vendas_atualizar_dia'),
    path('periodo/iniciar/', views_vendas.view_vendas_periodo_iniciar, name='gestao_vendas_periodo_iniciar'),
    path('periodo/status/', views_vendas.view_vendas_periodo_status, name='gestao_vendas_periodo_status'),
    path('periodo/parar/', views_vendas.view_vendas_periodo_parar, name='gestao_vendas_periodo_parar'),

    # * [EXPLICAÇÃO] → Guarda no banco o total de chamadas de UM clique em "Atualizar" (MLB ou produto): a tela soma os trechos e manda no fim. NÃO chama o
    #                  Mercado Livre. ("Atualizar dia" e "Coletar período" o servidor mesmo registra.) Tabela: ExecucaoColetaVendasMercadoLivre.
    path('execucao/registrar/', views_vendas.view_vendas_execucao_registrar, name='gestao_vendas_execucao_registrar'),
]
