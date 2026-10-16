# arquivos_referencia/funcoes_auxiliares/tabela_do_visualizador.py

# Função Objetivo: Desenha UMA aba do .xlsx como uma tabela HTML parecida com a do Excel (letras de coluna, números de linha, larguras e
# alturas do arquivo, células mescladas, cores de fundo e de letra, negrito, bordas, alinhamento, linhas e colunas congeladas), para o
# "Ver arquivo" da tela "Arquivos de referência". Só LÊ o que o openpyxl já abriu; nada é gravado nem consultado em banco.
#
# * [DECISÃO, 16/10/2026] → Visualizador (Matheus): "ver o arquivo literalmente como se estivesse abrindo o xlsx". Duas visões da MESMA tabela:
#   "Como no Excel" (formato de número, % , R$, datas) e "Valor bruto" (o que está guardado, mais as fórmulas). A troca é só CSS: cada
#   célula que muda entre as duas visões leva os dois textos (<span class="vx"> e <span class="vb">).
# * [IMPORTANTE] → SEGURANÇA: o arquivo vem da mão de uma pessoa. TUDO que vira texto na tela passa por escape (django.utils.html.escape);
#   cores, larguras e alturas só entram na página depois de validadas (6 dígitos hexadecimais, números, listas fechadas de valores).
#   Nada do arquivo vira atributo, classe ou CSS sem passar por esses filtros — nem nome de aba, nem fórmula, nem o texto da célula.
# * [EXPLICAÇÃO] → Limites (um .xlsx pode ser enorme): no máximo LIMITE_DE_LINHAS_MOSTRADAS linhas e LIMITE_DE_COLUNAS_MOSTRADAS colunas por
#   aba e LIMITE_DE_CELULAS_NO_ARQUIVO células no arquivo todo. O que passar disso não é desenhado, e a tela avisa quantas linhas faltaram
#   (o arquivo inteiro continua no Drive). Só a área realmente usada é desenhada: linhas e colunas vazias no fim não entram.
# * [EXPLICAÇÃO] → Fórmula cujo resultado não foi salvo no arquivo (arquivo gerado por programa e nunca aberto no Excel): o Excel recalcula ao
#   abrir, mas o sistema lê como célula VAZIA. A célula aparece marcada (canto vermelho) e a barra de fórmulas mostra a fórmula.

import colorsys
import re

from django.utils.html import escape
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

from .formato_de_celula import limpar_texto, texto_bruto, texto_do_excel

LIMITE_DE_LINHAS_MOSTRADAS = 2000
LIMITE_DE_COLUNAS_MOSTRADAS = 60
LIMITE_DE_CELULAS_NO_ARQUIVO = 90000
LIMITE_DA_VARREDURA_DE_LINHAS = 5000
LIMITE_DA_VARREDURA_DE_COLUNAS = 100
MAXIMO_DE_LINHAS_CONGELADAS = 6
MAXIMO_DE_COLUNAS_CONGELADAS = 4
TAMANHO_MAXIMO_DA_FORMULA = 2000

ALTURA_PADRAO_DA_LINHA_EM_PX = 20
LARGURA_PADRAO_DA_COLUNA_EM_CARACTERES = 8.43
ALTURA_DO_CABECALHO_EM_PX = 24
LARGURA_DO_NUMERO_DA_LINHA_EM_PX = 48
LARGURA_MINIMA_DA_COLUNA_EM_PX = 12
LARGURA_MAXIMA_DA_COLUNA_EM_PX = 600
ALTURA_MAXIMA_DA_LINHA_EM_PX = 400
TAMANHO_BASE_DA_LETRA_EM_PT = 11
TAMANHO_BASE_DA_LETRA_EM_PX = 13

TEMA_PADRAO = [
    'FFFFFF', '000000', 'E7E6E6', '44546A', '4472C4', 'ED7D31', 'A5A5A5', 'FFC000', '5B9BD5', '70AD47', '0563C1', '954F72',
]
NOMES_DO_TEMA = ['lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink']

_HEX6 = re.compile(r'^[0-9A-Fa-f]{6}$')
_HEX8 = re.compile(r'^[0-9A-Fa-f]{8}$')

