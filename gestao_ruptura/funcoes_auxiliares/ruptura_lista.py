# gestao_ruptura/funcoes_auxiliares/ruptura_lista.py
#
# Função Objetivo: A LISTA da tela "Previsão de Ruptura de estoque" (12/10/2026): o que aparece quando nenhum item está aberto. Uma linha por Produto (SKU), por Anúncio (MLB) ou por Código ML
# (decisão do Matheus: "a tela não pode fazer apenas por SKU"), com o estoque do Full, o ritmo de vendas do Full, a COBERTURA em dias, a data da ruptura, até quando enviar e o nível,
# com a ordem escolhida no título das colunas (a lista abre pelo "Enviar até": o que precisa ser enviado primeiro vem primeiro). Clicar no nome da linha (ou no botão da última coluna) abre a curva do item (ruptura_pagina.py).
# LÊ SÓ DO BANCO: nada aqui chama o Mercado Livre nem o ERP.
#
# REGRAS DO MATHEUS que moram aqui (as contas em si estão em ruptura_calculo.py; a regra do estoque considerado, em ruptura_estoque.py):
#   - O ESTOQUE da lista é o do FULL, lido da última consulta salva de cada Código ML (a mesma da tela "Estoque no Full"). O de um SKU ou de um MLB é a soma dos Códigos dele.
#   - O RITMO da lista é só o das vendas que SAÍRAM DO FULL (o estoque é o do Full): unidades dos dias completos ÷ nº de dias completos, com as mesmas regras da tela de Vendas.
#     O período é o "ritmo dos últimos N dias" escolhido na tela. Venda cancelada não conta; "ausente não é zero".
#   - O prazo até vender, os dias para chegar antes da ruptura e a folga são UM só para a lista inteira (campos no topo); no detalhe de cada item dá para testar outros. Os níveis (ruptura, crítico, baixo, alto) são os
#     PROVISÓRIOS de ruptura_calculo.py. Esta lista é só do mundo ENVIOS FULL (a do Fora do Full é a de ruptura_lista_fora.py: outro mundo, outra lista).
#   - Item sem consulta de estoque NÃO vira "estoque zero": fica em "Sem estoque lido" ("ausente não é zero"). Item com só parte dos Códigos lidos fica marcado "Estoque parcial".
#   - O SISTEMA É A BASE e o MERCADO LIVRE É A COMPARAÇÃO (decisão do Matheus, 13/10/2026, ao aprovar o mockup da tabela): o "Enviar até", o nível e a quantidade da linha são os do SISTEMA (ruptura_calculo: urgencia_do_sistema e
#     sugestao_do_sistema). A chave "Comparar com o Mercado Livre" (`comparar=1` na URL) acrescenta DOIS TRIOS roxos de colunas, lado a lado, cada um no formato COLUNA A | COLUNA B | Comparação (decisão do Matheus, 13/10/2026): URGÊNCIA = Sistema | Mercado Livre (lida da consulta de reposição salva:
#     ruptura_estoque.resumir_ml) | Comparação (Iguais | Divergem | Sem comparação); QUANTIDADE = Sistema | Mercado Livre | Comparação (quem sugere mais e quanto, ou Iguais). O filtro "Divergem" (à parte dos cartões de situação, combina com eles) mostra os itens em que as duas urgências estão em faixas diferentes e liga a
#     chave sozinho (sem comparar não há o que divergir). Item sem número do ML NUNCA vira urgência ou quantidade zero: fica "Sem dado do ML" / "sem número".
#   - UMA COLUNA = UM DADO e a ORDEM é o clique no título da coluna (ruptura_colunas.py é o dono das colunas, do cabeçalho e da ordenação; aqui só se diz o valor que ordena cada coluna e o texto de cada célula). Quem não tem o dado vai
#     sempre para o fim. O faturamento, os selos do anúncio e a conta do Sistema em palavras NÃO estão na lista (o alerta do depósito (ERP) fica no balão da quantidade).
#   - O STATUS DO ANÚNCIO (ativo, pausado...) aparece na linha e PAUSADO TEM O MESMO PESO DE ATIVO (decisão do Matheus, 13/10/2026: alguns anúncios só estão pausados por falta de estoque e a pessoa precisa ver isso para corrigir).
#
# * [EXPLICAÇÃO] → DE ONDE VEM CADA GRANULARIDADE: o estoque do Full mora no Código ML. Um MLB pode ter mais de um Código (variações) e um Código pode ser usado por mais de um MLB:
#                  nesse caso o estoque é o MESMO para os dois, e a cobertura do MLB (que olha só as vendas dele) pode ficar maior do que a real. A linha ganha o selo "Estoque compartilhado".
#                  Quem entra na lista é decidido pelo ANÚNCIO, não pelo Código ML: ver "QUEM É DO FULL" (anuncio_e_do_full), a mesma regra do filtro FULL do Hub de Anúncios.
# * [EXPLICAÇÃO] → COMO FICA RÁPIDA (~1000 SKUs): as vendas do Full do período entram numa consulta só (lista_vendas_ml.unidades_do_full_por_dia) e o estoque, em 2 consultas
#                  (full_estoque_ml.estoque_full_dos_codigos). O "A caminho" (consulta de reposição, a parte pesada) só é lido para as linhas da PÁGINA, a não ser que a opção "Considerar as
#                  unidades a caminho" esteja marcada: aí ele entra na cobertura (muda nível e ordem) e é lido para TODOS os Códigos, em lotes de LOTE_DO_A_CAMINHO (uma consulta por lote, nunca por
#                  Código). Textos e endereços só são montados para a página mostrada. Nenhuma consulta por SKU, por MLB ou por Código.
# * [EXPLICAÇÃO] → O que o ML recomenda (urgência e sugestão) também vem da consulta de reposição, mas o RESUMO de cada consulta é guardado no cache pelo id dela (full_estoque_ml.ml_dos_codigos): depois da
#                  primeira leitura só a consulta NOVA é lida de novo. Ele é lido para TODOS os Códigos porque a comparação, o filtro "Divergem" e a faixa Situação olham a lista inteira.

import unicodedata
from collections import Counter
from datetime import timedelta

from django.urls import reverse

from gestao_full.funcoes_auxiliares.full_estoque_ml import HORAS_PARA_DESATUALIZADO, a_caminho_dos_codigos, estoque_do_erp, estoque_full_dos_codigos, ml_dos_codigos
from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares import ruptura_colunas as col
from gestao_ruptura.funcoes_auxiliares import ruptura_estoque as full
from gestao_ruptura.funcoes_auxiliares.ruptura_filtros import notas_dos_filtros, mlbs_permitidos, painel_do_mundo, passa_no_filtro, sem_filtros_na_url
from gestao_ruptura.funcoes_auxiliares.ruptura_parametros import campos_escondidos, para_url
from gestao_ruptura.funcoes_auxiliares.ruptura_avisos import aviso, aviso_de_contagem
from gestao_ruptura.funcoes_auxiliares.ruptura_situacao import CHAVES_DE_NIVEL, contar_consultas, indicador_de_estoque, indicador_de_vendas, montar_situacao
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import aviso_do_deposito, data, data_curta, data_do_ml, em_dias, frescor, inteiro, pct as pct_texto, plural, comparacao_das_quantidades, porque_da_urgencia_do_sistema, quantidade_do_ml, un_dia
from gestao_vendas.funcoes_auxiliares.lista_vendas_ml import cobertura_do_item, unidades_do_full_por_dia
from mercado_livre.funcoes_auxiliares.badges import BADGES_STATUS
from mercado_livre.funcoes_auxiliares.logistica_do_anuncio import logistica_e_de_fora_do_full, logistica_e_do_full
from gestao_vendas.funcoes_auxiliares.vendas_ml import data_hora, estados_dos_dias, mlbs_da_cobertura, numero, url_da_tela

# (chave na URL, rótulo do botão, ajuda no "?", o que a linha é no plural, no singular)
GRANULARIDADES = [
    ('sku', 'Produto (SKU)', 'Cada linha é um produto (SKU) e junta todos os Códigos ML dele: o estoque é a soma do que está no Full e o ritmo é o de todas as vendas que saíram do Full.', 'produtos', 'produto'),
    ('mlb', 'Anúncio (MLB)', 'Cada linha é um anúncio (MLB). O estoque é o dos Códigos ML dele; se o Código é compartilhado com outro anúncio, o selo "Estoque compartilhado" avisa (o estoque é o mesmo para os dois).', 'anúncios', 'anúncio'),
    ('codigo', 'Código ML', 'Cada linha é um Código ML: o estoque exato dele no Full e as vendas que saíram dele. É o jeito mais preciso de olhar a ruptura.', 'Códigos ML', 'Código ML'),
]
GRANULARIDADE_PADRAO = 'sku'
# Os cartões de situação (nome, apoio, grupo, contagem e explicação) e os indicadores de dados são do dono único ruptura_situacao.py. Cada cartão é também o filtro "nivel" da URL (clicar mostra só aquela situação).
# "Divergem" NÃO é uma situação: é o filtro à parte `diverge=1` (os itens em que a urgência do Mercado Livre e a do Sistema estão em faixas diferentes, ruptura_calculo.urgencias_divergem), que combina com qualquer cartão.
NIVEIS_VALIDOS = ('todos',) + CHAVES_DE_NIVEL


ORDEM_PADRAO = 'enviar_ate'   # a lista abre pela coluna "Enviar até", do mais urgente para o mais tarde (a ordem é o clique no título da coluna: ruptura_colunas.py)
# a ordem do nível: quanto menor o número, mais grave (o que não tem nível calculado vem depois, "sem estoque lido" por último); também desempata a coluna "Enviar até"
URGENCIA = {'ruptura': 0, 'critico': 1, 'baixo': 2, 'sem_nivel': 3, 'alto': 4, 'sem_previsao': 5, 'sem_estoque': 6}
RANK_DA_URGENCIA_ML = {u: i for i, u in enumerate(calc.URGENCIAS_DO_ML)}   # URGENT 0 ... EXCEDENT 5 (a ordem das colunas de urgência)
POR_PAGINA_OPCOES = (10, 25, 50, 100)
POR_PAGINA_PADRAO = 25
BARRA_EM_LEADS = 3   # a barra de cobertura enche quando o estoque dura 3 vezes o prazo (a marca na barra é o próprio prazo, a 1/3)
FIM_DO_TEMPO = 1e12
LOTE_DO_A_CAMINHO = 150   # Códigos por leitura da reposição (a parte grande da consulta salva): limita a memória quando o "a caminho" é lido para a lista inteira


# ==================================================== pequenas ajudas ====================================================

def _sem_acento(texto):
    return unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode('ascii').lower()


def _escolher(parametros, nome, validos, padrao):
    valor = (parametros.get(nome) or '').strip()
    return valor if valor in validos else padrao


