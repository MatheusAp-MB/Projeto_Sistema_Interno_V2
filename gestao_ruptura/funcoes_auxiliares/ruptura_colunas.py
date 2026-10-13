# gestao_ruptura/funcoes_auxiliares/ruptura_colunas.py
#
# Função Objetivo: O DONO ÚNICO das COLUNAS das listas da tela "Previsão de Ruptura de estoque" (13/10/2026): como cada coluna se chama, qual a unidade dela, em que grupo fica, qual a largura, qual valor ordena
# a lista e em que sentido a primeira batida no título ordena. Daqui saem também o CABEÇALHO pronto (a faixa de grupos e os títulos clicáveis, com a seta do estado) e a ORDENAÇÃO. A lista do Full (ruptura_lista.py)
# e a do Fora do Full (ruptura_lista_fora.py) só dizem QUAIS colunas têm; os templates (parciais/estrutura_parcial_tabela_cabecalho.html e as duas parciais de células) só DESENHAM o que sai daqui, na MESMA ordem.
#
# REGRAS DO MATHEUS que moram aqui (mockup aprovado em 13/10/2026: "pode aplicar todos os ciclos, o mockup tá aprovado"):
#   - UMA COLUNA = UM DADO, com o nome e a unidade no cabeçalho ("Estoque Full" / "un"), para a tabela se explicar sozinha. Informações parecidas ficam juntas, em GRUPOS (Identificação, Anúncios e dados, Estoque e vendas,
#     Previsão de ruptura, Reposição e, só com a chave "Comparar com o Mercado Livre" ligada, os dois TRIOS de comparação: "Comparação · Urgência" e "Comparação · Quantidade").
#   - COMPARAR = UM TRIO POR COISA COMPARADA, lado a lado: COLUNA A | COLUNA B | Comparação entre A e B (decisão do Matheus, 13/10/2026: "ao habilitar a comparação as colunas comparadas deveriam ficar claramente destacadas e uma ao lado
#     da outra"). Hoje são dois: a urgência (Sistema | Mercado Livre | Iguais ou Divergem) e a quantidade a enviar (Sistema | Mercado Livre | quem sugere mais). A coluna do Sistema vem para dentro do trio (sai do grupo dela), para não repetir o dado.
#   - A ORDENAÇÃO é o clique no título da coluna (não há mais o seletor "Ordenar por"): a seta mostra o estado (sem seta cinza = não ordena por ela; seta para cima = crescente; para baixo = decrescente) e o texto
#     "Ordenado por <coluna> · <sentido>" diz em palavras. Clicar na coluna ativa inverte o sentido. A primeira batida numa coluna ordena no sentido que ajuda a agir (o que mais vende primeiro, o mais urgente primeiro).
#   - Quem não tem o valor (ex.: sem ritmo, sem estoque lido) vai SEMPRE para o fim, nos dois sentidos ("ausente não é zero"): nunca fica no topo por ser zero.
#
# * [EXPLICAÇÃO] → A coluna é um dicionário (ver `coluna`). `valor(linha)` devolve o que ordena (número ou texto; None = sem valor) e `desempate(linha)` uma tupla que desempata ANTES do nome (sempre crescente). O empate final é sempre o nome
#                  do item (A–Z), nos dois sentidos, para a ordem nunca "pular" de um carregamento para outro. A coluna sem `valor` (ex.: o botão do gráfico, ou o "Estoque fora" que ainda não tem fonte) não ordena e não tem seta.
# * [EXPLICAÇÃO] → A largura é em px e fica aqui, junto da coluna, porque a ORDEM e as LARGURAS da grade (cabeçalho e linhas usam a mesma) têm de andar juntas: o template recebe a grade pronta (`grade`) e a largura mínima da tabela
#                  (`largura_minima`, já como expressão calc()) e as aplica como variáveis CSS. As larguras foram MEDIDAS (13/10/2026) com as fontes reais do sistema (Open Sans): cada uma comporta o título numa linha só (nome + seta),
#                  a unidade e o maior conteúdo da coluna, com uns 4px de folga. A coluna do item é a única que estica (`flexivel`); a tabela rola para o lado dentro da própria caixa quando a janela é estreita, e a coluna do item
#                  fica parada à esquerda.

