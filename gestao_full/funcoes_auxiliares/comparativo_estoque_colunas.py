# gestao_full/funcoes_auxiliares/comparativo_estoque_colunas.py

# Função Objetivo: As COLUNAS da tabela do Comparativo de estoque — quais existem, como cada uma se chama (sem ambiguidade: fonte, local e id), em
# que grupo ficam e como ordenar por elas. É só o DESENHO da tabela: quem calcula os números de cada linha é comparativo_estoque.py.
#
# * [EXPLICAÇÃO] → A tabela segue o fluxo da esquerda para a direita: ① PRODUTO (quem é) → ② O QUE CADA FONTE DIZ (os números crus, agrupados por fonte:
#                  Arquivo | API Sysemp | API Mercado Livre) → ③ CONTAS (as diferenças, cada uma dizendo de quais colunas vem) → ④ ACHADOS.
#                  As colunas de ② e ③ saem do mapa da empresa (comparativo_estoque_locais.py): com outro mapa, outras colunas, sem mexer na tela.
# * [EXPLICAÇÃO] → Cada coluna é um dicionário: chave (o nome dela no endereço e na linha), fonte, tipo ("numero" ou "delta"), origem (de onde a linha tira o
#                  valor: uma tupla como ('sysemp_local', '2')), nome e papel (as duas linhas do título), as dicas e se abre um bloco ou uma fonte nova
#                  (para a divisória). Ordenar: ?ordem=<chave> (crescente ou "primeira" ordem da coluna) e ?ordem=<chave>_desc (a inversa).
# * [EXPLICAÇÃO] → O título compacto do cabeçalho usa "titulo_cab" (o nome sem o id, ex.: "Estoque Samvale 2º barracão") e "etiqueta" (o id, ex.: "id 10",
#                  que a tela desenha como uma pastilha). "nome" continua sendo o nome COMPLETO (com o id), usado nas dicas e na ordenação.

import re

from gestao_full.funcoes_auxiliares import comparativo_estoque_locais as mapa

FONTE_ARQUIVO = 'arquivo'
FONTE_SYSEMP = 'sysemp'
FONTE_ML = 'ml'
NOME_DA_FONTE = {FONTE_ARQUIVO: 'Arquivo do ERP', FONTE_SYSEMP: 'API Sysemp', FONTE_ML: 'API Mercado Livre'}

TIPO_NUMERO = 'numero'
TIPO_DELTA = 'delta'

SUFIXO_DECRESCENTE = '_desc'

# As colunas que não são número de estoque mas também ordenam: (chave, rótulo, tipo, primeira ordem).
# "primeira" = o que o 1º clique faz: texto A → Z; número maior primeiro; diferença maior primeiro (sem sinal); achados mais primeiro.
COLUNAS_FIXAS = (
    ('sku', 'SKU', 'texto', 'asc'),
    ('titulo', 'Título', 'texto', 'asc'),
    ('marca', 'Marca', 'texto', 'asc'),
    ('achados', 'Achados', 'contagem', 'desc'),
)

TEXTO_DO_SENTIDO = {
    'texto': ('A → Z', 'Z → A'),
    TIPO_NUMERO: ('menor primeiro', 'maior primeiro'),
    TIPO_DELTA: ('menor diferença primeiro (ignora o sinal)', 'maior diferença primeiro (ignora o sinal)'),
    'contagem': ('menos achados primeiro', 'mais achados primeiro'),
}


# Função Objetivo: "Estoque Emp 1" -> "estoque_emp_1" (a chave da coluna do arquivo no endereço).
def _slug(nome):
    return re.sub(r'[^a-z0-9]+', '_', nome.strip().lower()).strip('_')


# Função Objetivo: Os ids de uma conta: "id 4" (um só) ou "(id 2 + id 10)" (vários somados).
def _ids_da_conta(ids):
    return f'id {ids[0]}' if len(ids) == 1 else '(' + ' + '.join(f'id {i}' for i in ids) + ')'


def _ids_somados(ids):
    return ' + '.join(f'id {i}' for i in ids)


def _coluna(chave, fonte, origem, nome, papel, dica_celula, dica_cabecalho, tipo=TIPO_NUMERO, **extras):
    return {
        'chave': chave, 'fonte': fonte, 'origem': origem, 'tipo': tipo, 'nome': nome, 'papel': papel,
        'dica_celula': dica_celula, 'dica_cabecalho': dica_cabecalho, 'primeira': 'desc',
        'rotulo_ordem': f'{nome} ({papel})', 'inicio_bloco': False, 'inicio_fonte': False, 'titulo_cab': nome, 'etiqueta': '', **extras,
    }


