# arquivos_referencia/funcoes_auxiliares/formato_de_celula.py

# Função Objetivo: Escreve o valor de uma célula do .xlsx COMO O EXCEL MOSTRARIA (formato de número, porcentagem, moeda, data, "0,000 kg"...)
# e também como valor BRUTO (o que está guardado no arquivo, sem formatação). Usado só pelo "Ver arquivo" (visualizador da tela
# "Arquivos de referência"). Nada aqui grava em lugar nenhum nem lê o banco: recebe valor e formato, devolve texto.
#
# * [DECISÃO, 16/10/2026] → O visualizador mostra o arquivo "literalmente como se a pessoa abrisse o .xlsx" (Matheus). Por isso o texto
#   segue o Excel em português do Brasil: vírgula nos decimais, ponto nos milhares, VERDADEIRO/FALSO, meses e dias em português.
# * [EXPLICAÇÃO] → O código de formato do Excel (o "Formato de Número" da célula) tem até 4 seções separadas por ";": positivo; negativo;
#   zero; texto. Dentro de cada seção: 0 e # e ? são os dígitos, "," marca milhar, "." marca decimal, "%" multiplica por 100, o que está
#   entre aspas ou depois de "\" é texto literal. Exemplos reais dos arquivos de frete: `\R\$\ #,##0.00`, `0.000" kg"`, `0.00%`,
#   `"R$ "#,##0.0000`.
# * [IMPORTANTE] → Formato que este módulo não sabe desenhar (fração, científico, condição como [>100], tempo decorrido [h]) NUNCA quebra
#   a tela: cai no formato "Geral" (o número como ele é). O valor bruto continua disponível ao lado, então nada se perde.
# * [EXPLICAÇÃO] → Arredondamento igual ao do Excel: meio sobe (0,125 com 2 casas vira 0,13), contado sobre os 15 dígitos que o Excel guarda.

import datetime
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from openpyxl.styles.numbers import is_date_format

MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
DIAS_DA_SEMANA = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']

# Tamanho máximo do texto de 1 célula na tela (o valor inteiro continua na barra de fórmulas, que é recortada pelo servidor também).
TAMANHO_MAXIMO_DO_TEXTO = 2000

_CONTROLES = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_COR_OU_CONDICAO = re.compile(r'\[(?:red|black|blue|green|cyan|magenta|white|yellow|color\s*\d+)\]', re.IGNORECASE)
_LOCALE = re.compile(r'\[\$([^\]-]*)(?:-[^\]]*)?\]')
_CONDICAO = re.compile(r'\[\s*[<>=]')
_TEMPO_DECORRIDO = re.compile(r'\[(?:h+|m+|s+)\]', re.IGNORECASE)


class _FormatoNaoSuportado(Exception):
    pass


# Função Objetivo: Limpa o texto para a tela (sem caracteres de controle) e corta o que for exagerado.
def limpar_texto(texto):
    texto = _CONTROLES.sub('', str(texto))
    if len(texto) > TAMANHO_MAXIMO_DO_TEXTO:
        texto = texto[:TAMANHO_MAXIMO_DO_TEXTO] + '…'
    return texto


def _virgula(numero_em_texto):
    return numero_em_texto.replace('.', ',')


# Função Objetivo: O formato "Geral" do Excel: inteiro como é; decimal com até 11 dígitos significativos, sem zeros sobrando.
def numero_geral(valor):
    if isinstance(valor, bool):
        return 'VERDADEIRO' if valor else 'FALSO'
    if isinstance(valor, int):
        return str(valor)
    valor = float(valor)
    if valor != valor or valor in (float('inf'), float('-inf')):
        return '#NÚM!'
    if valor == int(valor) and abs(valor) < 1e11:
        return str(int(valor))
    texto = f'{valor:.11g}'
    if 'e' in texto:
        mantissa, expoente = texto.split('e')
        sinal = '-' if expoente.startswith('-') else '+'
        return f'{_virgula(mantissa)}E{sinal}{expoente.lstrip("+-").lstrip("0").rjust(2, "0")}'
    return _virgula(texto)