SENTIDOS = ('asc', 'desc')
OPOSTO = {'asc': 'desc', 'desc': 'asc'}
LARGURA_DA_ACAO = 58
LARGURA_MINIMA_DO_ITEM = 280


# Função Objetivo: Define UMA coluna. `unidade` é a linha pequena do cabeçalho; `nome` é como a coluna aparece no texto "Ordenado por ..." (quando é diferente do rótulo, ex.: "Enviar (Sistema)"); `valor`/`desempate` ver acima;
# `primeiro` é o sentido da primeira batida ('asc' | 'desc'); `textos` diz em palavras cada sentido; `alinhar` é 'esq', 'dir' ou 'centro' (número à direita, texto à esquerda); `resultado` = a coluna "Comparação" de um TRIO (A | B | Comparação entre A e B): ganha um destaque a mais.
def coluna(chave, rotulo, unidade, largura, dica='', alinhar='dir', valor=None, desempate=None, primeiro='asc', textos=('menor → maior', 'maior → menor'), nome=None, flexivel=False, resultado=False):
    return {'chave': chave, 'rotulo': rotulo, 'unidade': unidade, 'largura': largura, 'dica': dica, 'alinhar': alinhar, 'valor': valor, 'desempate': desempate, 'primeiro': primeiro, 'textos': textos,
            'nome': nome or rotulo, 'flexivel': flexivel, 'resultado': resultado}


# Função Objetivo: Define um GRUPO de colunas (a faixa de cima do cabeçalho). `ml` = o grupo do Mercado Livre (roxo): só existe com a chave "Comparar com o Mercado Livre" ligada.
def grupo(chave, rotulo, colunas, ml=False):
    for c in colunas:
        c['ml'] = ml
    return {'chave': chave, 'rotulo': rotulo, 'colunas': colunas, 'ml': ml}


# Função Objetivo: A última coluna de toda tabela: o botão (ícone de gráfico) que abre o gráfico e o diagnóstico do item, o mesmo destino do nome. Não ordena; o rótulo só existe para quem usa leitor de tela.
def coluna_do_grafico():
    return coluna('acao', 'Gráfico e diagnóstico', '', LARGURA_DA_ACAO, 'Abrir o gráfico e o diagnóstico do item', alinhar='centro')


# Função Objetivo: Todas as colunas, na ordem em que aparecem (de todos os grupos).
def todas_as_colunas(grupos):
    return [c for g in grupos for c in g['colunas']]


# Função Objetivo: Qual coluna ordena a lista e em que sentido, a partir da URL (`ord` = chave da coluna, `sentido` = asc | desc). Valor inválido, coluna que não ordena (ou que não existe agora, ex.: a do Mercado Livre
# com a chave desligada, ou a de outro mundo) volta ao padrão, com o sentido da primeira batida dela. Sem `sentido` vale o da primeira batida da coluna pedida. Devolve (coluna, sentido).
# * [EXPLICAÇÃO] → O `sentido` só vale junto de um `ord` válido: o endereço que leva `sentido` leva também `ord` (a lista do outro mundo não herda o sentido de uma coluna que ela não tem).
def escolher_ordem(parametros, colunas, padrao):
    ordenaveis = {c['chave']: c for c in colunas if c['valor'] is not None}
    pedida = ordenaveis.get((parametros.get('ord') or '').strip())
    if pedida is None:
        return ordenaveis[padrao], ordenaveis[padrao]['primeiro']
    sentido = (parametros.get('sentido') or '').strip()
    return pedida, (sentido if sentido in SENTIDOS else pedida['primeiro'])


