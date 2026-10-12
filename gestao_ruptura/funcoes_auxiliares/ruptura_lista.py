# gestao_ruptura/funcoes_auxiliares/ruptura_lista.py
#
# Função Objetivo: A LISTA da tela "Previsão de Ruptura de estoque" (12/10/2026): o que aparece quando nenhum item está aberto. Uma linha por Produto (SKU), por Anúncio (MLB) ou por Código ML
# (decisão do Matheus: "a tela não pode fazer apenas por SKU"), com o estoque do Full, o ritmo de vendas do Full, a COBERTURA em dias, a data da ruptura, até quando enviar e o nível,
# em ordem de URGÊNCIA. Clicar numa linha abre o detalhe com a curva (ruptura_pagina.py). LÊ SÓ DO BANCO: nada aqui chama o Mercado Livre nem o ERP.
#
# REGRAS DO MATHEUS que moram aqui (as contas em si estão em ruptura_calculo.py; a regra do estoque considerado, em ruptura_estoque.py):
#   - O ESTOQUE da lista é o do FULL, lido da última consulta salva de cada Código ML (a mesma da tela "Estoque no Full"). O de um SKU ou de um MLB é a soma dos Códigos dele.
#   - O RITMO da lista é só o das vendas que SAÍRAM DO FULL (o estoque é o do Full): unidades dos dias completos ÷ nº de dias completos, com as mesmas regras da tela de Vendas.
#     O período é o "ritmo dos últimos N dias" escolhido na tela. Venda cancelada não conta; "ausente não é zero".
#   - O prazo até vender, os dias para chegar antes da ruptura e a folga são UM só para a lista inteira (campos no topo); no detalhe de cada item dá para testar outros. Os níveis (ruptura, crítico, baixo, alto) são os
#     PROVISÓRIOS de ruptura_calculo.py. Esta lista é só do mundo ENVIOS FULL (a do Fora do Full é a de ruptura_lista_fora.py: outro mundo, outra lista).
#   - Item sem consulta de estoque NÃO vira "estoque zero": fica em "Sem estoque lido" ("ausente não é zero"). Item com só parte dos Códigos lidos fica marcado "Estoque parcial".
#   - DUAS REFERÊNCIAS de urgência e de quanto enviar (decisão do Matheus, 12/10/2026): a do MERCADO LIVRE (lida da consulta de reposição salva: ruptura_estoque.resumir_ml) e a do SISTEMA (a regra da tela:
#     ruptura_calculo.urgencia_do_sistema e sugestao_do_sistema). A escolhida manda na ordem "Mais urgentes primeiro" e aparece grande; a outra aparece pequena na mesma célula. O filtro "Divergem" (à parte dos
#     cartões de situação, combina com eles) mostra os itens em que as duas urgências estão em faixas diferentes. Item sem número do ML NUNCA vira urgência ou quantidade zero: fica "sem número do ML".
#
# * [EXPLICAÇÃO] → DE ONDE VEM CADA GRANULARIDADE: o estoque do Full mora no Código ML. Um MLB pode ter mais de um Código (variações) e um Código pode ser usado por mais de um MLB:
#                  nesse caso o estoque é o MESMO para os dois, e a cobertura do MLB (que olha só as vendas dele) pode ficar maior do que a real. A linha ganha o selo "Estoque compartilhado".
#                  Quem entra na lista é decidido pelo ANÚNCIO, não pelo Código ML: ver "QUEM É DO FULL" (anuncio_e_do_full), a mesma regra do filtro FULL do Hub de Anúncios.
# * [EXPLICAÇÃO] → COMO FICA RÁPIDA (~1000 SKUs): as vendas do Full do período entram numa consulta só (lista_vendas_ml.unidades_do_full_por_dia) e o estoque, em 2 consultas
#                  (full_estoque_ml.estoque_full_dos_codigos). O "A caminho" (consulta de reposição, a parte pesada) só é lido para as linhas da PÁGINA, a não ser que a opção "Considerar as
#                  unidades a caminho" esteja marcada: aí ele entra na cobertura (muda nível e ordem) e é lido para TODOS os Códigos, em lotes de LOTE_DO_A_CAMINHO (uma consulta por lote, nunca por
#                  Código). Textos e endereços só são montados para a página mostrada. Nenhuma consulta por SKU, por MLB ou por Código.
# * [EXPLICAÇÃO] → O que o ML recomenda (urgência e sugestão) também vem da consulta de reposição, mas o RESUMO de cada consulta é guardado no cache pelo id dela (full_estoque_ml.ml_dos_codigos): depois da
#                  primeira leitura só a consulta NOVA é lida de novo. Ele é lido para TODOS os Códigos porque a ordem, o filtro "Divergem" e a faixa Situação olham a lista inteira.

import unicodedata
from datetime import timedelta

from django.urls import reverse