# Função Objetivo: O valor bruto, do jeito que a barra de fórmulas do Excel mostra (15 dígitos, vírgula decimal).
def texto_bruto(valor):
    if valor is None:
        return ''
    if isinstance(valor, bool):
        return 'VERDADEIRO' if valor else 'FALSO'
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        if valor != valor or valor in (float('inf'), float('-inf')):
            return '#NÚM!'
        if valor == int(valor) and abs(valor) < 1e15:
            return str(int(valor))
        return _virgula(f'{valor:.15g}')
    if isinstance(valor, Decimal):
        return _virgula(format(valor.normalize(), 'f'))
    if isinstance(valor, datetime.datetime):
        return valor.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(valor, datetime.date):
        return valor.strftime('%Y-%m-%d')
    if isinstance(valor, datetime.time):
        return valor.strftime('%H:%M:%S')
    if isinstance(valor, datetime.timedelta):
        return _duracao(valor)
    return limpar_texto(valor)


def _duracao(valor):
    segundos = int(valor.total_seconds())
    sinal = '-' if segundos < 0 else ''
    segundos = abs(segundos)
    return f'{sinal}{segundos // 3600}:{(segundos % 3600) // 60:02d}:{segundos % 60:02d}'


# ---------------------------------------------------------------- seções e partes do formato

# Função Objetivo: Separa o código de formato nas seções (";") sem cortar o que está entre aspas ou depois de "\".
def _secoes(formato):
    secoes, atual, aspas, escapado = [], [], False, False
    for letra in formato:
        if escapado:
            atual.append(letra)
            escapado = False
        elif letra == '\\':
            atual.append(letra)
            escapado = True
        elif letra == '"':
            atual.append(letra)
            aspas = not aspas
        elif letra == ';' and not aspas:
            secoes.append(''.join(atual))
            atual = []
        else:
            atual.append(letra)
    secoes.append(''.join(atual))
    return secoes


def _tirar_enfeites(secao):
    # Cor ([Red]) não muda o texto; [$R$-416] vira "R$"; condição e tempo decorrido não são suportados.
    if _CONDICAO.search(secao) or _TEMPO_DECORRIDO.search(secao):
        raise _FormatoNaoSuportado()
    secao = _COR_OU_CONDICAO.sub('', secao)
    return _LOCALE.sub(lambda m: '"' + m.group(1) + '"' if m.group(1) else '', secao)


# Função Objetivo: Quebra uma seção em partes: ('lit', texto) · ('dig', '0|#|?') · ('ponto',) · ('virgula',) · ('pct',) · ('arroba',).
def _partes(secao):
    partes, i = [], 0
    while i < len(secao):
        letra = secao[i]
        if letra == '"':
            fim = secao.find('"', i + 1)
            fim = len(secao) if fim == -1 else fim
            partes.append(('lit', secao[i + 1:fim]))
            i = fim + 1
            continue
        if letra == '\\' and i + 1 < len(secao):
            partes.append(('lit', secao[i + 1]))
            i += 2
            continue
        if letra == '_' and i + 1 < len(secao):
            partes.append(('lit', ' '))
            i += 2
            continue
        if letra == '*' and i + 1 < len(secao):
            i += 2
            continue
        if letra in '0#?':
            partes.append(('dig', letra))
        elif letra == '.':
            partes.append(('ponto',))
        elif letra == ',':
            partes.append(('virgula',))
        elif letra == '%':
            partes.append(('pct',))
        elif letra == '@':
            partes.append(('arroba',))
        elif letra in 'EeGg/' or letra == '[' or letra == ']':
            # Científico, "Geral" no meio do formato, fração, colchete que sobrou: não desenhamos.
            if letra in 'Gg' and secao[i:i + 7].lower() == 'general':
                partes.append(('geral',))
                i += 7
                continue
            raise _FormatoNaoSuportado()
        else:
            partes.append(('lit', letra))
        i += 1
    return partes


