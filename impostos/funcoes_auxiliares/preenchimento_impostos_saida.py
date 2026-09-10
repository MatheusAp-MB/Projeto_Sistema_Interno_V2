# impostos/funcoes_auxiliares/preenchimento_impostos_saida.py

# Função Objetivo: Preenche os 4 campos fiscais de saída do Produto
# (icms_saida_sp, icms_saida_media, pis_percentual, cofins_percentual) a
# partir da planilha Busca Legal — camada 1 do plano de Impostos de Saída
# (ver checkpoint no vault). Só lê ICMS/ICMS MÉDIA/PIS/COFINS — CST e as 27
# colunas por UF ficam pras camadas 3 e 5, ainda não existem no modelo.
#
# Nunca cria Produto novo a partir de dado fiscal — produto só nasce do ERP
# (ver importar_produtos_erp.py). EAN sem produto correspondente no banco é
# só reportado, nunca vira produto novo.

from decimal import Decimal

import openpyxl

from core.empresa import obter_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from produtos.models import Produto

CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Arquivos usados para Popular Banco/Impostos Saida/TABELA SAIDA POR UF MAGAZINE.xlsx',
    EMPRESA_SAMVALE: 'Arquivos usados para Popular Banco/Impostos Saida/TABELA SAIDA POR UF SAMVALE.xlsx',
}

# * [EXPLICAÇÃO] → Nome exato das colunas na linha 2 da planilha Busca
#                  Legal (linha 1 é só o grupo — ENTRADA/SAÍDA/UF de
#                  destino — descartada). Se algum desses nomes não bater
#                  com o cabeçalho real da planilha, a coluna some do
#                  dicionário da linha e o campo vira 0 silenciosamente —
#                  1º lugar a conferir na camada 2 (validação).
COLUNA_EAN = 'Cód Barras'
COLUNA_ICMS = 'ICMS'
COLUNA_ICMS_MEDIA = 'ICMS MÉDIA'
COLUNA_PIS = 'PIS'
COLUNA_COFINS = 'COFINS'

DUAS_CASAS_DECIMAIS = Decimal('0.01')


# Função Objetivo: Lê a planilha Busca Legal (cabeçalho de 2 linhas), devolvendo 1 dicionário por linha de dado.
# Explicação em detalhe: diferente de ler_linhas_planilha_erp (cabeçalho de
# 1 linha só, com colunas duplicadas) — aqui a linha 1 é o grupo (descartada),
# a linha 2 é o nome real da coluna, e não há coluna duplicada nesta
# planilha, então não precisa da lógica de resolução de ambiguidade.
def ler_linhas_planilha_impostos_saida(caminho):
    workbook = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    planilha = workbook.active

    linhas = planilha.iter_rows(values_only=True)
    next(linhas)  # linha 1 — grupo (ENTRADA/SAÍDA/ICMS SAÍDA POR UF DE DESTINO), não usada aqui
    cabecalho = next(linhas)  # linha 2 — nome real de cada coluna

    linhas_como_dicionario = []
    for linha_bruta in linhas:
        if all(valor is None for valor in linha_bruta):
            continue  # linha em branco no fim da planilha
        linhas_como_dicionario.append(dict(zip(cabecalho, linha_bruta)))

    workbook.close()
    return linhas_como_dicionario


# Função Objetivo: Normaliza o EAN lido da célula.
# Explicação em detalhe: mesma lógica já usada em
# preencher_cest_planilha_samvale.py — se o Excel converteu o código de
# barras pra número (perde o formato texto), remove o ".0" residual do
# float. Nunca faz padding de zero à esquerda: se um EAN perder zero à
# esquerda, é melhor não casar com nada (contabilizado como "sem produto
# correspondente") do que casar errado com outro produto.
def _normalizar_ean(valor):
    if valor is None:
        return None
    if isinstance(valor, float):
        texto = str(int(valor)) if valor.is_integer() else str(valor)
    else:
        texto = str(valor)
    texto = texto.strip()
    return texto or None