# Função Objetivo: As colunas da tabela para a empresa: {'fontes': [grupos], 'contas': [grupos], 'todas': [colunas na ordem da linha]}.
# "colunas_do_arquivo" são as colunas de estoque que o arquivo do ERP tem (nome cru). Sem mapa da empresa (ex.: Magazine hoje), a tabela mostra o arquivo
# CRU (todas as colunas de estoque, sem papel) e o Mercado Livre, e não tem os blocos da Sysemp nem das contas.
def montar_colunas(empresa, colunas_do_arquivo):
    locais = mapa.locais_da_empresa(empresa)
    ids_full = [local.id for local in mapa.locais_do_papel(empresa, mapa.PAPEL_FULL)]
    ids_flex = [local.id for local in mapa.locais_do_papel(empresa, mapa.PAPEL_FLEX)]
    coluna_flex = mapa.coluna_flex_do_arquivo(empresa)
    nome_flex = coluna_flex.strip() if coluna_flex else ''

    # ② ARQUIVO: só a coluna escolhida no mapa como Flex; sem escolha no mapa, todas as colunas de estoque, cruas. As outras ficam na parte que abre.
    escolhidas = [nome for nome in colunas_do_arquivo if nome_flex and nome.strip() == nome_flex] or list(colunas_do_arquivo)
    arquivo = []
    for nome in escolhidas:
        eh_flex = bool(nome_flex) and nome.strip() == nome_flex
        limpo = nome.strip()
        arquivo.append(_coluna(
            f'arquivo_{_slug(limpo)}', FONTE_ARQUIVO, ('arquivo', nome), limpo,
            'usada como Flex' if eh_flex else 'papel a confirmar',
            f'Arquivo do ERP · coluna «{limpo}»',
            (f'Arquivo do ERP · coluna «{limpo}» (a que alimenta o banco). Comparada com o Flex da Sysemp: {_ids_da_conta(ids_flex)}.'
             if eh_flex and ids_flex else f'Arquivo do ERP · coluna «{limpo}». O papel desta coluna (Full ou Flex) ainda não foi confirmado.')))

    # ② API SYSEMP: um local por coluna (Full e Flex, na ordem do mapa) e, onde há mais de um local no mesmo papel, a soma deles.
    sysemp = []
    for local in locais:
        if local.papel in (mapa.PAPEL_FULL, mapa.PAPEL_FLEX):
            sysemp.append(_coluna(
                f'sysemp_{local.id}', FONTE_SYSEMP, ('sysemp_local', local.id), f'{local.nome} · id {local.id}', mapa.ROTULO_DO_PAPEL[local.papel],
                f'API Sysemp · {local.nome} (id {local.id})', f'API Sysemp · {local.nome} (id {local.id}). {local.explicacao}',
                titulo_cab=local.nome, etiqueta=f'id {local.id}'))
    for papel, ids in ((mapa.PAPEL_FULL, ids_full), (mapa.PAPEL_FLEX, ids_flex)):
        if len(ids) > 1:
            rotulo = mapa.ROTULO_DO_PAPEL[papel]
            sysemp.append(_coluna(
                f'sysemp_soma_{papel}', FONTE_SYSEMP, ('sysemp_soma', papel), f'Estoque {rotulo} (soma)', _ids_somados(ids),
                f'API Sysemp · soma do {rotulo} ({_ids_somados(ids)})', f'API Sysemp · soma dos locais do {rotulo}: {_ids_somados(ids)}. É uma conta, não um número da API.',
                soma=True))

    # ② API MERCADO LIVRE: sempre existe (não depende do mapa).
    ml = [
        _coluna('ml_full', FONTE_ML, ('ml', 'full'), 'Estoque Full', 'soma dos Códigos ML',
                'API Mercado Livre · Full', 'API Mercado Livre · Full: soma do Total no Full dos Códigos ML do SKU, pela última consulta gravada no banco.'),
        _coluna('ml_flex', FONTE_ML, ('ml', 'flex'), 'Estoque Flex', 'depósito, cada loja uma vez',
                'API Mercado Livre · Flex', 'API Mercado Livre · Flex: estoque do depósito do SKU (cada loja conta uma vez), pela última consulta gravada no banco.'),
    ]

    fontes = [{'chave': chave, 'titulo': NOME_DA_FONTE[chave], 'colunas': lista}
              for chave, lista in ((FONTE_ARQUIVO, arquivo), (FONTE_SYSEMP, sysemp), (FONTE_ML, ml)) if lista]

    # ③ CONTAS: só as que o mapa permite (sem mapa, sem contas).
    contas_full, contas_flex = [], []
    if ids_full:
        contas_full.append(_conta('full', [(FONTE_SYSEMP, f'Sysemp {_ids_da_conta(ids_full)}'), (FONTE_ML, 'ML Full')], 'Full'))
    if ids_flex:
        contas_flex.append(_conta('flex_api', [(FONTE_SYSEMP, f'Sysemp {_ids_da_conta(ids_flex)}'), (FONTE_ML, 'ML Flex')], 'Flex'))
        if nome_flex:
            contas_flex.append(_conta('flex_arquivo', [(FONTE_ARQUIVO, f'Arquivo «{nome_flex}»'), (FONTE_SYSEMP, f'Sysemp {_ids_da_conta(ids_flex)}')], 'Flex',
                                      nota=' O arquivo foi baixado em outro dia: parte da diferença pode ser só movimento de estoque desde então.'))
    contas = [{'titulo': titulo, 'colunas': lista} for titulo, lista in (('Full', contas_full), ('Flex', contas_flex)) if lista]

    # As divisórias: o 1º da lista de fontes e o 1º das contas abrem um bloco; o 1º de cada fonte seguinte abre uma fonte.
    for posicao, grupo in enumerate(fontes):
        grupo['colunas'][0]['inicio_bloco' if posicao == 0 else 'inicio_fonte'] = True
    if contas:
        contas[0]['colunas'][0]['inicio_bloco'] = True
    todas = [coluna for grupo in (*fontes, *contas) for coluna in grupo['colunas']]
    return {
        'fontes': fontes, 'contas': contas, 'todas': todas,
        'n_fontes': sum(len(grupo['colunas']) for grupo in fontes), 'n_contas': sum(len(grupo['colunas']) for grupo in contas),
    }


