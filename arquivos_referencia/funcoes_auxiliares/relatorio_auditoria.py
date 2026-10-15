# arquivos_referencia/funcoes_auxiliares/relatorio_auditoria.py

# Função Objetivo: Guarda o resultado da AUDITORIA de 1 arquivo (tela "Arquivos de referência"): o que
# foi achado (erros e avisos, cada um com o lugar exato na planilha e como corrigir), um resumo em
# números e a pré-visualização do que o sistema vai ler. Não lê planilha nem grava nada: só organiza o
# resultado para a tela.
#
# * [DECISÃO, 15/10/2026] → 2 gravidades, como combinado com Matheus:
#   - ERRO: o sistema leria o dado errado (ou ignoraria uma linha). O arquivo NÃO pode ser enviado.
#   - AVISO: o arquivo é lido normalmente, mas tem algo estranho que vale conferir (não bloqueia).
# * [EXPLICAÇÃO] → O estado do arquivo é 1 de 4: "valido" (nada a dizer), "com_avisos", "com_erros" ou
#   "ilegivel" (nem abriu como planilha). Estado nunca só por cor: a tela mostra ícone + texto.

import re
from dataclasses import dataclass, field

from openpyxl.utils import get_column_letter

GRAVIDADE_ERRO = 'erro'
GRAVIDADE_AVISO = 'aviso'

STATUS_VALIDO = 'valido'
STATUS_COM_AVISOS = 'com_avisos'
STATUS_COM_ERROS = 'com_erros'
STATUS_ILEGIVEL = 'ilegivel'

# * [EXPLICAÇÃO] → Se um arquivo estiver muito quebrado (ex.: 300 linhas com o mesmo problema), a tela
#   mostra só os primeiros achados de cada gravidade e diz quantos ficaram de fora. Os CONTADORES (que
#   decidem o estado do arquivo) são sempre exatos.
LIMITE_DE_ACHADOS_MOSTRADOS_POR_GRAVIDADE = 100
LIMITE_DE_LINHAS_DA_PREVIA = 400


# Função Objetivo: Tira quebras de linha e espaços repetidos de um texto de célula (cabeçalhos da
# planilha vêm com "\n", ex.: "Peso mín. (kg)\nexclusivo").
def limpar_texto(valor):
    return re.sub(r'\s+', ' ', str(valor)).strip()


# Função Objetivo: Número no jeito brasileiro (1.234,5), sem zeros sobrando: 0.499 -> "0,499", 5.0 -> "5".
def formatar_numero(valor, casas_maximas=3):
    if valor is None:
        return '—'
    texto = f'{float(valor):,.{casas_maximas}f}'
    inteiro, _, decimais = texto.partition('.')
    decimais = decimais.rstrip('0')
    inteiro = inteiro.replace(',', '.')
    return f'{inteiro},{decimais}' if decimais else inteiro


# Função Objetivo: Dinheiro no jeito brasileiro, sempre com 2 casas: 5.65 -> "R$ 5,65".
def formatar_dinheiro(valor):
    if valor is None:
        return '—'
    texto = f'{float(valor):,.2f}'
    return 'R$ ' + texto.replace(',', '#').replace('.', ',').replace('#', '.')


def formatar_peso(valor):
    return f'{formatar_numero(valor)} kg'


# Função Objetivo: Tamanho do arquivo em texto curto ("21 KB", "1,4 MB").
def formatar_tamanho(bytes_):
    if bytes_ < 1024:
        return f'{bytes_} bytes'
    if bytes_ < 1024 * 1024:
        return f'{round(bytes_ / 1024)} KB'
    return f'{formatar_numero(bytes_ / (1024 * 1024), 1)} MB'


