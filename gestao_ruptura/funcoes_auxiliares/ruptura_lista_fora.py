# gestao_ruptura/funcoes_auxiliares/ruptura_lista_fora.py
#
# Função Objetivo: A LISTA do mundo FORA DO FULL da tela "Previsão de Ruptura de estoque" (12/10/2026): o que aparece quando nenhum item está aberto e o seletor "Previsão para" está em "Fora do Full". Uma linha por
# Produto (SKU) ou por Anúncio (MLB), com as vendas e o RITMO de fora do Full, o ponto de pedido e a quantidade a pedir pelas Regras de pedido. Clicar numa linha abre o detalhe (a curva) do item no mesmo mundo,
# onde o estoque de fora do Full é DIGITADO para simular a ruptura (ruptura_pagina.py). LÊ SÓ DO BANCO: nada aqui chama o Mercado Livre nem o ERP.
#
# REGRAS DO MATHEUS que moram aqui (a lista do Full está em ruptura_lista.py; as contas, em ruptura_calculo.py):
#   - "Ver por Produto considera todos os anúncios fora do Full daquele produto; ver por MLB lista todos os anúncios fora do Full" (12/10/2026). NÃO existe "Código ML" aqui: o Código ML só existe no Full.
#   - O ESTOQUE de fora do Full ainda não tem fonte ligada à tela: a coluna mostra "—" com o aviso de que ele precisa ser digitado na simulação (no item). Sem leitura NÃO é estoque zero ("ausente não é zero"):
#     por isso a lista não tem cobertura, ruptura, "pedir até", urgência nem nível (tudo isso depende do estoque). Quando a fonte do estoque for escolhida, ele entra na mesma coluna e essas colunas nascem aqui.
#   - O RITMO é só o das vendas que SAÍRAM DE FORA DO FULL (lista_vendas_ml.unidades_por_dia_da_origem, origem 'fora', a regra única de classificar_origem): unidades dos dias completos ÷ nº de dias completos,
#     as mesmas regras da tela de Vendas. Venda cancelada não conta; "ausente não é zero"; "Sem origem informada" não entra.
#   - O prazo até vender, os dias para chegar antes da ruptura e a folga são os das REGRAS DE PEDIDO (cartão 2 do Fora do Full, isolado do Full). Com eles saem as duas colunas que NÃO dependem do estoque:
#     o PONTO DE PEDIDO (ritmo × (prazo + chegar antes): com menos estoque que isso já não dá tempo de pedir chegando N dias antes da ruptura) e a QUANTIDADE A PEDIR (ritmo × folga).
#
# * [EXPLICAÇÃO] → QUEM É "FORA DO FULL" (decisão do Matheus, 12/10/2026: "os números não batem" com o Hub filtrado pelas 6 logísticas): o mesmo que o filtro do Hub de Anúncios com as 6 logísticas que não são FULL (Coleta, Agência,
#                  Flex Puro, Legado, Correios, Por nossa conta), sem os "fósseis" de migração: ruptura_lista.anuncio_e_de_fora_do_full (logística preenchida e diferente de FULL, pergunta que tem UM dono, em
#                  mercado_livre/funcoes_auxiliares/logistica_do_anuncio.py; conferido no banco real: 4.634 = 4.634). Ter ou não Código ML não decide. A lista NÃO traz mais nada
#                  por conta própria: o anúncio do Full que também vendeu por fora (Flex, estoque próprio) não vira linha; ele só é CONTADO num aviso (e, no "Produto", as vendas dele continuam no ritmo do SKU que
#                  tem anúncio fora do Full, com o selo "Também no Full"). O anúncio sem logística conhecida também não entra e também é contado num aviso, para a conta fechar com o Hub.
# * [EXPLICAÇÃO] → COMO FICA RÁPIDA (~1000 SKUs): as vendas de fora do Full do período entram numa consulta só (a mesma função da lista do Full, com outra origem) e o resto é conta em memória. Nenhuma consulta por
#                  SKU ou por MLB e nenhuma leitura de estoque.

import unicodedata
from datetime import timedelta

