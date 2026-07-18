# produtos/funcoes_auxiliares/dimensoes_fisicas.py

# Função Objetivo: Conta pura — m³ a partir de altura/largura/comprimento em CM.
# Explicação em detalhe: movida de mercado_livre/funcoes_auxiliares/calculo_margem.py
# (17/07) — é operação puramente física sobre dimensões do Produto, sem nenhum conceito
# de marketplace embutido. Fica neutra aqui pra qualquer app de marketplace (mercado_livre,
# magalu, e os que vierem depois) reaproveitar sem criar dependência entre apps-irmãos.
def metro_cubico_de_dimensoes(altura, largura, comprimento):
    if altura is None or largura is None or comprimento is None:
        return 0
    return (altura / 100) * (largura / 100) * (comprimento / 100)


# Função Objetivo: Conta pura — acha a faixa (por dimensão) onde o produto se encaixa.
# Explicação em detalhe: movida junto — acha a primeira faixa (ordem crescente) onde
# TODAS as dimensões cabem; se nenhuma comportar, usa a maior (fallback). Funciona com
# qualquer objeto de faixa que tenha .max_altura/.max_largura/.max_profundidade — não
# depende de nenhum model específico de marketplace.
def selecionar_faixa_por_dimensao(altura, largura, comprimento, faixas):
    if not faixas:
        return None

    altura = altura or 0
    largura = largura or 0
    comprimento = comprimento or 0

    for faixa in faixas:
        if (altura <= faixa.max_altura
                and largura <= faixa.max_largura
                and comprimento <= faixa.max_profundidade):
            return faixa

    return faixas[-1]