# Função Objetivo: Representa 1 linha da planilha, já convertida pros 4 campos desta camada.
class LinhaImpostoSaida:

    CAMPOS_PRODUTO = ['icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual']

    def __init__(self, linha_bruta, conversor):
        self.linha_bruta = linha_bruta
        self.conversor = conversor

        self.ean = None
        self.icms_saida_sp = None
        self.icms_saida_media = None
        self.pis_percentual = None
        self.cofins_percentual = None

    # Função Objetivo: Converte fração da planilha (ex: 0,1942) pra percentual cheio (ex: 19,42).
    # Explicação em detalhe: todas as fórmulas de precificação já dividem
    # esses campos por 100 (ex: icms_saida_media / 100) — guardar a fração
    # crua sem multiplicar geraria imposto 100x menor que o real. Campo
    # vazio vira 0, mesma convenção já usada nos 4 campos do Produto (nunca
    # None — os 4 campos são default=0, not-null).
    def _fracao_para_percentual(self, valor_coluna):
        fracao = self.conversor.para_decimal(valor_coluna, padrao=Decimal('0'))
        return (fracao * 100).quantize(DUAS_CASAS_DECIMAIS)

    def extrair_campos(self):
        self.ean = _normalizar_ean(self.linha_bruta.get(COLUNA_EAN))
        self.icms_saida_sp = self._fracao_para_percentual(self.linha_bruta.get(COLUNA_ICMS))
        self.icms_saida_media = self._fracao_para_percentual(self.linha_bruta.get(COLUNA_ICMS_MEDIA))
        self.pis_percentual = self._fracao_para_percentual(self.linha_bruta.get(COLUNA_PIS))
        self.cofins_percentual = self._fracao_para_percentual(self.linha_bruta.get(COLUNA_COFINS))
        return self

    # Função Objetivo: Diz se essa linha tem o dado mínimo pra casar com um Produto.
    def esta_valida(self):
        return bool(self.ean)

    # Função Objetivo: Devolve os campos prontos pra sobrescrever num Produto existente.
    def para_dict_produto(self):
        return dict(
            icms_saida_sp=self.icms_saida_sp,
            icms_saida_media=self.icms_saida_media,
            pis_percentual=self.pis_percentual,
            cofins_percentual=self.cofins_percentual,
        )


# Função Objetivo: Orquestra o preenchimento inteiro, da planilha Busca Legal ao banco.
class ImportadorImpostosSaida:

    # Função Objetivo: Resolve o caminho da planilha sozinho a partir da empresa ativa, se não vier explícito.
    def __init__(self, caminho_planilha=None):
        if caminho_planilha is None:
            empresa = obter_empresa_ativa()
            if empresa is None:
                raise RuntimeError(
                    'Nenhuma empresa ativa — rode este comando com --empresa=MAGAZINE '
                    'ou --empresa=SAMVALE.'
                )
            caminho_planilha = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]

        self.caminho_planilha = caminho_planilha

        self.produtos_por_ean = {}
        self.produtos_para_atualizar = []

        self.atualizados = 0
        self.sem_ean_na_planilha = 0
        self.eans_duplicados_na_planilha = 0
        self.sem_produto_correspondente = 0
        self.eans_sem_produto = []

        self.conversor = ConversorCelulaExcel(origem='openpyxl')

    # Função Objetivo: Carrega em memória os produtos já existentes, só com os campos que este comando toca.
    def carregar_produtos_existentes(self):
        self.produtos_por_ean = {
            produto.ean: produto
            for produto in Produto.objects.only(
                'id', 'ean', 'icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual',
            )
        }

    # Função Objetivo: Lê a planilha inteira e casa cada linha com o Produto correspondente.
    def processar_planilha(self):
        eans_ja_processados = set()

        for linha_bruta in ler_linhas_planilha_impostos_saida(self.caminho_planilha):
            linha = LinhaImpostoSaida(linha_bruta, self.conversor).extrair_campos()

            if not linha.esta_valida():
                self.sem_ean_na_planilha += 1
                continue

            if linha.ean in eans_ja_processados:
                self.eans_duplicados_na_planilha += 1
                continue
            eans_ja_processados.add(linha.ean)

            produto = self.produtos_por_ean.get(linha.ean)
            if produto is None:
                self.sem_produto_correspondente += 1
                self.eans_sem_produto.append(linha.ean)
                continue

            for campo, valor in linha.para_dict_produto().items():
                setattr(produto, campo, valor)
            self.produtos_para_atualizar.append(produto)
            self.atualizados += 1

    # Função Objetivo: Grava tudo no banco em lote, 1 única vez.
    def salvar(self):
        if self.produtos_para_atualizar:
            Produto.objects.bulk_update(
                self.produtos_para_atualizar, LinhaImpostoSaida.CAMPOS_PRODUTO, batch_size=BATCH_SIZE_PADRAO,
            )

    # Função Objetivo: Roda o preenchimento inteiro, da planilha ao banco.
    def rodar_preenchimento_completo(self):
        self.carregar_produtos_existentes()
        self.processar_planilha()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[IMPOSTOS DE SAÍDA] Concluído!\n'
            f'    Produtos atualizados: {self.atualizados}\n'
            f'    Linhas sem EAN na planilha (ignoradas): {self.sem_ean_na_planilha}\n'
            f'    EAN duplicado na planilha (mantida a 1ª ocorrência): {self.eans_duplicados_na_planilha}\n'
            f'    EAN da planilha sem produto correspondente no banco: {self.sem_produto_correspondente}'
        )


# Função Objetivo: Ponto de entrada chamado pelo Command.
def preencher_impostos_saida(stdout, style):
    stdout.write('[IMPOSTOS DE SAÍDA] Lendo planilha Busca Legal...')

    importador = ImportadorImpostosSaida().rodar_preenchimento_completo()

    stdout.write('')
    stdout.write(style.SUCCESS(importador.relatorio()))

    if importador.eans_sem_produto:
        stdout.write(style.WARNING(
            '\n[EAN DA PLANILHA SEM PRODUTO CORRESPONDENTE NO BANCO — CONFERIR]'
        ))
        for ean in importador.eans_sem_produto:
            stdout.write(style.WARNING(f'    {ean}'))