from gestao_full.funcoes_auxiliares.full_estoque_ml import HORAS_PARA_DESATUALIZADO, a_caminho_dos_codigos, estoque_do_erp, estoque_full_dos_codigos, ml_dos_codigos
from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares import ruptura_estoque as full
from gestao_ruptura.funcoes_auxiliares.ruptura_filtros import notas_dos_filtros, mlbs_permitidos, painel_do_mundo, passa_no_filtro, sem_filtros_na_url
from gestao_ruptura.funcoes_auxiliares.ruptura_parametros import campos_escondidos, para_url
from gestao_ruptura.funcoes_auxiliares.ruptura_avisos import aviso, aviso_de_contagem
from gestao_ruptura.funcoes_auxiliares.ruptura_situacao import CHAVES_DE_NIVEL, contar_consultas, indicador_de_estoque, indicador_de_vendas, montar_situacao
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import aviso_do_deposito, data, data_curta, data_do_ml, em_dias, inteiro, pct as pct_texto, plural, porque_da_urgencia_do_sistema, quantidade_do_ml, reais, un_dia
from gestao_vendas.funcoes_auxiliares.lista_vendas_ml import unidades_do_full_por_dia
from mercado_livre.funcoes_auxiliares.logistica_do_anuncio import logistica_e_de_fora_do_full, logistica_e_do_full
from gestao_vendas.funcoes_auxiliares.vendas_ml import data_hora, numero, url_da_tela

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


ORDENS = (
    ('urgencia', 'Mais urgentes primeiro'),
    ('cobertura', 'Maior cobertura (dias)'),
    ('ritmo', 'Maior ritmo (un/dia)'),
    ('estoque', 'Maior estoque'),
    ('nome', 'Nome (A–Z)'),
)
# a ordem de urgência: quanto menor o número, mais urgente (o que não tem nível calculado vem depois, "sem estoque lido" por último)
URGENCIA = {'ruptura': 0, 'critico': 1, 'baixo': 2, 'sem_nivel': 3, 'alto': 4, 'sem_previsao': 5, 'sem_estoque': 6}
RANK_DA_URGENCIA_ML = {u: i for i, u in enumerate(calc.URGENCIAS_DO_ML)}   # URGENT 0 ... EXCEDENT 5; sem número do ML = SEM_NUMERO_DO_ML
SEM_NUMERO_DO_ML = 9
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

# Função Objetivo: Uma entidade da lista (o que a linha representa), do jeito que as três granularidades usam: chave, sku (para abrir o detalhe), título, foto, selos, ids (os chips pequenos), os
# Códigos ML dela, texto de busca e, no MLB e no SKU, a lista de quem divide estoque com ela.
def _entidade(chave, sku, titulo, subtitulo, marca, foto, selos, ids, codigos, busca, compartilha=()):
    return {'chave': chave, 'sku': sku, 'titulo': titulo, 'subtitulo': subtitulo, 'marca': marca, 'foto': foto, 'selos': selos, 'ids': ids, 'codigos': codigos,
            'busca': _sem_acento(' '.join(str(p) for p in busca if p)), 'titulo_ordem': _sem_acento(titulo), 'compartilha': list(compartilha)}


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
            ids = [f'SKU {sku}', plural(len(mlbs), 'anúncio', 'anúncios'), plural(len(codigos), 'Código ML', 'Códigos ML') if codigos else 'sem Código ML']
            entidades.append(_entidade(sku, sku, produto.get('titulo') or '(SKU fora do cadastro de Produto)', '', produto.get('marca', ''), produto.get('imagem', ''), [], ids, codigos,
                                       [sku, produto.get('titulo'), produto.get('marca'), produto.get('ean')] + mlbs + sorted(codigos), outros))
    elif gran == 'mlb':
        for mlb, anuncio in anuncios.items():
            if mlb not in do_full or not passa_no_filtro([mlb], permitidos):
                continue
            codigos = {c for _, c in anuncio['variacoes'] if c}
            skus = sorted(cad['candidatos'].get(mlb, {}))
            sku = skus[0] if skus else ''
            produto = produtos.get(sku) or {}
            outros_mlbs = sorted({m for c in codigos for m in codigos_cad[c]['mlbs'] if m != mlb})
            codigo_txt = (f'Código ML {sorted(codigos)[0]}' if len(codigos) == 1 else plural(len(codigos), 'Código ML', 'Códigos ML')) if codigos else 'sem Código ML'
            ids = [mlb, (f'SKU {sku}' + (f' +{len(skus) - 1}' if len(skus) > 1 else '')) if sku else 'sem SKU', codigo_txt]
            entidades.append(_entidade(mlb, sku, anuncio['titulo'] or produto.get('titulo') or 'Título indisponível', '', produto.get('marca', ''), anuncio['imagem'] or produto.get('imagem', ''),
                                       anuncio['selos'], ids, codigos, [mlb, anuncio['titulo'], sku, produto.get('marca'), produto.get('ean')] + sorted(codigos), outros_mlbs))
    else:
        for codigo, dados_do_codigo in codigos_cad.items():
            if not (dados_do_codigo['mlbs'] & do_full) or not passa_no_filtro(dados_do_codigo['mlbs'] & do_full, permitidos):
                continue
            skus = sorted(dados_do_codigo['skus'])
            sku = skus[0] if skus else ''
            produto = produtos.get(sku) or {}
            mlbs = sorted(dados_do_codigo['mlbs'])
            foto = next((anuncios[m]['imagem'] for m in mlbs if anuncios.get(m, {}).get('imagem')), '') or produto.get('imagem', '')
            ids = [(f'SKU {sku}' + (f' +{len(skus) - 1}' if len(skus) > 1 else '')) if sku else 'sem SKU', plural(len(mlbs), 'anúncio', 'anúncios')]
            entidades.append(_entidade(codigo, sku, codigo, produto.get('titulo', ''), produto.get('marca', ''), foto, [], ids, {codigo},
                                       [codigo, produto.get('titulo'), sku, produto.get('marca'), produto.get('ean')] + mlbs, skus[1:]))
    return entidades