# Função Objetivo: Lê o "A caminho" de TODOS os Códigos ML lidos da lista (só quando a opção "Contar o que está a caminho" está marcada: aí o número entra na cobertura de cada linha, não só
# das da página). Faz uma leitura por lote de LOTE_DO_A_CAMINHO Códigos (a_caminho_dos_codigos preenche os cartões na hora); Código sem leitura do estoque fica de fora.
def _ler_a_caminho_de_todos(cartoes):
    codigos = sorted(c for c, cartao in cartoes.items() if cartao['estado'] == 'ok')
    for ini in range(0, len(codigos), LOTE_DO_A_CAMINHO):
        a_caminho_dos_codigos({c: cartoes[c] for c in codigos[ini:ini + LOTE_DO_A_CAMINHO]})


# Função Objetivo: Os números de PÁGINAS da paginação (a primeira, a última e as vizinhas da atual); None = "…" entre dois saltos. (Mesma regra da lista de Vendas.)
def _janela_de_paginas(atual, total):
    paginas = sorted({1, total} | {p for p in range(atual - 2, atual + 3) if 1 <= p <= total})
    saida = []
    for p in paginas:
        if saida and p - saida[-1] > 1:
            saida.append(None)
        saida.append(p)
    return saida


# ==================================================== quem é "do Full" ====================================================

# * [EXPLICAÇÃO] → QUEM É "DO FULL" (decisão do Matheus, 12/10/2026: o Hub mostrava 887 anúncios no Full e a Previsão 1.290, "deveriam bater, é o mesmo filtro"): a MESMA regra do filtro FULL da tela Anúncios — Mercado Livre
#                  (mercado_livre/funcoes_auxiliares/classificacao_catalogo.py). O anúncio é do Full quando a LOGÍSTICA dele é FULL (a pergunta tem UM dono: mercado_livre/funcoes_auxiliares/logistica_do_anuncio.py, que também a
#                  tela de Vendas usa para a origem das vendas; aqui não se escreve "fulfillment" nem se compara logística) e ele NÃO é um
#                  anúncio "fóssil" de migração de variações (o Hub sempre os ignora). Ter Código ML NÃO decide: o Código continua gravado no anúncio depois que ele sai do Full, então usá-lo como critério trazia anúncios
#                  que já não são do Full (e deixava a conta diferente da do Hub). O Código ML serve para ler o ESTOQUE. As duas listas (Envios Full e Fora do Full) usam estas funções: nenhuma tem regra própria.
# * [EXPLICAÇÃO] → QUEM É "FORA DO FULL" (decisão do Matheus, 12/10/2026: o Hub com as 6 logísticas que não são FULL mostrava 4.634 anúncios e a Previsão 4.676, "os números não batem"; conferido no banco real: 4.634 = 4.634): é o anúncio
#                  com logística preenchida e diferente de FULL (hoje: Coleta, Agência, Flex Puro, Legado, Correios, Por nossa conta, as opções do filtro "Logística" do Hub), sem os fósseis. Quem não tem logística no banco não é
#                  de nenhum dos dois mundos (o Hub também o ignora quando se filtra por logística): as listas contam esses casos num aviso, para a conta fechar.


# Função Objetivo: O anúncio (um item de cad['anuncios'], de lista_vendas_ml._carregar_cadastro) é um "fóssil" de migração de variações? O Hub os ignora sempre: aqui eles não são nem do Full nem de fora do Full.
def anuncio_fossil(anuncio):
    return bool((anuncio or {}).get('fossil'))


# Função Objetivo: O anúncio é do Full? Logística "fulfillment" e não fóssil, o mesmo critério do filtro FULL do Hub. Anúncio sem registro de tipo (sem logística conhecida) não é do Full.
def anuncio_e_do_full(anuncio):
    tipo = (anuncio or {}).get('tipo')
    return bool(tipo) and logistica_e_do_full(tipo.get('tipo_logistico')) and not anuncio_fossil(anuncio)


# Função Objetivo: O anúncio é de fora do Full? Logística preenchida e diferente de FULL e não fóssil (hoje, o mesmo que os 6 filtros de logística do Hub). Anúncio sem registro de tipo ou sem logística não é de fora do Full.
def anuncio_e_de_fora_do_full(anuncio):
    tipo = (anuncio or {}).get('tipo')
    return bool(tipo) and logistica_e_de_fora_do_full(tipo.get('tipo_logistico')) and not anuncio_fossil(anuncio)


# Função Objetivo: O aviso das listas "Produto (SKU)" (as duas, com o mesmo texto e a mesma conta): quantos anúncios do mundo (`do_mundo` = anuncio_e_do_full ou anuncio_e_de_fora_do_full) NÃO têm Produto vinculado no ERP
# e por isso não aparecem em nenhuma linha de Produto. Devolve o aviso pronto ou None quando nenhum anúncio está nessa situação.
# * [EXPLICAÇÃO] → A lista "Produto (SKU)" agrupa pelo SKU do Produto (cadastro em lote: `candidatos`, só anúncios com variação ligada a um Produto). O Hub agrupa também pelo SKU do Mercado Livre ou pelo próprio MLB quando não há Produto,
#                  e conta cada um desses como "SKU": por isso o número de SKUs de lá é maior. Esses anúncios continuam na lista "Anúncio (MLB)", que bate com o Hub (decisão do Matheus, 12/10/2026: avisar).
#                  `permitidos` (ruptura_filtros.mlbs_permitidos; None = sem filtro): com filtros do Hub ativos conta só os anúncios que passam neles, como o Hub.
def aviso_anuncios_sem_produto(dados, do_mundo, permitidos=None):
    cad = dados['cad']
    n = sum(1 for mlb, a in cad['anuncios'].items() if do_mundo(a) and (permitidos is None or mlb in permitidos) and not cad['candidatos'].get(mlb))
    if not n:
        return None
    um = n == 1
    return aviso_de_contagem('info', n, 'anúncio não tem Produto vinculado no ERP', 'anúncios não têm Produto vinculado no ERP',
                             f'{"Não aparece" if um else "Não aparecem"} em "Produto (SKU)" e {"fica" if um else "ficam"} só em "Anúncio (MLB)". '
                             f'O Hub de Anúncios {"o conta" if um else "conta cada um deles"} como um "SKU" (pelo SKU do Mercado Livre ou pelo MLB), por isso o número de SKUs de lá é maior.')


# ==================================================== as entidades de cada granularidade ====================================================

# Função Objetivo: Uma entidade da lista (o que a linha representa), do jeito que as três granularidades usam: chave, sku (para abrir o detalhe), título, foto, `id_txt` (a linha de identificadores embaixo do título:
# "SKU", "MLB · SKU" ou "Código ML · SKU", igual à unidade do cabeçalho da coluna Item), os Códigos ML dela, texto de busca, no MLB e no SKU a lista de quem divide estoque com ela, os MLBs dela (a situação dos anúncios)
# e `mlbs_cob`: os MLBs que a COBERTURA das vendas exige para ela (vendas_ml.mlbs_da_cobertura: os mesmos do gráfico do detalhe), com os quais se conta quantos dias completos a linha tem.
def _entidade(chave, sku, titulo, subtitulo, marca, foto, id_txt, codigos, busca, compartilha=(), mlbs=(), mlbs_cob=()):
    return {'chave': chave, 'sku': sku, 'titulo': titulo, 'subtitulo': subtitulo, 'marca': marca, 'foto': foto, 'id_txt': id_txt, 'codigos': codigos,
            'busca': _sem_acento(' '.join(str(p) for p in busca if p)), 'titulo_ordem': _sem_acento(titulo), 'compartilha': list(compartilha), 'mlbs': sorted(mlbs), 'mlbs_cob': sorted(mlbs_cob)}


# Função Objetivo: O estado de cada dia da janela da lista (ok = dia completo | parcial | sem_dado) PARA UMA LINHA, e quando foi a coleta mais recente que a cobre: a cobertura dos MLBs dela (e_['mlbs_cob']) sobre as coletas já lidas
# (lista_vendas_ml.cobertura_do_item). É a MESMA conta do gráfico do detalhe (vendas_ml.unidades_por_dia): o mesmo item mostra o mesmo número de dias completos nos dois lugares. As duas listas (Full e Fora do Full) chamam esta função.
# * [EXPLICAÇÃO] → Só o CABEÇALHO ("X/Y dias completos na conta toda") continua olhando a conta toda: ele diz como está a coleta geral; o ritmo de cada linha olha a cobertura dela.
def cobertura_da_linha(e, dados, ctx):
    cob = cobertura_do_item(dados, e['mlbs_cob'])
    return {'estados': estados_dos_dias(cob, ctx['jan_todos']), 'coletado_em': max(cob.values()) if cob else None}


# Função Objetivo: O texto de identificadores da linha: o primeiro identificador (SKU, MLB ou Código ML) e, depois do "·", o SKU (com "+N" quando o item tem mais de um; "sem SKU" quando não tem nenhum).
def _id_txt(primeiro, skus):
    if not skus:
        return f'{primeiro} · sem SKU' if primeiro else 'sem SKU'
    sku = skus[0] + (f' +{len(skus) - 1}' if len(skus) > 1 else '')
    return f'{primeiro} · {sku}' if primeiro else sku


