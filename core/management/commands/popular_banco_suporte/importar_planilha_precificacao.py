# core/management/commands/popular_banco_suporte/importar_planilha_precificacao.py

# Função Objetivo: Importa os dados VALIDADOS de precificação (custo, fiscais,
# dimensões) de uma planilha Excel específica — diferente da Planilha_do_ML_Sysemp
# (dado geral do ERP) e do Relatório Completo ERP (dado geral também). Essa aqui é
# a fonte validada especificamente pro cálculo de margem/preço — testada e
# aprovada, mapeamento por índice de coluna (não por nome de cabeçalho, igual ao
# original). Roda por ÚLTIMO no popular_banco — precisa "vencer" a disputa dos
# mesmos campos com importar_produtos_erp.py. Casa por EAN (mesma chave do
# sistema antigo validado).
#
# Reescrito em POO (17/07) — 2 classes:
#   LinhaPlanilhaPrecificacao      → 1 linha da planilha, extrai e converte os campos
#   ImportadorPlanilhaPrecificacao → o processo inteiro, do arquivo ao banco

from pathlib import Path
from decimal import Decimal
import openpyxl
from produtos.models import Produto
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel

CAMINHO_PLANILHA_PRECIFICACAO = Path('Arquivos_de_Importação/Planilha_Importar_Pos_Macro.xlsm')


# Função Objetivo: Representa 1 linha da planilha, extrai e converte os campos.
class LinhaPlanilhaPrecificacao:

    CAMPOS_PRODUTO = [
        'custo', 'custo_com_boni', 'frete_cif_fob', 'mva', 'st_valor',
        'icms_entrada', 'ipi', 'pis_cofins', 'icms_saida_sp', 'icms_saida_media',
        'peso_produto_apos_embalado', 'altura_produto_apos_embalado',
        'comprimento_produto_apos_embalado', 'largura_produto_apos_embalado',
        'armazenagem_planilha', 'peso_cubado',
    ]

    # * [EXPLICAÇÃO] → peso_cubado é calculado AQUI, junto com as dimensões de
    #                  EMBALAGEM (confirmado com o usuário: as colunas desta
    #                  planilha representam o produto JÁ EMBALADO, a caixa real
    #                  usada pro frete — não o produto puro, que vem só do ERP
    #                  Completo). Essa planilha, quando roda, SOBRESCREVE só o
    #                  conjunto "apos_embalado" — nunca mexe em "sem_embalar".
    #                  6000 é o padrão internacional de peso cúbico — estável,
    #                  nunca muda — por isso fica encapsulado aqui.
    FATOR_PESO_CUBADO = 6000

    # Função Objetivo: Recebe a linha bruta e o conversor compartilhado.
    def __init__(self, row, conversor):
        self.row = row
        self.conversor = conversor
        self.ean = None
        self.produto = None

    # Função Objetivo: Detecta linha totalmente vazia (sem dado nas 10 primeiras colunas).
    def esta_vazia(self):
        return not any(v is not None for v in self.row[:10])

    # Função Objetivo: Extrai o EAN da linha (coluna 3).
    def extrair_ean(self):
        self.ean = str(self.row[3]).strip() if self.row[3] else None

    # Função Objetivo: Localiza o Produto correspondente pelo EAN.
    def localizar_produto(self, produtos_por_ean):
        self.produto = produtos_por_ean.get(self.ean) if self.ean else None

    # Função Objetivo: Converte fração pra percentual (0.04 → 4.00).
    # Explicação em detalhe: reaproveita o conversor só pra filtrar erro de
    # fórmula (#N/A, #REF!) e virar Decimal — a conta de fração→percentual em
    # si não tem equivalente no ConversorCelulaExcel, fica só aqui.
    def converter_percentual(self, valor):
        valor_filtrado = self.conversor.para_decimal(valor)
        if valor_filtrado is None:
            return Decimal('0')
        return Decimal(str(round(float(valor_filtrado) * 100, 2)))

    # Função Objetivo: Extrai e converte os campos fiscais e de custo.
    def extrair_fiscais_e_custo(self):
        self.produto.custo = self.conversor.para_decimal(self.row[9], padrao=Decimal('0'), casas_decimais=2)
        self.produto.custo_com_boni = self.conversor.para_decimal(self.row[10], casas_decimais=2)
        self.produto.frete_cif_fob = self.converter_percentual(self.row[11])
        self.produto.mva = self.conversor.para_decimal(self.row[7], casas_decimais=2)
        self.produto.st_valor = self.conversor.para_decimal(self.row[8], casas_decimais=2)
        self.produto.icms_entrada = self.converter_percentual(self.row[12])
        self.produto.ipi = self.converter_percentual(self.row[13])
        self.produto.pis_cofins = self.converter_percentual(self.row[14])
        self.produto.icms_saida_sp = self.converter_percentual(self.row[15])
        self.produto.icms_saida_media = self.converter_percentual(self.row[16])
        self.produto.armazenagem_planilha = self.conversor.para_decimal(self.row[59], casas_decimais=2)

    # Função Objetivo: Extrai dimensão de embalagem, padronizando eixos menor→maior.
    # Explicação em detalhe: mesma padronização aplicada no ERP Completo
    # (confirmada com o usuário) — ordem dos eixos nunca foi consistente entre
    # fontes, então sempre altura ≤ comprimento ≤ largura. Não muda o cálculo
    # (produto é comutativo), só a legibilidade/auditoria.
    def extrair_dimensoes_embalagem(self):
        self.produto.peso_produto_apos_embalado = self.conversor.para_decimal(
            self.row[19], padrao=Decimal('0'), casas_decimais=3
        )
        altura_bruta = self.conversor.para_decimal(self.row[21], padrao=Decimal('0'), casas_decimais=2)
        comprimento_bruto = self.conversor.para_decimal(self.row[22], padrao=Decimal('0'), casas_decimais=2)
        largura_bruta = self.conversor.para_decimal(self.row[23], padrao=Decimal('0'), casas_decimais=2)
        (
            self.produto.altura_produto_apos_embalado,
            self.produto.comprimento_produto_apos_embalado,
            self.produto.largura_produto_apos_embalado,
        ) = sorted([altura_bruta, comprimento_bruto, largura_bruta])

    # Função Objetivo: Calcula o peso cúbico a partir da embalagem já padronizada.
    def calcular_peso_cubado(self):
        self.produto.peso_cubado = (
            self.produto.altura_produto_apos_embalado
            * self.produto.largura_produto_apos_embalado
            * self.produto.comprimento_produto_apos_embalado
            / self.FATOR_PESO_CUBADO
        )

    # Função Objetivo: Roda os passos acima, na ordem certa, sobre o Produto já localizado.
    def aplicar_no_produto(self):
        self.extrair_fiscais_e_custo()
        self.extrair_dimensoes_embalagem()
        self.calcular_peso_cubado()
        return self.produto