def _arredondar(valor, casas):
    try:
        decimal = Decimal(repr(float(valor))) if not isinstance(valor, Decimal) else valor
        # O Excel guarda 15 dígitos significativos: 0,1+0,2 vira 0,3 (e não 0,30000000000000004) antes de arredondar.
        decimal = Decimal(f'{decimal:.15g}')
        return decimal.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise _FormatoNaoSuportado()


# Função Objetivo: Escreve um número com UMA seção do formato (sem se preocupar com o sinal: quem chama decide).
def _formatar_numero_na_secao(valor_absoluto, secao):
    partes = _partes(_tirar_enfeites(secao))
    if any(p[0] == 'geral' for p in partes):
        return ''.join(numero_geral(valor_absoluto) if p[0] == 'geral' else (p[1] if p[0] == 'lit' else '') for p in partes)

    posicao_do_ponto = next((n for n, p in enumerate(partes) if p[0] == 'ponto'), None)
    indices_dos_digitos = [n for n, p in enumerate(partes) if p[0] == 'dig']
    if not indices_dos_digitos:
        # Só texto (ex.: formato `"sem valor"`): mostra o texto.
        return ''.join(p[1] if p[0] == 'lit' else ('%' if p[0] == 'pct' else '') for p in partes)

    depois_do_ponto = [n for n in indices_dos_digitos if posicao_do_ponto is not None and n > posicao_do_ponto]
    antes_do_ponto = [n for n in indices_dos_digitos if n not in depois_do_ponto]
    casas = len(depois_do_ponto)

    # Vírgula entre dois dígitos = separador de milhar; vírgula depois do último dígito inteiro = divide por 1000 (cada uma).
    ultimo_inteiro = antes_do_ponto[-1] if antes_do_ponto else -1
    primeiro_inteiro = antes_do_ponto[0] if antes_do_ponto else 0
    milhar = any(p[0] == 'virgula' and primeiro_inteiro < n < ultimo_inteiro for n, p in enumerate(partes))
    fim_do_inteiro = posicao_do_ponto if posicao_do_ponto is not None else len(partes)
    ultimo_digito = indices_dos_digitos[-1]
    escala = sum(
        1 for n, p in enumerate(partes)
        if p[0] == 'virgula' and (ultimo_inteiro < n < fim_do_inteiro or n > ultimo_digito)
    )
    # Um literal NO MEIO dos dígitos (telefone, CPF) não é desenhado por este módulo.
    for n in range(primeiro_inteiro, ultimo_inteiro):
        if partes[n][0] == 'lit':
            raise _FormatoNaoSuportado()
    if depois_do_ponto:
        for n in range(depois_do_ponto[0], depois_do_ponto[-1]):
            if partes[n][0] == 'lit':
                raise _FormatoNaoSuportado()

    numero = Decimal(repr(float(valor_absoluto))) if not isinstance(valor_absoluto, Decimal) else valor_absoluto
    numero = Decimal(f'{numero:.15g}')
    for p in partes:
        if p[0] == 'pct':
            numero *= 100
    if escala:
        numero /= Decimal(1000) ** escala
    numero = _arredondar(numero, casas)

    texto_inteiro, _, texto_decimal = format(numero, 'f').partition('.')
    zeros_obrigatorios = sum(1 for n in antes_do_ponto if partes[n][1] == '0')
    espacos_obrigatorios = sum(1 for n in antes_do_ponto if partes[n][1] == '?')
    if texto_inteiro == '0' and not zeros_obrigatorios and not espacos_obrigatorios and (casas or antes_do_ponto):
        texto_inteiro = ''   # "#.##" mostra ",5" e não "0,5"
    texto_inteiro = texto_inteiro.rjust(zeros_obrigatorios, '0')
    if milhar and texto_inteiro:
        grupos = []
        while len(texto_inteiro) > 3:
            grupos.insert(0, texto_inteiro[-3:])
            texto_inteiro = texto_inteiro[:-3]
        grupos.insert(0, texto_inteiro)
        texto_inteiro = '.'.join(grupos)
    # Casas decimais: "0" obriga o dígito; "#" e "?" só aparecem se o dígito não for zero à direita.
    decimais = texto_decimal
    obrigatorias = sum(1 for n in depois_do_ponto if partes[n][1] == '0')
    while len(decimais) > obrigatorias and decimais.endswith('0'):
        decimais = decimais[:-1]
    numero_escrito = texto_inteiro + (',' + decimais if decimais else '')

    saida, colocou = [], False
    for n, p in enumerate(partes):
        if p[0] == 'lit':
            saida.append(p[1])
        elif p[0] == 'pct':
            saida.append('%')
        elif p[0] == 'dig' and not colocou:
            saida.append(numero_escrito)
            colocou = True
    return ''.join(saida)