# Função Objetivo: Monta as entidades da granularidade escolhida a partir do cadastro em lote (lista_vendas_ml._carregar_cadastro). Só entra quem é do Full (anuncio_e_do_full): o produto (SKU) com pelo menos um anúncio do
# Full, o anúncio (MLB) do Full e o Código ML usado por algum anúncio do Full.
# * [EXPLICAÇÃO] → O ESTOQUE continua sendo a soma dos Códigos ML de verdade (todos os do SKU, ou todos os do MLB), tenha o anúncio do Código saído do Full ou não: o que está no depósito do Full existe e conta.
#                  Anúncio do Full que ainda não tem Código ML no banco entra mesmo assim (é do Full pelo critério do Hub), sem estoque lido: a linha diz "sem Código ML" e cai em "Sem estoque lido".
# * [EXPLICAÇÃO] → `permitidos` = os MLBs que os filtros do Hub deixam passar (ruptura_filtros.mlbs_permitidos; None = sem filtro). A linha só aparece se algum anúncio DELA que é do Full passa nos filtros; os números dela
#                  (estoque, vendas, ritmo) seguem sendo os da entidade inteira, não só dos anúncios que passaram.
def _entidades(gran, dados, permitidos=None):
    cad, produtos = dados['cad'], dados['produtos']
    codigos_cad, anuncios = cad['codigos'], cad['anuncios']
    do_full = {mlb for mlb, a in anuncios.items() if anuncio_e_do_full(a)}
    entidades = []
    if gran == 'sku':
        for sku, info in cad['por_sku'].items():
            mlbs = sorted(m for m in info['mlbs'] if m in do_full)
            if not mlbs or not passa_no_filtro(mlbs, permitidos):
                continue
            codigos = {c for m in info['mlbs'].values() for _, c in m['variacoes'] if c}
            produto = produtos.get(sku) or {}
            outros = sorted({s for c in codigos for s in codigos_cad[c]['skus'] if s != sku})
            entidades.append(_entidade(sku, sku, produto.get('titulo') or '(SKU fora do cadastro de Produto)', '', produto.get('marca', ''), produto.get('imagem', ''), sku, codigos,
                                       [sku, produto.get('titulo'), produto.get('marca'), produto.get('ean')] + mlbs + sorted(codigos), outros, mlbs, mlbs_da_cobertura('sku', sku, info['mlbs'])))
    elif gran == 'mlb':
        for mlb, anuncio in anuncios.items():
            if mlb not in do_full or not passa_no_filtro([mlb], permitidos):
                continue
            codigos = {c for _, c in anuncio['variacoes'] if c}
            skus = sorted(cad['candidatos'].get(mlb, {}))
            sku = skus[0] if skus else ''
            produto = produtos.get(sku) or {}
            outros_mlbs = sorted({m for c in codigos for m in codigos_cad[c]['mlbs'] if m != mlb})
            entidades.append(_entidade(mlb, sku, anuncio['titulo'] or produto.get('titulo') or 'Título indisponível', '', produto.get('marca', ''), anuncio['imagem'] or produto.get('imagem', ''),
                                       _id_txt(mlb, skus), codigos, [mlb, anuncio['titulo'], sku, produto.get('marca'), produto.get('ean')] + sorted(codigos), outros_mlbs, [mlb], mlbs_da_cobertura('mlb', mlb, {})))
    else:
        for codigo, dados_do_codigo in codigos_cad.items():
            if not (dados_do_codigo['mlbs'] & do_full) or not passa_no_filtro(dados_do_codigo['mlbs'] & do_full, permitidos):
                continue
            skus = sorted(dados_do_codigo['skus'])
            sku = skus[0] if skus else ''
            produto = produtos.get(sku) or {}
            mlbs = sorted(dados_do_codigo['mlbs'])
            foto = next((anuncios[m]['imagem'] for m in mlbs if anuncios.get(m, {}).get('imagem')), '') or produto.get('imagem', '')
            entidades.append(_entidade(codigo, sku, produto.get('titulo') or codigo, '', produto.get('marca', ''), foto, _id_txt(codigo, skus), {codigo},
                                       [codigo, produto.get('titulo'), sku, produto.get('marca'), produto.get('ean')] + mlbs, skus[1:], [m for m in mlbs if m in do_full],
                                       mlbs_da_cobertura('codigo', codigo, {m: anuncios[m] for m in dados_do_codigo['mlbs'] if m in anuncios})))
    return entidades


# ==================================================== as colunas (a ordem delas, os nomes e o valor que ordena cada uma) ====================================================

# Função Objetivo: Os GRUPOS e as COLUNAS da lista do Full, na ordem em que aparecem (o dono de como uma coluna é feita é ruptura_colunas.py; aqui só se diz QUAIS colunas a lista tem, o que cada uma mostra e que valor da linha a ordena).
# `comparar` = a chave "Comparar com o Mercado Livre" está ligada: só então existem os dois trios roxos de comparação (urgência e quantidade). `caminho` = a opção "Contar o que está a caminho" (o número do Estoque Full passa a incluir o a caminho: o cabeçalho avisa).
# * [EXPLICAÇÃO] → Cada `valor` devolve o que ordena (número ou texto) ou None quando a linha NÃO TEM esse dado ("ausente não é zero": vai para o fim nos dois sentidos). Os valores são calculados em _calcular_linha, para a lista inteira,
#                  e só os TEXTOS são montados para a página mostrada (_apresentar). A ordem dos campos aqui é a ordem das células na tela (estrutura_parcial_celulas_full.html desenha uma célula por coluna, na ordem que sai daqui).
def _grupos(gran, dias, caminho, comparar):
    c = col.coluna
    unidade_do_item = {'sku': 'SKU', 'mlb': 'MLB · SKU', 'codigo': 'Código ML · SKU'}[gran]
    # a quantidade do Sistema: no grupo "Reposição" quando só há o Sistema ("Enviar" / "un · Sistema"); dentro do trio da quantidade com a comparação ligada ("Sistema" / "un")
    c_qtd = c('qtd', 'Sistema' if comparar else 'Enviar', 'un' if comparar else 'un · Sistema', 96 if comparar else 102, 'A quantidade que o Sistema sugere enviar: ritmo × os dias de folga (a nova ruptura vem esses dias depois).', nome='Enviar (Sistema)',
              valor=lambda l: l['qtd_ordem'], primeiro='desc', textos=('menor → maior', 'maior → menor'))
    reposicao = [
        c('enviar_ate', 'Enviar até', 'data', 104, 'A data recomendada para enviar: ruptura − prazo até vender − chegar antes. "Agora" = a data já passou ou é hoje.',
          valor=lambda l: l['enviar_ordem'], desempate=lambda l: (URGENCIA[l['cat']], l['dias_exatos'] if l['dias_exatos'] is not None else FIM_DO_TEMPO, -(l['media'] or 0)),
          textos=('mais urgente primeiro', 'mais tarde primeiro')),
        c('se_hoje', 'Se enviar hoje', 'chegada × ruptura', 134, 'O que acontece se o envio sair hoje: chega antes da ruptura (folga em dias), no dia dela ou depois (faltam dias).',
          alinhar='esq', valor=lambda l: l['se_ordem'], textos=('faltam mais dias primeiro', 'sobra mais folga primeiro')),
    ] + ([] if comparar else [c_qtd])
    grupos = [
        col.grupo('identificacao', 'Identificação', [
            c('item', 'Item', unidade_do_item, col.LARGURA_MINIMA_DO_ITEM, 'O item da linha (nome, foto e identificadores). O nome abre a curva de estoque do item.', alinhar='esq', valor=lambda l: l['titulo_ordem'],
              textos=('A → Z', 'Z → A'), flexivel=True),
        ]),
        col.grupo('anuncios', 'Anúncios e dados', [
            c('status', 'Anúncios', 'situação', 126, 'Situação dos anúncios do item no Mercado Livre (ativo, pausado...). Pausado tem o mesmo peso de ativo: alguns anúncios ficam pausados só por falta de estoque e dá para corrigir.',
              alinhar='esq', valor=lambda l: l['status_pausados'], textos=('sem pausados primeiro', 'mais pausados primeiro')),
            c('dados', 'Dados', 'leitura do estoque', 148, 'Se os números da linha merecem confiança: "Em dia" ou o aviso (sem leitura do estoque, estoque parcial, consulta antiga, Código ML compartilhado).',
              alinhar='esq', valor=lambda l: len(l['dados_avisos']), textos=('em dia primeiro', 'com aviso primeiro')),
            c('frescor', 'Atualizado', 'vendas · estoque', 156, 'Quão velho é o número da linha: até quando vão as vendas coletadas que cobrem o item e há quanto tempo foi a consulta de estoque mais antiga dos Códigos ML dele. '
              'Para atualizar, abra o item e clique em "Atualizar este item".', alinhar='esq'),
        ]),
        col.grupo('estoque', 'Estoque e vendas · hoje', [
            c('estoque', 'Estoque Full', 'un + a caminho' if caminho else 'un', 120, 'O estoque do Full: o da última consulta salva de cada Código ML do item (disponível + em transferência + em processo interno).' + (' Com a opção "Contar o que está a caminho" marcada, o número já inclui o a caminho.' if caminho else ''),
              valor=lambda l: l['estoque'], textos=('menor → maior', 'maior → menor')),
            c('caminho', 'A caminho', 'un', 104, 'Unidades já enviadas ao Full e ainda não recebidas (só informativo: é uma hipótese, não se sabe quando chegam).' + (' Está somado ao Estoque Full (opção marcada).' if caminho else ' Não entra na cobertura.'),
              valor=lambda l: l['caminho_ordem'], primeiro='desc', textos=('menor → maior', 'maior → menor')),
            c('vendas', 'Vendas', f'{dias} dias · un', 98, f'Unidades que saíram do Full nos dias completos dos últimos {dias} dias. É o volume que dá o ritmo.',
              valor=lambda l: l['vendas_ordem'], primeiro='desc', textos=('menos vendas primeiro', 'mais vendas primeiro')),
            c('ritmo', 'Ritmo', 'un/dia', 78, 'Média por dia das vendas que saíram do Full nos dias completos do período (unidades ÷ dias completos).',
              valor=lambda l: l['media'], primeiro='desc', textos=('menor → maior', 'maior → menor')),
            c('tendencia', 'Tendência', 'do ritmo', 104, 'Compara o ritmo dos últimos dias com o do período inteiro: acelerou, caiu ou estável. Só existe quando o período é maior que os últimos dias comparados.',
              alinhar='esq', valor=lambda l: l['tend_ordem'], primeiro='desc', textos=('caiu → acelerou', 'acelerou → caiu')),
        ]),
        col.grupo('previsao', 'Previsão de ruptura', [
            c('cobertura', 'Cobertura', 'dias', 106, 'Quantos dias o estoque dura neste ritmo (estoque ÷ ritmo). A marca na barra é o prazo até vender.',
              valor=lambda l: l['cob_ordem'], textos=('menos dias primeiro', 'mais dias primeiro')),
            c('ruptura', 'Ruptura em', 'data', 112, 'O dia em que o estoque acaba neste ritmo.',
              valor=lambda l: l['ruptura_ordem'], textos=('mais cedo primeiro', 'mais tarde primeiro')),
            c('nivel', 'Nível', 'do estoque', 116, 'A situação do estoque (ruptura, crítico, baixo, alto), pelas regras provisórias da faixa "Regras em uso".',
              alinhar='esq', valor=lambda l: l['nivel_ordem'], textos=('mais grave primeiro', 'menos grave primeiro')),
        ]),
        col.grupo('reposicao', 'Reposição · o que enviar', reposicao),
    ]
    if comparar:
        # * [EXPLICAÇÃO] → Cada coisa comparada é um TRIO, um do lado do outro: A (Sistema) | B (Mercado Livre) | Comparação entre A e B. A coluna da quantidade do Sistema ('qtd') muda de grupo: sai de "Reposição" e entra no trio da
        #                  quantidade, com o título "Sistema", para a mesma coluna não aparecer duas vezes (um dado, um lugar).
        grupos.append(col.grupo('cmp_urgencia', 'Comparação · Urgência', [
            c('urg_sistema', 'Sistema', 'urgência', 140, 'A urgência de envio pela regra do Sistema (a data de "Enviar até"): Urgente, Esta semana, Próxima semana, Em 2 semanas ou Sem urgência.', alinhar='esq', nome='Urgência do Sistema',
              valor=lambda l: l['urg_sistema_ordem'], textos=('mais urgente primeiro', 'menos urgente primeiro')),
            c('urg_ml', 'Mercado Livre', 'urgência', 156, 'A urgência que o Mercado Livre calcula, da última consulta de reposição salva. Sem consulta salva: "Sem dado do ML" (nunca zero).', alinhar='esq', nome='Urgência do ML',
              valor=lambda l: l['urg_ml_ordem'], textos=('mais urgente primeiro', 'menos urgente primeiro')),
            c('comparacao', 'Comparação', 'Sistema × ML', 130, 'As duas urgências estão na mesma faixa (Iguais) ou em faixas diferentes (Divergem)? Sem a leitura de um dos lados: Sem comparação.', alinhar='esq', nome='Comparação das urgências',
              valor=lambda l: l['comp_ordem'], textos=('divergentes primeiro', 'iguais primeiro'), resultado=True),
        ], ml=True))
        grupos.append(col.grupo('cmp_quantidade', 'Comparação · Quantidade a enviar', [
            c_qtd,
            c('qtd_ml', 'Mercado Livre', 'un', 132, 'A quantidade que o Mercado Livre sugere enviar (numa faixa vale o começo dela). Sem número do ML: "sem número" (nunca zero).', nome='Enviar (ML)',
              valor=lambda l: l['qtd_ml_ordem'], primeiro='desc', textos=('menor → maior', 'maior → menor')),
            c('qtd_comp', 'Comparação', 'quem sugere mais', 150, 'Quem sugere enviar mais e quanto a mais (ML +N un ou Sistema +N un), ou Iguais. Sem a quantidade de um dos lados: Sem comparação (nunca zero). Ordena pelo tamanho da diferença.', alinhar='esq',
              nome='Comparação das quantidades', valor=lambda l: l['qtd_comp_ordem'], primeiro='desc', textos=('menor diferença primeiro', 'maior diferença primeiro'), resultado=True),
        ], ml=True))
    grupos.append(col.grupo('detalhes', '', [col.coluna_do_grafico()]))
    return grupos


