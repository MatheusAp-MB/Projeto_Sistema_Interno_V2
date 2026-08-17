# core/management/commands/popular_banco_suporte/importar_tabela_frete_magalu.py

# Função Objetivo: Importa a tabela de frete do Magalu de uma planilha Excel separada.
# Explicação em detalhe: MUITO mais simples que a do ML — frete do Magalu é peso × faixa
# de reputação (3 colunas de valor: <92%/92-97%/>97%), sem nenhuma faixa de preço, sem
# matriz. Colunas esperadas (linha 1 = cabeçalho, dados a partir da linha 2):
#   A: Faixa Peso (kg) — só label, ignorada
#   B: <92% (0% desconto)      → valor_baixa
#   C: 92-97% (25% desconto)   → valor_media
#   D: >97% (50% desconto)     → valor_alta
#   E: Peso mínimo — SEMPRE preenchido na fonte, inclusive na última faixa
#      ("Acima de 200kg" = peso_min 200) — nunca adivinhado pelo sistema.
#   F: Peso máximo — vazio de verdade (não "-") na última faixa, sem teto.

from pathlib import Path
import openpyxl
from magalu.models import FreteMagalu
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel

CAMINHO_TABELA_FRETE_MAGALU = Path('Arquivos usados para Popular Banco/Tabelas de Frete/Tabela_Frete_Magalu.xlsx')

COL_VALOR_BAIXA = 1
COL_VALOR_MEDIA = 2
COL_VALOR_ALTA = 3
COL_PESO_MIN = 4
COL_PESO_MAX = 5


# Função Objetivo: Representa 1 faixa de peso, com os 3 valores de reputação.
class LinhaFreteMagalu:

    # Função Objetivo: Recebe a linha bruta e o conversor compartilhado.
    def __init__(self, row, conversor):
        self.row = row
        self.conversor = conversor

        self.peso_min = None
        self.peso_max = None
        self.valor_baixa = None
        self.valor_media = None
        self.valor_alta = None

    # Função Objetivo: Extrai os 5 valores numéricos da linha.
    # Explicação em detalhe: peso_min SEM padrão — se vier vazio na planilha, é erro de
    # cadastro na fonte (nunca adivinhado aqui), detectado e listado por quem chama.
    def processar(self):
        self.peso_min = self.conversor.para_decimal(self.row[COL_PESO_MIN], casas_decimais=3)
        self.peso_max = self.conversor.para_decimal(self.row[COL_PESO_MAX], casas_decimais=3)
        self.valor_baixa = self.conversor.para_decimal(self.row[COL_VALOR_BAIXA], casas_decimais=2)
        self.valor_media = self.conversor.para_decimal(self.row[COL_VALOR_MEDIA], casas_decimais=2)
        self.valor_alta = self.conversor.para_decimal(self.row[COL_VALOR_ALTA], casas_decimais=2)
        return self


# Função Objetivo: Orquestra a importação inteira, do arquivo ao banco.
class ImportadorFreteMagalu:

    # Função Objetivo: Recebe o caminho da planilha e o stdout, zera os contadores.
    def __init__(self, caminho, stdout):
        self.caminho = caminho
        self.stdout = stdout
        self.conversor = ConversorCelulaExcel(origem='openpyxl')

        self.existentes = {}
        self.para_criar = []
        self.para_atualizar = []
        self.erros = []

    # Função Objetivo: Abre a planilha e lê todas as linhas de dado.
    def abrir_planilha(self):
        wb = openpyxl.load_workbook(self.caminho, read_only=True, data_only=True)
        ws = wb.active
        self.rows = list(ws.iter_rows(min_row=2, values_only=True))

    # Função Objetivo: Carrega em memória as faixas já existentes no banco.
    def carregar_existentes(self):
        self.existentes = {f.peso_min: f for f in FreteMagalu.objects.all()}

    # Função Objetivo: Processa cada linha, com barra de progresso.
    def processar_linhas(self):
        total = len(self.rows)

        for indice, row in enumerate(self.rows, start=1):
            if indice % 10 == 0 or indice == total:
                self.stdout.write(f'    ... {indice}/{total} linhas processadas')

            if not any(v is not None for v in row[:4]):
                continue

            try:
                linha = LinhaFreteMagalu(row, self.conversor).processar()
                if linha.peso_min is None:
                    self.erros.append(f'  [ERRO] Linha {indice + 1}: peso_min vazio na planilha — corrija a fonte.')
                    continue
                self._registrar_linha(linha)
            except Exception as e:
                self.erros.append(f'  [ERRO] Linha {indice + 1}: {e}')

    # Função Objetivo: Cria ou atualiza 1 registro, chave peso_min.
    def _registrar_linha(self, linha):
        existente = self.existentes.get(linha.peso_min)
        if existente and existente.pk:
            existente.peso_max = linha.peso_max
            existente.valor_baixa = linha.valor_baixa
            existente.valor_media = linha.valor_media
            existente.valor_alta = linha.valor_alta
            self.para_atualizar.append(existente)
        else:
            novo = FreteMagalu(
                peso_min=linha.peso_min, peso_max=linha.peso_max,
                valor_baixa=linha.valor_baixa, valor_media=linha.valor_media, valor_alta=linha.valor_alta,
            )
            self.para_criar.append(novo)
            self.existentes[linha.peso_min] = novo

    # Função Objetivo: Grava tudo no banco em lote.
    def salvar(self):
        if self.para_criar:
            FreteMagalu.objects.bulk_create(self.para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.para_atualizar:
            FreteMagalu.objects.bulk_update(
                self.para_atualizar, ['peso_max', 'valor_baixa', 'valor_media', 'valor_alta'],
                batch_size=BATCH_SIZE_PADRAO,
            )

    # Função Objetivo: Roda a importação inteira, do arquivo ao banco.
    def rodar_importacao_completa(self):
        self.abrir_planilha()
        self.carregar_existentes()
        self.processar_linhas()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[FRETE MAGALU] Concluído!\n'
            f'    Criados:     {len(self.para_criar)}\n'
            f'    Atualizados: {len(self.para_atualizar)}\n'
            f'    Erros:       {len(self.erros)}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_tabela_frete_magalu(stdout, style, caminho=CAMINHO_TABELA_FRETE_MAGALU):
    if not caminho.exists():
        stdout.write(f'[FRETE MAGALU] Arquivo {caminho} não encontrado — pulando essa etapa.')
        return

    stdout.write(f'[FRETE MAGALU] Lendo {caminho}...')

    importador = ImportadorFreteMagalu(caminho, stdout)
    importador.rodar_importacao_completa()

    for erro in importador.erros:
        stdout.write(style.ERROR(erro))

    stdout.write(style.SUCCESS(importador.relatorio()))