# Função Objetivo: Orquestra a importação inteira da Planilha Validada, do arquivo ao banco.
class ImportadorPlanilhaPrecificacao:

    # Função Objetivo: Recebe o caminho da planilha e o stdout, zera os contadores.
    def __init__(self, caminho, stdout):
        self.caminho = caminho
        self.stdout = stdout
        self.conversor = ConversorCelulaExcel(origem='openpyxl')

        self.workbook = None
        self.planilha = None
        self.produtos_por_ean = {}

        self.para_atualizar = []
        self.sem_produto_correspondente = 0
        self.ignorados = 0
        self.erros = 0
        self.erros_detalhados = []
        self.total_linhas = 0

    # Função Objetivo: Abre a planilha (somente leitura, sem fórmulas).
    def abrir_planilha(self):
        self.workbook = openpyxl.load_workbook(self.caminho, read_only=True, data_only=True)
        self.planilha = self.workbook['Planilha1']

    # Função Objetivo: Carrega em memória os produtos já existentes no banco.
    def carregar_produtos_existentes(self):
        self.produtos_por_ean = {p.ean: p for p in Produto.objects.all()}

    # Função Objetivo: Processa cada linha da planilha, com barra de progresso.
    def processar_linhas(self):
        linhas = list(self.planilha.iter_rows(min_row=2, values_only=True))
        total = len(linhas)

        for indice, row in enumerate(linhas):
            if (indice + 1) % 200 == 0 or (indice + 1) == total:
                self.stdout.write(f'    ... {indice + 1}/{total} linhas processadas')

            linha = LinhaPlanilhaPrecificacao(row, self.conversor)

            if linha.esta_vazia():
                self.ignorados += 1
                continue

            self.total_linhas += 1

            try:
                linha.extrair_ean()
                if not linha.ean:
                    self.ignorados += 1
                    continue

                linha.localizar_produto(self.produtos_por_ean)
                if not linha.produto:
                    self.sem_produto_correspondente += 1
                    continue

                produto_atualizado = linha.aplicar_no_produto()
                self.para_atualizar.append(produto_atualizado)

            except Exception as e:
                self.erros += 1
                self.erros_detalhados.append(f'  [ERRO] Linha {indice + 2}: {e}')

    # Função Objetivo: Grava tudo no banco em lote.
    def salvar(self):
        if self.para_atualizar:
            Produto.objects.bulk_update(
                self.para_atualizar, LinhaPlanilhaPrecificacao.CAMPOS_PRODUTO, batch_size=BATCH_SIZE_PADRAO
            )

    # Função Objetivo: Roda a importação inteira, do arquivo ao banco.
    def rodar_importacao_completa(self):
        self.abrir_planilha()
        self.carregar_produtos_existentes()
        self.processar_linhas()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[PRECIFICAÇÃO — PLANILHA VALIDADA] Concluído!\n'
            f'    Linhas processadas: {self.total_linhas}\n'
            f'    Produtos atualizados: {len(self.para_atualizar)}\n'
            f'    Sem produto correspondente (EAN não achado): {self.sem_produto_correspondente}\n'
            f'    Ignorados: {self.ignorados}\n'
            f'    Erros: {self.erros}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_planilha_precificacao(stdout, style, caminho=CAMINHO_PLANILHA_PRECIFICACAO):
    if not caminho.exists():
        stdout.write(style.WARNING(
            f'[PRECIFICAÇÃO — PLANILHA VALIDADA] Arquivo {caminho} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[PRECIFICAÇÃO — PLANILHA VALIDADA] Lendo {caminho}...')

    importador = ImportadorPlanilhaPrecificacao(caminho, stdout)
    importador.rodar_importacao_completa()

    for erro in importador.erros_detalhados:
        stdout.write(style.ERROR(erro))

    stdout.write(style.SUCCESS(importador.relatorio()))