# ---------------------------------------------------------------- datas

def _para_datetime(valor):
    if isinstance(valor, datetime.datetime):
        return valor
    if isinstance(valor, datetime.date):
        return datetime.datetime.combine(valor, datetime.time())
    if isinstance(valor, datetime.time):
        return datetime.datetime.combine(datetime.date(1899, 12, 31), valor)
    raise _FormatoNaoSuportado()


# Função Objetivo: Escreve data/hora com um código do Excel (yyyy, mm, dd, hh, ss, AM/PM...). "m" depois de "h" (ou antes de "s") é minuto.
def _formatar_data(valor, formato):
    momento = _para_datetime(valor)
    secao = _tirar_enfeites(_secoes(formato)[0])
    blocos, i = [], 0
    while i < len(secao):
        letra = secao[i]
        if letra == '"':
            fim = secao.find('"', i + 1)
            fim = len(secao) if fim == -1 else fim
            blocos.append(('lit', secao[i + 1:fim]))
            i = fim + 1
        elif letra == '\\' and i + 1 < len(secao):
            blocos.append(('lit', secao[i + 1]))
            i += 2
        elif letra == '_' and i + 1 < len(secao):
            blocos.append(('lit', ' '))
            i += 2
        elif letra == '*' and i + 1 < len(secao):
            i += 2
        elif letra.lower() in 'ymdhs':
            fim = i
            while fim < len(secao) and secao[fim].lower() == letra.lower():
                fim += 1
            blocos.append(('cod', secao[i:fim].lower()))
            i = fim
        elif secao[i:i + 5].lower() == 'am/pm' or secao[i:i + 3].lower() == 'a/p':
            tamanho = 5 if secao[i:i + 5].lower() == 'am/pm' else 3
            blocos.append(('ampm', tamanho))
            i += tamanho
        elif letra == '.' and secao[i + 1:i + 2] == '0':
            fim = i + 1
            while fim < len(secao) and secao[fim] == '0':
                fim += 1
            blocos.append(('fracao', fim - i - 1))
            i = fim
        else:
            blocos.append(('lit', letra))
            i += 1

    tem_ampm = any(p[0] == 'ampm' for p in blocos)
    saida = []
    for n, (tipo, dado) in enumerate(blocos):
        if tipo == 'lit':
            saida.append(dado)
        elif tipo == 'fracao':
            saida.append(',' + f'{momento.microsecond:06d}'[:dado])
        elif tipo == 'ampm':
            saida.append(('AM' if momento.hour < 12 else 'PM') if dado == 5 else ('A' if momento.hour < 12 else 'P'))
        elif dado[0] == 'y':
            saida.append(f'{momento.year:04d}' if len(dado) > 2 else f'{momento.year % 100:02d}')
        elif dado[0] == 'd':
            if len(dado) == 1:
                saida.append(str(momento.day))
            elif len(dado) == 2:
                saida.append(f'{momento.day:02d}')
            elif len(dado) == 3:
                saida.append(DIAS_DA_SEMANA[momento.weekday()][:3])
            else:
                saida.append(DIAS_DA_SEMANA[momento.weekday()])
        elif dado[0] == 'h':
            hora = momento.hour % 12 or 12 if tem_ampm else momento.hour
            saida.append(f'{hora:02d}' if len(dado) > 1 else str(hora))
        elif dado[0] == 's':
            saida.append(f'{momento.second:02d}' if len(dado) > 1 else str(momento.second))
        else:   # "m": mês ou minuto?
            anteriores = [p for p in blocos[:n] if p[0] == 'cod']
            seguintes = [p for p in blocos[n + 1:] if p[0] == 'cod']
            minuto = (anteriores and anteriores[-1][1][0] == 'h') or (seguintes and seguintes[0][1][0] == 's')
            if minuto:
                saida.append(f'{momento.minute:02d}' if len(dado) > 1 else str(momento.minute))
            elif len(dado) == 1:
                saida.append(str(momento.month))
            elif len(dado) == 2:
                saida.append(f'{momento.month:02d}')
            elif len(dado) == 3:
                saida.append(MESES[momento.month - 1][:3])
            else:
                saida.append(MESES[momento.month - 1])
    return ''.join(saida)