from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares.ruptura_lista import POR_PAGINA_OPCOES, POR_PAGINA_PADRAO, _entidade, _escolher, _janela_de_paginas, anuncio_e_de_fora_do_full, anuncio_e_do_full, anuncio_fossil, aviso_anuncios_sem_produto
from gestao_ruptura.funcoes_auxiliares.ruptura_filtros import complemento_do_total, mlbs_permitidos, notas_dos_filtros, painel_do_mundo, passa_no_filtro, sem_filtros_na_url
from gestao_ruptura.funcoes_auxiliares.ruptura_parametros import campos_escondidos, para_url
from gestao_ruptura.funcoes_auxiliares.ruptura_avisos import aviso, aviso_de_contagem
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import data, inteiro, pct as pct_texto, plural, reais, un_dia
from gestao_vendas.funcoes_auxiliares.lista_vendas_ml import unidades_por_dia_da_origem
from gestao_vendas.funcoes_auxiliares.vendas_ml import data_hora, numero, url_da_tela

# (chave na URL, rótulo do botão, ajuda no "?", o que a linha é no plural, no singular). Sem "Código ML": ele só existe no Full.
GRANULARIDADES = [
    ('sku', 'Produto (SKU)', 'Cada linha é um produto (SKU) e junta todos os anúncios dele que vendem de fora do Full: o ritmo é o de todas as vendas que saíram de fora do Full.', 'produtos', 'produto'),
    ('mlb', 'Anúncio (MLB)', 'Cada linha é um anúncio (MLB) de fora do Full: logística diferente de FULL (Coleta, Agência, Flex Puro, Legado, Correios, Por nossa conta), a mesma conta do Hub de Anúncios filtrado por elas. O ritmo é o das vendas que saíram de fora do Full naquele anúncio.',
     'anúncios fora do Full', 'anúncio fora do Full'),
]
GRANULARIDADE_PADRAO = 'sku'
ORDENS = (
    ('ritmo', 'Maior ritmo (un/dia)'),
    ('vendas', 'Mais unidades vendidas'),
    ('nome', 'Nome (A–Z)'),
)
ORDEM_PADRAO = 'ritmo'


# ==================================================== as entidades de cada granularidade ====================================================

