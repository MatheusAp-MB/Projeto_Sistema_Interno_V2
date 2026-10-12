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
#   - O lead time é UM só para a lista inteira (campo no topo); no detalhe de cada item dá para testar outro. Os níveis (ruptura, crítico, baixo, alto) são os PROVISÓRIOS de ruptura_calculo.py.
#   - Item sem consulta de estoque NÃO vira "estoque zero": fica em "Sem estoque lido" ("ausente não é zero"). Item com só parte dos Códigos lidos fica marcado "Estoque parcial".
#   - DUAS REFERÊNCIAS de urgência e de quanto enviar (decisão do Matheus, 12/10/2026): a do MERCADO LIVRE (lida da consulta de reposição salva: ruptura_estoque.resumir_ml) e a do SISTEMA (a regra da tela:
#     ruptura_calculo.urgencia_do_sistema e sugestao_do_sistema). A escolhida manda na ordem "Mais urgentes primeiro" e aparece grande; a outra aparece pequena na mesma célula. O filtro "Divergem" mostra os
#     itens em que as duas urgências estão em faixas diferentes. Item sem número do ML NUNCA vira urgência ou quantidade zero: fica "sem número do ML".
#
# * [EXPLICAÇÃO] → DE ONDE VEM CADA GRANULARIDADE: o estoque do Full mora no Código ML. Um MLB pode ter mais de um Código (variações) e um Código pode ser usado por mais de um MLB:
#                  nesse caso o estoque é o MESMO para os dois, e a cobertura do MLB (que olha só as vendas dele) pode ficar maior do que a real. A linha ganha o selo "Estoque compartilhado".
#                  Só entram na lista itens com pelo menos um Código ML (sem Código ML o anúncio não é Full: não há estoque do Full para projetar).
# * [EXPLICAÇÃO] → COMO FICA RÁPIDA (~1000 SKUs): as vendas do Full do período entram numa consulta só (lista_vendas_ml.unidades_do_full_por_dia) e o estoque, em 2 consultas
#                  (full_estoque_ml.estoque_full_dos_codigos). O "A caminho" (consulta de reposição, a parte pesada) só é lido para as linhas da PÁGINA, a não ser que a opção "Considerar as
#                  unidades a caminho" esteja marcada: aí ele entra na cobertura (muda nível e ordem) e é lido para TODOS os Códigos, em lotes de LOTE_DO_A_CAMINHO (uma consulta por lote, nunca por
#                  Código). Textos e endereços só são montados para a página mostrada. Nenhuma consulta por SKU, por MLB ou por Código.
# * [EXPLICAÇÃO] → O que o ML recomenda (urgência e sugestão) também vem da consulta de reposição, mas o RESUMO de cada consulta é guardado no cache pelo id dela (full_estoque_ml.ml_dos_codigos): depois da
#                  primeira leitura só a consulta NOVA é lida de novo. Ele é lido para TODOS os Códigos porque a ordem, o cartão "Divergem" e o filtro olham a lista inteira.

import unicodedata
from datetime import timedelta
from math import ceil

from django.urls import reverse

from gestao_full.funcoes_auxiliares.full_estoque_ml import HORAS_PARA_DESATUALIZADO, a_caminho_dos_codigos, estoque_do_erp, estoque_full_dos_codigos, ml_dos_codigos
from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares import ruptura_estoque as full
from gestao_ruptura.funcoes_auxiliares.ruptura_parametros import REFERENCIA_DE_URGENCIA_PADRAO, para_url
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import aviso_do_deposito, data, data_curta, data_do_ml, em_dias, inteiro, pct as pct_texto, plural, porque_da_urgencia_do_sistema, quantidade_do_ml, reais, un_dia
from gestao_vendas.funcoes_auxiliares.lista_vendas_ml import unidades_do_full_por_dia
from gestao_vendas.funcoes_auxiliares.vendas_ml import data_hora, numero, url_da_tela