ESTILOS_DE_BORDA = {
    'thin': '1px solid', 'hair': '1px solid', 'medium': '2px solid', 'thick': '3px solid', 'dashed': '1px dashed', 'dotted': '1px dotted',
    'double': '3px double', 'mediumDashed': '2px dashed', 'dashDot': '1px dashed', 'dashDotDot': '1px dashed',
    'mediumDashDot': '2px dashed', 'mediumDashDotDot': '2px dashed', 'slantDashDot': '2px dashed',
}
ALINHAMENTO_HORIZONTAL = {'left': 'left', 'center': 'center', 'right': 'right', 'justify': 'justify', 'centerContinuous': 'center'}
ALINHAMENTO_VERTICAL = {'top': 'top', 'center': 'middle', 'bottom': 'bottom', 'justify': 'top', 'distributed': 'middle'}


# Função Objetivo: As cores do tema do arquivo (Office), na ordem que o Excel numera (0 = fundo claro, 1 = texto escuro, 2..: destaques).
# Lê o XML do tema por expressão regular (sem interpretar XML do arquivo da pessoa); falhou, usa o tema padrão do Office.
def ler_cores_do_tema(xml_do_tema):
    cores = list(TEMA_PADRAO)
    if not xml_do_tema:
        return cores
    try:
        texto = xml_do_tema.decode('utf-8', errors='ignore') if isinstance(xml_do_tema, bytes) else str(xml_do_tema)
        esquema = re.search(r'<a:clrScheme\b.*?</a:clrScheme>', texto, re.DOTALL)
        if not esquema:
            return cores
        for posicao, nome in enumerate(NOMES_DO_TEMA):
            achou = re.search(
                rf'<a:{nome}>\s*<a:(?:srgbClr\s+val="([0-9A-Fa-f]{{6}})"|sysClr\b[^>]*?lastClr="([0-9A-Fa-f]{{6}})")',
                esquema.group(0),
            )
            if achou:
                cores[posicao] = (achou.group(1) or achou.group(2)).upper()
    except Exception:
        return list(TEMA_PADRAO)
    return cores


def _aplicar_tom(hex6, tom):
    try:
        tom = float(tom)
    except (TypeError, ValueError):
        return hex6
    if not tom:
        return hex6
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, luz, s = colorsys.rgb_to_hls(r, g, b)
    luz = luz * (1 + tom) if tom < 0 else luz * (1 - tom) + tom
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, luz)), s)
    return f'{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}'


# Função Objetivo: Uma cor do openpyxl (rgb, tema ou índice) vira "#RRGGBB" validado — ou None quando não dá para saber.
def cor_em_css(cor, cores_do_tema):
    if cor is None:
        return None
    try:
        tipo = cor.type
        if tipo == 'rgb':
            valor = cor.rgb
            if not isinstance(valor, str):
                return None
            if _HEX8.match(valor):
                valor = valor[2:]
            if not _HEX6.match(valor):
                return None
            return '#' + valor.upper()
        if tipo == 'theme':
            indice = int(cor.theme)
            if not 0 <= indice < len(cores_do_tema):
                return None
            return '#' + _aplicar_tom(cores_do_tema[indice], cor.tint)
        if tipo == 'indexed':
            indice = int(cor.indexed)
            if not 0 <= indice < len(COLOR_INDEX):
                return None
            valor = COLOR_INDEX[indice]
            if isinstance(valor, str) and _HEX8.match(valor):
                return '#' + valor[2:].upper()
    except Exception:
        return None
    return None


class Estilos:
    """Guarda as regras de CSS das células (uma classe por combinação diferente de fundo, letra, borda e alinhamento)."""

    def __init__(self):
        self._classes = {}

    def classe(self, declaracoes):
        if not declaracoes:
            return ''
        chave = ';'.join(declaracoes)
        if chave not in self._classes:
            self._classes[chave] = f'arqz{len(self._classes) + 1}'
        return self._classes[chave]

    def css(self):
        return '\n'.join(f'.arq-viz td.{nome}{{{chave}}}' for chave, nome in self._classes.items())


def _tamanho_da_letra(pontos):
    try:
        pontos = float(pontos)
    except (TypeError, ValueError):
        return None
    if not 4 <= pontos <= 72 or abs(pontos - TAMANHO_BASE_DA_LETRA_EM_PT) < 0.1:
        return None
    return round(pontos * TAMANHO_BASE_DA_LETRA_EM_PX / TAMANHO_BASE_DA_LETRA_EM_PT)


