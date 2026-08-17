# core/management/commands/popular_banco_suporte/importar_tabela_frete_tiktok.py

# Função Objetivo: Importa a tabela de frete do TikTok Shop de uma planilha Excel separada.
# Explicação em detalhe: mais simples que a do Magalu — só peso × valor médio (sem faixa
# de reputação). Colunas esperadas (linha 1 = cabeçalho, dados a partir da linha 2):
#   A: Faixa Peso (kg) — só label, ignorada
#   B: Valor médio (R$)
#   C: Peso mínimo — SEMPRE preenchido, inclusive na última faixa
#   D: Peso máximo — vazio de verdade na última faixa (sem teto)

from pathlib import Path
import openpyxl
from tiktok.models import FreteTiktok
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel

CAMINHO_TABELA_FRETE_TIKTOK = Path('Arquivos usados para Popular Banco/Tabelas de Frete/Tabela_Frete_Tiktok_Shop.xlsx')

COL_VALOR = 1
COL_PESO_MIN = 2
COL_PESO_MAX = 3


class LinhaFreteTiktok:

    def __init__(self, row, conversor):
        self.row = row
        self.conversor = conversor
        self.peso_min = None
        self.peso_max = None
        self.valor = None

    def processar(self):
        self.peso_min = self.conversor.para_decimal(self.row[COL_PESO_MIN], casas_decimais=3)
        self.peso_max = self.conversor.para_decimal(self.row[COL_PESO_MAX], casas_decimais=3)
        self.valor = self.conversor.para_decimal(self.row[COL_VALOR], casas_decimais=2)
        return self


class ImportadorFreteTiktok:

    def __init__(self, caminho, stdout):
        self.caminho = caminho
        self.stdout = stdout
        self.conversor = ConversorCelulaExcel(origem='openpyxl')

        self.existentes = {}
        self.para_criar = []
        self.para_atualizar = []
        self.erros = []

    def abrir_planilha(self):
        wb = openpyxl.load_workbook(self.caminho, read_only=True, data_only=True)
        ws = wb.active
        self.rows = list(ws.iter_rows(min_row=2, values_only=True))

    def carregar_existentes(self):
        self.existentes = {f.peso_min: f for f in FreteTiktok.objects.all()}

    def processar_linhas(self):
        total = len(self.rows)

        for indice, row in enumerate(self.rows, start=1):
            if indice % 10 == 0 or indice == total:
                self.stdout.write(f'    ... {indice}/{total} linhas processadas')

            if not any(v is not None for v in row[:2]):
                continue

            try:
                linha = LinhaFreteTiktok(row, self.conversor).processar()
                if linha.peso_min is None:
                    self.erros.append(f'  [ERRO] Linha {indice + 1}: peso_min vazio na planilha — corrija a fonte.')
                    continue
                self._registrar_linha(linha)
            except Exception as e:
                self.erros.append(f'  [ERRO] Linha {indice + 1}: {e}')

    def _registrar_linha(self, linha):
        existente = self.existentes.get(linha.peso_min)
        if existente and existente.pk:
            existente.peso_max = linha.peso_max
            existente.valor = linha.valor
            self.para_atualizar.append(existente)
        else:
            novo = FreteTiktok(peso_min=linha.peso_min, peso_max=linha.peso_max, valor=linha.valor)
            self.para_criar.append(novo)
            self.existentes[linha.peso_min] = novo

    def salvar(self):
        if self.para_criar:
            FreteTiktok.objects.bulk_create(self.para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.para_atualizar:
            FreteTiktok.objects.bulk_update(self.para_atualizar, ['peso_max', 'valor'], batch_size=BATCH_SIZE_PADRAO)

    def rodar_importacao_completa(self):
        self.abrir_planilha()
        self.carregar_existentes()
        self.processar_linhas()
        self.salvar()
        return self

    def relatorio(self):
        return (
            f'[FRETE TIKTOK] Concluído!\n'
            f'    Criados:     {len(self.para_criar)}\n'
            f'    Atualizados: {len(self.para_atualizar)}\n'
            f'    Erros:       {len(self.erros)}'
        )


def importar_tabela_frete_tiktok(stdout, style, caminho=CAMINHO_TABELA_FRETE_TIKTOK):
    if not caminho.exists():
        stdout.write(f'[FRETE TIKTOK] Arquivo {caminho} não encontrado — pulando essa etapa.')
        return

    stdout.write(f'[FRETE TIKTOK] Lendo {caminho}...')

    importador = ImportadorFreteTiktok(caminho, stdout)
    importador.rodar_importacao_completa()

    for erro in importador.erros:
        stdout.write(style.ERROR(erro))

    stdout.write(style.SUCCESS(importador.relatorio()))