# (chave na URL, rótulo do botão, ajuda no "?", o que a linha é no plural, no singular)
GRANULARIDADES = [
    ('sku', 'Produto (SKU)', 'Cada linha é um produto (SKU) e junta todos os Códigos ML dele: o estoque é a soma do que está no Full e o ritmo é o de todas as vendas que saíram do Full.', 'produtos', 'produto'),
    ('mlb', 'Anúncio (MLB)', 'Cada linha é um anúncio (MLB). O estoque é o dos Códigos ML dele; se o Código é compartilhado com outro anúncio, o selo "Estoque compartilhado" avisa (o estoque é o mesmo para os dois).', 'anúncios', 'anúncio'),
    ('codigo', 'Código ML', 'Cada linha é um Código ML: o estoque exato dele no Full e as vendas que saíram dele. É o jeito mais preciso de olhar a ruptura.', 'Códigos ML', 'Código ML'),
]
GRANULARIDADE_PADRAO = 'sku'
# (chave do filtro de nível, rótulo do cartão, texto de apoio). Cada cartão é também o filtro: clicar mostra só aquele nível. O texto de apoio de "Baixo" e "Alto" depende do lead time e da margem
# de segurança (baixo = dura até lead time + margem), por isso é montado por _filtros_de_nivel. O último cartão, "Divergem", não é um nível de estoque: é o filtro dos itens em que a urgência do
# Mercado Livre e a do Sistema estão em faixas diferentes (ruptura_calculo.urgencias_divergem).
CHAVES_DE_NIVEL = ('ruptura', 'critico', 'baixo', 'alto', 'sem_previsao', 'sem_estoque', 'divergem')
NIVEIS_VALIDOS = ('todos',) + CHAVES_DE_NIVEL


def _filtros_de_nivel(lead, folga):
    limite = lead + folga
    return (
        ('ruptura', 'Em ruptura', 'estoque zerado no Full'),
        ('critico', 'Crítico', 'acaba antes do lead time'),
        ('baixo', 'Baixo', f'dura até {limite} dias'),
        ('alto', 'Alto', f'dura mais de {limite} dias'),
        ('sem_previsao', 'Sem previsão', 'sem venda no ritmo ou sem dias coletados'),
        ('sem_estoque', 'Sem estoque lido', 'sem consulta de estoque salva'),
        ('divergem', 'Divergem', 'ML e Sistema discordam'),
    )


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
BARRA_EM_LEADS = 3   # a barra de cobertura enche quando o estoque dura 3 vezes o lead time (a marca na barra é o próprio lead time, a 1/3)
FIM_DO_TEMPO = 1e12
LOTE_DO_A_CAMINHO = 150   # Códigos por leitura da reposição (a parte grande da consulta salva): limita a memória quando o "a caminho" é lido para a lista inteira


# ==================================================== pequenas ajudas ====================================================

def _sem_acento(texto):
    return unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode('ascii').lower()


def _escolher(parametros, nome, validos, padrao):
    valor = (parametros.get(nome) or '').strip()
    return valor if valor in validos else padrao


# Função Objetivo: Lê o "A caminho" de TODOS os Códigos ML lidos da lista (só quando a opção "Considerar as unidades a caminho" está marcada: aí o número entra na cobertura de cada linha, não só
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


# ==================================================== as entidades de cada granularidade ====================================================

# Função Objetivo: Uma entidade da lista (o que a linha representa), do jeito que as três granularidades usam: chave, sku (para abrir o detalhe), título, foto, selos, ids (os chips pequenos), os
# Códigos ML dela, texto de busca e, no MLB e no SKU, a lista de quem divide estoque com ela.
def _entidade(chave, sku, titulo, subtitulo, marca, foto, selos, ids, codigos, busca, compartilha=()):
    return {'chave': chave, 'sku': sku, 'titulo': titulo, 'subtitulo': subtitulo, 'marca': marca, 'foto': foto, 'selos': selos, 'ids': ids, 'codigos': codigos,
            'busca': _sem_acento(' '.join(str(p) for p in busca if p)), 'titulo_ordem': _sem_acento(titulo), 'compartilha': list(compartilha)}