# Função Objetivo: 1 coluna de CONTA (diferença). "operandos" = [(fonte, texto)] na ordem da conta: esquerda − direita.
def _conta(sufixo, operandos, grupo, nota=''):
    texto = ' − '.join(texto for _, texto in operandos)
    return _coluna(
        f'delta_{sufixo}', 'conta', ('delta', sufixo), f'Δ {grupo}', texto,
        texto, f'Conta: {texto}. Zero = igual; qualquer outro número = diferente.{nota}',
        tipo=TIPO_DELTA, operandos=operandos, sufixo=sufixo, tag_do_filtro=f'dif_{sufixo}',
        rotulo_do_filtro=f'{grupo}: ' + ' ≠ '.join(texto for _, texto in operandos),
        dica_do_filtro=f'A conta «{texto}» deu diferente de zero.{nota}',
        rotulo_ordem=f'Δ {grupo}: {texto}')


# Função Objetivo: Tudo que se pode ordenar: {chave: {rotulo, tipo, primeira}} — as fixas (SKU, Título, Marca, Achados) e as colunas de estoque/conta.
def registro_de_ordenacao(colunas):
    registro = {chave: {'rotulo': rotulo, 'tipo': tipo, 'primeira': primeira} for chave, rotulo, tipo, primeira in COLUNAS_FIXAS}
    for coluna in colunas['todas']:
        registro[coluna['chave']] = {'rotulo': coluna['rotulo_ordem'], 'tipo': coluna['tipo'], 'primeira': coluna['primeira']}
    return registro


# Função Objetivo: Separa "sysemp_2_desc" em ("sysemp_2", True).
def separar_ordem(ordem):
    if ordem.endswith(SUFIXO_DECRESCENTE):
        return ordem[:-len(SUFIXO_DECRESCENTE)], True
    return ordem, False


# Função Objetivo: As ordens que a tela aceita (cada coluna nos 2 sentidos).
def ordens_validas(registro):
    return {chave + sufixo for chave in registro for sufixo in ('', SUFIXO_DECRESCENTE)}


# Função Objetivo: Para cada coluna: o que o cabeçalho clicável precisa — o endereço do próximo clique, a seta e os textos de apoio.
# 1º clique usa a "primeira" ordem da coluna; clicar de novo inverte. "url_da_ordem(ordem)" é quem monta o endereço da tela.
def ordenacao_das_colunas(registro, ordem_atual, url_da_ordem):
    chave_atual, decrescente_atual = separar_ordem(ordem_atual)
    resultado = {}
    for chave, info in registro.items():
        ativa = chave == chave_atual
        proxima_decrescente = (not decrescente_atual) if ativa else info['primeira'] == 'desc'
        direcao = ('desc' if decrescente_atual else 'asc') if ativa else ''
        sentido = TEXTO_DO_SENTIDO[info['tipo']][1 if proxima_decrescente else 0]
        resultado[chave] = {
            'ativa': ativa, 'direcao': direcao,
            'url': url_da_ordem(chave + SUFIXO_DECRESCENTE if proxima_decrescente else chave),
            'icone': {'asc': 'fa-sort-up', 'desc': 'fa-sort-down'}.get(direcao, 'fa-sort'),
            'aria': {'asc': 'ascending', 'desc': 'descending'}.get(direcao, 'none'),
            'dica': f'Ordenar por {info["rotulo"]}: {sentido}',
        }
    return resultado


# Função Objetivo: Põe as linhas na ordem escolhida, valendo para a lista INTEIRA (a paginação vem depois). Parte sempre de SKU A → Z, então todo empate
# sai por SKU (o sort do Python é estável, inclusive com reverse). Quem não tem valor na coluna (— ou vazio) vai para o fim, nos dois sentidos.
# Cada linha traz em linha['ordem'] o valor de cada coluna (texto já normalizado, Decimal, ou None).
def ordenar(linhas, ordem):
    chave, decrescente = separar_ordem(ordem)
    por_sku = sorted(linhas, key=lambda linha: (linha['sku'] == '', linha['sku'].lower(), linha['chave']))
    com_valor = [linha for linha in por_sku if linha['ordem'].get(chave) not in (None, '')]
    sem_valor = [linha for linha in por_sku if linha['ordem'].get(chave) in (None, '')]
    com_valor.sort(key=lambda linha: linha['ordem'][chave], reverse=decrescente)
    return com_valor + sem_valor
