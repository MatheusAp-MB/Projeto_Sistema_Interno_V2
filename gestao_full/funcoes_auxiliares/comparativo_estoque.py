# gestao_full/funcoes_auxiliares/comparativo_estoque.py
#
# Monta a tela "Full — Comparativo de estoque (debug)": para cada SKU, o estoque lado a lado nas 3 fontes —
#   ARQUIVO       o relatório de produtos do ERP (o MESMO xlsx que alimenta o banco: importar_produtos_erp);
#   API SYSEMP    a última COLETA do método listarAnaliseEstoqueFull (botão "Coletar do Sysemp"; comparativo_estoque_sysemp.py);
#   API ML        o que o Mercado Livre respondeu nas últimas consultas gravadas no banco (Full e Flex).
# É uma tela de DEBUG: serve para o Matheus entender se os dados da API são confiáveis e o que pedir à Sysemp. Nada aqui é usado por outro
# módulo do sistema, e nada aqui chama API nenhuma — a tela só LÊ o arquivo, a coleta guardada no cache e o banco.
#
# * [EXPLICAÇÃO] → Diferença (Δ) é só a conta "esquerda menos direita", em número. NÃO há tolerância (o Matheus decidiu não definir um valor agora):
#                  zero = igual; qualquer outro número = diferente. Quem decide se uma diferença importa é quem lê.
# * [EXPLICAÇÃO] → Quem é Full e quem é Flex em cada fonte vem do mapa em comparativo_estoque_locais.py (Samvale: Full = local 4 da Sysemp;
#                  Flex = locais 2 + 10 e coluna "Estoque" do arquivo). O arquivo da Samvale NÃO tem coluna do Full.
# * [EXPLICAÇÃO] → As COLUNAS da tabela (quais existem, como se chamam, em que grupo ficam e como ordenar) moram em comparativo_estoque_colunas.py e saem do
#                  mapa da empresa. Aqui cada linha só guarda os valores; o desenho é de lá.
# * [EXPLICAÇÃO] → Ausente NÃO é sempre zero. A API Sysemp só manda linhas com estoque MAIOR que zero: com a coleta COMPLETA, um SKU que não veio
#                  vale 0 (a tela mostra esse 0 apagado, "implícito"). Com a coleta INCOMPLETA, ou sem coleta, ausente é "—" (não sei).
#                  No Mercado Livre, SKU sem Código do Full no banco, ou Código nunca consultado, também é "—": nunca vira 0.
# * [EXPLICAÇÃO] → Dado bruto (célula do arquivo, linha da API) só é tocado pelas funções de leitura (ler_arquivo, organizar_sysemp): elas
#                  limpam (tiram espaços, convertem texto em número) e marcam o que está estranho ("achados"). O resto trabalha com dado organizado.
# * [EXPLICAÇÃO] → O botão "Exportar Excel" usa a MESMA montagem da tela (montar_comparativo com todas_as_linhas=True): a lista sai inteira, sem paginar, com a mesma
#                  busca, filtro e ordem. O desenho do .xlsx mora em comparativo_estoque_exportacao.py; por isso cada célula da linha guarda também o NÚMERO ("valor"),
#                  não só o texto que a tela mostra.

import os
import re
import traceback
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone as fuso_utc
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from core.empresa import NOME_EXIBICAO_POR_EMPRESA
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from core.management.commands.popular_banco_suporte.importar_produtos_erp import CAMINHOS_ERP_POR_EMPRESA
from core.management.commands.popular_banco_suporte.leitor_planilha_erp import ler_linhas_planilha_erp
from gestao_full.funcoes_auxiliares import comparativo_estoque_colunas as colunas_mod
from gestao_full.funcoes_auxiliares import comparativo_estoque_locais as mapa
from gestao_full.funcoes_auxiliares.comparativo_estoque_sysemp import TEXTO_DO_FIM_ANORMAL, ler_coleta
from gestao_full.funcoes_auxiliares.full_estoque_ml import _data_hora_completa, _idade, _ler_cadastro, _normalizar, montar_produtos_com_full_e_flex

# O padrão de SKU do projeto: "F" + EAN + ".001" (ex.: F7908050719121.001). SKU fora disso aparece como achado, não como erro.
PADRAO_SKU = re.compile(r'^F\d+\.\d+$')

# Colunas do arquivo do ERP que esta tela lê (o resto da planilha, com mais de 100 colunas, é ignorado). Título, Marca e foto são as MESMAS colunas que o
# importador de produtos lê (importar_produtos_erp.py: titulo <- "Detalhes do Produto", marca <- "Marca", imagem_url <- "URL 1").
COLUNA_SKU_DO_ARQUIVO = 'Codigo Auxiliar'
COLUNA_DESCRICAO_DO_ARQUIVO = 'Detalhes do Produto'
COLUNA_MARCA_DO_ARQUIVO = 'Marca'
COLUNA_FOTO_DO_ARQUIVO = 'URL 1'

# * [EXPLICAÇÃO] → Quais colunas do arquivo SÃO estoque (conferido nos arquivos reais de 17/08/2026): "Estoque" (a que alimenta o banco), "Estoque Emp N"
#                  (1 coluna por local do ERP) e "Estoque Fornecedor". O arquivo também tem "estoque_minimo"/"Estoque Minimo" (um limite de reposição,
#                  NÃO é quantidade em estoque) — por isso não vale pegar "tudo que começa com Estoque".
PADRAO_COLUNA_DE_ESTOQUE = re.compile(r'^Estoque( Emp (\d+)| Fornecedor)?$', re.IGNORECASE)

CHAVE_CACHE_ARQUIVO = 'comparativo_estoque_arquivo_v2_{empresa}'
PREFIXO_SEM_SKU = 'sem-sku:'
NAO_DISPONIVEL = '—'

