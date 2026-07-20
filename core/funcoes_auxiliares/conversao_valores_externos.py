# core/funcoes_auxiliares/conversao_valores_externos.py

# Função Objetivo: Converte valores de células de arquivos externos (upload de
# plataforma) pra tipos Python confiáveis, sem quebrar em dado sujo.
# Explicação em detalhe: fontes externas vêm sujas — célula vazia pode chegar como
# None, "", ou string com espaço; símbolo de moeda e vírgula decimal também
# acontecem. Compartilhado entre Shopee/TikTok/qualquer marketplace futuro que
# precise ler arquivo de fora — não é lógica de negócio de nenhum marketplace
# específico, é limpeza de dado genérica.

from decimal import Decimal, InvalidOperation


def para_decimal_seguro(valor):
    if valor is None:
        return None
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor))

    texto = str(valor).strip()
    if not texto:
        return None

    texto = texto.replace('R$', '').replace(' ', '')
    if ',' in texto and '.' in texto:
        texto = texto.replace('.', '').replace(',', '.')
    elif ',' in texto:
        texto = texto.replace(',', '.')

    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def para_int_seguro(valor):
    if valor is None:
        return 0
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        return int(valor)

    texto = str(valor).strip()
    if not texto:
        return 0

    try:
        return int(float(texto))
    except ValueError:
        return 0