# Função Objetivo: Monta as entidades da granularidade escolhida a partir do cadastro em lote (lista_vendas_ml._carregar_cadastro). Só entra quem tem pelo menos um Código ML.
def _entidades(gran, dados):
    cad, produtos = dados['cad'], dados['produtos']
    codigos_cad = cad['codigos']
    entidades = []
    if gran == 'sku':
        for sku, info in cad['por_sku'].items():
            codigos = {c for m in info['mlbs'].values() for _, c in m['variacoes'] if c}
            if not codigos:
                continue
            produto = produtos.get(sku) or {}
            mlbs = sorted(info['mlbs'])
            outros = sorted({s for c in codigos for s in codigos_cad[c]['skus'] if s != sku})
            ids = [f'SKU {sku}', plural(len(mlbs), 'anúncio', 'anúncios'), plural(len(codigos), 'Código ML', 'Códigos ML')]
            entidades.append(_entidade(sku, sku, produto.get('titulo') or '(SKU fora do cadastro de Produto)', '', produto.get('marca', ''), produto.get('imagem', ''), [], ids, codigos,
                                       [sku, produto.get('titulo'), produto.get('marca'), produto.get('ean')] + mlbs + sorted(codigos), outros))
    elif gran == 'mlb':
        for mlb, anuncio in cad['anuncios'].items():
            codigos = {c for _, c in anuncio['variacoes'] if c}
            if not codigos:
                continue
            skus = sorted(cad['candidatos'].get(mlb, {}))
            sku = skus[0] if skus else ''
            produto = produtos.get(sku) or {}
            outros_mlbs = sorted({m for c in codigos for m in codigos_cad[c]['mlbs'] if m != mlb})
            ids = [mlb, (f'SKU {sku}' + (f' +{len(skus) - 1}' if len(skus) > 1 else '')) if sku else 'sem SKU',
                   f'Código ML {sorted(codigos)[0]}' if len(codigos) == 1 else plural(len(codigos), 'Código ML', 'Códigos ML')]
            entidades.append(_entidade(mlb, sku, anuncio['titulo'] or produto.get('titulo') or 'Título indisponível', '', produto.get('marca', ''), anuncio['imagem'] or produto.get('imagem', ''),
                                       anuncio['selos'], ids, codigos, [mlb, anuncio['titulo'], sku, produto.get('marca'), produto.get('ean')] + sorted(codigos), outros_mlbs))
    else:
        for codigo, dados_do_codigo in codigos_cad.items():
            skus = sorted(dados_do_codigo['skus'])
            sku = skus[0] if skus else ''
            produto = produtos.get(sku) or {}
            mlbs = sorted(dados_do_codigo['mlbs'])
            foto = next((cad['anuncios'][m]['imagem'] for m in mlbs if cad['anuncios'].get(m, {}).get('imagem')), '') or produto.get('imagem', '')
            ids = [(f'SKU {sku}' + (f' +{len(skus) - 1}' if len(skus) > 1 else '')) if sku else 'sem SKU', plural(len(mlbs), 'anúncio', 'anúncios')]
            entidades.append(_entidade(codigo, sku, codigo, produto.get('titulo', ''), produto.get('marca', ''), foto, [], ids, {codigo},
                                       [codigo, produto.get('titulo'), sku, produto.get('marca'), produto.get('ean')] + mlbs, skus[1:]))
    return entidades


# ==================================================== o cálculo de cada linha (todas as linhas, sem texto) ====================================================