# ==================================================== o cálculo de cada linha (todas as linhas, sem texto) ====================================================

# Função Objetivo: A TENDÊNCIA de uma linha (as duas listas, Full e Fora do Full, usam esta função): compara o ritmo dos últimos `recente` dias com o do período e devolve {sentido: acelerou | caiu | estavel, pct} (ruptura_calculo.comparar_ritmos).
# None quando não dá para comparar: o período não é maior que os últimos dias comparados, não há ritmo, ou não houve nenhuma venda nos dois períodos. Só olha as VENDAS: não precisa de estoque.
def tendencia_do_ritmo(ritmo_r, media, ctx):
    if ctx['mesmo_ritmo'] or media is None:
        return None
    comparacao = calc.comparar_ritmos(ritmo_r['media'], media)
    if comparacao and media <= 0 and not ritmo_r['media']:
        return None   # nenhuma venda nos dois ritmos: não há o que comparar
    return comparacao


# Função Objetivo: As células de VENDAS, RITMO e TENDÊNCIA de uma linha, com os textos e os balões (as duas listas usam esta função, só muda de onde saíram as vendas). `saiu_de` = "do Full" | "de fora do Full";
# `onde` = "Full" | "fora do Full". `l` precisa ter media, un, ritmo_p, ritmo_r e comparacao. O faturamento NÃO está na tabela.
def celulas_de_vendas(l, ctx, saiu_de, onde):
    dias, recente, media, ritmo_r, n_ok = ctx['dias'], ctx['recente'], l['media'], l['ritmo_r'], l['ritmo_p']['n_completos']
    vendas_dica = (f'Unidades que saíram {saiu_de} só nos {plural(n_ok, "dia completo", "dias completos")} dos últimos {dias} dias (de {data(ctx["de"])} até ontem): é o mesmo volume que '
                   f'dá o ritmo (unidades ÷ dias completos). Hoje (parcial) e os dias sem coleta ficam de fora; venda cancelada não conta.')
    if media is None:
        ritmo_txt, ritmo_dica = '—', f'Nenhum dos últimos {dias} dias está completo na coleta da conta toda: sem ritmo de vendas.'
    else:
        ritmo_txt, ritmo_dica = un_dia(media), f'Média de {un_dia(media)} un/dia ({onde}) nos {n_ok} dias completos dos últimos {dias}.'
    comparacao = l['comparacao']
    if comparacao:
        tend_txt, tend_classe = {'acelerou': ('Acelerou', 'acelerou'), 'caiu': ('Caiu', 'caiu'), 'estavel': ('Estável', 'estavel')}[comparacao['sentido']]
        tend_dica = (f'Últimos {recente} dias: {un_dia(ritmo_r["media"])} un/dia, contra {un_dia(media)} un/dia nos {dias} dias' + (f' ({pct_texto(comparacao["pct"])}).' if comparacao['pct'] is not None else '.')
                     + f' Fica "Estável" quando a diferença é de até {calc.LIMITE_DE_ACELERACAO_PCT:.0f}%.')
    else:
        tend_txt, tend_classe = '—', 'nulo'
        if media is None:
            tend_dica = 'Sem ritmo de vendas: não dá para comparar.'
        elif ctx['mesmo_ritmo']:
            tend_dica = f'A tendência compara os últimos {recente} dias com o período inteiro: escolha um período maior que {recente} dias em "Vendas dos últimos N dias".'
        else:
            tend_dica = f'Nenhuma venda {saiu_de} nos dois períodos: não há o que comparar.'
    return {'vendas_txt': numero(l['un']) if media is not None else '—', 'vendas_dica': vendas_dica, 'ritmo_txt': ritmo_txt, 'ritmo_dica': ritmo_dica, 'tend_txt': tend_txt, 'tend_classe': tend_classe, 'tend_dica': tend_dica}


# Função Objetivo: A situação dos anúncios de uma entidade: quantos estão ativos, pausados etc. (o `status` do anúncio no banco; anúncio sem status fica em 'sem_status'). Alimenta a coluna "Anúncios" e a ordem dela.
def status_dos_anuncios(mlbs, anuncios):
    return Counter((((anuncios.get(m) or {}).get('tipo') or {}).get('status') or 'sem_status') for m in mlbs)


# Função Objetivo: Os avisos de DADOS de uma linha (a coluna "Dados": a linha merece confiança?): sem leitura do estoque, estoque parcial, consulta antiga e Código ML compartilhado. Lista vazia = "Em dia".
# Cada aviso é {texto curto, classe, dica}; o texto curto cabe na coluna e a dica diz tudo.
def _avisos_de_dados(resumo, e, gran):
    avisos = []
    if resumo['estado'] == 'sem_leitura':
        motivo = 'a última consulta de estoque deu erro' if resumo['com_erro'] and not resumo['sem_consulta'] else 'ainda não há consulta de estoque salva'
        avisos.append({'texto': 'Sem leitura', 'classe': 'atencao', 'dica': f'Nenhum Código ML deste item tem o estoque do Full lido ({motivo}). Abra o item e clique em "Atualizar este item" (ou faça a consulta na tela "Estoque no Full"). '
                                                                           f'Sem leitura não é estoque zero: o item fica fora dos níveis.'})
    elif resumo['estado'] == 'parcial':
        faltando = resumo['sem_consulta'] + resumo['com_erro']
        avisos.append({'texto': 'Estoque parcial', 'classe': 'atencao', 'dica': f'Só {resumo["n_lidos"]} de {resumo["n_codigos"]} Códigos ML têm estoque lido; não entram na soma: {", ".join(faltando)}.'})
    if resumo['desatualizados'] and resumo['estado'] != 'sem_leitura':
        avisos.append({'texto': 'Consulta antiga', 'classe': 'info', 'dica': f'{plural(len(resumo["desatualizados"]), "Código", "Códigos")} com a consulta de estoque de mais de {HORAS_PARA_DESATUALIZADO} h.'})
    if e['compartilha']:
        if gran == 'mlb':
            dica = (f'O estoque do Código ML deste anúncio também é usado por {", ".join(e["compartilha"])}. O estoque é o mesmo para todos: a cobertura aqui olha só as vendas deste anúncio e pode estar maior do que a real. Veja pelo Código ML.')
        else:
            dica = f'Algum Código ML deste item também aparece no SKU {", ".join(e["compartilha"])}: o estoque é o mesmo para os dois.'
        avisos.append({'texto': 'Cód. compartilhado', 'classe': 'info', 'dica': dica})
    return avisos