# ==================================================== o cálculo de cada linha (todas as linhas, sem texto) ====================================================

# Função Objetivo: Os números de UMA entidade: o estoque do Full (soma dos Códigos), o ritmo do Full no período e no recente, a projeção, o nível e a categoria do filtro. `cat` é uma de
# ruptura | critico | baixo | alto | sem_previsao (sem venda no ritmo, ou nenhum dia completo) | sem_estoque (nenhum Código com estoque lido) | sem_nivel (sem lead time).
# * [EXPLICAÇÃO] → Estoque zerado é "ruptura" mesmo sem ritmo: não há o que vender. Sem estoque LIDO nunca é ruptura (ausente não é zero). Com a opção "Contar o que está a caminho" marcada,
#                  o "estoque" desta conta já inclui o a caminho (ruptura_estoque.estoque_para_cobertura): item zerado com unidades a caminho deixa de ser "ruptura".
def _calcular_linha(e, gran, dados, cartoes, ctx):
    hoje = ctx['hoje']
    por_dia = dados['dias'][gran].get(e['chave'], {})
    ritmo_p = calc.ritmo_da_janela(ctx['jan_p'], por_dia, dados['estados'])
    ritmo_r = ritmo_p if ctx['mesmo_ritmo'] else calc.ritmo_da_janela(ctx['jan_r'], por_dia, dados['estados'])
    resumo = full.somar_codigos(e['codigos'], cartoes)
    if ctx['caminho']:
        full.preencher_a_caminho(resumo, e['codigos'], cartoes)   # com a opção marcada o a caminho entra na cobertura: precisa estar preenchido em TODAS as linhas
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
            nivel = calc.nivel_do_estoque(projecao, ctx['lead'], ctx['folga'])
            cat = nivel or 'sem_nivel'
        else:
            cat = 'sem_previsao'
    # a sugestão do Sistema de quanto enviar (só quando há ritmo e a ruptura é calculável; sem estoque lido nunca vira "zero")
    sugestao = None
    if projecao and projecao['situacao'] in ('normal', 'zerado'):
        sugestao = calc.sugestao_do_sistema(estoque, media, ctx['lead'], ctx['folga'])
    # as duas urgências (Sistema e Mercado Livre) na mesma língua, para ordenar e comparar; `urg` é a da referência escolhida
    envio = calc.envio(projecao, ctx['lead'], hoje, ctx['ante']) if projecao and projecao['situacao'] == 'normal' else None
    ml = full.resumir_ml(e['codigos'], cartoes)
    urg_sistema, urg_ml = calc.urgencia_do_sistema(cat, envio), ml['urgencia']
    comparacao = None
    if not ctx['mesmo_ritmo'] and estoque and estoque > 0 and media is not None:
        comparacao = calc.comparar_ritmos(ritmo_r['media'], media)
        if comparacao and media <= 0 and not ritmo_r['media']:
            comparacao = None   # nenhuma venda nos dois ritmos: não há o que comparar
    return {'e': e, 'chave': e['chave'], 'cat': cat, 'nivel': nivel, 'resumo': resumo, 'estoque': estoque, 'ritmo_p': ritmo_p, 'ritmo_r': ritmo_r, 'media': media, 'projecao': projecao, 'sugestao': sugestao,
            'envio': envio, 'ml': ml, 'urg_sistema': urg_sistema, 'urg_ml': urg_ml, 'diverge': calc.urgencias_divergem(urg_sistema, urg_ml),
            'dias_exatos': projecao['dias_exatos'] if projecao and projecao['situacao'] in ('normal', 'zerado') else None,
            'sentido': comparacao['sentido'] if comparacao else '', 'pct': comparacao['pct'] if comparacao else None,
            'un': ritmo_p['unidades'], 'fat': sum(v for d, v in dados['fat'][gran].get(e['chave'], {}).items() if d in ctx['completos_p']), 'titulo_ordem': e['titulo_ordem']}