# ---------------------------------------------------------------------------
# OS FILTROS ("chips") — cada filtro é uma marca (tag) que a linha pode ter. Ordem e textos moram só aqui.
# ---------------------------------------------------------------------------
GRUPOS_DE_FILTROS = (
    ('Diferenças entre as fontes', (
        ('dif_full', 'Full: Sysemp ≠ ML', 'O estoque do Full no Sysemp (o local que controla o Full) é diferente do Full no Mercado Livre.'),
        ('dif_flex_api', 'Flex: Sysemp ≠ ML', 'O estoque fora do Full no Sysemp (locais Flex somados) é diferente do Flex no Mercado Livre.'),
        ('dif_flex_arquivo', 'Flex: Arquivo ≠ Sysemp', 'O estoque do arquivo do ERP é diferente do estoque fora do Full na API Sysemp (o arquivo foi baixado em outro dia).'),
    )),
    ('Presença do SKU', (
        ('so_arquivo', 'Só no Arquivo', 'O SKU está no arquivo do ERP, mas não veio na API Sysemp nem no Mercado Livre.'),
        ('so_sysemp', 'Só na API Sysemp', 'O SKU veio na API Sysemp, mas não está no arquivo do ERP nem no Mercado Livre.'),
        ('so_ml', 'Só no Mercado Livre', 'O SKU tem Código ML do Full no banco, mas não está no arquivo do ERP nem na API Sysemp.'),
    )),
    ('Achados na API Sysemp', (
        ('sysemp_sem_sku', 'Linha sem SKU', 'A API mandou uma linha de estoque sem SKU: não dá para casar com nenhuma outra fonte.'),
        ('sysemp_sku_fora_padrao', 'SKU fora do padrão', 'O SKU não segue o padrão do projeto ("F" + EAN + ".001").'),
        ('sysemp_sku_espaco', 'SKU com espaço nas pontas', 'O SKU veio com espaço antes ou depois (a tela já limpa para comparar).'),
        ('sysemp_sku_em_varios_produtos', 'SKU em mais de um id_produto', 'O mesmo SKU veio ligado a mais de um id_produto (as quantidades do mesmo local foram somadas).'),
        ('sysemp_linha_repetida', 'Linha repetida na paginação', 'A mesma linha (local + produto) veio mais de uma vez (as páginas podem estar se sobrepondo). Foi contada uma vez só.'),
        ('sysemp_local_sem_movimento', 'Estoque no local sem movimento', 'Há estoque num local que não deveria ter nenhum (VSComercio, id 1).'),
        ('sysemp_local_desconhecido', 'Local fora do mapa', 'A linha é de um local de estoque que não está no mapa da empresa (aparece como "fora do mapa" no detalhe).'),
        ('sysemp_estoque_invalido', 'Estoque não numérico', 'O campo estoque da linha não é um número.'),
    )),
    ('Achados no Arquivo', (
        ('arquivo_sku_fora_padrao', 'SKU fora do padrão', 'O SKU (coluna Codigo Auxiliar) não segue o padrão do projeto ("F" + EAN + ".001").'),
        ('arquivo_sku_espaco', 'SKU com espaço nas pontas', 'O SKU do arquivo veio com espaço antes ou depois (a tela já limpa para comparar).'),
        ('arquivo_sku_repetido', 'SKU repetido', 'O mesmo SKU aparece em mais de uma linha do arquivo (vale a primeira).'),
        ('arquivo_estoque_invalido', 'Estoque não numérico', 'Alguma coluna de estoque do arquivo tem um valor que não é número.'),
    )),
    ('Achados no Mercado Livre', (
        ('ml_sem_consulta', 'Sem consulta no ML', 'Nenhum Código ML do SKU foi consultado ainda: o número do Mercado Livre não existe (não é zero).'),
        ('ml_parcial', 'Número do ML parcial', 'Algum Código ML do SKU ficou sem consulta ou com erro: o Full do SKU soma só os Códigos que têm número.'),
    )),
)
FILTRO_PADRAO = 'todos'
# * [EXPLICAÇÃO] → Os 3 filtros de diferença acima são só o LUGAR deles na tela: o texto de verdade (qual conta, com qual id) vem das colunas da empresa
#                  (_filtros_da_empresa). Empresa sem a conta (ex.: Magazine, sem mapa) não mostra o filtro.
CHAVES_DAS_CONTAS = ('dif_full', 'dif_flex_api', 'dif_flex_arquivo')

# A ordem de abertura da tela: SKU de A a Z. Clicar no título de qualquer coluna ordena por ela (ver comparativo_estoque_colunas.py).
ORDEM_PADRAO = 'sku'

POR_PAGINA_PADRAO = 50
OPCOES_POR_PAGINA = (25, 50, 100, 200)
MAX_TEXTO_BUSCA = 100
PADROES_DA_URL = {'q': '', 'filtro': FILTRO_PADRAO, 'ordem': ORDEM_PADRAO, 'por_pagina': POR_PAGINA_PADRAO, 'p': 1}


# ---------------------------------------------------------------------------
# PEQUENAS AJUDAS (números e textos)
# ---------------------------------------------------------------------------
# Função Objetivo: Texto da API/célula como texto limpo ('' se vazio).
def _texto(valor):
    return '' if valor is None else str(valor).strip()


# Função Objetivo: A URL da foto só vale se começa com http:// ou https://: dado do arquivo nunca vira link com outro tipo de endereço (como "javascript:"). Senão, vazio.
def _url_da_foto(texto):
    texto = _texto(texto)
    return texto if texto.lower().startswith(('http://', 'https://')) else ''


# Função Objetivo: Número de uma célula/campo como Decimal, ou None se estiver vazio ou não for número. Aceita vírgula decimal.
def _para_decimal(valor):
    texto = _texto(valor).replace(',', '.')
    if not texto:
        return None
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        return None
    return numero if numero.is_finite() else None


# Função Objetivo: "1146" -> "1.146"; "22.5" -> "22,5"; None -> "—". Sem casas à toa: 22.0000 vira 22.
def _txt(valor):
    if valor is None:
        return NAO_DISPONIVEL
    numero = Decimal(valor)
    sinal = '-' if numero < 0 else ''
    numero = abs(numero)
    if numero == numero.to_integral_value():
        return sinal + f'{int(numero):,}'.replace(',', '.')
    inteira, _, fracao = format(numero.normalize(), 'f').partition('.')
    return sinal + f'{int(inteira):,}'.replace(',', '.') + ',' + fracao


# Função Objetivo: A diferença com sinal: "+3", "−2", "0", ou "—" se não dá para calcular.
def _txt_delta(delta):
    if delta is None:
        return NAO_DISPONIVEL
    if delta == 0:
        return '0'
    return ('+' if delta > 0 else '−') + _txt(abs(delta))


# Função Objetivo: "esquerda − direita" se as duas existem, senão None.
def _diferenca(esquerda, direita):
    return None if esquerda is None or direita is None else Decimal(esquerda) - Decimal(direita)


def _estado_da_diferenca(delta):
    return 'nd' if delta is None else ('igual' if delta == 0 else 'diferente')


def _plural(n, singular, plural):
    return singular if n == 1 else plural


