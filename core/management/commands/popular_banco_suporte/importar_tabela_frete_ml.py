# core/management/commands/popular_banco_suporte/importar_tabela_frete_ml.py

# Função Objetivo: Importa a tabela de frete do Mercado Livre de uma planilha Excel.
# Explicação em detalhe: roda dentro do popular_banco, com proteção pra não quebrar a
# importação inteira caso o arquivo não exista nesse ambiente (mesma proteção já usada em
# Qualidade/Competição) — é dado de referência raro de mudar. A unidade de dado aqui é a
# CÉLULA da matriz (1 faixa de peso × 1 faixa de preço × 1 regime), não a linha inteira.
#
# * [LAYOUT DA PLANILHA] → mudou em 23/09/2026: colunas A=rótulo, B=peso_min, C=peso_max,
#   D=Regime ("Sem"/"Com Frete Grátis Rápido"), E=free_shipping, F..M=8 faixas de preço.
#   A planilha traz 2 linhas por faixa de peso (1 por Regime) — são 2 tabelas reais de
#   frete diferentes. Desde 27/09/2026 o FreteML tem campo `regime` — as 2 linhas são
#   importadas, cada uma na sua célula (peso_min, preco_min, regime).

import re
from pathlib import Path
from decimal import Decimal
import openpyxl
from mercado_livre.models import FreteML
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO

CAMINHO_TABELA_FRETE = Path('Arquivos usados para Popular Banco/Tabelas de Frete/Tabela_Frete_Mercado_Livre.xlsx')

# * [EXPLICAÇÃO] → Posição (índice, começando em 0) de cada coluna fixa da planilha.
COLUNA_PESO_MIN = 1
COLUNA_PESO_MAX = 2
COLUNA_REGIME = 3
COLUNA_INICIO_PRECOS = 5  # colunas F (índice 5) até M (índice 12) — 8 faixas de preço

# * [EXPLICAÇÃO] → Traduz o texto da coluna Regime pro valor interno do model — a ÚNICA
#   fonte de verdade é o próprio FreteML.Regime (nunca reescrito aqui à parte, pra nunca
#   dessincronizar dos 2 valores válidos).
REGIME_POR_TEXTO_PLANILHA = {label: valor for valor, label in FreteML.Regime.choices}


# Função Objetivo: Representa 1 célula da matriz — 1 faixa de peso × 1 faixa de preço,
# já com o regime da linha de onde veio.
class LinhaFreteML:

    # Função Objetivo: Recebe a linha bruta, o índice da faixa de preço (0 a 7), a
    # faixa de preço já parseada, e o regime (já traduzido) dessa linha.
    def __init__(self, row, col_idx, preco_min, preco_max, regime):
        self.row = row
        self.col_idx = col_idx
        self.coluna_valor = COLUNA_INICIO_PRECOS + col_idx
        self.preco_min = preco_min
        self.preco_max = preco_max
        self.regime = regime

        self.peso_min = None
        self.peso_max = None
        self.valor = None

    # Função Objetivo: Diz se essa célula tem valor de frete preenchido.
    def tem_valor(self):
        return self.row[self.coluna_valor] is not None

    # Função Objetivo: Extrai a faixa de peso da linha (colunas B e C).
    def extrair_faixa_peso(self):
        self.peso_min = Decimal(str(self.row[COLUNA_PESO_MIN]))
        peso_max_raw = self.row[COLUNA_PESO_MAX]

        # * [EXPLICAÇÃO] → A última faixa ("Mais de 150 kg") não tem limite superior.
        #   A planilha atual marca isso com o texto "sem limite" na célula. Versões
        #   antigas usavam um número-sentinela gigante (>= 999999999) — mantemos os
        #   2 jeitos de reconhecer "sem limite", pra não quebrar de novo se o
        #   formato mudar outra vez.
        if peso_max_raw is None:
            self.peso_max = None
        elif isinstance(peso_max_raw, str):
            self.peso_max = None
        elif float(peso_max_raw) >= 999999999:
            self.peso_max = None
        else:
            self.peso_max = Decimal(str(peso_max_raw))

    # Função Objetivo: Extrai o valor do frete dessa célula.
    def extrair_valor(self):
        bruto = self.row[self.coluna_valor]
        self.valor = Decimal(str(round(float(bruto), 2)))

    # Função Objetivo: Roda os passos acima, na ordem certa.
    def processar(self):
        self.extrair_faixa_peso()
        self.extrair_valor()
        return self


