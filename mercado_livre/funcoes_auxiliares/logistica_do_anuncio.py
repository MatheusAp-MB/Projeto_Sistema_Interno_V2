# mercado_livre/funcoes_auxiliares/logistica_do_anuncio.py
#
# Função Objetivo: O DONO ÚNICO da pergunta "a logística deste anúncio é do Full ou de fora do Full?". Quem precisa dessa resposta (a Previsão de Ruptura de estoque, a regra de origem das vendas...) chama estas funções:
# nenhuma tela escreve "fulfillment" nem compara logística por conta própria. O valor vem do enum do próprio modelo (TipoDeAnuncioMercadoLivre.TipoLogistico), que é a fonte do dado.
#
# * [EXPLICAÇÃO] → Duas respostas e só duas. "Do Full" = logística FULL. "De fora do Full" = logística PREENCHIDA e diferente de FULL (Coleta, Agência, Flex Puro, Legado, Correios, Por nossa conta, ou o tipo que o Mercado
#                  Livre criar amanhã). Logística vazia (anúncio sem tipo cadastrado) não é de nenhum dos dois: ausente não é "fora do Full".
# * [EXPLICAÇÃO] → O filtro de Logística do painel de filtros do Hub (filtros_do_hub.py) NÃO é reimplementado: na Previsão de Ruptura (mundo Fora do Full) as opções são só as do Hub que esta regra
#                  aprova como "de fora do Full" (logistica_e_de_fora_do_full) — o Hub continua sendo o dono da lista de opções e esta regra a dona de "o que é Full".
# * [EXPLICAÇÃO] → O que NÃO mora aqui: a exclusão dos anúncios "fósseis" de migração (campo eh_fossil_migracao do anúncio, aplicada por cima desta regra pelo Hub e pela Previsão) e as opções de logística do filtro do
#                  Hub (escolha explícita da pessoa, com os selos de badges.py).

from mercado_livre.models import TipoDeAnuncioMercadoLivre

LOGISTICA_FULL = TipoDeAnuncioMercadoLivre.TipoLogistico.FULL.value


# Função Objetivo: A logística (valor bruto do banco, ex.: "fulfillment") é a do Full?
def logistica_e_do_full(tipo_logistico):
    return tipo_logistico == LOGISTICA_FULL


# Função Objetivo: A logística (valor bruto do banco) é de fora do Full? Preenchida e diferente de FULL. Vazia/None não é.
def logistica_e_de_fora_do_full(tipo_logistico):
    return bool(tipo_logistico) and tipo_logistico != LOGISTICA_FULL