def _quando(momento, agora):
    return f'{_data_hora_completa(momento)} ({_idade(momento, agora)})' if momento else ''


# ---------------------------------------------------------------------------
# FONTE 1 — O ARQUIVO DO ERP
# ---------------------------------------------------------------------------
# Função Objetivo: O que se sabe do arquivo do ERP depois de lido e limpo. "por_sku" = {sku: {descricao (o título), marca, foto (URL 1), valores {coluna: Decimal|None},
# espaco, repetido, invalido}}. "colunas" = as colunas de estoque, em ordem fixa: "Estoque", depois "Estoque Emp N" pelo número, depois "Estoque Fornecedor".
@dataclass
class FonteArquivo:
    caminho: str = ''
    disponivel: bool = False
    erro: str = ''
    modificado_em: datetime | None = None
    colunas: tuple = ()
    por_sku: dict = field(default_factory=dict)
    n_linhas: int = 0
    n_sem_sku: int = 0
    n_celulas_invalidas: int = 0


# Função Objetivo: Lê o arquivo de ATIVOS do ERP da empresa (o mesmo caminho e o mesmo leitor do importador de produtos) e o organiza. A leitura é
# guardada no cache junto com a data de modificação do arquivo: enquanto o arquivo não mudar, buscar, filtrar e paginar não o leem de novo.
def ler_arquivo(empresa):
    caminho = os.path.abspath(CAMINHOS_ERP_POR_EMPRESA[empresa]['ativos'])
    if not os.path.isfile(caminho):
        return FonteArquivo(caminho=caminho, erro='Arquivo não encontrado. Coloque o relatório de produtos ativos do ERP neste caminho (o mesmo que o importador usa).')
    modificado = os.path.getmtime(caminho)
    chave = CHAVE_CACHE_ARQUIVO.format(empresa=empresa)
    guardado = cache.get(chave)
    if guardado is not None and guardado[0] == modificado:
        return guardado[1]
    try:
        fonte = _organizar_arquivo(caminho, modificado)
    except Exception as erro:
        # Arquivo aberto no Excel (bloqueado), corrompido, sem as colunas... A tela mostra o motivo; o detalhe completo vai para o terminal.
        traceback.print_exc()
        return FonteArquivo(caminho=caminho, erro=f'Não consegui ler o arquivo: {str(erro)[:300]}')
    cache.set(chave, (modificado, fonte), timeout=None)
    return fonte


# Função Objetivo: A posição de uma coluna de estoque na tela: "Estoque" primeiro, depois "Estoque Emp N" (pelo número) e por último "Estoque Fornecedor".
def _ordem_da_coluna(nome):
    achado = PADRAO_COLUNA_DE_ESTOQUE.match(nome.strip())
    if achado.group(2):
        return (1, int(achado.group(2)))
    return (2, 0) if achado.group(1) else (0, 0)


# Função Objetivo: Organiza as linhas do arquivo: SKU limpo, estoque de cada coluna de estoque como número, e as marcas do que está estranho.
def _organizar_arquivo(caminho, modificado):
    linhas = ler_linhas_planilha_erp(caminho)
    conversor = ConversorCelulaExcel('openpyxl')
    colunas = tuple(sorted((nome for nome in (linhas[0].keys() if linhas else ())
                            if isinstance(nome, str) and PADRAO_COLUNA_DE_ESTOQUE.match(nome.strip())), key=_ordem_da_coluna))
    fonte = FonteArquivo(caminho=caminho, disponivel=True, modificado_em=datetime.fromtimestamp(modificado, tz=fuso_utc.utc),
                         colunas=colunas, n_linhas=len(linhas))
    for linha in linhas:
        bruto = linha.get(COLUNA_SKU_DO_ARQUIVO)
        if isinstance(bruto, float) and bruto.is_integer():
            bruto = int(bruto)
        sku_bruto = '' if bruto is None else str(bruto)
        sku = sku_bruto.strip()
        if not sku:
            fonte.n_sem_sku += 1
            continue
        valores, invalido = {}, False
        for coluna in colunas:
            celula = linha.get(coluna)
            # Mesmo critério do importador: célula vazia = 0. Texto que não é número vira None (e é marcado), nunca 0 em silêncio.
            try:
                numero = conversor.para_decimal(celula, padrao=Decimal(0))
            except InvalidOperation:
                numero = None
            if numero is None:
                invalido = True
                fonte.n_celulas_invalidas += 1
            valores[coluna] = numero
        if sku in fonte.por_sku:
            fonte.por_sku[sku]['repetido'] = True
            continue
        fonte.por_sku[sku] = {'descricao': conversor.para_texto(linha.get(COLUNA_DESCRICAO_DO_ARQUIVO), ''),
                              'marca': conversor.para_texto(linha.get(COLUNA_MARCA_DO_ARQUIVO), ''),
                              'foto': _url_da_foto(conversor.para_texto(linha.get(COLUNA_FOTO_DO_ARQUIVO), '')), 'valores': valores,
                              'espaco': sku_bruto != sku, 'repetido': False, 'invalido': invalido}
    return fonte


# ---------------------------------------------------------------------------
# FONTE 2 — A API SYSEMP (a última coleta)
# ---------------------------------------------------------------------------
# Função Objetivo: A última coleta da API Sysemp já organizada. "por_chave" = {chave: {sku, descricao, por_local {id: Decimal}, ids_produto,
# sku_bruto, tags}}; a chave é o SKU (ou "sem-sku:<id_produto>" para linha sem SKU).
@dataclass
class FonteSysemp:
    disponivel: bool = False
    coletada: bool = False
    completa: bool = False
    coletado_em: datetime | None = None
    paginas: int = 0
    tamanhos_das_paginas: list = field(default_factory=list)
    motivo_do_fim: str = ''
    detalhe_do_fim: str = ''
    duracao_segundos: int = 0
    n_linhas: int = 0
    n_linhas_repetidas: int = 0
    n_linhas_fora_do_formato: int = 0
    locais_vistos: Counter = field(default_factory=Counter)
    por_chave: dict = field(default_factory=dict)


