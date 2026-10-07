# gestao_full/funcoes_auxiliares/full_estoque_ml.py
#
# Monta a tela "Full — Estoque no Full" (Mercado Livre → Full → Estoque no Full): para cada PRODUTO, quanto
# estoque ele tem hoje no Full, somando os Códigos ML dele. É a tela de CONSULTA ("quanto temos?"); a tela de
# Planejamento de envios responde "quanto enviar?".
#
# REGRA DO MATHEUS: esta tela NUNCA chama a API do ML. Ela LÊ só do banco:
#   * produto -> Códigos ML: variacao.inventory_id (gravado pelo importar_anuncios_ml desde 07/10/2026);
#   * os números: a consulta mais recente de cada Código ML (ConsultaFullMercadoLivre), feita pelo botão
#     "Consultar no Mercado Livre" do Planejamento. Sem consulta não há número — a tela diz isso e não inventa.
#
# * [EXPLICAÇÃO] → O estoque pertence ao CÓDIGO ML, não ao anúncio: dois anúncios do mesmo Código ML mostram o
#                  mesmo valor. Por isso o total de um produto é a soma dos seus CÓDIGOS (nunca dos anúncios, que
#                  contaria em dobro). Um Código só entra na soma depois de consultado; enquanto algum Código do
#                  produto não foi consultado, o total aparece como PARCIAL.
# * [EXPLICAÇÃO] → O número em destaque é o "Total no estoque do Full" (ESTOQUE total): tudo que está fisicamente
#                  lá. Ele se divide em "Disponível para venda" + "Indisponível" (com o motivo). "Aptas e a caminho"
#                  (REPOS stock.total_stock) é outro número, de outra consulta; a parte "a caminho" é HIPÓTESE
#                  (REPOS menos ESTOQUE) até a equipe conferir com a tela do Mercado Livre.

import unicodedata

from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from gestao_full.funcoes_auxiliares.full_ml import MOTIVO_INDISPONIVEL, _n_br, pegar
from gestao_full.funcoes_auxiliares.full_planejamento_ml import _meta_do_campo
from mercado_livre.funcoes_auxiliares.badges import BADGES_CONFERENCIA_FULL, BADGES_ESTOQUE_FULL

# * [EXPLICAÇÃO] → Depois de quantas horas uma consulta salva é considerada "desatualizada". O estoque do Full muda
#                  o dia todo; 24 h é um ponto de partida — ajuste aqui se a equipe quiser outro prazo.
HORAS_PARA_DESATUALIZADO = 24
# * [EXPLICAÇÃO] → Quantos produtos aparecem por página: a pessoa escolhe entre as opções; sem escolha vale o padrão.
POR_PAGINA_PADRAO = 25
OPCOES_POR_PAGINA = (25, 50, 100, 200)
# Com poucos produtos na lista (ex.: depois de buscar um SKU) os Códigos ML já vêm abertos.
LIMITE_PARA_ABRIR_SOZINHO = 3
# Valor que a URL leva para "só os produtos sem marca cadastrada".
SEM_MARCA = '(sem marca)'

# * [EXPLICAÇÃO] → Filtros: (chave, rótulo, grupo). O grupo só organiza os botões na tela; só um filtro vale por vez.
FILTROS = (
    ('todos', 'Todos', ''),
    ('com_indisponivel', 'Com indisponível', 'Estoque'),
    ('sem_disponivel', 'Sem disponível para venda', 'Estoque'),
    ('zerados', 'Zerados no Full', 'Estoque'),
    ('desatualizados', 'Consulta desatualizada', 'Consulta'),
    ('faltam_consultas', 'Faltam consultas', 'Consulta'),
    ('com_erro', 'Consulta com erro', 'Consulta'),
    ('nao_bate', 'Total não bate', 'Conferir'),
    ('compartilhados', 'Código ML compartilhado', 'Conferir'),
    ('varios_codigos', 'Mais de um Código ML', 'Conferir'),
)

# * [EXPLICAÇÃO] → Ordenações: (chave, rótulo, grupo). O grupo vira um bloco no seletor "Ordenar por". Quem não tem número
#                  para a ordem escolhida (nunca consultado, por exemplo) vai SEMPRE para o fim; empates saem por título A–Z.
#                  As do grupo "Reposição" precisam ler a reposição de TODOS os Códigos da lista (e não só dos que cabem na
#                  página), por isso podem demorar um pouco mais — só pesam quando a pessoa as escolhe.
GRUPO_REPOSICAO = 'Reposição (lê mais dados: pode demorar um pouco mais)'
ORDENS = (
    ('total_desc', 'Total no Full — maior primeiro', 'Estoque'),
    ('total_asc', 'Total no Full — menor primeiro', 'Estoque'),
    ('disponivel_desc', 'Disponível para venda — maior primeiro', 'Estoque'),
    ('disponivel_asc', 'Disponível para venda — menor primeiro', 'Estoque'),
    ('indisponivel_desc', 'Indisponível — maior primeiro', 'Estoque'),
    ('indisponivel_asc', 'Indisponível — menor primeiro', 'Estoque'),
    ('pct_indisponivel_desc', 'Maior % indisponível do total', 'Estoque'),
    ('aptas_desc', 'Aptas e a caminho — maior primeiro', GRUPO_REPOSICAO),
    ('aptas_asc', 'Aptas e a caminho — menor primeiro', GRUPO_REPOSICAO),
    ('a_caminho_desc', 'Mais unidades a caminho (hipótese)', GRUPO_REPOSICAO),
    ('titulo', 'Título (A–Z)', 'Produto'),
    ('titulo_desc', 'Título (Z–A)', 'Produto'),
    ('sku', 'SKU (A–Z)', 'Produto'),
    ('marca', 'Marca (A–Z)', 'Produto'),
    ('codigos_desc', 'Mais Códigos ML primeiro', 'Produto'),
    ('consulta_antiga', 'Consulta mais antiga primeiro', 'Consulta'),
    ('consulta_recente', 'Consulta mais recente primeiro', 'Consulta'),
)
ORDENS_QUE_LEEM_REPOSICAO = {'aptas_desc', 'aptas_asc', 'a_caminho_desc'}
FILTRO_PADRAO = 'todos'
ORDEM_PADRAO = 'total_desc'