# Função Objetivo: Põe as linhas na ordem escolhida. "Mais urgentes primeiro" com a referência SISTEMA = ruptura, crítico, baixo, alto, sem previsão, sem estoque lido; dentro de cada nível, quem acaba antes (e,
# no empate, quem vende mais por dia). Com a referência MERCADO LIVRE = a urgência do ML (Urgente, Esta semana, Próxima semana, Em 2 semanas, Sem urgência, Excedente) e, só para desempatar, a ordem do
# Sistema; quem não tem número do ML vai para o fim. Nas outras ordens, quem não tem o valor (ex.: sem ritmo) fica no fim; empate desempata pelo nome.
def _ordenar(linhas, ordem, ref_urg='sistema'):
    if ordem == 'urgencia':
        def chave(l):
            do_sistema = (URGENCIA[l['cat']], l['dias_exatos'] if l['dias_exatos'] is not None else FIM_DO_TEMPO, -(l['media'] or 0), l['titulo_ordem'])
            if ref_urg == 'ml':
                return (RANK_DA_URGENCIA_ML.get(l['urg_ml'], SEM_NUMERO_DO_ML) if l['urg_ml'] else SEM_NUMERO_DO_ML,) + do_sistema
            return do_sistema
        return sorted(linhas, key=chave)
    if ordem == 'nome':
        return sorted(linhas, key=lambda l: l['titulo_ordem'])
    valor = {'cobertura': lambda l: l['dias_exatos'], 'ritmo': lambda l: l['media'], 'estoque': lambda l: l['estoque']}[ordem]
    com_valor = [l for l in linhas if valor(l) is not None]
    sem_valor = sorted((l for l in linhas if valor(l) is None), key=lambda l: l['titulo_ordem'])
    com_valor.sort(key=lambda l: l['titulo_ordem'])
    com_valor.sort(key=valor, reverse=True)
    return com_valor + sem_valor


# ==================================================== o texto de cada linha (só as da página) ====================================================

# Função Objetivo: A sugestão do SISTEMA de uma linha como texto: (texto, dica, classe). Texto None = sem número (sem estoque lido, sem ruptura prevista).
def _quantidade_do_sistema(l, ctx):
    sug, lead = l['sugestao'], ctx['lead']
    if sug is None:
        return None, ('Sem estoque lido: não há como sugerir a quantidade.' if l['cat'] == 'sem_estoque' else 'Sem ruptura prevista neste ritmo (ou sem dias coletados): não há quantidade a sugerir.')
    folga = plural(ctx['folga'], 'dia', 'dias')
    if sug['qtd'] == 0:
        return '0', 'Sugestão do Sistema: 0 un, porque a folga está em 0 dias (a quantidade é o ritmo × a folga). Digite a folga desejada no cartão "Regras de envio".'
    return numero(sug['qtd']), (f'Sugestão do Sistema: {numero(sug["qtd"])} un = ritmo ({un_dia(l["media"])} un/dia) × folga ({folga}). É a quantidade que acrescenta {folga} de estoque: a nova ruptura vem {folga} depois da atual '
                                f'(ou depois da chegada, que leva {plural(lead, "dia", "dias")}, se o estoque acabar antes dela).')


# Função Objetivo: A quantidade da referência escolhida como NÚMERO (None sem número): a do ML (numa faixa vale o começo dela; "não repor" é 0) ou a sugestão do Sistema. Serve para comparar com o depósito.
def _quantidade_numerica(l, ctx):
    if ctx['ref_qtd'] == 'ml':
        return l['ml']['sugestao_min']
    return l['sugestao']['qtd'] if l['sugestao'] is not None else None


# Função Objetivo: A célula "Enviar (un)": a quantidade da referência escolhida em grande (qtd_txt) e a da outra pequena (qtd_sub, "Sistema: 127" ou "ML: 100–150"). Devolve (texto, apoio, classe, dica). Sem número
# na referência escolhida: "—" e o motivo no apoio.
def _celula_de_quanto_enviar(l, ctx):
    ref = ctx['ref_qtd']
    do_sistema, dica_sistema = _quantidade_do_sistema(l, ctx)
    do_ml, dica_ml = quantidade_do_ml(l['ml'])
    principal, dica_principal, outra, rotulo_outra = (do_ml, dica_ml, do_sistema, 'Sistema') if ref == 'ml' else (do_sistema, dica_sistema, do_ml, 'ML')
    if principal is None:
        apoio = 'sem número do ML' if ref == 'ml' else ('sem estoque' if l['cat'] == 'sem_estoque' else '')
        return '—', apoio, '', f'{dica_principal} {rotulo_outra}: {outra if outra is not None else "sem número"}.'
    apoio = f'{rotulo_outra}: {outra}' if outra is not None else f'{rotulo_outra}: sem número'
    outra_dica = dica_sistema if ref == 'ml' else dica_ml
    return principal, apoio, ('qtd' if principal != '0' else ''), f'{dica_principal} Outra referência — {outra_dica}'