# Função Objetivo: Organiza a coleta guardada da empresa: limpa SKU e estoque, junta o mesmo SKU de vários locais e marca o que está estranho.
def organizar_sysemp(empresa):
    fonte = FonteSysemp(disponivel=mapa.api_sysemp_disponivel(empresa))
    coleta = ler_coleta(empresa) if fonte.disponivel else None
    if coleta is None:
        return fonte
    fonte.coletada, fonte.completa = True, bool(coleta['completa'])
    fonte.coletado_em, fonte.paginas = coleta['coletado_em'], coleta['paginas']
    fonte.tamanhos_das_paginas = list(coleta['tamanhos_das_paginas'])
    fonte.motivo_do_fim, fonte.detalhe_do_fim = coleta['motivo_do_fim'], coleta['detalhe_do_fim']
    fonte.duracao_segundos, fonte.n_linhas = coleta['duracao_segundos'], len(coleta['linhas'])

    tem_mapa = bool(mapa.locais_da_empresa(empresa))
    ja_vistas = set()
    for numero, linha in enumerate(coleta['linhas'], start=1):
        if not isinstance(linha, dict):
            fonte.n_linhas_fora_do_formato += 1
            continue
        id_local, id_produto = _texto(linha.get('id_empresa')), _texto(linha.get('id_produto'))
        sku_bruto = '' if linha.get('sku') is None else str(linha.get('sku'))
        sku = sku_bruto.strip()
        chave = sku or f'{PREFIXO_SEM_SKU}{id_produto or numero}'
        item = fonte.por_chave.setdefault(chave, {'sku': sku, 'descricao': '', 'por_local': {}, 'ids_produto': set(), 'sku_bruto': sku_bruto, 'tags': set()})

        # A mesma linha (local + produto) de novo = páginas que se sobrepõem: conta uma vez só e marca.
        if (id_local, id_produto) in ja_vistas:
            fonte.n_linhas_repetidas += 1
            item['tags'].add('sysemp_linha_repetida')
            continue
        ja_vistas.add((id_local, id_produto))

        fonte.locais_vistos[id_local] += 1
        item['ids_produto'].add(id_produto)
        item['descricao'] = item['descricao'] or _texto(linha.get('descricao'))
        estoque = _para_decimal(linha.get('estoque'))
        if estoque is None:
            item['tags'].add('sysemp_estoque_invalido')
        else:
            item['por_local'][id_local] = item['por_local'].get(id_local, Decimal(0)) + estoque

        if not sku:
            item['tags'].add('sysemp_sem_sku')
        else:
            if sku_bruto != sku:
                item['tags'].add('sysemp_sku_espaco')
            if not PADRAO_SKU.match(sku):
                item['tags'].add('sysemp_sku_fora_padrao')
        if tem_mapa:
            local = mapa.local_por_id(empresa, id_local)
            if local is None:
                item['tags'].add('sysemp_local_desconhecido')
            elif local.papel == mapa.PAPEL_SEM_MOVIMENTO and estoque is not None and estoque > 0:
                item['tags'].add('sysemp_local_sem_movimento')

    for item in fonte.por_chave.values():
        if len(item['ids_produto']) > 1:
            item['tags'].add('sysemp_sku_em_varios_produtos')
    return fonte


# ---------------------------------------------------------------------------
# FONTE 3 — A API DO MERCADO LIVRE (o que está gravado no banco)
# ---------------------------------------------------------------------------
# Função Objetivo: O que o banco sabe do Full e do Flex de cada SKU, pela última consulta de cada Código ML. "por_sku" = {sku: {full, flex, ...}}.
@dataclass
class FonteMl:
    n_produtos: int = 0
    n_sem_consulta: int = 0
    n_parciais: int = 0
    n_codigos_sem_sku: int = 0
    mais_antiga: datetime | None = None
    mais_recente: datetime | None = None
    por_sku: dict = field(default_factory=dict)


# Função Objetivo: LÊ SÓ DO BANCO (nunca chama o Mercado Livre). Full = soma do Total no Full dos Códigos ML do SKU; Flex = depósito (cada loja uma vez).
def ler_ml(agora):
    fonte = FonteMl()
    for produto in montar_produtos_com_full_e_flex(agora):
        if not produto['sku']:
            fonte.n_codigos_sem_sku += produto['n_codigos']
            continue
        sem_consulta = produto['status'] == 'sem_consulta'
        parcial = not sem_consulta and (produto['n_ok'] < produto['n_codigos'])
        fonte.por_sku[produto['sku']] = {
            'full': produto['total'], 'flex': produto['deposito'], 'flex_parcial': produto['deposito_parcial'], 'flex_aviso': produto['deposito_aviso'],
            'n_codigos': produto['n_codigos'], 'n_ok': produto['n_ok'], 'n_erro': produto['n_erro'], 'n_sem_consulta': produto['n_sem_consulta'],
            'sem_consulta': sem_consulta, 'parcial': parcial, 'mais_antiga': produto['mais_antiga'], 'mais_recente': produto['mais_recente'],
        }
        fonte.n_sem_consulta += int(sem_consulta)
        fonte.n_parciais += int(parcial)
        if produto['mais_antiga'] is not None:
            fonte.mais_antiga = produto['mais_antiga'] if fonte.mais_antiga is None else min(fonte.mais_antiga, produto['mais_antiga'])
        if produto['mais_recente'] is not None:
            fonte.mais_recente = produto['mais_recente'] if fonte.mais_recente is None else max(fonte.mais_recente, produto['mais_recente'])
    fonte.n_produtos = len(fonte.por_sku)
    return fonte


# ---------------------------------------------------------------------------
# AS LINHAS (1 por SKU, juntando as 3 fontes)
# ---------------------------------------------------------------------------
# Função Objetivo: O estoque de 1 local da Sysemp para 1 SKU: (valor, implicito). Ver a regra "ausente não é sempre zero" no cabeçalho do arquivo.
def _valor_do_local(id_local, item_sysemp, sysemp):
    if not sysemp.coletada:
        return None, False
    if item_sysemp is not None and id_local in item_sysemp['por_local']:
        return item_sysemp['por_local'][id_local], False
    return (Decimal(0), True) if sysemp.completa else (None, False)


# Função Objetivo: Soma o estoque dos locais de um papel; None se o mapa não tem esse papel ou se algum dos locais está sem dado.
def _somar_locais(ids, valores_por_id):
    if not ids:
        return None
    valores = [valores_por_id[id_local] for id_local in ids]
    return None if any(valor is None for valor in valores) else sum(valores, Decimal(0))