# * [EXPLICAÇÃO] → Clicar no título de uma coluna ordena por ela: o 1º clique usa a primeira ordem, o 2º inverte, o 3º volta.
ORDEM_DAS_COLUNAS = {
    'produto': ('titulo', 'titulo_desc'),
    'total': ('total_desc', 'total_asc'),
    'disponivel': ('disponivel_desc', 'disponivel_asc'),
    'indisponivel': ('indisponivel_desc', 'indisponivel_asc'),
    'aptas': ('aptas_desc', 'aptas_asc'),
    'consulta': ('consulta_antiga', 'consulta_recente'),
}

# Os 4 números da tela: (chave, fonte, caminho do campo, rótulo). O selo de conferência de cada um vem do registro
# que a equipe preenche na ficha de debug (o mesmo das telas de Planejamento).
COLUNAS_FONTE = (
    ('total', 'ESTOQUE', 'total', 'Total no Full'),
    ('disponivel', 'ESTOQUE', 'available_quantity', 'Disponível para venda'),
    ('indisponivel', 'ESTOQUE', 'not_available_quantity', 'Indisponível'),
    ('aptas', 'REPOS', 'stock.total_stock', 'Aptas e a caminho'),
)

BADGE_A_CAMINHO = BADGES_CONFERENCIA_FULL['hipotese']


# ---------------------------------------------------------------------------
# PEQUENAS AJUDAS
# ---------------------------------------------------------------------------
def _normalizar(texto):
    """'Água Limpa' -> 'agua limpa' (para a busca ignorar acento e maiúscula)."""
    return unicodedata.normalize('NFD', str(texto or '')).encode('ascii', 'ignore').decode('ascii').lower()


def _inteiro(valor):
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _n(valor):
    return '—' if valor is None else _n_br(valor)