# Função Objetivo: Os números de UMA entidade: o estoque do Full (soma dos Códigos), o ritmo do Full no período e no recente, a projeção, o nível e a categoria do filtro, mais o VALOR QUE ORDENA cada coluna (`*_ordem`, None = sem o dado).
# `cat` é uma de ruptura | critico | baixo | alto | sem_previsao (sem venda no ritmo, ou nenhum dia completo) | sem_estoque (nenhum Código com estoque lido) | sem_nivel (sem lead time).
# * [EXPLICAÇÃO] → Estoque zerado é "ruptura" mesmo sem ritmo: não há o que vender. Sem estoque LIDO nunca é ruptura (ausente não é zero). Com a opção "Contar o que está a caminho" marcada,
#                  o "estoque" desta conta já inclui o a caminho (ruptura_estoque.estoque_para_cobertura): item zerado com unidades a caminho deixa de ser "ruptura".
# * [EXPLICAÇÃO] → O Sistema e o Mercado Livre são calculados SEMPRE (a urgência de cada um, a quantidade e se divergem): o cartão "Divergem" da faixa Situação conta a lista inteira, com a chave "Comparar com o Mercado Livre" ligada ou não.
#                  A chave só decide se os dois trios de comparação aparecem. O que o Mercado Livre recomenda vem do cache (full_estoque_ml.ml_dos_codigos), não pesa.
# * [EXPLICAÇÃO] → A TENDÊNCIA (acelerou | caiu | estável) é uma coluna própria e só olha as VENDAS (não precisa de estoque): compara o ritmo dos últimos `recente` dias com o do período, quando o período é maior que eles.
def _calcular_linha(e, gran, dados, cartoes, ctx):
    hoje, lead, ante = ctx['hoje'], ctx['lead'], ctx['ante']
    por_dia = dados['dias'][gran].get(e['chave'], {})
    cobertura = cobertura_da_linha(e, dados, ctx)
    ritmo_p = calc.ritmo_da_janela(ctx['jan_p'], por_dia, cobertura['estados'])
    ritmo_r = ritmo_p if ctx['mesmo_ritmo'] else calc.ritmo_da_janela(ctx['jan_r'], por_dia, cobertura['estados'])
    resumo = full.somar_codigos(e['codigos'], cartoes)
    if ctx['a_caminho_de_todos']:
        full.preencher_a_caminho(resumo, e['codigos'], cartoes)   # com a opção marcada (ou ordenando pela coluna "A caminho") o número precisa estar preenchido em TODAS as linhas
    estoque, media = full.estoque_para_cobertura(resumo, ctx['caminho']), ritmo_p['media']
    projecao, nivel = None, None
    if resumo['estado'] == 'sem_leitura':
        cat = 'sem_estoque'
    elif estoque <= 0:
        cat, nivel, projecao = 'ruptura', 'ruptura', calc.projetar(estoque, media, hoje)
    elif media is None:
        cat = 'sem_previsao'
    else:
        projecao = calc.projetar(estoque, media, hoje)
        if projecao['situacao'] == 'normal':
            nivel = calc.nivel_do_estoque(projecao, lead, ctx['folga'])
            cat = nivel or 'sem_nivel'
        else:
            cat = 'sem_previsao'
    # a sugestão do Sistema de quanto enviar (só quando há ritmo e a ruptura é calculável; sem estoque lido nunca vira "zero")
    sugestao = None
    if projecao and projecao['situacao'] in ('normal', 'zerado'):
        sugestao = calc.sugestao_do_sistema(estoque, media, lead, ctx['folga'])
    # as duas urgências (Sistema e Mercado Livre) na mesma língua, para comparar
    envio = calc.envio(projecao, lead, hoje, ante) if projecao and projecao['situacao'] == 'normal' else None
    ml = full.resumir_ml(e['codigos'], cartoes)
    urg_sistema, urg_ml = calc.urgencia_do_sistema(cat, envio), ml['urgencia']
    diverge = calc.urgencias_divergem(urg_sistema, urg_ml)
    qtd_dif = calc.diferenca_de_quantidades(sugestao['qtd'] if sugestao else None, ml['sugestao_min'])   # ML − Sistema, em unidades (None = falta um dos lados)
    comparacao = tendencia_do_ritmo(ritmo_r, media, ctx)
    com_data = projecao is not None and projecao['situacao'] in ('normal', 'zerado')
    # "Se enviar hoje": negativo = faltam dias de estoque até a chegada; 0 = chega no dia da ruptura; positivo = chega com folga (zerado: o produto só volta depois do prazo)
    if cat == 'ruptura' and lead is not None:
        margem = -lead
    elif envio:
        margem = -envio['faltam_dias'] if envio['estado'] == 'vencido' else envio['sobra_na_chegada']
    else:
        margem = None
    status = status_dos_anuncios(e['mlbs'], ctx['anuncios'])
    return {'e': e, 'chave': e['chave'], 'cat': cat, 'nivel': nivel, 'resumo': resumo, 'estoque': estoque, 'ritmo_p': ritmo_p, 'ritmo_r': ritmo_r, 'media': media, 'projecao': projecao, 'sugestao': sugestao,
            'envio': envio, 'ml': ml, 'urg_sistema': urg_sistema, 'urg_ml': urg_ml, 'diverge': diverge, 'qtd_dif': qtd_dif, 'margem': margem,
            'dias_exatos': projecao['dias_exatos'] if com_data else None,
            'comparacao': comparacao, 'un': ritmo_p['unidades'], 'titulo_ordem': e['titulo_ordem'], 'vendas_ate': cobertura['coletado_em'],
            'status': status, 'status_pausados': status.get('paused', 0), 'dados_avisos': _avisos_de_dados(resumo, e, gran),
            # ---- o valor que ordena cada coluna (None = a linha não tem esse dado: vai para o fim nos dois sentidos) ----
            'caminho_ordem': resumo['a_caminho'], 'vendas_ordem': ritmo_p['unidades'] if media is not None else None,
            'tend_ordem': {'caiu': 0, 'estavel': 1, 'acelerou': 2}.get(comparacao['sentido']) if comparacao else None,
            'cob_ordem': projecao['dias_exatos'] if com_data else None, 'ruptura_ordem': projecao['data'].toordinal() if com_data else None,
            'nivel_ordem': None if cat == 'sem_estoque' else URGENCIA[cat],
            'enviar_ordem': (projecao['data'] - timedelta(days=lead + ante)).toordinal() if com_data and lead is not None and ante is not None else None,
            'se_ordem': margem, 'qtd_ordem': sugestao['qtd'] if sugestao else None,
            'urg_sistema_ordem': RANK_DA_URGENCIA_ML.get(urg_sistema) if urg_sistema else None, 'urg_ml_ordem': RANK_DA_URGENCIA_ML.get(urg_ml) if urg_ml else None,
            'qtd_ml_ordem': ml['sugestao_min'], 'qtd_comp_ordem': abs(qtd_dif) if qtd_dif is not None else None, 'comp_ordem': None if (urg_sistema is None or urg_ml is None) else (0 if diverge else 1)}


# ==================================================== o texto de cada linha (só as da página) ====================================================

# Função Objetivo: A sugestão do SISTEMA de uma linha como texto: (texto, dica). Texto None = sem número (sem estoque lido, sem ruptura prevista).
def _quantidade_do_sistema(l, ctx):
    sug, lead = l['sugestao'], ctx['lead']
    if sug is None:
        return None, ('Sem estoque lido: não há como sugerir a quantidade.' if l['cat'] == 'sem_estoque' else 'Sem ruptura prevista neste ritmo (ou sem dias coletados): não há quantidade a sugerir.')
    folga = plural(ctx['folga'], 'dia', 'dias')
    if sug['qtd'] == 0:
        return '0', 'Sugestão do Sistema: 0 un, porque a folga está em 0 dias (a quantidade é o ritmo × a folga). Digite a folga desejada no cartão "Regras de envio".'
    return numero(sug['qtd']), (f'Sugestão do Sistema: {numero(sug["qtd"])} un = ritmo ({un_dia(l["media"])} un/dia) × folga ({folga}). É a quantidade que acrescenta {folga} de estoque: a nova ruptura vem {folga} depois da atual '
                                f'(ou depois da chegada, que leva {plural(lead, "dia", "dias")}, se o estoque acabar antes dela).')


# Função Objetivo: As duas fontes de urgência de uma linha: (selo do Sistema, selo do Mercado Livre, frase do Sistema, frase do Mercado Livre). O selo é o mesmo da tela de Planejamento de envios (ruptura_estoque.selo_da_urgencia) e é None quando
# a fonte não tem número ("ausente não é zero"); a frase diz de onde veio ("Esta semana (prazo para repor: 20/10/2026)", "Urgente — o estoque está zerado") e serve ao balão da coluna "Comparação" das urgências.
def _frases_da_urgencia(l):
    ml = l['ml']
    selo_ml, selo_sistema = full.selo_da_urgencia(l['urg_ml']), full.selo_da_urgencia(l['urg_sistema'])
    if selo_ml:
        frase_ml = selo_ml['label'] + (f' (prazo para repor: {data_do_ml(ml["prazo"])})' if ml['prazo'] else '')
    else:
        frase_ml = f'sem número do ML ({ml["motivo"] or "a consulta não trouxe a urgência"})'
    frase_sistema = f'{selo_sistema["label"]} — {porque_da_urgencia_do_sistema(l["cat"], l["envio"])}' if selo_sistema else 'sem estoque lido'
    return selo_sistema, selo_ml, frase_sistema, frase_ml