# Função Objetivo: Quem é o produto (título, marca, foto) e de onde isso veio. Vale a PRIMEIRA fonte que conhece o SKU: o arquivo do ERP (as mesmas colunas que o
# importador lê); se o SKU não está no arquivo, o cadastro do banco (Produto); por último, a descrição que a Sysemp mandou (só o título).
def _identificacao(a, cadastro, s):
    if a is not None:
        return {'titulo': a['descricao'], 'marca': a['marca'], 'foto': a['foto'], 'origem': 'arquivo', 'nota': ''}
    if cadastro is not None:
        return {'titulo': cadastro['titulo'], 'marca': cadastro['marca'], 'foto': _url_da_foto(cadastro['imagem_url']),
                'origem': 'banco', 'nota': 'do banco (SKU fora do arquivo)'}
    if s is not None:
        return {'titulo': s['descricao'], 'marca': '', 'foto': '', 'origem': 'sysemp', 'nota': 'da Sysemp (SKU fora do arquivo e do banco)'}
    return {'titulo': '', 'marca': '', 'foto': '', 'origem': '', 'nota': ''}


# Função Objetivo: A linha de 1 SKU (ou de 1 linha da Sysemp sem SKU): quem é, os números de cada coluna da tabela (na ordem das colunas), o valor de cada coluna
# para ordenar e as marcas (tags). "colunas" vem de comparativo_estoque_colunas.montar_colunas; "rotulos_da_marca" = {tag: (rótulo, dica)} dos achados da empresa.
def _montar_linha(chave, empresa, arquivo, sysemp, ml, cadastro, colunas, rotulos_da_marca, agora):
    a, s, m = arquivo.por_sku.get(chave), sysemp.por_chave.get(chave), ml.por_sku.get(chave)
    sku = '' if chave.startswith(PREFIXO_SEM_SKU) else chave
    quem = _identificacao(a, cadastro.get(chave), s)
    ids_full = [local.id for local in mapa.locais_do_papel(empresa, mapa.PAPEL_FULL)]
    ids_flex = [local.id for local in mapa.locais_do_papel(empresa, mapa.PAPEL_FLEX)]
    coluna_flex = (mapa.coluna_flex_do_arquivo(empresa) or '').strip()

    # ARQUIVO: o número da coluna escolhida no mapa como Flex (se o mapa tem uma). As demais colunas aparecem na parte que abre, ou na tabela se o mapa não escolheu.
    arquivo_flex = next((valor for nome, valor in a['valores'].items() if nome.strip() == coluna_flex), None) if (a and coluna_flex) else None

    # SYSEMP: cada local do mapa (na ordem do mapa) + os locais que vieram e não estão no mapa.
    sysemp_locais, valores_por_id = [], {}
    for local in mapa.locais_da_empresa(empresa):
        valor, implicito = _valor_do_local(local.id, s, sysemp)
        valores_por_id[local.id] = valor
        sysemp_locais.append({'id': local.id, 'rotulo': local.rotulo, 'papel': local.papel, 'valor': valor, 'txt': _txt(valor), 'implicito': implicito})
    for id_local, valor in sorted(((s or {}).get('por_local') or {}).items()):
        if id_local not in valores_por_id:
            sysemp_locais.append({'id': id_local, 'rotulo': f'Local {id_local} (fora do mapa)', 'papel': '', 'valor': valor, 'txt': _txt(valor), 'implicito': False})
    sysemp_full, sysemp_flex = _somar_locais(ids_full, valores_por_id), _somar_locais(ids_flex, valores_por_id)
    implicito_por_id = {local['id']: local['implicito'] for local in sysemp_locais}
    sysemp_full_implicito = sysemp_full is not None and all(implicito_por_id[id_local] for id_local in ids_full)
    sysemp_flex_implicito = sysemp_flex is not None and all(implicito_por_id[id_local] for id_local in ids_flex)

    # MERCADO LIVRE
    ml_full, ml_flex = (m['full'] if m else None), (m['flex'] if m else None)
    ml_linha = None
    if m:
        ml_linha = {**m, 'mais_antiga_txt': _quando(m['mais_antiga'], agora), 'mais_recente_txt': _quando(m['mais_recente'], agora)}

    delta_full = _diferenca(sysemp_full, ml_full)
    delta_flex_api = _diferenca(sysemp_flex, ml_flex)
    delta_flex_arquivo = _diferenca(arquivo_flex, sysemp_flex)

    # Os valores de cada "origem" de coluna (ver comparativo_estoque_colunas): (valor, é zero implícito?). Quem não está aqui é "—".
    valores = {('arquivo', nome): (valor, False) for nome, valor in (a['valores'].items() if a else ())}
    valores.update({('sysemp_local', local['id']): (local['valor'], local['implicito']) for local in sysemp_locais})
    valores.update({
        ('sysemp_soma', mapa.PAPEL_FULL): (sysemp_full, sysemp_full_implicito), ('sysemp_soma', mapa.PAPEL_FLEX): (sysemp_flex, sysemp_flex_implicito),
        ('ml', 'full'): (ml_full, False), ('ml', 'flex'): (ml_flex, False),
        ('delta', 'full'): (delta_full, False), ('delta', 'flex_api'): (delta_flex_api, False), ('delta', 'flex_arquivo'): (delta_flex_arquivo, False),
    })

    # As células, na MESMA ordem das colunas (o cabeçalho e a linha andam juntos). "ordem" guarda o valor de cada coluna para ordenar a lista inteira:
    # a diferença ordena pelo tamanho dela (sem o sinal).
    celulas, ordem = [], {}
    for coluna in colunas['todas']:
        valor, implicito = valores.get(coluna['origem'], (None, False))
        eh_diferenca = coluna['tipo'] == colunas_mod.TIPO_DELTA
        celulas.append({
            'tipo': coluna['tipo'], 'txt': _txt_delta(valor) if eh_diferenca else _txt(valor), 'estado': _estado_da_diferenca(valor) if eh_diferenca else '',
            'valor': valor, 'implicito': implicito, 'dica': coluna['dica_celula'], 'inicio_bloco': coluna['inicio_bloco'], 'inicio_fonte': coluna['inicio_fonte'],
        })
        ordem[coluna['chave']] = (abs(valor) if valor is not None else None) if eh_diferenca else valor

    tags = set()
    if a:
        tags |= {tag for tag, ativo in (('arquivo_sku_espaco', a['espaco']), ('arquivo_sku_repetido', a['repetido']), ('arquivo_estoque_invalido', a['invalido']),
                                        ('arquivo_sku_fora_padrao', not PADRAO_SKU.match(chave))) if ativo}
    if s:
        tags |= s['tags']
    if m:
        if m['sem_consulta']:
            tags.add('ml_sem_consulta')
        if m['parcial']:
            tags.add('ml_parcial')
    # "Só em uma fonte" só tem sentido quando pelo menos 2 fontes têm dado carregado.
    carregadas = (arquivo.disponivel, sysemp.coletada, ml.n_produtos > 0)
    presentes = (a is not None, s is not None, m is not None)
    if sum(carregadas) >= 2 and sum(presentes) == 1:
        tags.add(('so_arquivo', 'so_sysemp', 'so_ml')[presentes.index(True)])
    for tag, delta in (('dif_full', delta_full), ('dif_flex_api', delta_flex_api), ('dif_flex_arquivo', delta_flex_arquivo)):
        if delta is not None and delta != 0:
            tags.add(tag)

    achados = [rotulos_da_marca[tag] for tag in rotulos_da_marca if tag in tags]
    n_achados = sum(1 for tag in tags if tag.startswith(('sysemp_', 'arquivo_', 'ml_')))
    ordem.update({'sku': sku.lower(), 'titulo': _normalizar(quem['titulo']), 'marca': _normalizar(quem['marca']), 'achados': n_achados})

    # O que NÃO está na tabela e aparece na parte que abre: colunas do arquivo que a tabela não mostra e locais da Sysemp que a tabela não mostra.
    nomes_do_arquivo_na_tabela = {coluna['origem'][1] for coluna in colunas['todas'] if coluna['origem'][0] == 'arquivo'}
    ids_da_sysemp_na_tabela = {coluna['origem'][1] for coluna in colunas['todas'] if coluna['origem'][0] == 'sysemp_local'}
    return {
        'chave': chave, 'sku': sku, 'titulo': quem['titulo'], 'marca': quem['marca'], 'foto': quem['foto'],
        'identificacao_origem': quem['origem'], 'identificacao_nota': quem['nota'], 'busca': _normalizar(f"{sku} {quem['titulo']} {quem['marca']}"),
        'no_arquivo': a is not None, 'no_sysemp': s is not None, 'no_ml': m is not None,
        'celulas': celulas, 'ordem': ordem,
        'arquivo_fora_da_tabela': [{'rotulo': nome.strip(), 'txt': _txt(valor), 'valor': valor} for nome, valor in a['valores'].items() if nome not in nomes_do_arquivo_na_tabela] if a else [],
        'sysemp_fora_da_tabela': [local for local in sysemp_locais if local['id'] not in ids_da_sysemp_na_tabela],
        'sysemp_ids_produto': sorted((s or {}).get('ids_produto') or ()), 'sysemp_sku_bruto': (s or {}).get('sku_bruto', ''),
        'ml': ml_linha, 'tags': tags, 'achados': achados, 'n_achados': n_achados,
    }