# Função Objetivo: Monta as entidades da granularidade escolhida a partir do cadastro em lote: SÓ os anúncios de fora do Full (ruptura_lista.anuncio_e_de_fora_do_full, o filtro de 6 logísticas do Hub; fóssil nunca entra) e,
# no Produto (SKU), os produtos que têm pelo menos um deles. `em_full` (só no Produto) = quantos anúncios do Full desse produto tiveram venda de fora (alimenta o selo "Também no Full").
# Devolve (entidades, fora_da_lista): os números dos avisos da lista, para a conta fechar com o Hub: `so_do_full` = produtos (SKU) sem anúncio de fora do Full e com anúncio do Full, ou anúncios (MLB) do Full;
# `so_do_full_vendeu` = quantos desses venderam por fora do Full no período (essas vendas não entram em nenhuma linha); `sem_logistica` = anúncios (MLB) que não são nem do Full nem de fora (sem tipo no banco).
# * [EXPLICAÇÃO] → `permitidos` = os MLBs que os filtros do Hub deixam passar (ruptura_filtros.mlbs_permitidos; None = sem filtro). A linha só aparece se algum anúncio DELA que é de fora do Full passa nos filtros; os números dela
#                  seguem sendo os da entidade inteira.
# * [EXPLICAÇÃO] → Os números de `fora_da_lista` seguem a MESMA BASE das linhas e dos outros avisos da caixa (decisão do Matheus, 12/10/2026: um aviso contando a conta toda ao lado de outro filtrado confunde): com filtros do Hub
#                  ativos, só contam os anúncios que passam neles (`permitidos`); sem filtro, contam o mundo inteiro, como o Hub.
def _entidades(gran, dados, permitidos=None):
    cad, produtos = dados['cad'], dados['produtos']
    anuncios = cad['anuncios']
    por_dia = dados['dias'][gran]
    vendeu_fora = {chave for chave, dias in por_dia.items() if chave and sum(dias.values()) > 0}
    entidades = []
    fora_da_lista = {'so_do_full': 0, 'so_do_full_vendeu': 0,
                     'sem_logistica': sum(1 for mlb, a in anuncios.items() if passa_no_filtro([mlb], permitidos) and not anuncio_fossil(a) and not anuncio_e_do_full(a) and not anuncio_e_de_fora_do_full(a))}
    if gran == 'sku':
        por_dia_mlb = dados['dias']['mlb']
        for sku, info in cad['por_sku'].items():
            mlbs = sorted(m for m in info['mlbs'] if not anuncio_fossil(anuncios.get(m)))
            no_full = [m for m in mlbs if anuncio_e_do_full(anuncios.get(m))]
            fora = [m for m in mlbs if anuncio_e_de_fora_do_full(anuncios.get(m))]
            if not fora:
                if no_full and passa_no_filtro(no_full, permitidos):
                    fora_da_lista['so_do_full'] += 1
                    fora_da_lista['so_do_full_vendeu'] += 1 if sku in vendeu_fora else 0
                continue
            if not passa_no_filtro(fora, permitidos):
                continue
            produto = produtos.get(sku) or {}
            ids = [f'SKU {sku}', plural(len(fora), 'anúncio fora do Full', 'anúncios fora do Full')] + ([f'{len(no_full)} no Full'] if no_full else [])
            e = _entidade(sku, sku, produto.get('titulo') or '(SKU fora do cadastro de Produto)', '', produto.get('marca', ''), produto.get('imagem', ''), [], ids, set(),
                          [sku, produto.get('titulo'), produto.get('marca'), produto.get('ean')] + mlbs)
            e['em_full'] = sum(1 for m in no_full if sum(por_dia_mlb.get(m, {}).values()) > 0)
            entidades.append(e)
    else:
        for mlb, anuncio in anuncios.items():
            if anuncio_fossil(anuncio):
                continue
            if not anuncio_e_de_fora_do_full(anuncio):
                if anuncio_e_do_full(anuncio) and passa_no_filtro([mlb], permitidos):
                    fora_da_lista['so_do_full'] += 1
                    fora_da_lista['so_do_full_vendeu'] += 1 if mlb in vendeu_fora else 0
                continue
            if not passa_no_filtro([mlb], permitidos):
                continue
            skus = sorted(cad['candidatos'].get(mlb, {}))
            sku = skus[0] if skus else ''
            produto = produtos.get(sku) or {}
            ids = [mlb, (f'SKU {sku}' + (f' +{len(skus) - 1}' if len(skus) > 1 else '')) if sku else 'sem SKU']
            entidades.append(_entidade(mlb, sku, anuncio['titulo'] or produto.get('titulo') or 'Título indisponível', '', produto.get('marca', ''), anuncio['imagem'] or produto.get('imagem', ''),
                                       anuncio['selos'], ids, set(), [mlb, anuncio['titulo'], sku, produto.get('marca'), produto.get('ean')]))
    return entidades, fora_da_lista


# ==================================================== o cálculo de cada linha (todas as linhas, sem texto) ====================================================

# Função Objetivo: Os números de UMA entidade: o ritmo de fora do Full no período e no recente, as unidades e o faturamento dos dias completos, o ponto de pedido e a quantidade a pedir.
# * [EXPLICAÇÃO] → Sem ritmo (nenhum dia completo) ou com ritmo zero não há ponto de pedido nem quantidade: ficam em None e a tela mostra "—" (nada a pedir, não "zero unidades").
def _calcular_linha(e, gran, dados, ctx):
    por_dia = dados['dias'][gran].get(e['chave'], {})
    ritmo_p = calc.ritmo_da_janela(ctx['jan_p'], por_dia, dados['estados'])
    ritmo_r = ritmo_p if ctx['mesmo_ritmo'] else calc.ritmo_da_janela(ctx['jan_r'], por_dia, dados['estados'])
    media = ritmo_p['media']
    comparacao = None
    if not ctx['mesmo_ritmo'] and media is not None:
        comparacao = calc.comparar_ritmos(ritmo_r['media'], media)
        if comparacao and media <= 0 and not ritmo_r['media']:
            comparacao = None   # nenhuma venda nos dois ritmos: não há o que comparar
    com_ritmo = media is not None and media > 0
    return {'e': e, 'chave': e['chave'], 'ritmo_p': ritmo_p, 'ritmo_r': ritmo_r, 'media': media, 'un': ritmo_p['unidades'],
            'fat': sum(v for d, v in dados['fat'][gran].get(e['chave'], {}).items() if d in ctx['completos_p']),
            'sentido': comparacao['sentido'] if comparacao else '', 'pct': comparacao['pct'] if comparacao else None,
            'pedido': calc.ponto_de_pedido(media, ctx['lead'], ctx['ante']) if com_ritmo else None,
            'qtd': calc.quantidade_do_sistema(media, ctx['folga']), 'titulo_ordem': e['titulo_ordem']}