# Função Objetivo: Transforma os números de uma linha nos textos que a tela mostra, UMA célula por coluna (ver _grupos): cada célula tem UM valor e o resto vai no `title` (tooltip) dela, porque a tela é rígida na vertical.
def _apresentar(l, gran, ctx, base_url):
    e, r, hoje, lead, dias = l['e'], l['resumo'], ctx['hoje'], ctx['lead'], ctx['dias']

    # ---- anúncios (a situação deles: pausado pesa o mesmo que ativo) ----
    anuncios_chips, anuncios_sub, anuncios_dica = _celula_de_anuncios(l, gran)

    # ---- estoque (do Full, considerado) e a caminho ----
    conta = full.texto_da_conta(r, numero, ctx['caminho'])
    if r['estado'] == 'sem_leitura':
        estoque_txt, estoque_classe = '—', 'nulo'
        estoque_dica = 'Sem leitura do estoque do Full (veja a coluna "Dados"). Sem leitura não é estoque zero: o item fica fora dos níveis.'
    else:
        estoque_txt = numero(l['estoque'])   # com a opção "Contar o que está a caminho" marcada, já inclui o a caminho
        estoque_classe = 'zero' if l['estoque'] <= 0 else ''
        extras = [f'Consulta mais antiga entre os Códigos: {r["idade"]}.']
        if r['estado'] == 'parcial':
            extras.append(f'Só {r["n_lidos"]} de {r["n_codigos"]} Códigos ML têm estoque lido (parcial).')
        if r['desatualizados']:
            extras.append(f'{plural(len(r["desatualizados"]), "Código está", "Códigos estão")} com a consulta de estoque de mais de {HORAS_PARA_DESATUALIZADO} h.')
        if r['a_caminho'] and ctx['caminho']:
            extras.append(f'O a caminho (+{numero(r["a_caminho"])}{" (parcial)" if r["a_caminho_parcial"] else ""}) está SOMADO ao estoque, como se já estivesse no Full hoje.')
        estoque_dica = f'Estoque considerado no Full: {conta} {" ".join(extras)}'
    if r['a_caminho']:
        caminho_txt, caminho_classe = numero(r['a_caminho']), ''
        caminho_dica = (f'Enviado ao Full e ainda não recebido: {numero(r["a_caminho"])} un{" (parcial)" if r["a_caminho_parcial"] else ""}. É só hipótese (não se sabe quando chega). '
                        + ('Está SOMADO ao Estoque Full (opção "Contar o que está a caminho").' if ctx['caminho'] else 'Não entra na cobertura.'))
    else:
        caminho_txt, caminho_classe = '—', 'nulo'
        caminho_dica = ('Nada a caminho deste item.' if r['a_caminho'] == 0 else 'Sem a leitura do "a caminho" deste item (a consulta de reposição não está salva ou deu erro).')

    # ---- vendas, ritmo e tendência (só o que saiu do Full) ----
    media = l['media']
    vendas = celulas_de_vendas(l, ctx, 'do Full', 'Full')

    # ---- cobertura, ruptura, nível, enviar até e "se enviar hoje" ----
    projecao, cat = l['projecao'], l['cat']
    cob_sub, barra_pct, ruptura_txt, ruptura_classe, ruptura_dica = '', None, '—', '', 'Sem ruptura prevista.'
    enviar_txt, enviar_classe, enviar_dica, se_txt, se_classe, se_dica = '—', 'nulo', 'Sem data de envio: não há ruptura prevista neste ritmo.', '—', 'nulo', 'Sem ruptura prevista: não há o que comparar com a chegada.'
    envio = l['envio']
    if cat == 'ruptura':
        cob_txt, barra_pct = '0', 0
        ruptura_txt, ruptura_classe, ruptura_dica = 'Agora', 'zero', 'O estoque do Full está zerado: o produto já está em ruptura.'
        enviar_txt, enviar_classe = 'Agora', 'falta'
        enviar_dica = f'Estoque zerado: envie o quanto antes. Com prazo de {plural(lead, "dia", "dias")}, o produto só volta a ficar disponível em {data(hoje + timedelta(days=lead))}.'
        cob_dica = f'O estoque do Full está zerado{" (contando o que está a caminho)" if ctx["caminho"] else ""}: o produto já está em ruptura.'
    elif projecao and projecao['situacao'] == 'normal':
        dias_inteiros = projecao['dias']
        cob_txt = numero(dias_inteiros)
        referencia = max(lead or 0, 1) * BARRA_EM_LEADS
        barra_pct = min(100, round(l['dias_exatos'] / referencia * 100))
        ruptura_txt, ruptura_dica = data_curta(projecao['data'], hoje), f'O estoque acaba em {data(projecao["data"])} ({em_dias(dias_inteiros)}) neste ritmo.'
        regra = f'ruptura − prazo ({lead} d) − chegar antes ({ctx["ante"]} d)'
        if envio and envio['estado'] == 'vencido':
            enviar_txt, enviar_classe = 'Agora', 'falta'
            enviar_dica = (f'O último dia para enviar foi {data(envio["ultimo_dia"])}: enviando hoje o produto só fica disponível em {data(envio["chegada"])} '
                           f'e vão faltar cerca de {plural(envio["faltam_dias"], "dia", "dias")} de estoque.')
        elif envio and envio['estado'] == 'ja':
            sobra = envio['sobra_na_chegada']
            enviar_txt, enviar_classe = 'Agora', 'dia'
            enviar_dica = (f'A data recomendada ({data(envio["enviar_ate"])} = {regra}) já passou, mas ainda dá tempo: enviando hoje, o produto chega em {data(envio["chegada"])}, '
                           f'{"no próprio dia da ruptura" if sobra == 0 else plural(sobra, "dia", "dias") + " antes da ruptura"} (o desejado é chegar {ctx["ante"]} d antes). O último dia possível é {data(envio["ultimo_dia"])}.')
        elif envio:
            enviar_txt = data_curta(envio['enviar_ate'], hoje)
            enviar_classe = 'dia' if envio['estado'] == 'hoje' else ''
            enviar_dica = (f'Data recomendada para enviar: {data(envio["enviar_ate"])} = {regra}. O último dia possível (chegando em cima da ruptura) é {data(envio["ultimo_dia"])}.'
                           + (' É hoje.' if envio['estado'] == 'hoje' else f' Faltam {plural(envio["em_dias"], "dia", "dias")}.'))
        cob_dica = (f'O estoque considerado{" (com as unidades a caminho)" if ctx["caminho"] else ""} ({numero(l["estoque"])} un) dura cerca de {plural(dias_inteiros, "dia", "dias")} no ritmo de {un_dia(media)} un/dia. '
                    f'A marca na barra é o prazo até vender ({plural(lead, "dia", "dias")}); a barra enche com {BARRA_EM_LEADS}× o prazo.')
    elif cat == 'sem_previsao':
        cob_txt = '—'
        if media is None:
            cob_sub, cob_dica = 'sem dados', 'Sem dias completos coletados no período: não dá para calcular o ritmo.'
        elif media <= 0:
            cob_sub, cob_dica = 'sem vendas', 'Nenhuma venda do Full nos dias completos do período: o estoque não acaba neste ritmo.'
        else:
            cob_sub, cob_dica = 'muito longa', f'Dura mais de {numero(calc.DIAS_MAXIMOS_DA_PROJECAO)} dias neste ritmo.'
    else:
        cob_txt, cob_dica = '—', 'Sem estoque lido: não há como calcular a cobertura.'
        ruptura_dica = enviar_dica = se_dica = 'Sem estoque lido: não há como calcular.'
    margem = l['margem']
    if margem is not None:
        chega = f'Enviando hoje, o produto chega em {data(hoje + timedelta(days=lead))} (hoje + {plural(lead, "dia", "dias")}). '
        if margem < 0:
            se_txt, se_classe = f'Faltam {numero(-margem)} d', 'falta'
            se_dica = chega + (f'O estoque acaba antes: vão faltar {plural(-margem, "dia", "dias")} de estoque até a chegada.' if cat != 'ruptura' else 'O estoque já está zerado: o produto só volta a ficar disponível na chegada.')
        elif margem == 0:
            se_txt, se_classe, se_dica = 'No dia', 'dia', chega + 'Chega no próprio dia da ruptura.'
        else:
            se_txt, se_classe, se_dica = f'Folga {numero(margem)} d', 'folga', chega + f'Chega {plural(margem, "dia", "dias")} antes da ruptura.'

    # ---- nível ----
    if l['nivel']:
        nivel_rotulo, nivel_classe, nivel_dica = calc.NIVEIS_CURTOS[l['nivel']], l['nivel'], calc.NIVEIS[l['nivel']]
    elif cat == 'sem_previsao' and media is None:
        nivel_rotulo, nivel_classe, nivel_dica = 'Sem previsão', 'neutro', f'Nenhum dos últimos {dias} dias está completo na coleta da conta toda: sem ritmo de vendas não há como prever a ruptura.'
    elif cat == 'sem_previsao':
        nivel_rotulo, nivel_classe, nivel_dica = 'Sem vendas', 'neutro', f'Tem estoque, mas nenhuma venda do Full nos dias completos do período (ou vendas tão baixas que o estoque dura mais de {numero(calc.DIAS_MAXIMOS_DA_PROJECAO)} dias): não há ruptura prevista neste ritmo.'
    elif cat == 'sem_estoque':
        nivel_rotulo, nivel_classe, nivel_dica = 'Sem estoque', 'neutro', 'Nenhum Código ML com estoque do Full lido.'
    else:
        nivel_rotulo, nivel_classe, nivel_dica = '', '', ''

    # ---- quanto enviar (Sistema) e, com a chave ligada, o Mercado Livre ----
    qtd_txt, qtd_dica = _quantidade_do_sistema(l, ctx)
    qtd_deposito, qtd_deposito_dica = aviso_do_deposito(l['sugestao']['qtd'] if l['sugestao'] else None, ctx['erp'].get(e['sku']))   # a quantidade passa do que há no depósito (ERP)? Aviso no lugar certo, número inteiro
    if qtd_deposito:
        qtd_dica = f'{qtd_deposito_dica} {qtd_dica}'
    qtd_ml_txt, qtd_ml_dica = quantidade_do_ml(l['ml'])
    qtd_ml_deposito, qtd_ml_deposito_dica = aviso_do_deposito(l['ml']['sugestao_min'], ctx['erp'].get(e['sku']))
    if qtd_ml_deposito:
        qtd_ml_dica = f'{qtd_ml_deposito_dica} {qtd_ml_dica}'
    qtd_comp_txt, qtd_comp_classe, qtd_comp_dica = comparacao_das_quantidades(l['sugestao']['qtd'] if l['sugestao'] else None, l['ml']['sugestao_min'], l['qtd_dif'])
    selo_sistema, selo_ml, frase_sistema, frase_ml = _frases_da_urgencia(l)
    if l['comp_ordem'] is None:
        comp_txt, comp_classe = 'Sem comparação', 'sem'
    else:
        comp_txt, comp_classe = ('Divergem', 'div') if l['diverge'] else ('Iguais', 'ig')
    comp_dica = f'Sistema: {frase_sistema}. Mercado Livre: {frase_ml}.' + (' As duas estão em faixas diferentes.' if l['diverge'] else (' As duas estão na mesma faixa.' if l['comp_ordem'] is not None else ' Sem a leitura de um dos lados não há o que comparar.'))

    link = ''
    if e['sku']:
        link = url_da_tela(base_url, sku=e['sku'], gran=gran if gran != 'sku' else None, item=e['chave'] if gran != 'sku' else None, **para_url(ctx['comuns']))
    return {
        'chave': e['chave'], 'titulo': e['titulo'], 'subtitulo': e['subtitulo'], 'foto': e['foto'], 'id_txt': e['id_txt'], 'cat': cat, 'em_ruptura': cat == 'ruptura',
        'url_detalhe': link, 'motivo': 'Sem SKU no cadastro de anúncios: a curva abre por produto.',
        'anuncios_chips': anuncios_chips, 'anuncios_sub': anuncios_sub, 'anuncios_dica': anuncios_dica,
        'frescor': frescor(l['vendas_ate'], l['resumo']),
        'dados_avisos': l['dados_avisos'], 'dados_chips': l['dados_avisos'][:2], 'dados_mais': max(0, len(l['dados_avisos']) - 2), 'dados_dica': ' · '.join(a['dica'] for a in l['dados_avisos']) or 'Estoque lido de todos os Códigos ML, consulta recente.',
        'estoque_txt': estoque_txt, 'estoque_classe': estoque_classe, 'estoque_dica': estoque_dica, 'caminho_txt': caminho_txt, 'caminho_classe': caminho_classe, 'caminho_dica': caminho_dica,
        **vendas,
        'cob_txt': cob_txt, 'cob_sub': cob_sub, 'cob_dica': cob_dica, 'barra_pct': barra_pct, 'barra_classe': l['nivel'] or 'neutro',
        'ruptura_txt': ruptura_txt, 'ruptura_classe': ruptura_classe, 'ruptura_dica': ruptura_dica,
        'nivel_rotulo': nivel_rotulo, 'nivel_classe': nivel_classe, 'nivel_dica': nivel_dica,
        'enviar_txt': enviar_txt, 'enviar_classe': enviar_classe, 'enviar_dica': enviar_dica, 'se_txt': se_txt, 'se_classe': se_classe, 'se_dica': se_dica,
        'qtd_txt': qtd_txt if qtd_txt is not None else '—', 'qtd_classe': 'nulo' if qtd_txt is None else '', 'qtd_dica': qtd_dica, 'qtd_deposito': qtd_deposito,
        'urg_sistema_selo': selo_sistema, 'urg_sistema_vazio': 'sem estoque lido', 'urg_ml_selo': selo_ml, 'urg_ml_vazio': 'Sem dado do ML',
        'qtd_ml_txt': qtd_ml_txt if qtd_ml_txt is not None else 'sem número', 'qtd_ml_classe': 'nulo' if qtd_ml_txt is None else '', 'qtd_ml_dica': qtd_ml_dica, 'qtd_ml_deposito': qtd_ml_deposito,
        'comp_txt': comp_txt, 'comp_classe': comp_classe, 'comp_dica': comp_dica,
        'qtd_comp_txt': qtd_comp_txt, 'qtd_comp_classe': qtd_comp_classe, 'qtd_comp_dica': qtd_comp_dica,
    }


# Função Objetivo: Os chips da coluna "Anúncios" a partir da contagem de status (as duas listas, Full e Fora do Full, usam esta função): "2 ativos", "1 pausado"; no Anúncio (MLB) um chip só, o status dele. Devolve (chips, frase),
# com chips = [{texto, classe}] (classe: ativo | pausa | outro) e a frase "Situação no Mercado Livre — 2 anúncios: ativo; 1 anúncio: pausado." para o balão.
def celula_de_status(status, gran):
    ordem = ['active', 'paused'] + sorted(k for k in status if k not in ('active', 'paused'))
    chips, partes = [], []
    for chave in ordem:
        n = status.get(chave, 0)
        if not n:
            continue
        rotulo = (BADGES_STATUS.get(chave) or {}).get('label') or 'Sem status'
        classe = 'ativo' if chave == 'active' else 'pausa' if chave == 'paused' else 'outro'
        if gran == 'mlb':
            chips.append({'texto': rotulo, 'classe': classe})
        else:
            sing, plur = {'active': ('ativo', 'ativos'), 'paused': ('pausado', 'pausados')}.get(chave, (rotulo.lower(), rotulo.lower()))
            chips.append({'texto': f'{n} {sing if n == 1 else plur}', 'classe': classe})
        partes.append(f'{plural(n, "anúncio", "anúncios")}: {rotulo.lower()}')
    return chips, 'Situação no Mercado Livre — ' + '; '.join(partes) + '.'