def _formato_de_data_padrao(valor):
    if isinstance(valor, datetime.time):
        return 'hh:mm:ss'
    if isinstance(valor, datetime.datetime) and (valor.hour or valor.minute or valor.second):
        return 'dd/mm/yyyy hh:mm'
    return 'dd/mm/yyyy'


# ---------------------------------------------------------------- ponto de entrada

# Função Objetivo: Como o Excel mostraria esta célula. Devolve (texto, tipo) onde tipo é 'numero' | 'texto' | 'centro' (alinhamento natural:
# número à direita, texto à esquerda, VERDADEIRO/FALSO e erros no centro). `tipo_de_dado` é o data_type do openpyxl ('n','s','b','e','d').
def texto_do_excel(valor, formato, tipo_de_dado='n'):
    try:
        return _texto_do_excel(valor, formato, tipo_de_dado)
    except Exception:
        # Rede de proteção: um valor ou formato esquisito nunca derruba a janela inteira; a célula só aparece sem formatação.
        try:
            return limpar_texto(texto_bruto(valor)), 'texto'
        except Exception:
            return '', 'texto'


def _texto_do_excel(valor, formato, tipo_de_dado):
    if valor is None:
        return '', 'texto'
    if tipo_de_dado == 'e':
        return limpar_texto(valor), 'centro'
    if isinstance(valor, bool):
        return ('VERDADEIRO' if valor else 'FALSO'), 'centro'
    if isinstance(valor, (datetime.datetime, datetime.date, datetime.time)):
        try:
            codigo = formato if formato and formato != 'General' and is_date_format(formato) else _formato_de_data_padrao(valor)
            return limpar_texto(_formatar_data(valor, codigo)), 'numero'
        except _FormatoNaoSuportado:
            return limpar_texto(texto_bruto(valor)), 'numero'
    if isinstance(valor, datetime.timedelta):
        return _duracao(valor), 'numero'
    if isinstance(valor, (int, float, Decimal)):
        return limpar_texto(_numero_do_excel(valor, formato)), 'numero'
    return limpar_texto(valor), 'texto'


def _numero_do_excel(valor, formato):
    if not formato or formato == 'General' or formato == '@' or valor != valor:   # valor != valor: NaN
        return numero_geral(valor)
    try:
        secoes = _secoes(formato)
        if is_date_format(formato):
            # Número que o formato quer ver como data (serial do Excel) e que o openpyxl não converteu: mostra o número como está.
            return numero_geral(valor)
        negativo = valor < 0
        zero = valor == 0
        if zero and len(secoes) >= 3:
            return _formatar_numero_na_secao(abs(valor), secoes[2])
        if negativo and len(secoes) >= 2:
            return _formatar_numero_na_secao(abs(valor), secoes[1])
        texto = _formatar_numero_na_secao(abs(valor), secoes[0])
        if negativo and any(c.isdigit() for c in texto) and not _so_zeros(texto):
            return '-' + texto
        return texto
    except _FormatoNaoSuportado:
        return numero_geral(valor)


def _so_zeros(texto):
    digitos = [c for c in texto if c.isdigit()]
    return bool(digitos) and all(c == '0' for c in digitos)