# Função Objetivo: Põe as linhas na ordem escolhida (quem não tem valor para ordenar vai para o fim, por nome; empate pelo nome).
def _ordenar(linhas, ordem):
    if ordem == 'nome':
        return sorted(linhas, key=lambda l: l['titulo_ordem'])
    valor = {'ritmo': lambda l: l['media'], 'vendas': lambda l: l['un']}[ordem]
    com_valor = [l for l in linhas if valor(l) is not None]
    sem_valor = sorted((l for l in linhas if valor(l) is None), key=lambda l: l['titulo_ordem'])
    com_valor.sort(key=lambda l: l['titulo_ordem'])
    com_valor.sort(key=valor, reverse=True)
    return com_valor + sem_valor


# ==================================================== o texto de cada linha (só as da página) ====================================================

# Função Objetivo: Transforma os números de uma linha nos textos que a tela mostra. Cada célula tem UM valor e UMA linha de apoio (a tela é rígida na vertical); o resto vai no `title` (tooltip) da célula.
def _apresentar(l, gran, ctx, base_url):
    e, lead, ante, folga, dias, recente = l['e'], ctx['lead'], ctx['ante'], ctx['folga'], ctx['dias'], ctx['recente']
    media, ritmo_r, n_ok = l['media'], l['ritmo_r'], l['ritmo_p']['n_completos']

    # ---- estoque: não há fonte ligada, então "—" (nunca zero) e o caminho para simular ----
    estoque_dica = ('O estoque de fora do Full ainda não vem de nenhuma fonte ligada a esta tela, por isso fica em "—" (sem leitura não é estoque zero). '
                    'Para simular a ruptura, abra o item e digite o estoque no cartão Projeção.')

    # ---- vendas e ritmo (só o que saiu de fora do Full) ----
    vendas_dica = (f'Unidades que saíram de fora do Full e o faturamento delas, só nos {plural(n_ok, "dia completo", "dias completos")} dos últimos {dias} dias (de {data(ctx["de"])} até ontem): é o mesmo volume que '
                   f'dá o ritmo (unidades ÷ dias completos). Hoje (parcial) e os dias sem coleta ficam de fora; venda cancelada não conta.')
    if media is None:
        ritmo_txt, ritmo_dica = '—', f'Nenhum dos últimos {dias} dias está completo na coleta da conta toda: sem ritmo de vendas.'
    else:
        ritmo_txt, ritmo_dica = un_dia(media), f'Média de {un_dia(media)} un/dia (fora do Full) nos {n_ok} dias completos dos últimos {dias}.'
    ritmo_sub, ritmo_sub_classe = '', ''
    if l['sentido'] in ('acelerou', 'caiu'):
        ritmo_sub, ritmo_sub_classe = ('↑ acelerou', 'alerta') if l['sentido'] == 'acelerou' else ('↓ caiu', 'info')
        ritmo_dica += f' Nos últimos {recente} dias: {un_dia(ritmo_r["media"])} un/dia' + (f' ({pct_texto(l["pct"])}).' if l['pct'] is not None else '.')

    # ---- ponto de pedido e quantidade (só dependem do ritmo e das Regras de pedido) ----
    if l['pedido'] is None:
        sem = 'sem dados' if media is None else 'sem vendas'
        motivo = 'Sem dias completos coletados: não dá para calcular o ritmo.' if media is None else 'Nenhuma venda de fora do Full nos dias completos do período: não há o que pedir neste ritmo.'
        pedido_txt, pedido_sub, pedido_dica = '—', sem, motivo
        qtd_txt, qtd_sub, qtd_dica = '—', sem, motivo
    else:
        pedido_txt, pedido_sub = numero(l['pedido']), ''
        pedido_dica = (f'Ponto de pedido = ritmo × (prazo + chegar antes) = {un_dia(media)} × ({lead} + {ante}) = {numero(l["pedido"])} un. É o estoque abaixo do qual já não dá tempo de pedir e o pedido chegar '
                       f'{plural(ante, "dia", "dias")} antes da ruptura: quando o estoque do item chegar a esse número, é hora de pedir. Sem o estoque na lista, ela não diz se o item já está abaixo dele (abra o item e digite o estoque).')
        qtd_txt, qtd_sub = numero(l['qtd']), f'{plural(folga, "dia", "dias")} de folga'
        qtd_dica = (f'Sugestão do Sistema: {numero(l["qtd"])} un = ritmo ({un_dia(media)} un/dia) × folga ({plural(folga, "dia", "dias")}). É a quantidade que acrescenta {plural(folga, "dia", "dias")} de estoque: '
                    f'a nova ruptura vem {plural(folga, "dia", "dias")} depois da atual (ou depois da chegada, que leva {plural(lead, "dia", "dias")}).')

    # ---- selos de atenção (vão junto dos selos do anúncio; o que não cabe na linha some inteiro) ----
    avisos = []
    if e.get('em_full'):
        quem = f'{plural(e["em_full"], "anúncio deste produto é", "anúncios deste produto são")} do Full (logística FULL)'
        avisos.append({'texto': 'Também no Full', 'classe': 'info', 'dica': f'{quem}, mas teve vendas que saíram de fora do Full no período (ex.: Flex, estoque próprio). Só essas vendas entram no ritmo daqui; as do Full ficam no mundo Envios Full.'})

    link = ''
    if e['sku']:
        link = url_da_tela(base_url, sku=e['sku'], gran=gran if gran != 'sku' else None, item=e['chave'] if gran != 'sku' else None, **para_url(ctx['comuns']))
    return {
        'chave': e['chave'], 'titulo': e['titulo'], 'subtitulo': e['subtitulo'], 'foto': e['foto'], 'selos': e['selos'], 'avisos': avisos, 'ids': e['ids'], 'codigo': False,
        'url_detalhe': link, 'motivo': 'Sem SKU no cadastro de anúncios: a curva abre por produto.', 'cat': 'fora',
        'estoque_txt': '—', 'estoque_sub': 'digitar no item', 'estoque_classe': 'info', 'estoque_dica': estoque_dica,
        'vendas_txt': f'{numero(l["un"])} un', 'vendas_sub': reais(l['fat']), 'vendas_dica': vendas_dica,
        'ritmo_txt': ritmo_txt, 'ritmo_sub': ritmo_sub, 'ritmo_sub_classe': ritmo_sub_classe, 'ritmo_dica': ritmo_dica,
        'pedido_txt': pedido_txt, 'pedido_sub': pedido_sub, 'pedido_dica': pedido_dica, 'qtd_txt': qtd_txt, 'qtd_sub': qtd_sub, 'qtd_dica': qtd_dica,
    }


