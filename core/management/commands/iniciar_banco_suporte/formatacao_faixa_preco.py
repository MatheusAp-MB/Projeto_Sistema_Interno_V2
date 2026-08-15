# core/management/commands/iniciar_banco_suporte/formatacao_faixa_preco.py

# * [RESUMO] → Helper compartilhado pelos seeds de faixa de preço (Tabela de
#              Comissão Shopee/Tiktok, Taxa de KG Adicional Amazon) — formata
#              o teto de uma faixa pro log do terminal, sempre do mesmo
#              jeito. Extraído porque a mesma linha estava copiada e colada
#              em 3 arquivos diferentes.

def formatar_teto(preco_max):
    return preco_max if preco_max is not None else 'sem teto'