# Função Objetivo: A célula "Urgência": o selo da referência escolhida (urg_selo) e, pequena, a outra ("Sistema: Urgente" / "ML: Esta semana", em laranja quando as duas divergem). Sem número na escolhida:
# urg_selo None e o motivo em urg_vazio. Devolve o dicionário de campos `urg_*` para a linha.
def _celula_de_urgencia(l, ctx):
    ml_principal = ctx['ref_urg'] == 'ml'
    ml, sem_ml, sem_leitura = l['ml'], 'sem número do ML', 'sem estoque lido'
    selo_ml, selo_sistema = full.selo_da_urgencia(l['urg_ml']), full.selo_da_urgencia(l['urg_sistema'])
    selo_principal, selo_outra = (selo_ml, selo_sistema) if ml_principal else (selo_sistema, selo_ml)
    rotulo_outra, vazio_outra = ('Sistema', sem_leitura) if ml_principal else ('ML', sem_ml)
    apoio = f'{rotulo_outra}: {selo_outra["label"] if selo_outra else vazio_outra}'
    if selo_ml:
        texto_ml = f'Mercado Livre: {selo_ml["label"]}' + (f' (prazo para repor: {data_do_ml(ml["prazo"])})' if ml['prazo'] else '')
    else:
        texto_ml = f'Mercado Livre: {sem_ml} ({ml["motivo"] or "a consulta não trouxe a urgência"})'
    if selo_sistema:
        texto_sistema = f'Sistema: {selo_sistema["label"]} — {porque_da_urgencia_do_sistema(l["cat"], l["envio"])}'
    else:
        texto_sistema = f'Sistema: {sem_leitura}'
    dica = f'{texto_ml}. {texto_sistema}.' + (' As duas referências estão em faixas diferentes.' if l['diverge'] else '')
    return {'urg_selo': selo_principal, 'urg_vazio': sem_ml if ml_principal else sem_leitura, 'urg_sub': apoio, 'urg_sub_classe': 'diverge' if l['diverge'] else '', 'urg_dica': dica}