# Função Objetivo: Monta o "onde" de um achado, no jeito que a pessoa acha na planilha:
# 'aba "Magalu" · linha 5 · coluna E (Peso mínimo)'.
def descrever_local(aba=None, linha=None, coluna=None, titulo_da_coluna=None):
    partes = []
    if aba:
        partes.append(f'aba “{aba}”')
    if linha:
        partes.append(f'linha {linha}')
    if coluna is not None:
        texto = f'coluna {get_column_letter(coluna + 1)}'
        if titulo_da_coluna:
            texto += f' ({limpar_texto(titulo_da_coluna)})'
        partes.append(texto)
    return ' · '.join(partes) or 'arquivo inteiro'


@dataclass
class Achado:
    gravidade: str
    onde: str
    o_que: str
    como_corrigir: str = ''


@dataclass
class Previa:
    titulo: str
    colunas: list
    linhas: list = field(default_factory=list)
    total_de_linhas: int = 0

    @property
    def truncada(self):
        return self.total_de_linhas > len(self.linhas)


class RelatorioDeAuditoria:

    # Função Objetivo: Começa um relatório vazio para 1 arquivo.
    def __init__(self, nome_do_arquivo, tamanho_em_bytes):
        self.nome_do_arquivo = nome_do_arquivo
        self.tamanho_em_bytes = tamanho_em_bytes
        self.conseguiu_ler = True
        self.resumo = []        # lista de (rótulo, valor)
        self.previas = []
        self.total_de_erros = 0
        self.total_de_avisos = 0
        self._erros = []
        self._avisos = []

    # Função Objetivo: Registra um ERRO (impede o envio do arquivo).
    def erro(self, onde, o_que, como_corrigir=''):
        self.total_de_erros += 1
        if len(self._erros) < LIMITE_DE_ACHADOS_MOSTRADOS_POR_GRAVIDADE:
            self._erros.append(Achado(GRAVIDADE_ERRO, onde, o_que, como_corrigir))

    # Função Objetivo: Registra um AVISO (não impede o envio, mas vale conferir).
    def aviso(self, onde, o_que, como_corrigir=''):
        self.total_de_avisos += 1
        if len(self._avisos) < LIMITE_DE_ACHADOS_MOSTRADOS_POR_GRAVIDADE:
            self._avisos.append(Achado(GRAVIDADE_AVISO, onde, o_que, como_corrigir))

    # Função Objetivo: O arquivo nem abriu como planilha — não há mais nada a conferir.
    def nao_conseguiu_ler(self, o_que, como_corrigir=''):
        self.conseguiu_ler = False
        self.erro('arquivo inteiro', o_que, como_corrigir)

    def resumir(self, rotulo, valor):
        self.resumo.append((rotulo, str(valor)))

    def adicionar_previa(self, previa):
        self.previas.append(previa)

    @property
    def erros(self):
        return self._erros

    @property
    def avisos(self):
        return self._avisos

    @property
    def erros_ocultos(self):
        return self.total_de_erros - len(self._erros)

    @property
    def avisos_ocultos(self):
        return self.total_de_avisos - len(self._avisos)

    @property
    def status(self):
        if not self.conseguiu_ler:
            return STATUS_ILEGIVEL
        if self.total_de_erros:
            return STATUS_COM_ERROS
        if self.total_de_avisos:
            return STATUS_COM_AVISOS
        return STATUS_VALIDO

    # * [EXPLICAÇÃO] → Só um arquivo SEM erros pode seguir para o envio (avisos não bloqueiam).
    @property
    def pode_enviar(self):
        return self.conseguiu_ler and self.total_de_erros == 0

    @property
    def tamanho_texto(self):
        return formatar_tamanho(self.tamanho_em_bytes)


# Função Objetivo: Corta uma pré-visualização no limite e guarda o total real de linhas.
def montar_previa(titulo, colunas, linhas):
    return Previa(
        titulo=titulo,
        colunas=colunas,
        linhas=linhas[:LIMITE_DE_LINHAS_DA_PREVIA],
        total_de_linhas=len(linhas),
    )