# Função Objetivo: Orquestra a importação inteira, do arquivo ao banco.
class ImportadorFreteML:

    # Função Objetivo: Recebe o caminho da planilha e o stdout, zera os contadores.
    def __init__(self, caminho, stdout):
        self.caminho = caminho
        self.stdout = stdout

        self.rows = []
        self.faixas_preco = []
        self.existentes = {}

        self.para_criar = []
        self.para_atualizar = []
        self.regimes_nao_reconhecidos = []
        self.erros = []

    # Função Objetivo: Abre a planilha e lê todas as linhas.
    def abrir_planilha(self):
        wb = openpyxl.load_workbook(self.caminho, read_only=True, data_only=True)
        ws = wb.active
        self.rows = list(ws.iter_rows(values_only=True))

    # Função Objetivo: Extrai os números do texto do cabeçalho de 1 faixa de preço.
    # Explicação em detalhe: funciona independente do formato (com/sem "R$", ponto de
    # milhar, vírgula decimal, traço solto no final).
    def _parsear_faixa_preco(self, texto):
        numeros = re.findall(r'[\d]+(?:[.,]\d+)?', texto)

        def to_decimal(s):
            return Decimal(s.replace('.', '').replace(',', '.'))

        preco_min = to_decimal(numeros[0]) if numeros else Decimal('0')
        preco_max = to_decimal(numeros[1]) if len(numeros) > 1 else None
        return preco_min, preco_max

    # Função Objetivo: Parseia as 8 faixas de preço do cabeçalho (colunas F..M), 1 vez só.
    def parsear_cabecalho(self):
        header = self.rows[0]
        self.faixas_preco = [
            self._parsear_faixa_preco(str(header[col_idx]))
            for col_idx in range(COLUNA_INICIO_PRECOS, COLUNA_INICIO_PRECOS + 8)
        ]

    # Função Objetivo: Carrega em memória os registros já existentes no banco.
    def carregar_existentes(self):
        self.existentes = {
            (f.peso_min, f.preco_min, f.regime): f for f in FreteML.objects.all()
        }

    # Função Objetivo: Processa cada célula da matriz, com barra de progresso.
    def processar_linhas(self):
        linhas_dado = self.rows[1:]
        total = len(linhas_dado)

        for indice, row in enumerate(linhas_dado, start=1):
            if indice % 10 == 0 or indice == total:
                self.stdout.write(f'    ... {indice}/{total} linhas processadas')

            # * [EXPLICAÇÃO] → peso_min vazio identifica linha em branco ou nota de
            #   rodapé (fonte, observação) — não é dado de matriz, pula.
            if row[COLUNA_PESO_MIN] is None:
                continue

            texto_regime = row[COLUNA_REGIME]
            regime = REGIME_POR_TEXTO_PLANILHA.get(texto_regime)
            if regime is None:
                # * [EXPLICAÇÃO] → Regime não reconhecido (texto da coluna D não bate
                #   com nenhuma das 2 opções do model) — não inventa um valor, avisa
                #   e pula, pra não gravar dado errado silenciosamente.
                self.regimes_nao_reconhecidos.append(f'  [REGIME?] Linha {row[0]}: "{texto_regime}"')
                continue

            try:
                for col_idx, (preco_min, preco_max) in enumerate(self.faixas_preco):
                    linha = LinhaFreteML(row, col_idx, preco_min, preco_max, regime)
                    if not linha.tem_valor():
                        continue
                    linha.processar()
                    self._registrar_linha(linha)
            except Exception as e:
                self.erros.append(f'  [ERRO] Linha {row[0]}: {e}')

    # Função Objetivo: Cria ou atualiza 1 registro, chave (peso_min, preco_min, regime).
    # Explicação em detalhe: um objeto "existente" pode ser (a) um registro de verdade
    # já salvo no banco (tem pk) — aí atualiza e manda pro lote de UPDATE — ou (b) um
    # objeto criado NESTA MESMA rodada, ainda sem pk (a chave repetiu na planilha) — aí
    # só atualiza os campos em memória, sem duplicar no lote de CREATE nem mandar pro
    # de UPDATE (bulk_update exige pk, senão quebra — foi esse o erro que apareceu antes).
    def _registrar_linha(self, linha):
        chave = (linha.peso_min, linha.preco_min, linha.regime)
        existente = self.existentes.get(chave)

        if existente is not None and existente.pk is not None:
            existente.peso_max = linha.peso_max
            existente.preco_max = linha.preco_max
            existente.valor = linha.valor
            self.para_atualizar.append(existente)
        elif existente is not None:
            existente.peso_max = linha.peso_max
            existente.preco_max = linha.preco_max
            existente.valor = linha.valor
        else:
            novo = FreteML(
                peso_min=linha.peso_min, peso_max=linha.peso_max,
                preco_min=linha.preco_min, preco_max=linha.preco_max,
                regime=linha.regime, valor=linha.valor,
            )
            self.para_criar.append(novo)
            self.existentes[chave] = novo

    # Função Objetivo: Grava tudo no banco em lote.
    def salvar(self):
        if self.para_criar:
            FreteML.objects.bulk_create(self.para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.para_atualizar:
            FreteML.objects.bulk_update(
                self.para_atualizar, ['peso_max', 'preco_max', 'valor'], batch_size=BATCH_SIZE_PADRAO
            )

    # Função Objetivo: Roda a importação inteira, do arquivo ao banco.
    def rodar_importacao_completa(self):
        self.abrir_planilha()
        self.parsear_cabecalho()
        self.carregar_existentes()
        self.processar_linhas()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[FRETE ML] Concluído!\n'
            f'    Criados:     {len(self.para_criar)}\n'
            f'    Atualizados: {len(self.para_atualizar)}\n'
            f'    Regime não reconhecido: {len(self.regimes_nao_reconhecidos)}\n'
            f'    Erros:       {len(self.erros)}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_tabela_frete_ml(stdout, style, caminho=CAMINHO_TABELA_FRETE):
    if not caminho.exists():
        stdout.write(f'[FRETE ML] Arquivo {caminho} não encontrado — pulando essa etapa.')
        return

    stdout.write(f'[FRETE ML] Lendo {caminho}...')

    importador = ImportadorFreteML(caminho, stdout)
    importador.rodar_importacao_completa()

    for aviso in importador.regimes_nao_reconhecidos:
        stdout.write(style.WARNING(aviso))
    for erro in importador.erros:
        stdout.write(style.ERROR(erro))

    stdout.write(style.SUCCESS(importador.relatorio()))