# Função Objetivo: A célula "Anúncios" do Full: os chips de status (celula_de_status) e, quando há pausado, o FATO que ajuda a corrigir: o que o Full tem de estoque. Devolve (chips, linha pequena, dica).
# * [EXPLICAÇÃO] → O banco guarda o STATUS do anúncio (ativo, pausado, em revisão...) mas NÃO o motivo da pausa (o Mercado Livre manda esse "sub status" e ele ainda não é gravado). Por isso a tela não afirma "pausado por falta de
#                  estoque": mostra os dois fatos lado a lado (pausado + o que há no Full), e quem vê "pausado com estoque no Full" sabe que dá para reativar.
def _celula_de_anuncios(l, gran):
    status, estoque = l['status'], l['estoque']
    chips, dica = celula_de_status(status, gran)
    sub = ''
    if status.get('paused'):
        sub = 'estoque Full zerado' if (estoque is not None and estoque <= 0) else ('tem estoque no Full' if estoque is not None else 'estoque não lido')
        dica += (' Pausado pesa o mesmo que ativo: alguns anúncios ficam pausados só por falta de estoque. O banco guarda a situação, não o motivo da pausa: use o estoque do Full ao lado para decidir '
                 '(com estoque no Full e pausado, vale reativar no Mercado Livre).')
    return chips, sub, dica


# ==================================================== a lista ====================================================