# Função Objetivo: Põe as linhas na ordem da coluna e do sentido. Quem não tem valor vai para o fim (por `desempate` e depois pelo nome); o empate entre os que têm valor é `desempate` e depois o nome, sempre A–Z.
# * [EXPLICAÇÃO] → Duas ordenações seguidas (a de desempate primeiro e a do valor depois): a do Python é ESTÁVEL, inclusive com reverse=True, então o desempate vale também no sentido decrescente.
def ordenar(linhas, escolhida, sentido):
    valor = escolhida['valor']
    desempate = escolhida['desempate'] or (lambda linha: ())

    def para_empate(linha):
        return desempate(linha) + (linha['titulo_ordem'],)

    com_valor = [linha for linha in linhas if valor(linha) is not None]
    sem_valor = sorted((linha for linha in linhas if valor(linha) is None), key=para_empate)
    com_valor.sort(key=para_empate)
    com_valor.sort(key=valor, reverse=sentido == 'desc')
    return com_valor + sem_valor


# Função Objetivo: O cabeçalho pronto para o template: a faixa de grupos, os títulos (cada um com o endereço da batida e a seta do estado), a grade (as larguras, na ordem), a largura mínima da tabela e o texto "Ordenado por".
# * [EXPLICAÇÃO] → Cada largura sai como `calc(<largura>px - var(--rup-recuo, 0px))`: a largura é a da faixa FOLGADA (janela de 2000px ou mais). Na faixa COMPACTA (janela menor que 2000px: o PC do escritório, 1600x900 ou 1366x768, e também o Full HD com a barra lateral aberta) o CSS troca o respiro lateral
#                  de cada célula de 10px para 6px (--rup-pad) e põe --rup-recuo = 8px, que tira esses 2 x 4px de cada coluna: a tabela encolhe ~8px por coluna sem as células ficarem apertadas.
# `url_da_ordem(chave, sentido)` é o dono dos endereços da lista (devolve o endereço que ordena por essa coluna nesse sentido).
# * [EXPLICAÇÃO] → `seta`: 'neutra' (a lista não está ordenada por esta coluna), 'cima' (crescente) ou 'baixo' (decrescente); `aria` é o aria-sort. O 1º grupo e o 1º campo de cada grupo ganham a divisória (`divisoria`) que separa os grupos.
def cabecalho(grupos, escolhida, sentido, url_da_ordem):
    faixa, colunas, larguras, minima, quantas = [], [], [], 0, 0
    for i, g in enumerate(grupos):
        faixa.append({'chave': g['chave'], 'rotulo': g['rotulo'], 'n': len(g['colunas']), 'ml': g['ml'], 'divisoria': i > 0, 'primeiro': i == 0})
        for j, c in enumerate(g['colunas']):
            ordenavel = c['valor'] is not None
            ativa = ordenavel and c['chave'] == escolhida['chave']
            proximo = OPOSTO[sentido] if ativa else c['primeiro']
            colunas.append({
                'chave': c['chave'], 'rotulo': c['rotulo'], 'unidade': c['unidade'], 'dica': c['dica'], 'alinhar': c['alinhar'], 'ml': c['ml'], 'resultado': c['resultado'], 'divisoria': i > 0 and j == 0, 'item': c['flexivel'],
                'ordenavel': ordenavel, 'ativa': ativa, 'seta': ('cima' if sentido == 'asc' else 'baixo') if ativa else 'neutra',
                'aria': ('ascending' if sentido == 'asc' else 'descending') if ativa else 'none',
                'url': url_da_ordem(c['chave'], proximo) if ordenavel else '',
                'dica_da_ordem': f'Ordenar por {c["nome"]} ({c["textos"][0 if proximo == "asc" else 1]})' if ordenavel else '',
            })
            recuada = f'calc({c["largura"]}px - var(--rup-recuo, 0px))'
            larguras.append(f'minmax({recuada}, 1fr)' if c['flexivel'] else recuada)
            minima += c['largura']
            quantas += 1
    texto = f'{escolhida["nome"]} · {escolhida["textos"][0 if sentido == "asc" else 1]}'
    return {'grupos': faixa, 'colunas': colunas, 'grade': ' '.join(larguras), 'largura_minima': f'calc({minima}px - {quantas} * var(--rup-recuo, 0px))', 'ordenado_por': texto}