# Função Objetivo: Uma linha para cada SKU que existe em QUALQUER das 3 fontes (a união), mais uma para cada linha da Sysemp sem SKU.
def _montar_linhas(empresa, arquivo, sysemp, ml, cadastro, colunas, rotulos_da_marca, agora):
    chaves = set(arquivo.por_sku) | set(sysemp.por_chave) | set(ml.por_sku)
    return [_montar_linha(chave, empresa, arquivo, sysemp, ml, cadastro, colunas, rotulos_da_marca, agora) for chave in chaves]


# Função Objetivo: O cadastro (título, marca, foto) do banco SÓ dos SKUs que não estão no arquivo (ex.: produto inativo, ou que só existe no Mercado Livre).
# Uma consulta só. Se o banco falhar, a tela continua: esses SKUs ficam sem identificação.
def _ler_cadastro_fora_do_arquivo(arquivo, sysemp, ml):
    skus = {sku for sku in (*sysemp.por_chave, *ml.por_sku) if sku and not sku.startswith(PREFIXO_SEM_SKU) and sku not in arquivo.por_sku}
    if not skus:
        return {}
    try:
        return _ler_cadastro(skus)
    except Exception:
        traceback.print_exc()
        return {}


# Função Objetivo: Os filtros da empresa: o mesmo que GRUPOS_DE_FILTROS, mas com o texto REAL das 3 contas (ex.: "Full: Sysemp id 4 ≠ ML Full"), e sem as contas
# que a empresa não tem.
def _filtros_da_empresa(colunas):
    contas = {coluna['tag_do_filtro']: coluna for coluna in colunas['todas'] if coluna['tipo'] == colunas_mod.TIPO_DELTA}
    grupos = []
    for rotulo_do_grupo, filtros in GRUPOS_DE_FILTROS:
        mantidos = []
        for chave, rotulo, dica in filtros:
            if chave in CHAVES_DAS_CONTAS:
                coluna = contas.get(chave)
                if coluna is None:
                    continue
                rotulo, dica = coluna['rotulo_do_filtro'], coluna['dica_do_filtro']
            mantidos.append((chave, rotulo, dica))
        if mantidos:
            grupos.append((rotulo_do_grupo, tuple(mantidos)))
    return grupos


# ---------------------------------------------------------------------------
# OS CARTÕES DAS 3 FONTES (o resumo do topo)
# ---------------------------------------------------------------------------
def _item(rotulo, valor, alerta=False):
    return {'rotulo': rotulo, 'valor': valor, 'alerta': alerta}


def _cartao_do_arquivo(arquivo, agora):
    if not arquivo.disponivel:
        return {'estado': 'erro', 'mensagem': arquivo.erro, 'itens': [_item('Caminho', arquivo.caminho)]}
    n_repetidos = sum(1 for dados in arquivo.por_sku.values() if dados['repetido'])
    itens = [
        _item('Arquivo', os.path.basename(arquivo.caminho)),
        _item('Última modificação', _quando(arquivo.modificado_em, agora)),
        _item('SKUs lidos', _txt(len(arquivo.por_sku))),
        _item('Colunas de estoque', ', '.join(coluna.strip() for coluna in arquivo.colunas) or 'nenhuma encontrada', alerta=not arquivo.colunas),
    ]
    if arquivo.n_sem_sku:
        itens.append(_item('Linhas sem SKU', _txt(arquivo.n_sem_sku), alerta=True))
    if n_repetidos:
        itens.append(_item('SKUs repetidos', _txt(n_repetidos), alerta=True))
    if arquivo.n_celulas_invalidas:
        itens.append(_item('Células de estoque não numéricas', _txt(arquivo.n_celulas_invalidas), alerta=True))
    return {'estado': 'ok', 'mensagem': '', 'itens': itens}


