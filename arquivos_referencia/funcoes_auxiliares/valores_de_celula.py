# arquivos_referencia/funcoes_auxiliares/valores_de_celula.py

# Função Objetivo: Lê o valor de UMA célula como número, dizendo — em português — o que há de errado quando
# não dá. Usado por todos os auditores de tabela de frete, para a mensagem ser sempre a mesma.
#
# * [EXPLICAÇÃO] → Por que "texto no lugar de número" é ERRO: os importadores do popular banco convertem a
#   célula com float()/Decimal(); um texto como "0,3" (com vírgula) derruba a linha, e o dado não entra.
#   O Excel mostra esse número alinhado à ESQUERDA e, geralmente, com um triângulo verde no canto.

import math
from datetime import date, datetime
from decimal import Decimal

from .relatorio_auditoria import descrever_local, limpar_texto

# Problemas possíveis ao ler um número
VAZIO = 'vazio'
TEXTO_EM_BRANCO = 'texto_em_branco'
FORMULA_COM_ERRO = 'formula_com_erro'
TEXTO = 'texto'
DATA = 'data'
BOOLEANO = 'booleano'
INVALIDO = 'invalido'


# Função Objetivo: Converte a célula bruta em (número, problema). problema é None quando deu certo.
def ler_numero(bruto):
    if bruto is None:
        return None, VAZIO
    if isinstance(bruto, bool):
        return None, BOOLEANO
    if isinstance(bruto, (int, float, Decimal)):
        numero = float(bruto)
        if math.isnan(numero) or math.isinf(numero):
            return None, INVALIDO
        return numero, None
    if isinstance(bruto, (datetime, date)):
        return None, DATA
    if isinstance(bruto, str):
        texto = bruto.strip()
        if not texto:
            return None, TEXTO_EM_BRANCO
        if texto.startswith('#'):
            return None, FORMULA_COM_ERRO
        return None, TEXTO
    return None, INVALIDO


def _resumo_do_bruto(bruto):
    texto = limpar_texto(bruto)
    return texto if len(texto) <= 40 else texto[:37] + '…'


# Função Objetivo: Texto do problema ("tem o texto “0,3” onde deveria ter um número").
def explicar_problema(problema, bruto):
    if problema == VAZIO:
        return 'está vazia'
    if problema == TEXTO_EM_BRANCO:
        return 'tem só espaços em branco'
    if problema == FORMULA_COM_ERRO:
        return f'tem um erro de fórmula do Excel ({_resumo_do_bruto(bruto)})'
    if problema == TEXTO:
        return f'tem o texto “{_resumo_do_bruto(bruto)}” onde deveria haver um número'
    if problema == DATA:
        return 'foi lida como data/hora (o Excel converteu o que foi digitado)'
    if problema == BOOLEANO:
        return 'tem VERDADEIRO/FALSO onde deveria haver um número'
    return 'não tem um número válido'


COMO_CORRIGIR_NUMERO = 'Digite só o número (ex.: 12,5) e deixe a célula no formato “Número”, não “Texto”.'


class LeitorDeNumeros:

    # Função Objetivo: Lê células numéricas de 1 aba e registra os problemas no relatório.
    def __init__(self, relatorio, aba):
        self.relatorio = relatorio
        self.aba = aba

    # Função Objetivo: Lê 1 célula como número. Devolve (valor, ok):
    #   - ok False  → a célula tem problema (já registrado como ERRO) ou está vazia sendo obrigatória;
    #   - ok True e valor None → vazia, e podia estar vazia.
    # `permite_negativo` False (padrão): número negativo vira ERRO — nenhum peso/preço/frete é negativo.
    def ler(self, n_linha, coluna, bruto, titulo_da_coluna, obrigatorio=True, permite_negativo=False):
        valor, problema = ler_numero(bruto)
        onde = descrever_local(self.aba, n_linha, coluna, titulo_da_coluna)

        if problema == VAZIO:
            if obrigatorio:
                self.relatorio.erro(
                    onde, f'A célula {explicar_problema(problema, bruto)}, mas é obrigatória.',
                    'Preencha o valor ou apague a linha inteira se ela não deve existir.',
                )
                return None, False
            return None, True

        if problema is not None:
            self.relatorio.erro(onde, f'A célula {explicar_problema(problema, bruto)}.', COMO_CORRIGIR_NUMERO)
            return None, False

        if valor < 0 and not permite_negativo:
            self.relatorio.erro(onde, f'O valor {valor} é negativo.', 'Confira o sinal: pesos, preços e fretes não são negativos.')
            return valor, False
        return valor, True