def _borda_em_css(lado, cores_do_tema):
    if lado is None or not getattr(lado, 'style', None):
        return None
    estilo = ESTILOS_DE_BORDA.get(lado.style, '1px solid')
    return f'{estilo} {cor_em_css(lado.color, cores_do_tema) or "#000000"}'


# Função Objetivo: As declarações de CSS de 1 célula (só o que difere do padrão da tabela). Lista fechada de propriedades e valores validados.
def declaracoes_da_celula(celula, cores_do_tema):
    declaracoes = []
    try:
        preenchimento = celula.fill
        if preenchimento is not None and preenchimento.fill_type == 'solid':
            fundo = cor_em_css(preenchimento.fgColor, cores_do_tema)
            if fundo:
                declaracoes.append(f'background:{fundo}')
                declaracoes.append('box-shadow:none')
    except Exception:
        pass
    try:
        fonte = celula.font
        if fonte is not None:
            cor = cor_em_css(fonte.color, cores_do_tema)
            if cor and cor != '#000000':
                declaracoes.append(f'color:{cor}')
            if fonte.b:
                declaracoes.append('font-weight:700')
            if fonte.i:
                declaracoes.append('font-style:italic')
            decoracao = []
            if fonte.u and fonte.u != 'none':
                decoracao.append('underline')
            if fonte.strike:
                decoracao.append('line-through')
            if decoracao:
                declaracoes.append('text-decoration:' + ' '.join(decoracao))
            tamanho = _tamanho_da_letra(fonte.sz)
            if tamanho:
                declaracoes.append(f'font-size:{tamanho}px')
    except Exception:
        pass
    try:
        alinhamento = celula.alignment
        if alinhamento is not None:
            horizontal = ALINHAMENTO_HORIZONTAL.get(alinhamento.horizontal)
            if horizontal:
                declaracoes.append(f'text-align:{horizontal}')
            vertical = ALINHAMENTO_VERTICAL.get(alinhamento.vertical)
            if vertical and vertical != 'bottom':
                declaracoes.append(f'vertical-align:{vertical}')
            if alinhamento.wrap_text:
                declaracoes.append('white-space:pre-wrap')
                declaracoes.append('overflow-wrap:anywhere')
            recuo = int(alinhamento.indent or 0)
            if 0 < recuo <= 15:
                declaracoes.append(f'padding-left:{4 + recuo * 9}px')
    except Exception:
        pass
    try:
        borda = celula.border
        if borda is not None:
            for nome_css, lado in (('top', borda.top), ('right', borda.right), ('bottom', borda.bottom), ('left', borda.left)):
                valor = _borda_em_css(lado, cores_do_tema)
                if valor:
                    declaracoes.append(f'border-{nome_css}:{valor}')
    except Exception:
        pass
    return tuple(declaracoes)


def _tem_marca_visual(celula):
    # Célula sem valor mas com fundo ou borda: aparece no Excel, então entra na área usada.
    try:
        if celula.fill is not None and celula.fill.fill_type == 'solid':
            return True
        borda = celula.border
        return any(lado is not None and getattr(lado, 'style', None) for lado in (borda.top, borda.right, borda.bottom, borda.left))
    except Exception:
        return False


def _texto_da_formula(valor):
    if isinstance(valor, str):
        return valor if valor.startswith('=') else None
    texto = getattr(valor, 'text', None)   # fórmula de matriz / tabela de dados do openpyxl
    if isinstance(texto, str) and texto:
        return texto if texto.startswith('=') else '=' + texto
    return None


def _largura_em_px(caracteres):
    try:
        px = int(float(caracteres) * 7 + 5)
    except (TypeError, ValueError):
        px = int(LARGURA_PADRAO_DA_COLUNA_EM_CARACTERES * 7 + 5)
    return max(LARGURA_MINIMA_DA_COLUNA_EM_PX, min(LARGURA_MAXIMA_DA_COLUNA_EM_PX, px))


def _altura_em_px(pontos):
    try:
        px = round(float(pontos) * 96 / 72)
    except (TypeError, ValueError):
        return ALTURA_PADRAO_DA_LINHA_EM_PX
    return max(4, min(ALTURA_MAXIMA_DA_LINHA_EM_PX, px))