# Função Objetivo: Transforma os números de uma linha nos textos que a tela mostra (estoque, vendas, ritmo, cobertura, ruptura, enviar até, urgência, quanto enviar, nível e os selos de atenção). Cada célula tem UM valor e
# UMA linha de apoio (a tela é rígida na vertical); o resto vai no `title` (tooltip) da célula.
def _apresentar(l, gran, ctx, base_url):
    e, r, hoje, lead, dias, recente = l['e'], l['resumo'], ctx['hoje'], ctx['lead'], ctx['dias'], ctx['recente']

    # ---- estoque (do Full, considerado) ----
    conta = full.texto_da_conta(r, numero, ctx['caminho'])
    if r['estado'] == 'sem_leitura':
        motivo = 'a última consulta de estoque deu erro' if r['com_erro'] and not r['sem_consulta'] else 'ainda não há consulta de estoque salva'
        estoque_txt, estoque_sub, estoque_classe = '—', 'sem leitura', 'atencao'
        estoque_dica = f'Nenhum Código ML deste item tem o estoque do Full lido ({motivo}). Abra o item e clique em "Consultar no Mercado Livre" (ou faça a consulta na tela "Estoque no Full"). Sem leitura não é estoque zero: o item fica fora dos níveis.'
    else:
        estoque_txt = numero(l['estoque'])   # com a opção "Contar o que está a caminho" marcada, já inclui o a caminho
        estoque_classe = 'atencao' if r['estado'] == 'parcial' else ''
        if r['estado'] == 'parcial':
            estoque_sub = f'parcial {r["n_lidos"]}/{r["n_codigos"]}'
        elif r['a_caminho'] and ctx['caminho']:
            estoque_sub = f'{numero(r["considerado"])} + {numero(r["a_caminho"])} a caminho'
        elif r['a_caminho']:
            estoque_sub = f'+{numero(r["a_caminho"])} a caminho'
        else:
            estoque_sub = ''
        extras = [f'Consulta mais antiga entre os Códigos: {r["idade"]}.']
        if r['desatualizados']:
            extras.append(f'{plural(len(r["desatualizados"]), "Código está", "Códigos estão")} com a consulta de estoque de mais de {HORAS_PARA_DESATUALIZADO} h.')
        if r['a_caminho'] and ctx['caminho']:
            extras.append(f'O a caminho (enviado e ainda não recebido; é só hipótese) está SOMADO ao estoque: +{numero(r["a_caminho"])}{" (parcial)" if r["a_caminho_parcial"] else ""}, como se já estivesse no Full hoje.')
        elif r['a_caminho']:
            extras.append(f'A caminho (enviado e ainda não recebido; é só hipótese): +{numero(r["a_caminho"])}{" (parcial)" if r["a_caminho_parcial"] else ""}. Não entra na cobertura.')
        estoque_dica = f'Estoque considerado no Full: {conta} {" ".join(extras)}'

    # ---- vendas e ritmo (só o que saiu do Full) ----
    media, ritmo_r, n_ok = l['media'], l['ritmo_r'], l['ritmo_p']['n_completos']
    vendas_dica = (f'Unidades que saíram do Full e o faturamento delas, só nos {plural(n_ok, "dia completo", "dias completos")} dos últimos {dias} dias (de {data(ctx["de"])} até ontem): é o mesmo volume que '
                   f'dá o ritmo (unidades ÷ dias completos). Hoje (parcial) e os dias sem coleta ficam de fora; venda cancelada não conta.')
    if media is None:
        ritmo_txt, ritmo_dica = '—', f'Nenhum dos últimos {dias} dias está completo na coleta da conta toda: sem ritmo de vendas.'
    else:
        ritmo_txt, ritmo_dica = un_dia(media), f'Média de {un_dia(media)} un/dia (Full) nos {n_ok} dias completos dos últimos {dias}.'
    ritmo_sub, ritmo_sub_classe = '', ''
    if l['sentido'] in ('acelerou', 'caiu'):
        ritmo_sub, ritmo_sub_classe = ('↑ acelerou', 'alerta') if l['sentido'] == 'acelerou' else ('↓ caiu', 'info')
        ritmo_dica += f' Nos últimos {recente} dias: {un_dia(ritmo_r["media"])} un/dia' + (f' ({pct_texto(l["pct"])}).' if l['pct'] is not None else '.')

    # ---- cobertura, ruptura e envio ----
    projecao, cat = l['projecao'], l['cat']
    cob_sub, barra_pct, ruptura_txt, ruptura_sub, enviar_txt, enviar_sub, enviar_classe, enviar_dica = '', None, '—', '', '—', '', '', ''
    if cat == 'ruptura':
        cob_txt, barra_pct = '0', 0
        ruptura_txt, ruptura_sub = 'Agora', 'estoque zerado'
        enviar_txt, enviar_classe = 'Agora', 'vencido'
        enviar_sub = f'chega em {data_curta(hoje + timedelta(days=lead), hoje)}' if lead is not None else ''
        enviar_dica = f'Estoque zerado: envie o quanto antes. Com prazo de {plural(lead, "dia", "dias")}, o produto só volta a ficar disponível em {data(hoje + timedelta(days=lead))}.'
        cob_dica = f'O estoque do Full está zerado{" (contando o que está a caminho)" if ctx["caminho"] else ""}: o produto já está em ruptura.'
    elif projecao and projecao['situacao'] == 'normal':
        dias_inteiros = projecao['dias']
        cob_txt = numero(dias_inteiros)
        referencia = max(lead or 0, 1) * BARRA_EM_LEADS
        barra_pct = min(100, round(l['dias_exatos'] / referencia * 100))
        ruptura_txt, ruptura_sub = data_curta(projecao['data'], hoje), em_dias(dias_inteiros)
        envio = l['envio']
        regra = f'ruptura − prazo ({lead} d) − chegar antes ({ctx["ante"]} d)'
        if envio and envio['estado'] == 'vencido':
            enviar_txt, enviar_classe, enviar_sub = 'Atrasado', 'vencido', f'vão faltar {envio["faltam_dias"]} d'
            enviar_dica = (f'O último dia para enviar foi {data(envio["ultimo_dia"])}: enviando hoje o produto só fica disponível em {data(envio["chegada"])} '
                           f'e vão faltar cerca de {plural(envio["faltam_dias"], "dia", "dias")} de estoque.')
        elif envio and envio['estado'] == 'ja':
            sobra = envio['sobra_na_chegada']
            enviar_txt, enviar_classe, enviar_sub = 'Enviar já', 'alerta', 'chega no dia da ruptura' if sobra == 0 else f'chega {sobra} d antes'
            enviar_dica = (f'A data recomendada ({data(envio["enviar_ate"])} = {regra}) já passou, mas ainda dá tempo: enviando hoje, o produto chega em {data(envio["chegada"])}, '
                           f'{"no próprio dia da ruptura" if sobra == 0 else plural(sobra, "dia", "dias") + " antes da ruptura"} (o desejado é chegar {ctx["ante"]} d antes). O último dia possível é {data(envio["ultimo_dia"])}.')
        elif envio:
            enviar_txt = data_curta(envio['enviar_ate'], hoje)
            enviar_sub, enviar_classe = ('hoje, último dia', 'alerta') if envio['estado'] == 'hoje' else (em_dias(envio['em_dias']), '')
            enviar_dica = f'Data recomendada para enviar: {data(envio["enviar_ate"])} = {regra}. O último dia possível (chegando em cima da ruptura) é {data(envio["ultimo_dia"])}.'
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

    # ---- quanto enviar e urgência: a referência escolhida em grande, a outra pequena na mesma célula ----
    qtd_txt, qtd_sub, qtd_classe, qtd_dica = _celula_de_quanto_enviar(l, ctx)
    qtd_deposito, qtd_deposito_dica = aviso_do_deposito(_quantidade_numerica(l, ctx), ctx['erp'].get(e['sku']))   # a quantidade passa do que há no depósito (ERP)? Aviso no lugar certo, número inteiro
    if qtd_deposito:
        qtd_dica = f'{qtd_deposito_dica} {qtd_dica}'
    urg = _celula_de_urgencia(l, ctx)

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

    # ---- selos de atenção (vão junto dos selos do anúncio; o que não cabe na linha some inteiro) ----
    avisos = []
    if r['estado'] == 'parcial':
        faltando = r['sem_consulta'] + r['com_erro']
        avisos.append({'texto': 'Estoque parcial', 'classe': 'atencao', 'dica': f'Só {r["n_lidos"]} de {r["n_codigos"]} Códigos ML têm estoque lido; não entram na soma: {", ".join(faltando)}.'})
    if e['compartilha'] and gran == 'mlb':
        avisos.append({'texto': 'Estoque compartilhado', 'classe': 'info', 'dica': f'O estoque do Código ML deste anúncio também é usado por {", ".join(e["compartilha"])}. O estoque é o mesmo para todos: '
                                                                                   f'a cobertura aqui olha só as vendas deste anúncio e pode estar maior do que a real. Veja pelo Código ML.'})
    if e['compartilha'] and gran in ('sku', 'codigo'):
        avisos.append({'texto': 'Código compartilhado', 'classe': 'info', 'dica': f'Algum Código ML deste item também aparece no SKU {", ".join(e["compartilha"])}: o estoque é o mesmo para os dois.'})
    if r['desatualizados'] and r['estado'] != 'sem_leitura':
        avisos.append({'texto': 'Consulta antiga', 'classe': 'info', 'dica': f'{plural(len(r["desatualizados"]), "Código", "Códigos")} com a consulta de estoque de mais de {HORAS_PARA_DESATUALIZADO} h.'})

    link = ''
    if e['sku']:
        link = url_da_tela(base_url, sku=e['sku'], gran=gran if gran != 'sku' else None, item=e['chave'] if gran != 'sku' else None, **para_url(ctx['comuns']))
    return {
        'chave': e['chave'], 'titulo': e['titulo'], 'subtitulo': e['subtitulo'], 'foto': e['foto'], 'selos': e['selos'], 'avisos': avisos, 'ids': e['ids'], 'codigo': gran == 'codigo',
        'url_detalhe': link, 'motivo': 'Sem SKU no cadastro de anúncios: a curva abre por produto.', 'cat': cat, 'em_ruptura': cat == 'ruptura',
        'estoque_txt': estoque_txt, 'estoque_sub': estoque_sub, 'estoque_classe': estoque_classe, 'estoque_dica': estoque_dica,
        'vendas_txt': f'{numero(l["un"])} un', 'vendas_sub': reais(l['fat']), 'vendas_dica': vendas_dica,
        'ritmo_txt': ritmo_txt, 'ritmo_sub': ritmo_sub, 'ritmo_sub_classe': ritmo_sub_classe, 'ritmo_dica': ritmo_dica,
        'cob_txt': cob_txt, 'cob_sub': cob_sub, 'cob_dica': cob_dica, 'barra_pct': barra_pct, 'barra_classe': l['nivel'] or 'neutro',
        'ruptura_txt': ruptura_txt, 'ruptura_sub': ruptura_sub, 'enviar_txt': enviar_txt, 'enviar_sub': enviar_sub, 'enviar_classe': enviar_classe, 'enviar_dica': enviar_dica,
        'qtd_txt': qtd_txt, 'qtd_sub': qtd_sub, 'qtd_classe': qtd_classe, 'qtd_dica': qtd_dica, 'qtd_deposito': qtd_deposito, **urg,
        'nivel_rotulo': nivel_rotulo, 'nivel_classe': nivel_classe, 'nivel_dica': nivel_dica,
    }


