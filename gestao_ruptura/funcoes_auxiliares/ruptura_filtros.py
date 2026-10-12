# gestao_ruptura/funcoes_auxiliares/ruptura_filtros.py
#
# Função Objetivo: Os FILTROS DO HUB na lista da tela "Previsão de Ruptura de estoque" (decisão do Matheus, 12/10/2026: "trazer esses filtros para a tela de previsão de ruptura"). Esta tela NÃO tem regra de filtro própria:
# quem decide quais anúncios passam é o Hub (classificacao_catalogo.mlbs_visiveis_com_filtros, a mesma cascata Base↔Catálogo que desenha a tela de Anúncios); os nomes, a leitura e o painel são de
# mercado_livre/funcoes_auxiliares/filtros_do_hub.py (o painel é o mesmo parcial do Hub). Aqui só mora a ponte: o conjunto de anúncios permitidos, o painel de cada mundo e os avisos.
#
# REGRAS DO MATHEUS que moram aqui:
#   - O filtro decide QUAIS LINHAS aparecem; os NÚMEROS de cada linha continuam sendo os do item inteiro. Num Produto (SKU) com 5 anúncios em que só 2 passam no filtro, a linha aparece (tem anúncio que passa) e o estoque, as vendas e o
#     ritmo dela continuam sendo os do produto todo: o estoque do Full mora no Código ML, e cortar as vendas por anúncio sem cortar o estoque daria uma cobertura que não existe. Uma nota logo abaixo dos chips dos filtros ativos (notas_dos_filtros) diz isso.
#   - "Passa" = o mesmo que o Hub mostraria (Base puxada por catálogo filho que passou, catálogo órfão, simples; fósseis nunca). Nunca uma regra copiada para cá.
#
# * [EXPLICAÇÃO] → COMO FICA RÁPIDA: sem filtro ativo nada é lido do Hub (mlbs_permitidos devolve None = tudo passa). Com filtro ativo, o Hub monta a árvore dos SKUs candidatos sem os cards (a mesma conta do filtro dele), uma vez por abertura da lista.

from mercado_livre.funcoes_auxiliares.classificacao_catalogo import mlbs_visiveis_com_filtros
from mercado_livre.funcoes_auxiliares.filtros_do_hub import PARAMETROS_DO_FILTRO, contexto_do_painel, tem_filtro_ativo
from gestao_ruptura.funcoes_auxiliares.ruptura_parametros import filtros_escondidos


# Função Objetivo: Os MLBs que os filtros do Hub deixam passar no mundo da tela (`comuns['filtros_do_mundo']`), ou None quando não há filtro ativo (None = todos passam).
def mlbs_permitidos(comuns):
    filtros = comuns['filtros_do_mundo']
    if not tem_filtro_ativo(filtros):
        return None
    return mlbs_visiveis_com_filtros(filtros)


# Função Objetivo: A entidade (uma linha) passa nos filtros? Passa se algum dos MLBs dela passa (`mlbs` = os anúncios do mundo que a linha representa). Sem filtro ativo (`permitidos` None), passa sempre.
def passa_no_filtro(mlbs, permitidos):
    return permitidos is None or any(m in permitidos for m in mlbs)


# Função Objetivo: O que o painel "Filtros" precisa no mundo da tela: os marcados, as opções (no Fora do Full, só as logísticas de fora do Full), os chips e os filtros escondidos (estoque; no Envios Full, logística).
# `url_limpar` é o endereço do botão "Limpar filtros".
def painel_do_mundo(comuns, url_limpar):
    return contexto_do_painel(comuns['filtros_do_mundo'], url_limpar, escondidos=filtros_escondidos(comuns['mundo']), so_logisticas_de_fora_do_full=True)


# Função Objetivo: Tira os filtros dos parâmetros de um endereço (para o "Limpar filtros"): os parâmetros dos filtros ficam None (fora do endereço).
def sem_filtros_na_url(parametros):
    return {**parametros, **{parametro: None for _, parametro in PARAMETROS_DO_FILTRO}}


# Função Objetivo: O pedaço do texto do total ("12 anúncios com essa busca e esses filtros") que fala da busca e dos filtros do Hub; '' quando não há nenhum dos dois.
def complemento_do_total(tem_busca, tem_filtros):
    if tem_busca and tem_filtros:
        return ' com essa busca e esses filtros'
    return ' com essa busca' if tem_busca else (' com esses filtros' if tem_filtros else '')


# Função Objetivo: As NOTAS dos filtros do Hub (frases curtas que a lista mostra logo abaixo dos chips dos filtros ativos, e não na caixa de avisos sobre os dados): o que os filtros mudam na lista (só as linhas, não os
# números), que a caixa de avisos conta a mesma base e, no Envios Full, que a logística escolhida no Fora do Full não vale ali. `gran` = sku | mlb | codigo; `unidade_plural` = o que a linha é ("produtos", "anúncios", "Códigos ML").
def notas_dos_filtros(comuns, gran, unidade_plural):
    notas = []
    if tem_filtro_ativo(comuns['filtros_do_mundo']):
        if gran == 'mlb':
            nota = 'Só aparecem os anúncios que passam nos filtros (o mesmo critério da tela Anúncios — Mercado Livre).'
        else:
            nota = (f'Só aparecem os {unidade_plural} com pelo menos um anúncio que passa nos filtros (o mesmo critério da tela Anúncios — Mercado Livre). '
                    f'Os números de cada linha continuam sendo os do item inteiro, não só dos anúncios que passaram.')
        notas.append(nota)
        notas.append('A caixa de avisos sobre os dados também segue esses filtros (só a cobertura das vendas é da conta toda).')
    if comuns['mundo'] == 'full' and comuns['filtros']['tipos_logisticos']:
        notas.append('O filtro de Logística escolhido em "Fora do Full" não vale aqui: todo anúncio do Envios Full é FULL. Ele continua guardado e volta a valer no Fora do Full.')
    return notas