# ==================================================== a lista ====================================================

# Função Objetivo: Tudo da lista do Fora do Full a partir da query string. Parâmetros: gran (sku|mlb), q (busca), ord, por e pag; o ritmo (dias), o prazo, os dias para chegar antes da ruptura e a folga chegam já lidos em
# `comuns` (ruptura_parametros, mundo Fora do Full). Parâmetro inválido volta ao padrão (inclusive o que só existe no Full: gran=codigo, nivel, ord=urgencia). Qualquer mudança de busca ou ordem volta para a página 1.
def montar_lista_fora(parametros, base_url, hoje, comuns):
    dias, lead, ante, folga, recente = comuns['dias'], comuns['lead'], comuns['ante'], comuns['folga'], comuns['recente']
    por_chave = {g[0]: g for g in GRANULARIDADES}
    gran = _escolher(parametros, 'gran', por_chave, GRANULARIDADE_PADRAO)
    _, _, ajuda, unidade_plural, unidade_singular = por_chave[gran]
    texto = (parametros.get('q') or '').strip()
    ordem = _escolher(parametros, 'ord', dict(ORDENS), ORDEM_PADRAO)
    por = inteiro(parametros.get('por'), 1, 1000)
    por = por if por in POR_PAGINA_OPCOES else POR_PAGINA_PADRAO
    numero_da_pagina = inteiro(parametros.get('pag'), 1, 100000) or 1
    padroes = {'gran': GRANULARIDADE_PADRAO, 'ord': ORDEM_PADRAO, 'por': POR_PAGINA_PADRAO, 'pag': 1}

    # * [EXPLICAÇÃO] → O endereço leva só o que a pessoa mudou: o que é da lista (Ver por, busca, ordem, itens por página e página) sai daqui e as regras dos dois mundos saem de ruptura_parametros.para_url,
    #                  a mesma fonte do detalhe.
    def parametros_da_url(mudancas):
        atuais = {'gran': gran, 'q': texto, 'ord': ordem, 'por': por, 'pag': numero_da_pagina}
        atuais.update(mudancas)
        if 'pag' not in mudancas:
            atuais['pag'] = 1
        return {**{k: (None if v == padroes.get(k) else v) for k, v in atuais.items()}, **para_url(comuns)}

    def url(**mudancas):
        return url_da_tela(base_url, **parametros_da_url(mudancas))

    # ---- dados: as vendas de fora do Full por dia (1 leitura) e a conta de cada linha ----
    de = hoje - timedelta(days=max(dias, recente))
    dados = unidades_por_dia_da_origem(de, hoje, 'fora')
    estados = dados['estados']
    jan_p = [hoje - timedelta(days=i) for i in range(dias, -1, -1)]
    ctx = {'hoje': hoje, 'dias': dias, 'recente': recente, 'lead': lead, 'ante': ante, 'folga': folga, 'comuns': comuns, 'de': hoje - timedelta(days=dias), 'mesmo_ritmo': dias <= recente,
           'jan_p': jan_p, 'jan_r': [hoje - timedelta(days=i) for i in range(recente, -1, -1)], 'completos_p': {d for d in jan_p if estados.get(d) == 'ok'}}
    permitidos = mlbs_permitidos(comuns)   # os filtros do Hub: None = sem filtro ativo (nada é lido do Hub)
    entidades, fora_da_lista = _entidades(gran, dados, permitidos)
    todas = [_calcular_linha(e, gran, dados, ctx) for e in entidades]

    # ---- busca e ordem ----
    procurado = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii').lower()
    filtradas = _ordenar([l for l in todas if not procurado or procurado in l['e']['busca']], ordem)

    # ---- a página atual: só aqui se montam textos e endereços ----
    total = len(filtradas)
    total_paginas = max(1, -(-total // por))
    pagina_atual = min(numero_da_pagina, total_paginas)
    ini = (pagina_atual - 1) * por
    fim = min(total, ini + por)
    linhas = [_apresentar(l, gran, ctx, base_url) for l in filtradas[ini:fim]]

    # ---- cobertura das vendas e pontos de atenção (sobre a lista inteira) ----
    n_ok = sum(1 for d in jan_p if estados.get(d) == 'ok')
    coletado_em = dados['coletado_em']
    avisos = []
    if not coletado_em:
        avisos.append(aviso('aviso', f'Nenhum dia dos últimos {dias} foi coletado da conta toda', 'Sem ritmo de vendas, não há ponto de pedido nem quantidade. Colete o período na tela de Vendas.'))
    elif n_ok < dias:
        avisos.append(aviso('aviso', 'dias completos na coleta de vendas da conta toda', 'A média usa só os dias completos (hoje e dias parciais ficam de fora).', numero_texto=f'{n_ok}/{dias}'))
    so_do_full, vendeu = fora_da_lista['so_do_full'], fora_da_lista['so_do_full_vendeu']
    if so_do_full > 0:
        plural_ = so_do_full != 1
        titulo_um, titulo_varios = (('produto só tem anúncios do Full', 'produtos só têm anúncios do Full') if gran == 'sku' else ('anúncio é do Full', 'anúncios são do Full'))
        mensagem = f'{"Não aparecem" if plural_ else "Não aparece"} aqui: {"estão" if plural_ else "está"} no mundo Envios Full.'
        if vendeu > 0:
            mensagem += (f' {plural(vendeu, "deles vendeu", "deles venderam")} por fora do Full no período (Flex, estoque próprio) e essas vendas não entram nesta lista, que só traz o que o filtro de logísticas de fora do Full do Hub traz.')
        avisos.append(aviso_de_contagem('info', so_do_full, titulo_um, titulo_varios, mensagem))
    if gran == 'sku':
        aviso_sem_produto = aviso_anuncios_sem_produto(dados, anuncio_e_de_fora_do_full, permitidos)
        if aviso_sem_produto:
            avisos.append(aviso_sem_produto)
    if fora_da_lista['sem_logistica'] > 0:
        n_sem = fora_da_lista['sem_logistica']
        avisos.append(aviso_de_contagem('info', n_sem, 'anúncio não tem logística no banco', 'anúncios não têm logística no banco',
                                        f'{"Não é" if n_sem == 1 else "Não são"} nem do Full nem de fora do Full e {"fica" if n_sem == 1 else "ficam"} fora das duas listas (o Hub também os esconde ao filtrar por logística).'))

    ordens = [{'rotulo': rotulo, 'url': url(**{'ord': chave}), 'ativo': chave == ordem} for chave, rotulo in ORDENS]
    # os campos escondidos do formulário: o que é da lista (Ver por, ordem, itens por página) + o que é do outro mundo; os campos visíveis (busca, ritmo, prazo, chegar antes e folga) não viram campo escondido
    ocultos = [{'nome': k, 'valor': v} for k, v in {'gran': gran, 'ord': ordem, 'por': por}.items() if v != padroes.get(k)] + campos_escondidos(comuns)
    return {
        'gran': gran, 'ajuda': ajuda, 'texto': texto, 'ocultos': ocultos,
        'granularidades': [{'chave': g[0], 'rotulo': g[1], 'ativo': g[0] == gran, 'url': url(gran=g[0])} for g in GRANULARIDADES],
        'contexto': (f'Ritmo dos últimos {dias} dias (de {data(ctx["de"])} até hoje) · só as vendas que saíram de fora do Full · prazo de {plural(lead, "dia", "dias")} · chegar {plural(ante, "dia", "dias")} antes · '
                     f'folga de {plural(folga, "dia", "dias")}'),
        'cobertura': {'n_completos': n_ok, 'n_dias': dias, 'tudo_completo': n_ok >= dias, 'nada_coletado': not coletado_em, 'ultima': data_hora(coletado_em) if coletado_em else ''},
        'avisos': avisos, 'ordens': ordens, 'por_pagina': [{'rotulo': str(p), 'url': url(por=p), 'ativo': p == por} for p in POR_PAGINA_OPCOES],
        'total_texto': f'{numero(total)} {unidade_singular if total == 1 else unidade_plural}' + complemento_do_total(bool(texto), permitidos is not None), 'coluna_nome': por_chave[gran][1], 'linhas': linhas, 'vazio': total == 0,
        'filtros_ativos': bool(texto), 'url_limpar_tudo': url(q=''),
        'painel': painel_do_mundo(comuns, url_da_tela(base_url, **sem_filtros_na_url(parametros_da_url({})))), 'notas_filtros': notas_dos_filtros(comuns, gran, unidade_plural),
        'paginacao': {
            'numero': pagina_atual, 'total_paginas': total_paginas,
            'texto': 'Nenhum item' if not total else f'Mostrando {numero(ini + 1)}–{numero(fim)} de {numero(total)} {unidade_plural}',
            'url_anterior': url(pag=pagina_atual - 1) if pagina_atual > 1 else '', 'url_proxima': url(pag=pagina_atual + 1) if pagina_atual < total_paginas else '',
            'janela': [{'numero': p, 'url': url(pag=p), 'atual': p == pagina_atual} if p else {'reticencias': True} for p in _janela_de_paginas(pagina_atual, total_paginas)],
        },
    }