def _idade(consultado_em, agora):
    """'há 3 h', 'há 12 min', 'há 2 dias'."""
    minutos = max(int((agora - consultado_em).total_seconds() // 60), 0)
    if minutos < 1:
        return 'agora há pouco'
    if minutos < 60:
        return f'há {minutos} min'
    horas = minutos // 60
    if horas < 48:
        return f'há {horas} h'
    return f'há {horas // 24} dias'


def _data_hora_completa(valor):
    return '' if valor is None else timezone.localtime(valor).strftime('%d/%m/%Y %H:%M')


# * [EXPLICAÇÃO] → MOTIVO_INDISPONIVEL escreve os motivos no singular ("danificada"). Com 1 unidade fica certo; com 5 não
#                  ("5 danificada"). Estes são os que mudam no plural; os outros ("em transferência") não mudam.
PLURAL_DO_MOTIVO = {'danificada': 'danificadas', 'perdida': 'perdidas', 'não suportada': 'não suportadas'}


def _texto_do_motivo(status, quantidade):
    """'danificada' com 5 unidades -> '5 danificadas'."""
    rotulo = MOTIVO_INDISPONIVEL.get(status, status)
    if quantidade != 1:
        rotulo = PLURAL_DO_MOTIVO.get(rotulo, rotulo)
    return f'{_n(quantidade)} {rotulo}'


def _motivos(detalhe):
    """[{"status": "transfer", "quantity": 2}] -> [{"status", "quantidade", "texto": "2 em transferência"}]. Motivo novo aparece como veio."""
    motivos = []
    if isinstance(detalhe, list):
        for item in detalhe:
            if isinstance(item, dict):
                quantidade = _inteiro(item.get('quantity'))
                status = item.get('status')
                motivos.append({'status': status, 'quantidade': quantidade,
                                'texto': _texto_do_motivo(status, quantidade)})
    return motivos


# Função Objetivo: Os motivos de indisponível de um PRODUTO: soma, por motivo, o que cada Código ML dele informou
# (3 em transferência no Código A + 2 no Código B = "5 em transferência"). Maior quantidade primeiro.
def _somar_motivos(cartoes):
    somas = {}
    for cartao in cartoes:
        for motivo in cartao['motivos']:
            if motivo['quantidade'] is not None:
                somas[motivo['status']] = somas.get(motivo['status'], 0) + motivo['quantidade']
    return [{'texto': _texto_do_motivo(status, quantidade)}
            for status, quantidade in sorted(somas.items(), key=lambda par: (-par[1], str(par[0])))]


# Função Objetivo: "6,5%" — quanto do total no Full está indisponível. Só aparece quando há indisponível; sem total não há conta.
def _pct_indisponivel(total, indisponivel):
    if not total or not indisponivel:
        return None
    return round(indisponivel / total * 100, 1)


def _pct_txt(pct):
    return '' if pct is None else f"{pct:.1f}".replace('.', ',') + '%'


def _soma(cartoes, campo):
    valores = [c[campo] for c in cartoes if c['estado'] == 'ok' and c[campo] is not None]
    return sum(valores) if valores else None


# ---------------------------------------------------------------------------
# BANCO (as únicas funções deste arquivo que tocam o banco — só leitura)
# ---------------------------------------------------------------------------
# Função Objetivo: Quais Códigos ML cada SKU tem, segundo o banco: {sku: {CÓDIGO_MAIÚSCULO: {"codigo", "mlbs"}}}.
# O SKU é o do Produto ligado à variação; se a variação não achou Produto, o sku_ml dela; se nem isso, "".
def _ler_codigos_por_sku():
    from mercado_livre.models import VariacaoAnuncioMercadoLivre

    linhas = (VariacaoAnuncioMercadoLivre.objects
              .exclude(inventory_id__isnull=True).exclude(inventory_id='')
              .values_list('inventory_id', 'produto_id', 'sku_ml', 'anuncio__mlb'))
    por_sku = {}
    for inventory_id, produto_id, sku_ml, mlb in linhas:
        codigo = str(inventory_id).strip()
        if not codigo:
            continue
        sku = str(produto_id or sku_ml or '').strip()
        item = por_sku.setdefault(sku, {}).setdefault(codigo.upper(), {'codigo': codigo, 'mlbs': set()})
        item['mlbs'].add(mlb)
    return por_sku


def _ler_cadastro(skus):
    from produtos.models import Produto

    skus = sorted({s for s in skus if s})
    produtos = Produto.objects.filter(sku__in=skus).only('sku', 'ean', 'titulo', 'marca', 'cod_fabricante', 'estoque', 'imagem_url')
    return {p.sku: {'sku': p.sku, 'ean': p.ean or '', 'titulo': p.titulo or '', 'marca': p.marca or '',
                    'cod_fabricante': p.cod_fabricante or '', 'estoque': p.estoque, 'imagem_url': p.imagem_url or ''}
            for p in produtos}


# Função Objetivo: A consulta MAIS RECENTE de cada Código ML ({CÓDIGO_MAIÚSCULO: consulta}). Só traz o estoque (pequeno);
# a reposição, que é maior, só é lida para os produtos da página (_preencher_aptas).
def _ler_ultimas_consultas(codigos_maiusculos):
    from mercado_livre.models import ConsultaFullMercadoLivre

    ultimas = {}
    consultas = (ConsultaFullMercadoLivre.objects.filter(codigo__in=sorted(codigos_maiusculos))
                 .only('id', 'codigo', 'consultado_em', 'estoque'))
    for consulta in consultas:   # a ordem do model é da mais recente para a mais antiga
        ultimas.setdefault(consulta.codigo.upper(), consulta)
    return ultimas


# ---------------------------------------------------------------------------
# OS NÚMEROS DE 1 CÓDIGO ML
# ---------------------------------------------------------------------------
# Função Objetivo: O que a consulta salva diz do estoque de 1 Código ML. "estado": "ok" (tem número), "sem_consulta"
# (ninguém consultou) ou "erro" (consultou, mas o ML não devolveu o estoque).
def _numeros_do_codigo(codigo, consulta, agora):
    cartao = {
        'codigo': codigo, 'estado': 'sem_consulta', 'erro': '', 'consultado_em': None, 'idade': '', 'consultado_completo': '',
        'desatualizado': False, 'total': None, 'disponivel': None, 'indisponivel': None, 'motivos': [], 'conferencia': None,
        'aptas': None, 'aptas_txt': '—', 'a_caminho_txt': '', 'aptas_nota': '', 'pct_indisponivel_txt': '',
    }
    if consulta is not None:
        cartao['consultado_em'] = consulta.consultado_em
        cartao['idade'] = _idade(consulta.consultado_em, agora)
        cartao['consultado_completo'] = _data_hora_completa(consulta.consultado_em)
        cartao['desatualizado'] = (agora - consulta.consultado_em).total_seconds() > HORAS_PARA_DESATUALIZADO * 3600

        pacotes = {str(chave).upper(): pacote for chave, pacote in (consulta.estoque or {}).items()}
        pacote = pacotes.get(codigo.upper())
        if not pacote:
            cartao['estado'], cartao['erro'] = 'erro', 'A consulta salva não trouxe o estoque deste Código ML.'
        elif pacote.get('erro') or pacote.get('dados') is None:
            cartao['estado'], cartao['erro'] = 'erro', str(pacote.get('erro') or 'sem resposta')
        else:
            dados = pacote['dados']
            cartao['estado'] = 'ok'
            cartao['total'] = _inteiro(pegar(dados, 'total'))
            cartao['disponivel'] = _inteiro(pegar(dados, 'available_quantity'))
            cartao['indisponivel'] = _inteiro(pegar(dados, 'not_available_quantity'))
            cartao['motivos'] = _motivos(pegar(dados, 'not_available_detail'))
            total, disponivel, indisponivel = cartao['total'], cartao['disponivel'], cartao['indisponivel']
            if None not in (total, disponivel, indisponivel):
                soma = disponivel + indisponivel
                bate = total == soma
                cartao['conferencia'] = {
                    'bate': bate,
                    'texto': (f'Total {_n(total)} = disponível {_n(disponivel)} + indisponível {_n(indisponivel)}' if bate else
                              f'Total ({_n(total)}) não bate com disponível ({_n(disponivel)}) + indisponível ({_n(indisponivel)}) = {_n(soma)}'),
                }
    for campo in ('total', 'disponivel', 'indisponivel'):
        cartao[f'{campo}_txt'] = _n(cartao[campo]) if cartao['estado'] == 'ok' else '—'
    cartao['pct_indisponivel_txt'] = _pct_txt(_pct_indisponivel(cartao['total'], cartao['indisponivel']))
    cartao['status'] = ('desatualizado' if cartao['desatualizado'] else 'atualizado') if cartao['estado'] == 'ok' else cartao['estado']
    cartao['badge'] = BADGES_ESTOQUE_FULL[cartao['status']]
    return cartao


# Função Objetivo: "Aptas e a caminho" de 1 Código ML, a partir da consulta de REPOSIÇÃO salva (REPOS stock.total_stock),
# e a diferença para o total no Full, que é só HIPÓTESE de "a caminho". Se o Código tem mais de um produto do vendedor
# com valores diferentes, não escolho um: aviso e deixo para o Planejamento.
def _aptas_do_codigo(reposicao, total):
    valores = []
    for pacote in (reposicao or {}).values():
        dados = (pacote or {}).get('dados')
        valor = _inteiro(pegar(dados, 'stock.total_stock')) if dados else None
        if valor is not None:
            valores.append(valor)
    if not valores:
        return {'aptas': None, 'aptas_txt': '—', 'a_caminho_txt': '', 'aptas_nota': 'Sem consulta de reposição salva para este Código ML.'}
    if len(set(valores)) > 1:
        return {'aptas': None, 'aptas_txt': '—', 'a_caminho_txt': '',
                'aptas_nota': 'Há mais de um produto do vendedor neste Código ML, com valores diferentes — veja o Planejamento.'}
    aptas = valores[0]
    resultado = {'aptas': aptas, 'aptas_txt': _n(aptas), 'a_caminho_txt': '', 'aptas_nota': ''}
    if total is not None:
        if aptas > total:
            resultado['a_caminho_txt'] = f'+{_n(aptas - total)}'
        elif aptas < total:
            resultado['aptas_nota'] = 'Menor que o total no Full — vale conferir com a tela do Mercado Livre.'
    return resultado


# Função Objetivo: Preenche "Aptas e a caminho" só dos Códigos dos produtos que aparecem na página (a reposição é a parte
# pesada da consulta; para os milhares de Códigos da lista inteira ela não é lida).
def _preencher_aptas(produtos, ultimas):
    from mercado_livre.models import ConsultaFullMercadoLivre

    pks = {ultimas[c['codigo'].upper()].pk for p in produtos for c in p['codigos'] if c['estado'] == 'ok'}
    if not pks:
        return
    reposicoes = {c.pk: c.reposicao for c in ConsultaFullMercadoLivre.objects.filter(pk__in=pks).only('id', 'reposicao')}
    for produto in produtos:
        for cartao in produto['codigos']:
            if cartao['estado'] == 'ok':
                cartao.update(_aptas_do_codigo(reposicoes.get(ultimas[cartao['codigo'].upper()].pk), cartao['total']))
        # Soma do produto: só dos Códigos com número de "aptas"; se algum Código ficou de fora, a soma é parcial.
        com_aptas = [c for c in produto['codigos'] if c['aptas'] is not None]
        if com_aptas:
            produto['aptas'] = sum(c['aptas'] for c in com_aptas)
            produto['aptas_txt'] = _n(produto['aptas'])
            a_caminho = sum(c['aptas'] - c['total'] for c in com_aptas if c['total'] is not None and c['aptas'] > c['total'])
            produto['a_caminho'] = a_caminho
            produto['a_caminho_txt'] = f'+{_n(a_caminho)}' if a_caminho else ''
        produto['aptas_parcial'] = bool(com_aptas) and len(com_aptas) < produto['n_codigos']


# ---------------------------------------------------------------------------
# O PRODUTO
# ---------------------------------------------------------------------------
def _montar_produto(sku, codigos_do_sku, cadastro, ultimas, produtos_do_codigo, agora):
    cartoes = []
    for codigo_maiusculo, info in codigos_do_sku.items():
        cartao = _numeros_do_codigo(info['codigo'], ultimas.get(codigo_maiusculo), agora)
        cartao['n_anuncios'] = len(info['mlbs'])
        cartao['compartilhado_com'] = sorted(s for s in produtos_do_codigo[codigo_maiusculo] if s != sku)
        cartoes.append(cartao)
    # Maior total primeiro; quem ainda não tem número vai para o fim.
    cartoes.sort(key=lambda c: (c['total'] is None, -(c['total'] or 0), c['codigo']))

    ok = [c for c in cartoes if c['estado'] == 'ok']
    n_erro = sum(1 for c in cartoes if c['estado'] == 'erro')
    n_sem = sum(1 for c in cartoes if c['estado'] == 'sem_consulta')
    n_desatualizados = sum(1 for c in ok if c['desatualizado'])
    # Códigos em que o total que o ML mandou não é igual a disponível + indisponível (a tela avisa, não corrige).
    n_diverge = sum(1 for c in ok if c['conferencia'] and not c['conferencia']['bate'])
    if not ok and not n_erro:
        status = 'sem_consulta'
    elif not ok:
        status = 'erro'
    elif len(ok) < len(cartoes):
        status = 'parcial'
    elif n_desatualizados:
        status = 'desatualizado'
    else:
        status = 'atualizado'

    consultas = [c['consultado_em'] for c in cartoes if c['consultado_em'] is not None]
    mais_antiga = min(consultas) if consultas else None
    mais_recente = max(consultas) if consultas else None
    total, disponivel, indisponivel = _soma(cartoes, 'total'), _soma(cartoes, 'disponivel'), _soma(cartoes, 'indisponivel')
    titulo = (cadastro or {}).get('titulo') or sku or 'Sem SKU'
    marca = (cadastro or {}).get('marca') or ''
    pct_indisponivel = _pct_indisponivel(total, indisponivel)
    return {
        'sku': sku, 'titulo': titulo, 'cadastro': cadastro, 'codigos': cartoes,
        'n_codigos': len(cartoes), 'n_ok': len(ok), 'n_erro': n_erro, 'n_sem_consulta': n_sem, 'n_desatualizados': n_desatualizados, 'n_diverge': n_diverge,
        'total': total, 'disponivel': disponivel, 'indisponivel': indisponivel,
        'total_txt': _n(total), 'disponivel_txt': _n(disponivel), 'indisponivel_txt': _n(indisponivel),
        'parcial': bool(ok) and len(ok) < len(cartoes), 'motivos': _somar_motivos(cartoes),
        'aptas': None, 'a_caminho': None, 'aptas_txt': '—', 'a_caminho_txt': '', 'aptas_parcial': False,
        'pct_indisponivel': pct_indisponivel, 'pct_indisponivel_txt': _pct_txt(pct_indisponivel),
        'marca': marca, 'marca_chave': _normalizar(marca),
        'n_compartilhados': sum(1 for c in cartoes if c['compartilhado_com']),
        'status': status, 'badge': BADGES_ESTOQUE_FULL[status],
        'mais_antiga': mais_antiga, 'mais_recente': mais_recente, 'idade_mais_antiga': _idade(mais_antiga, agora) if mais_antiga else '',
        'mais_antiga_completa': _data_hora_completa(mais_antiga),
        'url_planejamento': (reverse('gestao_full_planejamento') + '?' + urlencode({'q': sku})) if sku else '',
        'busca': _normalizar(' '.join([sku, titulo, (cadastro or {}).get('ean', ''), (cadastro or {}).get('marca', ''),
                                       (cadastro or {}).get('cod_fabricante', '')] + [c['codigo'] for c in cartoes])),
    }


def _passa_no_filtro(produto, filtro):
    if filtro == 'com_indisponivel':
        return (produto['indisponivel'] or 0) > 0
    if filtro == 'sem_disponivel':
        return produto['n_ok'] > 0 and produto['disponivel'] == 0
    if filtro == 'zerados':
        return produto['n_ok'] > 0 and produto['total'] == 0
    if filtro == 'desatualizados':
        return produto['n_desatualizados'] > 0
    if filtro == 'faltam_consultas':
        return produto['n_sem_consulta'] > 0
    if filtro == 'com_erro':
        return produto['n_erro'] > 0
    if filtro == 'nao_bate':
        return produto['n_diverge'] > 0
    if filtro == 'compartilhados':
        return produto['n_compartilhados'] > 0
    if filtro == 'varios_codigos':
        return produto['n_codigos'] > 1
    return True


# * [EXPLICAÇÃO] → Ordens que comparam um NÚMERO do produto: ordem -> (campo, decrescente?).
ORDENS_NUMERICAS = {
    'total_desc': ('total', True), 'total_asc': ('total', False),
    'disponivel_desc': ('disponivel', True), 'disponivel_asc': ('disponivel', False),
    'indisponivel_desc': ('indisponivel', True), 'indisponivel_asc': ('indisponivel', False),
    'pct_indisponivel_desc': ('pct_indisponivel', True),
    'aptas_desc': ('aptas', True), 'aptas_asc': ('aptas', False),
    'a_caminho_desc': ('a_caminho', True),
    'codigos_desc': ('n_codigos', True),
}


# Função Objetivo: Põe a lista na ordem escolhida. Sempre parte do título A–Z, então todo empate sai em ordem alfabética
# (o sort do Python é estável, inclusive com reverse=True). Quem não tem valor para a ordem vai para o fim.
def _ordenar(lista, ordem):
    por_titulo = sorted(lista, key=lambda p: _normalizar(p['titulo']))
    if ordem in ORDENS_NUMERICAS:
        campo, decrescente = ORDENS_NUMERICAS[ordem]
        com_valor = [p for p in por_titulo if p[campo] is not None]
        sem_valor = [p for p in por_titulo if p[campo] is None]
        com_valor.sort(key=lambda p: p[campo], reverse=decrescente)
        return com_valor + sem_valor
    if ordem == 'titulo_desc':
        return sorted(lista, key=lambda p: _normalizar(p['titulo']), reverse=True)
    if ordem in ('sku', 'marca'):
        campo = 'sku' if ordem == 'sku' else 'marca_chave'
        com_valor = sorted((p for p in por_titulo if p[campo]), key=lambda p: _normalizar(p[campo]))
        return com_valor + [p for p in por_titulo if not p[campo]]
    if ordem == 'consulta_antiga':
        # Quem nunca foi consultado vem primeiro (é o mais "antigo" de todos); depois, da consulta mais velha à mais nova.
        nunca = [p for p in por_titulo if p['mais_antiga'] is None]
        return nunca + sorted((p for p in por_titulo if p['mais_antiga'] is not None), key=lambda p: p['mais_antiga'])
    if ordem == 'consulta_recente':
        recentes = sorted((p for p in por_titulo if p['mais_recente'] is not None), key=lambda p: p['mais_recente'], reverse=True)
        return recentes + [p for p in por_titulo if p['mais_recente'] is None]
    return por_titulo


# * [EXPLICAÇÃO] → O "estado" da tela é o conjunto de escolhas da pessoa. Ele vira o endereço (?q=...&filtro=...), então
#                  recarregar, voltar e copiar o link mantêm tudo. Só o que foge do padrão vai para o endereço.
PADROES_DA_URL = {'q': '', 'filtro': FILTRO_PADRAO, 'marca': '', 'ordem': ORDEM_PADRAO, 'por_pagina': POR_PAGINA_PADRAO, 'p': 1}


# Função Objetivo: O endereço da própria tela com o estado atual mais as mudanças pedidas. Mudou busca, filtro, marca, ordem
# ou itens por página (e não disse a página)? Volta para a página 1, para a pessoa não cair numa página que não existe mais.
def _url(estado, **mudancas):
    novo = {**estado, **mudancas}
    if 'p' not in mudancas and any(chave in mudancas for chave in ('q', 'filtro', 'marca', 'ordem', 'por_pagina')):
        novo['p'] = 1
    parametros = {chave: novo[chave] for chave in PADROES_DA_URL if novo[chave] != PADROES_DA_URL[chave]}
    base = reverse('gestao_full_estoque')
    return f'{base}?{urlencode(parametros)}' if parametros else base


def _direcao(ordem):
    return 'desc' if ordem.endswith('_desc') or ordem == 'consulta_recente' else 'asc'


# Função Objetivo: Para cada coluna clicável, o que o título dela precisa: o endereço do próximo clique, a seta e o texto de
# apoio (aria-sort para leitor de tela; dica ao passar o mouse).
def _ordenacao_das_colunas(estado, ordem):
    rotulos = {chave: rotulo for chave, rotulo, _ in ORDENS}
    colunas = {}
    for coluna, (primeira, segunda) in ORDEM_DAS_COLUNAS.items():
        ativa = ordem in (primeira, segunda)
        proxima = segunda if ordem == primeira else primeira
        direcao = _direcao(ordem) if ativa else ''
        colunas[coluna] = {
            'ativa': ativa, 'direcao': direcao, 'url': _url(estado, ordem=proxima),
            'icone': {'asc': 'fa-sort-up', 'desc': 'fa-sort-down'}.get(direcao, 'fa-sort'),
            'aria': {'asc': 'ascending', 'desc': 'descending'}.get(direcao, 'none'),
            'dica': f'Ordenar: {rotulos[proxima]}',
        }
    return colunas


# Função Objetivo: O resumo (faixa de totais) da lista que a pessoa está vendo. Soma por CÓDIGO ÚNICO: um Código ML
# que aparece em 2 produtos conta uma vez só.
def _resumo(produtos):
    codigos = {}
    for produto in produtos:
        for cartao in produto['codigos']:
            codigos.setdefault(cartao['codigo'].upper(), cartao)
    unicos = list(codigos.values())
    n_ok = sum(1 for c in unicos if c['estado'] == 'ok')
    return {
        'n_produtos': len(produtos), 'n_codigos': len(unicos), 'n_ok': n_ok, 'n_sem_numero': len(unicos) - n_ok,
        'total_txt': _n(_soma(unicos, 'total')),
        'disponivel_txt': _n(_soma(unicos, 'disponivel')),
        'indisponivel_txt': _n(_soma(unicos, 'indisponivel')),
    }


# ---------------------------------------------------------------------------
# A PÁGINA
# ---------------------------------------------------------------------------
# Função Objetivo: Lê da URL o que a pessoa escolheu (busca, filtro, marca, ordem, itens por página) e descarta o que for
# inválido (volta ao padrão). Devolve o "estado" da tela, no mesmo formato que _url usa.
def _ler_estado(parametros):
    texto = ' '.join(str(parametros.get('q') or '').split())
    filtro = parametros.get('filtro')
    ordem = parametros.get('ordem')
    try:
        por_pagina = int(parametros.get('por_pagina') or POR_PAGINA_PADRAO)
    except (TypeError, ValueError):
        por_pagina = POR_PAGINA_PADRAO
    return {
        'q': texto,
        'filtro': filtro if filtro in {chave for chave, _, _ in FILTROS} else FILTRO_PADRAO,
        'marca': ' '.join(str(parametros.get('marca') or '').split()),
        'ordem': ordem if ordem in {chave for chave, _, _ in ORDENS} else ORDEM_PADRAO,
        'por_pagina': por_pagina if por_pagina in OPCOES_POR_PAGINA else POR_PAGINA_PADRAO,
        'p': 1,
    }


# Função Objetivo: Agrupa itens (chave, rótulo, grupo) por grupo, na ordem em que aparecem, para a tela desenhar os blocos.
def _agrupar(itens, grupo_de):
    grupos = []
    for item in itens:
        grupo = grupo_de(item)
        if not grupos or grupos[-1]['rotulo'] != grupo:
            grupos.append({'rotulo': grupo, 'itens': []})
        grupos[-1]['itens'].append(item)
    return grupos


# Função Objetivo: A tela inteira. "parametros" são os textos de request.GET (q, filtro, marca, ordem, por_pagina, p).
# LÊ SÓ DO BANCO. Devolve o que a tela desenha: colunas (com selos e setas de ordenação), filtros e marcas (com contagem),
# resumo, produtos da página e paginação.
def montar_estoque(parametros, validacoes, rotulos_situacao):
    estado = _ler_estado(parametros)
    texto, filtro, ordem, marca, por_pagina = estado['q'], estado['filtro'], estado['ordem'], estado['marca'], estado['por_pagina']
    agora = timezone.now()

    por_sku = _ler_codigos_por_sku()
    produtos_do_codigo = {}
    for sku, codigos in por_sku.items():
        for codigo_maiusculo in codigos:
            produtos_do_codigo.setdefault(codigo_maiusculo, set()).add(sku)
    cadastro = _ler_cadastro(por_sku.keys())
    ultimas = _ler_ultimas_consultas(set(produtos_do_codigo))

    produtos = [_montar_produto(sku, codigos, cadastro.get(sku), ultimas, produtos_do_codigo, agora)
                for sku, codigos in por_sku.items()]

    # 1) busca de texto; 2) marca; 3) filtro; 4) ordem; 5) página. As contagens dos botões de filtro respeitam a busca e a marca;
    # as contagens da lista de marcas respeitam a busca e o filtro — assim nenhuma escolha leva a uma lista vazia sem aviso.
    palavras = _normalizar(texto).split()
    achados = [p for p in produtos if all(palavra in p['busca'] for palavra in palavras)]
    marca_alvo = '' if marca == SEM_MARCA else _normalizar(marca)
    da_marca = lambda p: not marca or p['marca_chave'] == marca_alvo
    achados_da_marca = [p for p in achados if da_marca(p)]
    por_filtro = [p for p in achados if _passa_no_filtro(p, filtro)]

    filtros = [{'chave': chave, 'rotulo': rotulo, 'grupo': grupo, 'contagem': sum(1 for p in achados_da_marca if _passa_no_filtro(p, chave)),
                'ativo': chave == filtro, 'url': _url(estado, filtro=chave)} for chave, rotulo, grupo in FILTROS]

    # Marcas escritas com caixa diferente ("Bosch", "bosch") contam como a mesma; o nome mostrado é a grafia mais usada.
    contagem_marcas, grafias = {}, {}
    for produto in por_filtro:
        contagem_marcas[produto['marca_chave']] = contagem_marcas.get(produto['marca_chave'], 0) + 1
        das_grafias = grafias.setdefault(produto['marca_chave'], {})
        das_grafias[produto['marca']] = das_grafias.get(produto['marca'], 0) + 1
    rotulo_da_marca = {chave: max(sorted(das_grafias), key=das_grafias.get) for chave, das_grafias in grafias.items()}
    if marca and marca_alvo not in contagem_marcas:
        contagem_marcas[marca_alvo], rotulo_da_marca[marca_alvo] = 0, ('' if marca == SEM_MARCA else marca)
    marcas = [{'rotulo': 'Todas as marcas', 'contagem': len(por_filtro), 'ativo': not marca, 'url': _url(estado, marca='')}]
    marcas += [{'rotulo': rotulo_da_marca[chave], 'contagem': contagem_marcas[chave], 'ativo': bool(marca) and chave == marca_alvo,
                'url': _url(estado, marca=rotulo_da_marca[chave])} for chave in sorted(contagem_marcas) if chave]
    if '' in contagem_marcas:
        marcas.append({'rotulo': 'Sem marca cadastrada', 'contagem': contagem_marcas[''], 'ativo': bool(marca) and marca_alvo == '',
                       'url': _url(estado, marca=SEM_MARCA)})

    lista = [p for p in por_filtro if da_marca(p)]
    # Ordenar por aptas / a caminho exige a reposição de TODOS os Códigos da lista; nas outras ordens só se lê a da página.
    precisa_reposicao = ordem in ORDENS_QUE_LEEM_REPOSICAO
    if precisa_reposicao:
        _preencher_aptas(lista, ultimas)
    lista = _ordenar(lista, ordem)

    paginador = Paginator(lista, por_pagina)
    pagina = paginador.get_page(parametros.get('p') or 1)
    produtos_da_pagina = list(pagina.object_list)
    if not precisa_reposicao:
        _preencher_aptas(produtos_da_pagina, ultimas)
    for posicao, produto in enumerate(produtos_da_pagina, start=1):
        produto['indice'] = (pagina.number - 1) * por_pagina + posicao

    colunas = {chave: {'rotulo': rotulo, 'meta': _meta_do_campo(fonte, caminho, validacoes, rotulos_situacao)}
               for chave, fonte, caminho, rotulo in COLUNAS_FONTE}
    grupos_ordens = [{'rotulo': grupo['rotulo'], 'ordens': [{'chave': chave, 'rotulo': rotulo, 'ativo': chave == ordem, 'url': _url(estado, ordem=chave)}
                                                            for chave, rotulo, _ in grupo['itens']]}
                     for grupo in _agrupar(ORDENS, lambda item: item[2])]
    grupos_filtros = [{'rotulo': grupo['rotulo'], 'filtros': [f for f in filtros if f['chave'] in {i[0] for i in grupo['itens']}]}
                      for grupo in _agrupar(FILTROS, lambda item: item[2])]
    return {
        'texto': texto, 'filtro': filtro, 'ordem': ordem, 'marca': marca, 'por_pagina': por_pagina,
        'filtro_padrao': FILTRO_PADRAO, 'ordem_padrao': ORDEM_PADRAO, 'por_pagina_padrao': POR_PAGINA_PADRAO,
        'filtrada': bool(texto or marca or filtro != FILTRO_PADRAO),
        'tem_ajustes': bool(texto or marca or filtro != FILTRO_PADRAO or ordem != ORDEM_PADRAO or por_pagina != POR_PAGINA_PADRAO),
        'grupos_ordens': grupos_ordens, 'grupos_filtros': grupos_filtros, 'marcas': marcas,
        'opcoes_por_pagina': [{'valor': n, 'rotulo': f'{n} por página', 'ativo': n == por_pagina, 'url': _url(estado, por_pagina=n)}
                              for n in OPCOES_POR_PAGINA],
        'ordenacao': _ordenacao_das_colunas(estado, ordem),
        'colunas': colunas, 'badge_a_caminho': BADGE_A_CAMINHO,
        'resumo': _resumo(lista), 'produtos': produtos_da_pagina,
        'abrir_sozinho': bool(texto) and len(lista) <= LIMITE_PARA_ABRIR_SOZINHO,
        'sem_codigos_no_banco': not por_sku,
        'horas_desatualizado': HORAS_PARA_DESATUALIZADO,
        'situacoes': [
            {'badge': BADGES_ESTOQUE_FULL['atualizado'],
             'texto': f'Todos os Códigos ML do produto foram consultados há menos de {HORAS_PARA_DESATUALIZADO} horas.'},
            {'badge': BADGES_ESTOQUE_FULL['desatualizado'],
             'texto': f'Algum Código ML foi consultado há mais de {HORAS_PARA_DESATUALIZADO} horas: o número pode ter mudado desde então.'},
            {'badge': BADGES_ESTOQUE_FULL['parcial'],
             'texto': 'Só parte dos Códigos ML do produto tem número. O total do produto soma apenas esses.'},
            {'badge': BADGES_ESTOQUE_FULL['sem_consulta'],
             'texto': 'Nenhum Código ML do produto foi consultado ainda: não existe número para mostrar.'},
            {'badge': BADGES_ESTOQUE_FULL['erro'],
             'texto': 'O Mercado Livre não devolveu o estoque na última consulta.'},
        ],
        'paginacao': {
            'numero': pagina.number, 'total_paginas': paginador.num_pages, 'total': paginador.count,
            'primeiro': pagina.start_index() if paginador.count else 0, 'ultimo': pagina.end_index() if paginador.count else 0,
            'url_anterior': _url(estado, p=pagina.number - 1) if pagina.has_previous() else '',
            'url_proxima': _url(estado, p=pagina.number + 1) if pagina.has_next() else '',
        },
        'url_limpar': _url({**estado, 'q': '', 'filtro': FILTRO_PADRAO, 'marca': '', 'ordem': ORDEM_PADRAO, 'por_pagina': POR_PAGINA_PADRAO}),
    }