def _area_usada(aba):
    """Última linha e última coluna que têm valor (ou fundo/borda), dentro dos limites da varredura, e quanto o arquivo tem de verdade."""
    ultima_linha = ultima_coluna = 0
    limite_l = min(aba.max_row or 0, LIMITE_DA_VARREDURA_DE_LINHAS)
    limite_c = min(aba.max_column or 0, LIMITE_DA_VARREDURA_DE_COLUNAS)
    if limite_l and limite_c:
        for numero, linha in enumerate(aba.iter_rows(min_row=1, max_row=limite_l, max_col=limite_c), start=1):
            for celula in linha:
                if celula.value is not None or (celula.has_style and _tem_marca_visual(celula)):
                    ultima_linha = numero
                    if celula.column > ultima_coluna:
                        ultima_coluna = celula.column
    for faixa in aba.merged_cells.ranges:
        ultima_linha = max(ultima_linha, min(faixa.max_row, LIMITE_DA_VARREDURA_DE_LINHAS))
        ultima_coluna = max(ultima_coluna, min(faixa.max_col, LIMITE_DA_VARREDURA_DE_COLUNAS))
    return ultima_linha, ultima_coluna


def _congelamento(aba):
    linhas = colunas = 0
    try:
        topo = aba.freeze_panes
        if topo:
            letra, linha = coordinate_from_string(topo)
            linhas = max(0, linha - 1)
            colunas = max(0, column_index_from_string(letra) - 1)
    except Exception:
        return 0, 0
    return min(linhas, MAXIMO_DE_LINHAS_CONGELADAS), min(colunas, MAXIMO_DE_COLUNAS_CONGELADAS)


def _larguras_das_colunas(aba, ultima_coluna):
    padrao = LARGURA_PADRAO_DA_COLUNA_EM_CARACTERES
    try:
        if aba.sheet_format.defaultColWidth:
            padrao = aba.sheet_format.defaultColWidth
    except Exception:
        pass
    larguras = {c: _largura_em_px(padrao) for c in range(1, ultima_coluna + 1)}
    ocultas = set()
    for dimensao in aba.column_dimensions.values():
        try:
            minimo, maximo = int(dimensao.min), int(dimensao.max)
        except (TypeError, ValueError):
            continue
        for coluna in range(max(1, minimo), min(maximo, ultima_coluna) + 1):
            if dimensao.hidden:
                ocultas.add(coluna)
            if dimensao.width:
                larguras[coluna] = _largura_em_px(dimensao.width)
    return larguras, ocultas