# Função Objetivo: Tudo da lista a partir da query string. Parâmetros: gran (sku|mlb|codigo), q (busca), nivel (todos|ruptura|critico|baixo|alto|sem_previsao|sem_estoque), diverge (1 = só os que divergem; combina com o nivel; o
# antigo nivel=divergem de endereços salvos vale como diverge=1), comparar (1 = a chave "Comparar com o Mercado Livre" ligada; o "Divergem" liga sozinho), ord (a chave da coluna que ordena) e sentido (asc | desc), por e pag; o ritmo
# (dias), o prazo, os dias para chegar antes da ruptura, a folga e a opção "Contar o que está a caminho" (caminho=1) chegam já lidos em `comuns` (ruptura_parametros, mundo Full; as escolhas de "Quem recomenda", ref_urg e
# ref_qtd, só valem no detalhe de um item e aqui só viajam no endereço). Parâmetro inválido volta ao padrão. Qualquer mudança de filtro, busca ou ordem volta para a página 1.
def montar_lista(parametros, base_url, hoje, comuns):
    dias, lead, ante, folga, recente, caminho = comuns['dias'], comuns['lead'], comuns['ante'], comuns['folga'], comuns['recente'], comuns['caminho']
    por_chave = {g[0]: g for g in GRANULARIDADES}
    gran = _escolher(parametros, 'gran', por_chave, GRANULARIDADE_PADRAO)
    _, _, ajuda, unidade_plural, unidade_singular = por_chave[gran]
    texto = (parametros.get('q') or '').strip()
    filtro = _escolher(parametros, 'nivel', NIVEIS_VALIDOS, 'todos')
    diverge = (parametros.get('diverge') or '').strip() == '1' or (parametros.get('nivel') or '').strip() == 'divergem'   # "nivel=divergem" é o endereço antigo (quando era um cartão de nível)
    comparar = diverge or (parametros.get('comparar') or '').strip() == '1'   # o "Divergem" só faz sentido comparando: liga a chave sozinho
    por = inteiro(parametros.get('por'), 1, 1000)
    por = por if por in POR_PAGINA_OPCOES else POR_PAGINA_PADRAO
    numero_da_pagina = inteiro(parametros.get('pag'), 1, 100000) or 1

    # as colunas (e a ordem delas): ruptura_colunas é o dono; aqui só se escolhe qual ordena a lista e em que sentido
    colunas = col.todas_as_colunas(_grupos(gran, dias, caminho, comparar))
    escolhida, sentido = col.escolher_ordem(parametros, colunas, ORDEM_PADRAO)
    todas_as_colunas = col.todas_as_colunas(_grupos(gran, dias, caminho, True))
    primeiro_sentido = {c['chave']: c['primeiro'] for c in todas_as_colunas}   # o sentido da primeira batida em cada coluna: é o padrão dela e não precisa ir no endereço
    chaves_do_ml = {c['chave'] for c in todas_as_colunas if c['ml']}
    padroes = {'gran': GRANULARIDADE_PADRAO, 'nivel': 'todos', 'ord': ORDEM_PADRAO, 'por': POR_PAGINA_PADRAO, 'pag': 1}

    # * [EXPLICAÇÃO] → O endereço leva só o que a pessoa mudou: o que é da lista (Ver por, busca, nível, "Divergem", chave do Mercado Livre, ordem e sentido, itens por página e página) sai daqui e as regras (ritmo, prazo, chegar antes,
    #                  folga, "a caminho" e as escolhas de "Quem recomenda", dos dois mundos) saem de ruptura_parametros.para_url, a mesma fonte do detalhe.
    # * [EXPLICAÇÃO] → Trocar a coluna da ordem sem dizer o sentido vale o sentido da primeira batida dela; sem a chave do Mercado Livre ligada as colunas dele não existem (a ordem volta ao padrão).
    def parametros_da_url(mudancas):
        atuais = {'gran': gran, 'q': texto, 'nivel': filtro, 'diverge': '1' if diverge else None, 'comparar': '1' if comparar else None, 'ord': escolhida['chave'], 'sentido': sentido, 'por': por, 'pag': numero_da_pagina}
        atuais.update(mudancas)
        if 'ord' in mudancas and 'sentido' not in mudancas:
            atuais['sentido'] = None
        if 'pag' not in mudancas:
            atuais['pag'] = 1
        if not (atuais['comparar'] or atuais['diverge']) and atuais['ord'] in chaves_do_ml:
            atuais['ord'], atuais['sentido'] = ORDEM_PADRAO, None
        if atuais['sentido'] == primeiro_sentido.get(atuais['ord']):
            atuais['sentido'] = None
        saida = {k: (None if v == padroes.get(k) else v) for k, v in atuais.items()}
        if atuais['sentido'] is not None:
            saida['ord'] = atuais['ord']   # o sentido só vale junto da coluna dele: com `sentido` o `ord` vai junto, mesmo sendo o padrão
        return {**saida, **para_url(comuns)}

    def url(**mudancas):
        return url_da_tela(base_url, **parametros_da_url(mudancas))

    # ---- dados: vendas do Full por dia (1 leitura), estoque do Full (2 leituras) e a conta de cada linha ----
    de = hoje - timedelta(days=max(dias, recente))
    dados = unidades_do_full_por_dia(de, hoje)
    estados = dados['estados']
    jan_p = [hoje - timedelta(days=i) for i in range(dias, -1, -1)]
    jan_r = [hoje - timedelta(days=i) for i in range(recente, -1, -1)]
    # * [EXPLICAÇÃO] → `a_caminho_de_todos`: o "a caminho" é a parte pesada da consulta de reposição, então só é lido para a lista INTEIRA quando precisa (a opção "Contar o que está a caminho" o soma ao estoque de cada linha, ou a lista está
    #                  ordenada pela coluna "A caminho"); senão só as linhas da página mostrada o leem.
    ctx = {'hoje': hoje, 'dias': dias, 'recente': recente, 'lead': lead, 'ante': ante, 'folga': folga, 'comuns': comuns, 'caminho': caminho, 'comparar': comparar, 'de': hoje - timedelta(days=dias), 'mesmo_ritmo': dias <= recente,
           'a_caminho_de_todos': caminho or escolhida['chave'] == 'caminho', 'anuncios': dados['cad']['anuncios'],
           'jan_p': jan_p, 'jan_r': jan_r, 'jan_todos': sorted(set(jan_p) | set(jan_r))}
    permitidos = mlbs_permitidos(comuns)   # os filtros do Hub: None = sem filtro ativo (nada é lido do Hub)
    entidades = _entidades(gran, dados, permitidos)
    cartoes = estoque_full_dos_codigos(sorted(set().union(*(e['codigos'] for e in entidades)))) if entidades else {}
    if ctx['a_caminho_de_todos']:
        _ler_a_caminho_de_todos(cartoes)   # o a caminho entra na cobertura de CADA linha (muda nível e ordem) ou ordena a lista: lido para todos os Códigos, em lotes
    ml_dos_codigos(cartoes)   # o que o Mercado Livre recomenda (urgência e sugestão), de todos os Códigos: o "Divergem", a comparação e a contagem olham a lista inteira (resumos em cache)
    todas = [_calcular_linha(e, gran, dados, cartoes, ctx) for e in entidades]

    # ---- busca, situação (cartões) e "Divergem" (os números da faixa Situação são sobre o resultado da busca; quem conta é ruptura_situacao.montar_situacao) ----
    n_ok = sum(1 for d in ctx['jan_p'] if estados.get(d) == 'ok')
    coletado_em = dados['coletado_em']
    procurado = _sem_acento(texto)
    base = [l for l in todas if not procurado or procurado in l['e']['busca']]
    filtradas = [l for l in base if (filtro == 'todos' or l['cat'] == filtro) and (l['diverge'] or not diverge)]
    filtradas = col.ordenar(filtradas, escolhida, sentido)

    # * [EXPLICAÇÃO] → Ligar o "Divergem" liga também a chave do Mercado Livre (sem comparar não há o que divergir); o endereço de quem o liga leva `comparar=1` junto, para a chave continuar ligada ao desligar o filtro.
    def url_da_situacao(**mudancas):
        if mudancas.get('diverge') == '1':
            mudancas['comparar'] = '1'
        return url(**mudancas)

    situacao = montar_situacao(base, filtro, diverge, url_da_situacao, unidade_plural, unidade_singular, lead, folga, sem_dados=n_ok == 0)

    # ---- a página atual: só aqui se lê o "A caminho" e se montam textos e endereços ----
    total = len(filtradas)
    total_paginas = max(1, -(-total // por))
    pagina_atual = min(numero_da_pagina, total_paginas)
    ini = (pagina_atual - 1) * por
    fim = min(total, ini + por)
    da_pagina = filtradas[ini:fim]
    if not ctx['a_caminho_de_todos']:   # com a opção marcada (ou ordenando por ela) o a caminho já foi lido para todos (e preenchido em cada linha por _calcular_linha)
        codigos_da_pagina = {c for l in da_pagina for c in l['e']['codigos']}
        a_caminho_dos_codigos({c: cartoes[c] for c in codigos_da_pagina if c in cartoes})
        for l in da_pagina:
            full.preencher_a_caminho(l['resumo'], l['e']['codigos'], cartoes)
    ctx['erp'] = estoque_do_erp({l['e']['sku'] for l in da_pagina if l['e']['sku']})   # o depósito (ERP) dos SKUs da página: 1 leitura, só para o aviso de "só há N un no depósito"
    linhas = [_apresentar(l, gran, ctx, base_url) for l in da_pagina]

    # ---- cobertura das vendas, consultas de estoque e pontos de atenção (sobre a lista inteira) ----
    consultas = contar_consultas(cartoes)
    n_sem_consulta, n_erro, n_antigas = consultas['sem_consulta'], consultas['erro'], consultas['antigas']
    # * [EXPLICAÇÃO] → Todo aviso nasce em ruptura_avisos.py (aviso / aviso_de_contagem) e a caixa os ordena por gravidade: aqui só se diz O QUE aconteceu (título curto + número), O QUE ISSO CAUSA (texto) e, se der, ONDE resolver (link).
    link_estoque = reverse('gestao_full_estoque')
    avisos = []
    if not coletado_em:
        avisos.append(aviso('aviso', f'Nenhum dia dos últimos {dias} foi coletado da conta toda', 'Sem ritmo de vendas, os itens ficam em "Sem previsão". Colete o período na tela de Vendas.'))
    elif n_ok < dias:
        avisos.append(aviso('aviso', 'dias completos na coleta de vendas da conta toda', 'A média usa só os dias completos (hoje e dias parciais ficam de fora).', numero_texto=f'{n_ok}/{dias}'))
    if n_sem_consulta:
        avisos.append(aviso_de_contagem('aviso', n_sem_consulta, 'Código ML ainda sem consulta de estoque salva', 'Códigos ML ainda sem consulta de estoque salva',
                                        f'Total na lista: {numero(len(cartoes))}. Os itens {"dele ficam" if n_sem_consulta == 1 else "deles ficam"} em "Sem estoque lido" (ou "Estoque parcial"). Faça a consulta na tela "Estoque no Full".',
                                        link_estoque, 'Abrir Estoque no Full'))
    if n_erro:
        avisos.append(aviso_de_contagem('aviso', n_erro, 'Código ML com erro na última consulta de estoque', 'Códigos ML com erro na última consulta de estoque',
                                        f'{"Ele não entra" if n_erro == 1 else "Eles não entram"} na soma: os itens ficam "parciais" ou "sem estoque lido". Refaça a consulta na tela "Estoque no Full".',
                                        link_estoque, 'Abrir Estoque no Full'))
    if n_antigas:
        avisos.append(aviso_de_contagem('info', n_antigas, 'Código ML com consulta de estoque antiga', 'Códigos ML com consulta de estoque antiga',
                                        f'A consulta {"dele" if n_antigas == 1 else "deles"} tem mais de {HORAS_PARA_DESATUALIZADO} h: o estoque pode ter mudado desde então. Atualize na tela "Estoque no Full".', link_estoque, 'Abrir Estoque no Full'))
    if comparar:
        n_sem_ml = sum(1 for l in todas if l['ml']['estado'] == 'sem_dados')
        if n_sem_ml:
            avisos.append(aviso_de_contagem('aviso', n_sem_ml, f'{unidade_singular} sem a recomendação do Mercado Livre', f'{unidade_plural} sem a recomendação do Mercado Livre',
                                            f'Sem consulta de reposição salva (ou com erro): {"fica" if n_sem_ml == 1 else "ficam"} "sem número do ML", nunca zero, e {"vai" if n_sem_ml == 1 else "vão"} para o fim da ordem de urgência. '
                                            f'A recomendação vem da mesma consulta da tela "Estoque no Full".', link_estoque, 'Abrir Estoque no Full'))
    if caminho:
        n_sem_caminho = sum(1 for c in cartoes.values() if c['estado'] == 'ok' and c.get('a_caminho') is None)
        if n_sem_caminho:
            avisos.append(aviso_de_contagem('info', n_sem_caminho, 'Código ML sem o número de "a caminho"', 'Códigos ML sem o número de "a caminho"',
                                            'Sem consulta de reposição salva, com erro ou sem conta que feche: neles só entra o estoque do Full.'))
    if gran == 'mlb':
        n_compartilhados = sum(1 for e in entidades if e['compartilha'])
        if n_compartilhados:
            avisos.append(aviso_de_contagem('info', n_compartilhados, 'anúncio divide o Código ML com outro anúncio', 'anúncios dividem o Código ML com outro anúncio',
                                            'Selo "Estoque compartilhado": o estoque é o mesmo, mas aqui só entram as vendas de cada anúncio.'))
    if gran == 'sku':
        aviso_sem_produto = aviso_anuncios_sem_produto(dados, anuncio_e_do_full, permitidos)
        if aviso_sem_produto:
            avisos.append(aviso_sem_produto)
    # * [EXPLICAÇÃO] → A conta com o Hub, em ANÚNCIOS (MLBs) seja qual for o "Ver por": quantos anúncios têm Código ML no banco mas não entram (já não são do Full, ou são fósseis de migração) e quantos anúncios do Full ainda
    #                  não têm Código ML (entram, sem estoque lido). Assim a diferença para qualquer número antigo se explica na própria tela.
    # * [EXPLICAÇÃO] → A MESMA BASE de todos os avisos da caixa (decisão do Matheus, 12/10/2026: com o filtro "Ativo" os avisos de consulta antiga e de Código compartilhado caíram, mas estes dois seguiam contando a conta toda):
    #                  com filtros do Hub ativos, só contam os anúncios que passam neles (`permitidos`), como as linhas da lista e o aviso de "sem Produto". O Hub nunca deixa um fóssil passar num filtro, então com filtro
    #                  ativo os fósseis não entram na conta. Só "dias completos na coleta" é da conta toda (as vendas são coletadas por dia, não por anúncio) e o próprio título diz isso.
    n_ja_nao_full = n_fossil = n_full_sem_codigo = 0
    for mlb, a in dados['cad']['anuncios'].items():
        if permitidos is not None and mlb not in permitidos:
            continue
        tem_codigo = any(c for _, c in a['variacoes'])
        if anuncio_fossil(a):
            n_fossil += 1 if tem_codigo else 0
        elif not anuncio_e_do_full(a):
            n_ja_nao_full += 1 if tem_codigo else 0
        elif not tem_codigo:
            n_full_sem_codigo += 1
    n_de_fora = n_ja_nao_full + n_fossil
    if n_de_fora:
        partes = ([f'{plural(n_ja_nao_full, "já não é do Full", "já não são do Full")} (a logística de hoje é diferente de FULL)'] if n_ja_nao_full else []) \
                 + ([f'{plural(n_fossil, "é anúncio fóssil de migração", "são anúncios fósseis de migração")}'] if n_fossil else [])
        avisos.append(aviso_de_contagem('info', n_de_fora, 'anúncio com Código ML no banco fica de fora', 'anúncios com Código ML no banco ficam de fora',
                                        'Motivo: ' + ' e '.join(partes) + '. É o mesmo critério do filtro FULL da tela Anúncios — Mercado Livre.'))
    if n_full_sem_codigo:
        avisos.append(aviso_de_contagem('aviso', n_full_sem_codigo, 'anúncio do Full ainda sem Código ML no banco', 'anúncios do Full ainda sem Código ML no banco',
                                        f'{"Ele fica" if n_full_sem_codigo == 1 else "Eles ficam"} em "Sem estoque lido". O Código ML vem da importação dos anúncios (popular_banco).'))

    # os campos escondidos do formulário: o que é da lista (Ver por, nível, "Divergem", chave do Mercado Livre, ordem e sentido, itens por página) + o que é do outro mundo e as escolhas de "Quem recomenda"; os campos visíveis
    # (busca, ritmo, prazo, chegar antes, folga e caminho) não viram campo escondido
    da_lista = parametros_da_url({})
    ocultos = [{'nome': k, 'valor': da_lista[k]} for k in ('gran', 'nivel', 'diverge', 'comparar', 'ord', 'sentido', 'por') if da_lista.get(k) is not None] + campos_escondidos(comuns)
    # * [EXPLICAÇÃO] → A chave "Comparar com o Mercado Livre": ligada, o endereço do clique a desliga (e desliga o "Divergem", que só existe comparando); desligada, liga. O texto "N de M ... divergem" conta os itens da busca
    #                  que têm as duas urgências (sem a leitura de um dos lados não há o que comparar).
    n_comparaveis = sum(1 for l in base if l['comp_ordem'] is not None)
    n_divergem = sum(1 for l in base if l['comp_ordem'] == 0)
    info_da_comparacao = f'{numero(n_divergem)} de {numero(n_comparaveis)} {unidade_singular if n_comparaveis == 1 else unidade_plural} {"diverge" if n_divergem == 1 else "divergem"} do Mercado Livre' if n_comparaveis else 'Nenhum item tem a leitura do Mercado Livre'
    return {
        'gran': gran, 'ajuda': ajuda, 'texto': texto, 'ocultos': ocultos, 'cabecalho': col.cabecalho(_grupos(gran, dias, caminho, comparar), escolhida, sentido, lambda chave, proximo: url(ord=chave, sentido=proximo)),
        'comparar': {'ligado': comparar, 'url': url(comparar=None, diverge=None) if comparar else url(comparar='1'), 'info': info_da_comparacao if comparar else ''},
        'granularidades': [{'chave': g[0], 'rotulo': g[1], 'ativo': g[0] == gran, 'url': url(gran=g[0], nivel='todos')} for g in GRANULARIDADES],
        'dados': [d for d in (indicador_de_vendas(n_ok, dias, not coletado_em, data_hora(coletado_em) if coletado_em else ''), indicador_de_estoque(consultas, link_estoque)) if d],
        'avisos': avisos, 'situacao': situacao,
        'por_pagina': [{'rotulo': str(p), 'url': url(por=p), 'ativo': p == por} for p in POR_PAGINA_OPCOES],
        'total_texto': f'{numero(total)} {unidade_singular if total == 1 else unidade_plural} com os filtros atuais', 'coluna_nome': por_chave[gran][1], 'linhas': linhas, 'vazio': total == 0,
        'filtros_ativos': bool(texto or filtro != 'todos' or diverge), 'url_limpar_tudo': url(q='', nivel='todos', diverge=None),
        'painel': painel_do_mundo(comuns, url_da_tela(base_url, **sem_filtros_na_url(parametros_da_url({})))), 'notas_filtros': notas_dos_filtros(comuns, gran, unidade_plural),
        'paginacao': {
            'numero': pagina_atual, 'total_paginas': total_paginas,
            'texto': 'Nenhum item' if not total else f'Mostrando {numero(ini + 1)}–{numero(fim)} de {numero(total)} {unidade_plural}',
            'url_anterior': url(pag=pagina_atual - 1) if pagina_atual > 1 else '', 'url_proxima': url(pag=pagina_atual + 1) if pagina_atual < total_paginas else '',
            'janela': [{'numero': p, 'url': url(pag=p), 'atual': p == pagina_atual} if p else {'reticencias': True} for p in _janela_de_paginas(pagina_atual, total_paginas)],
        },
    }