# Função Objetivo: Os números de UMA entidade: o estoque do Full (soma dos Códigos), o ritmo do Full no período e no recente, a projeção, o nível e a categoria do filtro. `cat` é uma de
# ruptura | critico | baixo | alto | sem_previsao (sem venda no ritmo, ou nenhum dia completo) | sem_estoque (nenhum Código com estoque lido) | sem_nivel (sem lead time).
# * [EXPLICAÇÃO] → Estoque zerado é "ruptura" mesmo sem ritmo: não há o que vender. Sem estoque LIDO nunca é ruptura (ausente não é zero). Com a opção "Considerar as unidades a caminho" marcada,
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
        sugestao = calc.sugestao_do_sistema(estoque, media, ctx['lead'], ctx['folga'], ctx['cobre'])
    # as duas urgências (Sistema e Mercado Livre) na mesma língua, para ordenar e comparar; `urg` é a da referência escolhida
    envio = calc.envio(projecao, ctx['lead'], hoje, ctx['folga']) if projecao and projecao['situacao'] == 'normal' else None
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
    if sug['qtd'] == 0:
        return '0', (f'Sugestão do Sistema: nada agora. Na chegada de uma remessa (daqui a {plural(lead, "dia", "dias")}) o estoque ainda terá cerca de {numero(ceil(sug["sobra_na_chegada"]))} un, '
                     f'mais que a meta de {numero(ceil(sug["meta"]))} un (margem de {ctx["folga"]} d + cobertura de {ctx["cobre"]} d).')
    return numero(sug['qtd']), (f'Sugestão do Sistema: {numero(sug["qtd"])} un, cobrindo {ctx["cobre"]} d. Meta na chegada (daqui a {plural(lead, "dia", "dias")}): margem de {ctx["folga"]} d + cobertura de {ctx["cobre"]} d = '
                                f'{numero(ceil(sug["meta"]))} un, menos {numero(ceil(sug["sobra_na_chegada"]))} un que ainda sobram.')


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
        estoque_txt = numero(l['estoque'])   # com a opção "Considerar as unidades a caminho" marcada, já inclui o a caminho
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
        enviar_dica = f'Estoque zerado: envie o quanto antes. Com lead time de {plural(lead, "dia", "dias")}, o produto só volta a ficar disponível em {data(hoje + timedelta(days=lead))}.'
        cob_dica = f'O estoque do Full está zerado{" (contando o que está a caminho)" if ctx["caminho"] else ""}: o produto já está em ruptura.'
    elif projecao and projecao['situacao'] == 'normal':
        dias_inteiros = projecao['dias']
        cob_txt = numero(dias_inteiros)
        referencia = max(lead or 0, 1) * BARRA_EM_LEADS
        barra_pct = min(100, round(l['dias_exatos'] / referencia * 100))
        ruptura_txt, ruptura_sub = data_curta(projecao['data'], hoje), em_dias(dias_inteiros)
        envio = l['envio']
        regra = f'ruptura − lead time ({lead} d) − margem de segurança ({ctx["folga"]} d)'
        if envio and envio['estado'] == 'vencido':
            enviar_txt, enviar_classe, enviar_sub = 'Atrasado', 'vencido', f'vão faltar {envio["faltam_dias"]} d'
            enviar_dica = (f'O último dia para enviar foi {data(envio["ultimo_dia"])}: enviando hoje o produto só fica disponível em {data(envio["chegada"])} '
                           f'e vão faltar cerca de {plural(envio["faltam_dias"], "dia", "dias")} de estoque.')
        elif envio and envio['estado'] == 'ja':
            enviar_txt, enviar_classe, enviar_sub = 'Enviar já', 'alerta', f'chega c/ {envio["folga_na_chegada"]} d de folga'
            enviar_dica = (f'A data recomendada ({data(envio["enviar_ate"])} = {regra}) já passou, mas ainda dá tempo: enviando hoje, o produto chega em {data(envio["chegada"])} com '
                           f'{plural(envio["folga_na_chegada"], "dia", "dias")} de estoque sobrando (a margem é de {ctx["folga"]} d). O último dia possível é {data(envio["ultimo_dia"])}.')
        elif envio:
            enviar_txt = data_curta(envio['enviar_ate'], hoje)
            enviar_sub, enviar_classe = ('hoje, último dia', 'alerta') if envio['estado'] == 'hoje' else (em_dias(envio['em_dias']), '')
            enviar_dica = f'Data recomendada para enviar: {data(envio["enviar_ate"])} = {regra}. O último dia possível (sem margem) é {data(envio["ultimo_dia"])}.'
        cob_dica = (f'O estoque considerado{" (com as unidades a caminho)" if ctx["caminho"] else ""} ({numero(l["estoque"])} un) dura cerca de {plural(dias_inteiros, "dia", "dias")} no ritmo de {un_dia(media)} un/dia. '
                    f'A marca na barra é o lead time ({plural(lead, "dia", "dias")}); a barra enche com {BARRA_EM_LEADS}× o lead time.')
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
    elif cat == 'sem_previsao':
        nivel_rotulo, nivel_classe, nivel_dica = 'Sem previsão', 'neutro', 'Sem venda no ritmo (ou sem dias coletados): não há ruptura prevista.'
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