# Função Objetivo: Desenha 1 aba. `aba_valores` = aba aberta com os resultados (data_only=True); `aba_formulas` = a mesma aba aberta com as
# fórmulas (ou None se o arquivo não tem fórmula). `estilos` (Estilos) e `cores_do_tema` valem para o arquivo todo.
# Devolve {'html', 'linhas', 'colunas', 'linhas_no_arquivo', 'cortada', 'formulas_sem_resultado', 'celulas'}.
def montar_aba(aba_valores, aba_formulas, estilos, cores_do_tema, celulas_disponiveis):
    ultima_linha, ultima_coluna = _area_usada(aba_valores)
    if aba_formulas is not None:
        # Fórmula SEM resultado salvo (arquivo gerado por programa) parece célula vazia na aba de resultados: a área usada também olha a aba de fórmulas.
        formulas_linha, formulas_coluna = _area_usada(aba_formulas)
        ultima_linha, ultima_coluna = max(ultima_linha, formulas_linha), max(ultima_coluna, formulas_coluna)
    linhas_no_arquivo = ultima_linha
    cortada = False
    ultima_linha_mostrada = min(ultima_linha, LIMITE_DE_LINHAS_MOSTRADAS)
    ultima_coluna_mostrada = min(ultima_coluna, LIMITE_DE_COLUNAS_MOSTRADAS)
    if ultima_coluna_mostrada:
        cabem = max(0, celulas_disponiveis) // ultima_coluna_mostrada
        ultima_linha_mostrada = min(ultima_linha_mostrada, cabem)
    cortada = ultima_linha_mostrada < ultima_linha or ultima_coluna_mostrada < ultima_coluna

    if ultima_linha_mostrada == 0 or ultima_coluna_mostrada == 0:
        return {
            'html': '', 'linhas': 0, 'colunas': 0, 'linhas_no_arquivo': linhas_no_arquivo, 'cortada': cortada,
            'formulas_sem_resultado': 0, 'celulas': 0, 'vazia': linhas_no_arquivo == 0,
        }

    larguras, colunas_ocultas = _larguras_das_colunas(aba_valores, ultima_coluna_mostrada)
    colunas_visiveis = [c for c in range(1, ultima_coluna_mostrada + 1) if c not in colunas_ocultas]
    linhas_ocultas, alturas = set(), {}
    altura_padrao = ALTURA_PADRAO_DA_LINHA_EM_PX
    try:
        if aba_valores.sheet_format.defaultRowHeight:
            altura_padrao = _altura_em_px(aba_valores.sheet_format.defaultRowHeight)
    except Exception:
        pass
    for numero in range(1, ultima_linha_mostrada + 1):
        dimensao = aba_valores.row_dimensions.get(numero)
        if dimensao is not None:
            if dimensao.hidden:
                linhas_ocultas.add(numero)
            if dimensao.height:
                alturas[numero] = _altura_em_px(dimensao.height)
    linhas_visiveis = [n for n in range(1, ultima_linha_mostrada + 1) if n not in linhas_ocultas]

    linhas_congeladas, colunas_congeladas = _congelamento(aba_valores)
    deslocamento_do_topo, acumulado = {}, ALTURA_DO_CABECALHO_EM_PX
    for numero in linhas_visiveis:
        if numero > linhas_congeladas:
            break
        deslocamento_do_topo[numero] = acumulado
        acumulado += alturas.get(numero, altura_padrao)
    deslocamento_da_esquerda, acumulado = {}, LARGURA_DO_NUMERO_DA_LINHA_EM_PX
    for coluna in colunas_visiveis:
        if coluna > colunas_congeladas:
            break
        deslocamento_da_esquerda[coluna] = acumulado
        acumulado += larguras[coluna]

    # Mesclagens: a célula de cima à esquerda leva rowspan/colspan (só do que está visível); as outras do bloco não são desenhadas.
    ancoras, cobertas = {}, set()
    visiveis_l, visiveis_c = set(linhas_visiveis), set(colunas_visiveis)
    for faixa in aba_valores.merged_cells.ranges:
        if faixa.min_row > ultima_linha_mostrada or faixa.min_col > ultima_coluna_mostrada:
            continue
        linhas_da_faixa = [n for n in range(faixa.min_row, min(faixa.max_row, ultima_linha_mostrada) + 1) if n in visiveis_l]
        colunas_da_faixa = [c for c in range(faixa.min_col, min(faixa.max_col, ultima_coluna_mostrada) + 1) if c in visiveis_c]
        if not linhas_da_faixa or not colunas_da_faixa:
            continue
        primeira_l, primeira_c = linhas_da_faixa[0], colunas_da_faixa[0]
        ancoras[(primeira_l, primeira_c)] = (len(linhas_da_faixa), len(colunas_da_faixa), faixa.min_row, faixa.min_col)
        for n in linhas_da_faixa:
            for c in colunas_da_faixa:
                if (n, c) != (primeira_l, primeira_c):
                    cobertas.add((n, c))

    cache_de_estilo = {}
    formulas_sem_resultado = 0
    sem_grade = False
    try:
        sem_grade = aba_valores.sheet_view.showGridLines is False
    except Exception:
        pass

    # As células da área desenhada, linha a linha (o openpyxl cria as que faltam, vazias).
    cortar = dict(min_row=1, max_row=ultima_linha_mostrada, max_col=ultima_coluna_mostrada)
    linhas_de_valores = dict(enumerate(aba_valores.iter_rows(**cortar), start=1))
    linhas_de_formulas = dict(enumerate(aba_formulas.iter_rows(**cortar), start=1)) if aba_formulas is not None else None

    largura_total = LARGURA_DO_NUMERO_DA_LINHA_EM_PX + sum(larguras[c] for c in colunas_visiveis)
    saida = [
        f'<table class="arq-viz__tabela{" arq-viz__tabela--sem-grade" if sem_grade else ""}" style="width:{largura_total}px">',
        '<colgroup><col style="width:%dpx">%s</colgroup>' % (
            LARGURA_DO_NUMERO_DA_LINHA_EM_PX, ''.join(f'<col style="width:{larguras[c]}px">' for c in colunas_visiveis),
        ),
        '<thead><tr><th class="arq-viz__canto"></th>',
    ]
    for coluna in colunas_visiveis:
        estilo = f' style="left:{deslocamento_da_esquerda[coluna]}px"' if coluna in deslocamento_da_esquerda else ''
        classe = ' class="arq-viz__cn arq-viz__cf"' if coluna in deslocamento_da_esquerda else ' class="arq-viz__cn"'
        saida.append(f'<th{classe}{estilo}>{get_column_letter(coluna)}</th>')
    saida.append('</tr></thead><tbody>')

    for numero in linhas_visiveis:
        altura = alturas.get(numero)
        estilo_da_linha = f' style="height:{altura}px"' if altura else ''
        topo = deslocamento_do_topo.get(numero)
        cabeca = f' style="top:{topo}px"' if topo is not None else ''
        classe_da_cabeca = 'arq-viz__ln arq-viz__lf' if topo is not None else 'arq-viz__ln'
        saida.append(f'<tr data-r="{numero}"{estilo_da_linha}><th class="{classe_da_cabeca}"{cabeca}>{numero}</th>')
        linha_de_valores = linhas_de_valores[numero]
        linha_de_formulas = linhas_de_formulas[numero] if linhas_de_formulas is not None else None
        for coluna in colunas_visiveis:
            if (numero, coluna) in cobertas:
                continue
            if coluna - 1 < len(linha_de_valores):
                celula = linha_de_valores[coluna - 1]
            else:
                celula = None
            if celula is None:
                saida.append(f'<td data-c="{get_column_letter(coluna)}"></td>')
                continue

            valor = celula.value
            formula = None
            if linha_de_formulas is not None and coluna - 1 < len(linha_de_formulas):
                formula = _texto_da_formula(linha_de_formulas[coluna - 1].value)
            texto_excel, tipo = texto_do_excel(valor, celula.number_format, celula.data_type)
            texto_cru = limpar_texto(formula) if formula else texto_bruto(valor)
            sem_resultado = formula is not None and valor is None
            if sem_resultado:
                formulas_sem_resultado += 1

            chave_de_estilo = (celula._style.fontId, celula._style.fillId, celula._style.borderId, celula._style.alignmentId)
            if chave_de_estilo not in cache_de_estilo:
                cache_de_estilo[chave_de_estilo] = estilos.classe(declaracoes_da_celula(celula, cores_do_tema))
            classes = []
            if tipo == 'numero':
                classes.append('n')
            elif tipo == 'centro':
                classes.append('c')
            if cache_de_estilo[chave_de_estilo]:
                classes.append(cache_de_estilo[chave_de_estilo])
            if sem_resultado:
                classes.append('sr')
            topo_da_celula = deslocamento_do_topo.get(numero)
            esquerda_da_celula = deslocamento_da_esquerda.get(coluna)
            posicao = []
            if topo_da_celula is not None:
                classes.append('arq-viz__tf')
                posicao.append(f'top:{topo_da_celula}px')
            if esquerda_da_celula is not None:
                classes.append('arq-viz__ce')
                posicao.append(f'left:{esquerda_da_celula}px')

            atributos = [f'data-c="{get_column_letter(coluna)}"']
            if (numero, coluna) in ancoras:
                linhas_juntas, colunas_juntas, origem_l, origem_c = ancoras[(numero, coluna)]
                if linhas_juntas > 1:
                    atributos.append(f'rowspan="{linhas_juntas}"')
                if colunas_juntas > 1:
                    atributos.append(f'colspan="{colunas_juntas}"')
                if (origem_l, origem_c) != (numero, coluna):
                    atributos.append(f'data-o="{get_column_letter(origem_c)}{origem_l}"')
            if classes:
                atributos.append(f'class="{" ".join(classes)}"')
            if posicao:
                atributos.append(f'style="{";".join(posicao)}"')
            if formula:
                atributos.append(f'data-f="{escape(formula[:TAMANHO_MAXIMO_DA_FORMULA])}"')

            if texto_excel == texto_cru:
                conteudo = escape(texto_excel)
            else:
                conteudo = f'<span class="vx">{escape(texto_excel)}</span><span class="vb">{escape(texto_cru)}</span>'
            saida.append(f'<td {" ".join(atributos)}>{conteudo}</td>')
        saida.append('</tr>')
    saida.append('</tbody></table>')

    return {
        'html': ''.join(saida), 'linhas': len(linhas_visiveis), 'colunas': len(colunas_visiveis),
        'linhas_no_arquivo': linhas_no_arquivo, 'cortada': cortada, 'formulas_sem_resultado': formulas_sem_resultado,
        'celulas': len(linhas_visiveis) * len(colunas_visiveis), 'vazia': False,
    }