def _cartao_da_sysemp(empresa, sysemp, agora):
    nome = NOME_EXIBICAO_POR_EMPRESA.get(empresa, empresa)
    if not sysemp.disponivel:
        return {'estado': 'indisponivel', 'itens': [],
                'mensagem': f'A Sysemp ainda não liberou este método para {nome}. A tela já está pronta: quando liberarem, a coleta passa a funcionar.'}
    if not sysemp.coletada:
        return {'estado': 'vazio', 'itens': [], 'mensagem': 'Ainda não há coleta (o servidor guarda só na memória: reiniciar apaga). Clique em "Coletar do Sysemp".'}
    resultado = ('Completa (a API avisou que não havia mais linhas)' if sysemp.completa else
                 f"INCOMPLETA — {TEXTO_DO_FIM_ANORMAL.get(sysemp.motivo_do_fim, sysemp.motivo_do_fim)}"
                 + (f' ({sysemp.detalhe_do_fim})' if sysemp.detalhe_do_fim else ''))
    ordem_do_mapa = {local.id: posicao for posicao, local in enumerate(mapa.locais_da_empresa(empresa))}
    locais = []
    for id_local, quantidade in sorted(sysemp.locais_vistos.items(), key=lambda par: (ordem_do_mapa.get(par[0], 99), par[0])):
        local = mapa.local_por_id(empresa, id_local)
        locais.append(f"{local.rotulo if local else f'id {id_local} (fora do mapa)'}: {_txt(quantidade)}")
    tamanhos = sysemp.tamanhos_das_paginas
    itens = [
        _item('Coletada em', _quando(sysemp.coletado_em, agora)),
        _item('Linhas / páginas', f"{_txt(sysemp.n_linhas)} linhas em {_txt(sysemp.paginas)} {_plural(sysemp.paginas, 'página', 'páginas')}"
                                  + (f' (de {min(tamanhos)} a {max(tamanhos)} por página)' if tamanhos else '')),
        _item('Resultado', resultado, alerta=not sysemp.completa),
        _item('Linhas por local', '; '.join(locais) or 'nenhuma'),
    ]
    if sysemp.n_linhas_repetidas:
        itens.append(_item('Linhas repetidas', _txt(sysemp.n_linhas_repetidas), alerta=True))
    if sysemp.n_linhas_fora_do_formato:
        itens.append(_item('Linhas fora do formato', _txt(sysemp.n_linhas_fora_do_formato), alerta=True))
    return {'estado': 'ok', 'mensagem': '', 'itens': itens}


def _cartao_do_ml(ml, agora):
    if not ml.n_produtos:
        return {'estado': 'vazio', 'itens': [],
                'mensagem': 'O banco não tem Códigos ML do Full nesta empresa (importe os anúncios do ML e faça a varredura na tela "Estoque no Full").'}
    itens = [
        _item('SKUs com Código ML do Full', _txt(ml.n_produtos)),
        _item('Consulta mais antiga', _quando(ml.mais_antiga, agora) or 'nenhuma'),
        _item('Consulta mais recente', _quando(ml.mais_recente, agora) or 'nenhuma'),
        _item('SKUs sem nenhuma consulta', _txt(ml.n_sem_consulta), alerta=bool(ml.n_sem_consulta)),
        _item('SKUs com número parcial', _txt(ml.n_parciais), alerta=bool(ml.n_parciais)),
    ]
    if ml.n_codigos_sem_sku:
        itens.append(_item('Códigos ML sem SKU no banco', _txt(ml.n_codigos_sem_sku), alerta=True))
    return {'estado': 'ok', 'mensagem': '', 'itens': itens}


# ---------------------------------------------------------------------------
# A TELA (busca, filtros, ordem, paginação — tudo no endereço)
# ---------------------------------------------------------------------------
def _inteiro_positivo(texto, padrao):
    try:
        numero = int(texto)
    except (TypeError, ValueError):
        return padrao
    return numero if numero >= 1 else padrao


# Função Objetivo: As escolhas da pessoa (q, filtro, ordem, por_pagina, p) a partir do endereço; o que for inválido volta ao padrão.
def _ler_estado(parametros, filtros_validos, ordens_validas):
    filtro = parametros.get('filtro', FILTRO_PADRAO)
    ordem = parametros.get('ordem', ORDEM_PADRAO)
    por_pagina = _inteiro_positivo(parametros.get('por_pagina'), POR_PAGINA_PADRAO)
    return {
        'q': (parametros.get('q') or '').strip()[:MAX_TEXTO_BUSCA],
        'filtro': filtro if filtro in filtros_validos else FILTRO_PADRAO,
        'ordem': ordem if ordem in ordens_validas else ORDEM_PADRAO,
        'por_pagina': por_pagina if por_pagina in OPCOES_POR_PAGINA else POR_PAGINA_PADRAO,
        'p': _inteiro_positivo(parametros.get('p'), 1),
    }


# Função Objetivo: O endereço da tela com as escolhas atuais, trocando só o que mudou. Mudar busca, filtro, ordem ou "mostrar" volta à página 1.
def _url(estado, **mudancas):
    novo = {**estado, **mudancas}
    if 'p' not in mudancas and any(chave in mudancas for chave in ('q', 'filtro', 'ordem', 'por_pagina')):
        novo['p'] = 1
    parametros = {chave: valor for chave, valor in novo.items() if valor != PADROES_DA_URL[chave]}
    base = reverse('gestao_full_comparativo_estoque')
    return f'{base}?{urlencode(parametros)}' if parametros else base


# Função Objetivo: O endereço do botão "Exportar Excel": leva a busca, o filtro e a ordem de agora (o Excel sai com a MESMA lista que a pessoa está vendo, só que inteira).
def _url_exportar(estado):
    parametros = {chave: estado[chave] for chave in ('q', 'filtro', 'ordem') if estado[chave] != PADROES_DA_URL[chave]}
    base = reverse('gestao_full_comparativo_exportar')
    return f'{base}?{urlencode(parametros)}' if parametros else base


# Função Objetivo: A data e a hora sem o ano ("02/10 12:14"), para a faixa estreita de cima de uma coluna, quando ela mostra duas datas ("de ... a ...").
def _data_hora_curta(valor):
    return timezone.localtime(valor).strftime('%d/%m %H:%M')