# Função Objetivo: Tudo da lista a partir da query string. Parâmetros: gran (sku|mlb|codigo), q (busca), nivel (todos|ruptura|critico|baixo|alto|sem_previsao|sem_estoque|divergem), ord, por e pag; o ritmo
# (dias), o lead time, a margem de segurança, os dias que a remessa cobre, a opção "Considerar as unidades a caminho" (caminho=1) e as referências (ref_urg, ref_qtd) chegam já lidos em `comuns`
# (ruptura_pagina). Parâmetro inválido volta ao padrão. Qualquer mudança de filtro, busca ou ordem volta para a página 1.
def montar_lista(parametros, base_url, hoje, comuns):
    dias, lead, folga, cobre, recente, caminho = comuns['dias'], comuns['lead'], comuns['folga'], comuns['cobre'], comuns['recente'], comuns['caminho']
    por_chave = {g[0]: g for g in GRANULARIDADES}
    gran = _escolher(parametros, 'gran', por_chave, GRANULARIDADE_PADRAO)
    _, _, ajuda, unidade_plural, unidade_singular = por_chave[gran]
    texto = (parametros.get('q') or '').strip()
    filtro = _escolher(parametros, 'nivel', NIVEIS_VALIDOS, 'todos')
    ordem = _escolher(parametros, 'ord', dict(ORDENS), 'urgencia')
    por = inteiro(parametros.get('por'), 1, 1000)
    por = por if por in POR_PAGINA_OPCOES else POR_PAGINA_PADRAO
    numero_da_pagina = inteiro(parametros.get('pag'), 1, 100000) or 1

    ref_urg = comuns['ref_urg']
    ref_qtd = 'sistema' if comuns['ref_qtd'] == 'manual' else comuns['ref_qtd']   # a lista não tem quantidade digitada: "Minha quantidade" só existe no detalhe de um item
    padroes = {'gran': GRANULARIDADE_PADRAO, 'dias': calc.DIAS_PADRAO, 'lead': calc.LEAD_TIME_PADRAO, 'margem': calc.MARGEM_PADRAO_PCT, 'cobre': None, 'nivel': 'todos', 'ord': 'urgencia',
               'por': POR_PAGINA_PADRAO, 'pag': 1, 'caminho': 0, 'ref_urg': REFERENCIA_DE_URGENCIA_PADRAO, 'ref_qtd': 'sistema'}

    def parametros_da_url(mudancas):
        atuais = {'gran': gran, 'dias': dias, 'lead': lead, 'margem': comuns['margem'], 'cobre': comuns['cobre_digitado'], 'q': texto, 'nivel': filtro, 'ord': ordem, 'por': por,
                  'pag': numero_da_pagina, 'caminho': 1 if caminho else 0, 'ref_urg': ref_urg, 'ref_qtd': ref_qtd}
        atuais.update(mudancas)
        if 'pag' not in mudancas:
            atuais['pag'] = 1
        return {k: (None if v == padroes.get(k) else v) for k, v in atuais.items()}

    def url(**mudancas):
        return url_da_tela(base_url, **parametros_da_url(mudancas))

    # ---- dados: vendas do Full por dia (1 leitura), estoque do Full (2 leituras) e a conta de cada linha ----
    de = hoje - timedelta(days=max(dias, recente))
    dados = unidades_do_full_por_dia(de, hoje)
    estados = dados['estados']
    jan_p = [hoje - timedelta(days=i) for i in range(dias, -1, -1)]
    ctx = {'hoje': hoje, 'dias': dias, 'recente': recente, 'lead': lead, 'folga': folga, 'cobre': cobre, 'comuns': comuns, 'caminho': caminho, 'de': hoje - timedelta(days=dias), 'mesmo_ritmo': dias <= recente,
           'ref_urg': ref_urg, 'ref_qtd': ref_qtd,
           'jan_p': jan_p, 'jan_r': [hoje - timedelta(days=i) for i in range(recente, -1, -1)], 'completos_p': {d for d in jan_p if estados.get(d) == 'ok'}}
    entidades = _entidades(gran, dados)
    cartoes = estoque_full_dos_codigos(sorted(set().union(*(e['codigos'] for e in entidades)))) if entidades else {}
    if caminho:
        _ler_a_caminho_de_todos(cartoes)   # o a caminho entra na cobertura de CADA linha (muda nível e ordem): lido para todos os Códigos, em lotes
    ml_dos_codigos(cartoes)   # o que o Mercado Livre recomenda (urgência e sugestão), de todos os Códigos: a ordem, o "Divergem" e a contagem olham a lista inteira (resumos em cache)
    todas = [_calcular_linha(e, gran, dados, cartoes, ctx) for e in entidades]

    # ---- busca e filtro de nível (os números dos cartões são sobre o resultado da busca) ----
    procurado = _sem_acento(texto)
    base = [l for l in todas if not procurado or procurado in l['e']['busca']]
    filtros_de_nivel = _filtros_de_nivel(lead, folga)
    contagem = {chave: sum(1 for l in base if l['cat'] == chave) for chave in CHAVES_DE_NIVEL if chave != 'divergem'}
    contagem['divergem'] = sum(1 for l in base if l['diverge'])
    filtradas = [l for l in base if filtro == 'todos' or (l['diverge'] if filtro == 'divergem' else l['cat'] == filtro)]
    filtradas = _ordenar(filtradas, ordem, ref_urg)

    cartoes_de_nivel = [{'chave': chave, 'rotulo': rotulo, 'apoio': apoio, 'n': numero(contagem[chave]), 'vazio': contagem[chave] == 0, 'ativo': filtro == chave,
                         'url': url(nivel='todos' if filtro == chave else chave)} for chave, rotulo, apoio in filtros_de_nivel]

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

    # ---- cobertura das vendas e pontos de atenção (sobre a lista inteira) ----
    n_ok = sum(1 for d in ctx['jan_p'] if estados.get(d) == 'ok')
    coletado_em = dados['coletado_em']
    n_sem_consulta = sum(1 for c in cartoes.values() if c['estado'] == 'sem_consulta')
    n_erro = sum(1 for c in cartoes.values() if c['estado'] == 'erro')
    n_antigas = sum(1 for c in cartoes.values() if c['estado'] == 'ok' and c['desatualizado'])
    avisos = []
    if not coletado_em:
        avisos.append({'classe': 'aviso', 'texto': f'Nenhum dia dos últimos {dias} foi coletado da conta toda: sem ritmo de vendas, os itens ficam em "Sem previsão". Colete o período na tela de Vendas.'})
    elif n_ok < dias:
        avisos.append({'classe': 'aviso', 'texto': f'Só {n_ok} dos últimos {dias} dias estão completos na coleta da conta toda: a média usa só esses dias (hoje e dias parciais ficam de fora).'})
    if n_sem_consulta:
        avisos.append({'classe': 'aviso', 'texto': f'{numero(n_sem_consulta)} de {numero(len(cartoes))} Códigos ML ainda não têm consulta de estoque salva: os itens deles ficam em "Sem estoque lido" '
                                                   f'(ou "Estoque parcial"). Faça a consulta na tela "Estoque no Full".', 'link': reverse('gestao_full_estoque'), 'link_texto': 'Abrir Estoque no Full'})
    if n_erro:
        avisos.append({'classe': 'aviso', 'texto': f'{numero(n_erro)} Códigos ML tiveram erro na última consulta de estoque: não entram na soma (ficam "parciais" ou "sem estoque lido").'})
    if n_antigas:
        avisos.append({'classe': 'info', 'texto': f'{numero(n_antigas)} Códigos ML têm a consulta de estoque com mais de {HORAS_PARA_DESATUALIZADO} h: o estoque deles pode ter mudado desde então.'})
    if ref_urg == 'ml' or ref_qtd == 'ml':
        n_sem_ml = sum(1 for l in todas if l['ml']['estado'] == 'sem_dados')
        if n_sem_ml:
            avisos.append({'classe': 'aviso', 'texto': f'{numero(n_sem_ml)} {unidade_plural} não têm a recomendação do Mercado Livre (sem consulta de reposição salva ou com erro): ficam "sem número do ML", '
                                                       f'nunca zero, e vão para o fim da ordem de urgência. A recomendação vem da mesma consulta da tela "Estoque no Full".', 'link': reverse('gestao_full_estoque'), 'link_texto': 'Abrir Estoque no Full'})
    if caminho:
        n_sem_caminho = sum(1 for c in cartoes.values() if c['estado'] == 'ok' and c.get('a_caminho') is None)
        if n_sem_caminho:
            avisos.append({'classe': 'info', 'texto': f'{numero(n_sem_caminho)} Códigos ML não têm o número de "a caminho" (sem consulta de reposição salva, com erro ou sem conta que feche): neles só entra o estoque do Full.'})
    if gran == 'mlb':
        n_compartilhados = sum(1 for e in entidades if e['compartilha'])
        if n_compartilhados:
            avisos.append({'classe': 'info', 'texto': f'{numero(n_compartilhados)} anúncios dividem o Código ML com outro anúncio (selo "Estoque compartilhado"): o estoque é o mesmo, mas aqui só entram as vendas de cada anúncio.'})
    if gran in ('sku', 'mlb'):
        cad = dados['cad']
        sem_codigo = (sum(1 for info in cad['por_sku'].values() if not any(c for m in info['mlbs'].values() for _, c in m['variacoes'])) if gran == 'sku'
                      else sum(1 for a in cad['anuncios'].values() if not any(c for _, c in a['variacoes'])))
        if sem_codigo:
            avisos.append({'classe': 'info', 'texto': f'{numero(sem_codigo)} {unidade_plural} sem Código ML não aparecem aqui: sem Código ML não são Full, então não há estoque do Full para projetar.'})

    ordens = [{'rotulo': rotulo, 'url': url(**{'ord': chave}), 'ativo': chave == ordem} for chave, rotulo in ORDENS]
    ocultos = [{'nome': k, 'valor': v} for k, v in parametros_da_url({}).items() if v not in (None, '') and k not in ('q', 'dias', 'lead', 'margem', 'cobre', 'pag', 'caminho', 'ref_urg', 'ref_qtd')]   # os campos do formulário (ritmo, lead time, margem, cobre, caminho e as referências) não viram campo escondido
    return {
        'gran': gran, 'ajuda': ajuda, 'texto': texto, 'ocultos': ocultos,
        'granularidades': [{'chave': g[0], 'rotulo': g[1], 'ativo': g[0] == gran, 'url': url(gran=g[0], nivel='todos')} for g in GRANULARIDADES],
        'contexto': (f'Ritmo dos últimos {dias} dias (de {data(ctx["de"])} até hoje) · só as vendas que saíram do Full · lead time de {plural(lead, "dia", "dias")} · margem de {plural(folga, "dia", "dias")}'
                     + (' · estoque com as unidades a caminho' if caminho else '')
                     + f' · urgência: {"Mercado Livre" if ref_urg == "ml" else "Sistema"}'),
        'cobertura': {'n_completos': n_ok, 'n_dias': dias, 'tudo_completo': n_ok >= dias, 'nada_coletado': not coletado_em, 'ultima': data_hora(coletado_em) if coletado_em else ''},
        'avisos': avisos, 'cartoes_de_nivel': cartoes_de_nivel, 'url_todos': url(nivel='todos'), 'n_base': numero(len(base)), 'filtro_ativo': filtro != 'todos',
        'ordens': ordens, 'por_pagina': [{'rotulo': str(p), 'url': url(por=p), 'ativo': p == por} for p in POR_PAGINA_OPCOES],
        'total_texto': f'{numero(total)} {unidade_singular if total == 1 else unidade_plural} com os filtros atuais', 'coluna_nome': por_chave[gran][1], 'linhas': linhas, 'vazio': total == 0,
        'filtros_ativos': bool(texto or filtro != 'todos'), 'url_limpar_tudo': url(q='', nivel='todos'),
        'paginacao': {
            'numero': pagina_atual, 'total_paginas': total_paginas,
            'texto': 'Nenhum item' if not total else f'Mostrando {numero(ini + 1)}–{numero(fim)} de {numero(total)} {unidade_plural}',
            'url_anterior': url(pag=pagina_atual - 1) if pagina_atual > 1 else '', 'url_proxima': url(pag=pagina_atual + 1) if pagina_atual < total_paginas else '',
            'janela': [{'numero': p, 'url': url(pag=p), 'atual': p == pagina_atual} if p else {'reticencias': True} for p in _janela_de_paginas(pagina_atual, total_paginas)],
        },
    }