# ==================================================== a lista ====================================================

# Função Objetivo: Tudo da lista a partir da query string. Parâmetros: gran (sku|mlb|codigo), q (busca), nivel (todos|ruptura|critico|baixo|alto|sem_previsao|sem_estoque), diverge (1 = só os que divergem; combina com o nivel; o
# antigo nivel=divergem de endereços salvos vale como diverge=1), ord, por e pag; o ritmo
# (dias), o prazo, os dias para chegar antes da ruptura, a folga, a opção "Contar o que está a caminho" (caminho=1) e as referências (ref_urg, ref_qtd) chegam já lidos em `comuns`
# (ruptura_parametros, mundo Full). Parâmetro inválido volta ao padrão. Qualquer mudança de filtro, busca ou ordem volta para a página 1.
def montar_lista(parametros, base_url, hoje, comuns):
    dias, lead, ante, folga, recente, caminho = comuns['dias'], comuns['lead'], comuns['ante'], comuns['folga'], comuns['recente'], comuns['caminho']
    por_chave = {g[0]: g for g in GRANULARIDADES}
    gran = _escolher(parametros, 'gran', por_chave, GRANULARIDADE_PADRAO)
    _, _, ajuda, unidade_plural, unidade_singular = por_chave[gran]
    texto = (parametros.get('q') or '').strip()
    filtro = _escolher(parametros, 'nivel', NIVEIS_VALIDOS, 'todos')
    diverge = (parametros.get('diverge') or '').strip() == '1' or (parametros.get('nivel') or '').strip() == 'divergem'   # "nivel=divergem" é o endereço antigo (quando era um cartão de nível)
    ordem = _escolher(parametros, 'ord', dict(ORDENS), 'urgencia')
    por = inteiro(parametros.get('por'), 1, 1000)
    por = por if por in POR_PAGINA_OPCOES else POR_PAGINA_PADRAO
    numero_da_pagina = inteiro(parametros.get('pag'), 1, 100000) or 1

    ref_urg = comuns['ref_urg']
    ref_qtd = 'sistema' if comuns['ref_qtd'] == 'manual' else comuns['ref_qtd']   # a lista não tem quantidade digitada: "Minha quantidade" só existe no detalhe de um item
    padroes = {'gran': GRANULARIDADE_PADRAO, 'nivel': 'todos', 'ord': 'urgencia', 'por': POR_PAGINA_PADRAO, 'pag': 1}

    # * [EXPLICAÇÃO] → O endereço leva só o que a pessoa mudou: o que é da lista (Ver por, busca, nível, "Divergem", ordem, itens por página e página) sai daqui e as regras (ritmo, prazo, chegar antes, folga, "a caminho" e as
    #                  referências, dos dois mundos) saem de ruptura_parametros.para_url, a mesma fonte do detalhe.
    def parametros_da_url(mudancas):
        atuais = {'gran': gran, 'q': texto, 'nivel': filtro, 'diverge': '1' if diverge else None, 'ord': ordem, 'por': por, 'pag': numero_da_pagina}
        atuais.update(mudancas)
        if 'pag' not in mudancas:
            atuais['pag'] = 1
        return {**{k: (None if v == padroes.get(k) else v) for k, v in atuais.items()}, **para_url(comuns)}

    def url(**mudancas):
        return url_da_tela(base_url, **parametros_da_url(mudancas))

    # ---- dados: vendas do Full por dia (1 leitura), estoque do Full (2 leituras) e a conta de cada linha ----
    de = hoje - timedelta(days=max(dias, recente))
    dados = unidades_do_full_por_dia(de, hoje)
    estados = dados['estados']
    jan_p = [hoje - timedelta(days=i) for i in range(dias, -1, -1)]
    ctx = {'hoje': hoje, 'dias': dias, 'recente': recente, 'lead': lead, 'ante': ante, 'folga': folga, 'comuns': comuns, 'caminho': caminho, 'de': hoje - timedelta(days=dias), 'mesmo_ritmo': dias <= recente,
           'ref_urg': ref_urg, 'ref_qtd': ref_qtd,
           'jan_p': jan_p, 'jan_r': [hoje - timedelta(days=i) for i in range(recente, -1, -1)], 'completos_p': {d for d in jan_p if estados.get(d) == 'ok'}}
    permitidos = mlbs_permitidos(comuns)   # os filtros do Hub: None = sem filtro ativo (nada é lido do Hub)
    entidades = _entidades(gran, dados, permitidos)
    cartoes = estoque_full_dos_codigos(sorted(set().union(*(e['codigos'] for e in entidades)))) if entidades else {}
    if caminho:
        _ler_a_caminho_de_todos(cartoes)   # o a caminho entra na cobertura de CADA linha (muda nível e ordem): lido para todos os Códigos, em lotes
    ml_dos_codigos(cartoes)   # o que o Mercado Livre recomenda (urgência e sugestão), de todos os Códigos: a ordem, o "Divergem" e a contagem olham a lista inteira (resumos em cache)
    todas = [_calcular_linha(e, gran, dados, cartoes, ctx) for e in entidades]

    # ---- busca, situação (cartões) e "Divergem" (os números da faixa Situação são sobre o resultado da busca; quem conta é ruptura_situacao.montar_situacao) ----
    n_ok = sum(1 for d in ctx['jan_p'] if estados.get(d) == 'ok')
    coletado_em = dados['coletado_em']
    procurado = _sem_acento(texto)
    base = [l for l in todas if not procurado or procurado in l['e']['busca']]
    filtradas = [l for l in base if (filtro == 'todos' or l['cat'] == filtro) and (l['diverge'] or not diverge)]
    filtradas = _ordenar(filtradas, ordem, ref_urg)
    situacao = montar_situacao(base, filtro, diverge, url, unidade_plural, unidade_singular, lead, folga, sem_dados=n_ok == 0)

    # ---- a página atual: só aqui se lê o "A caminho" e se montam textos e endereços ----
    total = len(filtradas)
    total_paginas = max(1, -(-total // por))
    pagina_atual = min(numero_da_pagina, total_paginas)
    ini = (pagina_atual - 1) * por
    fim = min(total, ini + por)
    da_pagina = filtradas[ini:fim]
    if not caminho:   # com a opção marcada o a caminho já foi lido para todos (e preenchido em cada linha por _calcular_linha)
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
    if ref_urg == 'ml' or ref_qtd == 'ml':
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

    ordens = [{'rotulo': rotulo, 'url': url(**{'ord': chave}), 'ativo': chave == ordem} for chave, rotulo in ORDENS]
    # os campos escondidos do formulário: o que é da lista (Ver por, nível, ordem, itens por página) + o que é do outro mundo; os campos visíveis (busca, ritmo, prazo, chegar antes, folga, caminho e as referências) não viram campo escondido
    ocultos = [{'nome': k, 'valor': v} for k, v in {'gran': gran, 'nivel': filtro, 'diverge': '1' if diverge else None, 'ord': ordem, 'por': por}.items() if v != padroes.get(k) and v is not None] + campos_escondidos(comuns)
    return {
        'gran': gran, 'ajuda': ajuda, 'texto': texto, 'ocultos': ocultos,
        'granularidades': [{'chave': g[0], 'rotulo': g[1], 'ativo': g[0] == gran, 'url': url(gran=g[0], nivel='todos')} for g in GRANULARIDADES],
        'dados': [d for d in (indicador_de_vendas(n_ok, dias, not coletado_em, data_hora(coletado_em) if coletado_em else ''), indicador_de_estoque(consultas, link_estoque)) if d],
        'avisos': avisos, 'situacao': situacao,
        'ordens': ordens, 'por_pagina': [{'rotulo': str(p), 'url': url(por=p), 'ativo': p == por} for p in POR_PAGINA_OPCOES],
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