# Função Objetivo: A frase que fica embaixo do nome de cada fonte no cabeçalho da tabela: de quando são os dados dela.
def _subtitulo_da_fonte(fonte, arquivo, sysemp, ml):
    if fonte == colunas_mod.FONTE_ARQUIVO:
        return f'arquivo de {_data_hora_completa(arquivo.modificado_em)}' if arquivo.modificado_em else 'arquivo não lido'
    if fonte == colunas_mod.FONTE_SYSEMP:
        if not sysemp.coletada:
            return 'sem coleta ainda'
        return f'coleta de {_data_hora_completa(sysemp.coletado_em)}' + ('' if sysemp.completa else ' (INCOMPLETA)')
    if not ml.mais_recente:
        return 'sem nenhuma consulta gravada'
    if ml.mais_antiga == ml.mais_recente:
        return f'consulta de {_data_hora_completa(ml.mais_recente)}'
    # Duas datas na faixa estreita da fonte: sem o ano, para caber numa linha só (as datas completas estão no cartão do Mercado Livre, lá em cima).
    return f'consultas de {_data_hora_curta(ml.mais_antiga)} a {_data_hora_curta(ml.mais_recente)}'


# Função Objetivo: Monta tudo que o template precisa. LÊ o arquivo, a coleta guardada no cache e o banco; não chama API nenhuma.
# "todas_as_linhas" (usado pela exportação para Excel): em vez de uma página, devolve a lista INTEIRA (depois da busca, do filtro e da ordem).
def montar_comparativo(parametros, empresa, todas_as_linhas=False):
    agora = timezone.now()
    arquivo, sysemp, ml = ler_arquivo(empresa), organizar_sysemp(empresa), ler_ml(agora)
    colunas = colunas_mod.montar_colunas(empresa, arquivo.colunas)
    grupos_de_filtros_da_empresa = _filtros_da_empresa(colunas)
    rotulos_da_marca = {chave: (rotulo, dica) for _, filtros in grupos_de_filtros_da_empresa for chave, rotulo, dica in filtros}
    cadastro = _ler_cadastro_fora_do_arquivo(arquivo, sysemp, ml)
    linhas = _montar_linhas(empresa, arquivo, sysemp, ml, cadastro, colunas, rotulos_da_marca, agora)
    registro = colunas_mod.registro_de_ordenacao(colunas)
    estado = _ler_estado(parametros, {FILTRO_PADRAO, *rotulos_da_marca}, colunas_mod.ordens_validas(registro))

    # A contagem de cada filtro vale para a lista DEPOIS da busca (a mesma que a pessoa está vendo), mas antes do filtro escolhido.
    texto = _normalizar(estado['q'])
    buscadas = [linha for linha in linhas if texto in linha['busca']] if texto else linhas
    contagens = Counter(tag for linha in buscadas for tag in linha['tags'])
    filtradas = buscadas if estado['filtro'] == FILTRO_PADRAO else [linha for linha in buscadas if estado['filtro'] in linha['tags']]
    ordenadas = colunas_mod.ordenar(filtradas, estado['ordem'])

    paginador = Paginator(ordenadas, (len(ordenadas) or 1) if todas_as_linhas else estado['por_pagina'])
    pagina = paginador.get_page(1 if todas_as_linhas else estado['p'])
    por_pagina_atual = {**estado, 'p': pagina.number}

    # Cada título de coluna sabe para onde o próximo clique leva (ver comparativo_estoque_colunas.ordenacao_das_colunas).
    ordenacao = colunas_mod.ordenacao_das_colunas(registro, estado['ordem'], lambda ordem: _url(por_pagina_atual, ordem=ordem))
    for coluna in colunas['todas']:
        coluna['ordenacao'] = ordenacao[coluna['chave']]
    for grupo in colunas['fontes']:
        grupo['subtitulo'] = _subtitulo_da_fonte(grupo['chave'], arquivo, sysemp, ml)

    grupos_filtros = [{'rotulo': '', 'filtros': [{'chave': FILTRO_PADRAO, 'rotulo': 'Todos', 'dica': 'Todos os SKUs de qualquer fonte.',
                                                  'contagem': len(buscadas), 'ativo': estado['filtro'] == FILTRO_PADRAO,
                                                  'url': _url(por_pagina_atual, filtro=FILTRO_PADRAO)}]}]
    for rotulo_do_grupo, filtros in grupos_de_filtros_da_empresa:
        grupos_filtros.append({'rotulo': rotulo_do_grupo, 'filtros': [
            {'chave': chave, 'rotulo': rotulo, 'dica': dica, 'contagem': contagens.get(chave, 0), 'ativo': estado['filtro'] == chave,
             'url': _url(por_pagina_atual, filtro=chave)} for chave, rotulo, dica in filtros]})

    return {
        'empresa_nome': NOME_EXIBICAO_POR_EMPRESA.get(empresa, empresa),
        'api_disponivel': sysemp.disponivel,
        'sysemp_coletada': sysemp.coletada,
        'colunas': colunas,
        'ordenacao': ordenacao,
        # 1 (seta) + 4 (foto, SKU, título, marca) + as colunas de fontes e de contas + 1 (achados): é o colspan da parte que abre.
        'n_colunas_total': 1 + 4 + colunas['n_fontes'] + colunas['n_contas'] + 1,
        'fontes': {'arquivo': _cartao_do_arquivo(arquivo, agora), 'sysemp': _cartao_da_sysemp(empresa, sysemp, agora), 'ml': _cartao_do_ml(ml, agora)},
        'texto': estado['q'], 'filtro': estado['filtro'], 'filtro_padrao': FILTRO_PADRAO,
        'ordem': estado['ordem'], 'ordem_padrao': ORDEM_PADRAO, 'por_pagina': estado['por_pagina'], 'por_pagina_padrao': POR_PAGINA_PADRAO,
        'tem_ajustes': any(estado[chave] != PADROES_DA_URL[chave] for chave in ('q', 'filtro', 'ordem', 'por_pagina')),
        'url_limpar': _url(PADROES_DA_URL),
        'url_exportar': _url_exportar(estado),
        'grupos_filtros': grupos_filtros,
        'opcoes_por_pagina': [{'rotulo': str(opcao), 'ativo': estado['por_pagina'] == opcao, 'url': _url(por_pagina_atual, por_pagina=opcao)}
                              for opcao in OPCOES_POR_PAGINA],
        'linhas': list(pagina.object_list),
        'paginacao': {
            'total': paginador.count, 'numero': pagina.number, 'total_paginas': paginador.num_pages,
            'primeiro': pagina.start_index(), 'ultimo': pagina.end_index(),
            'url_anterior': _url(por_pagina_atual, p=pagina.number - 1) if pagina.has_previous() else '',
            'url_proxima': _url(por_pagina_atual, p=pagina.number + 1) if pagina.has_next() else '',
        },
    }
