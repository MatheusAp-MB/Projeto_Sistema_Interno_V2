# impostos/funcoes_auxiliares/preenchimento_cst_produtos.py

# Função Objetivo: Lê CST da planilha Busca Legal, grava só Produto.cst_saida
# — Passo 1 do fluxo de 4 comandos auto-suficientes (decisão no vault,
# 13/09/2026: "Fluxo de Impostos de Saida Passa a 4 Comandos Auto-Suficientes,
# CST Isolado em Comando Proprio Como Fonte Unica"). A partir de agora, esta é
# a ÚNICA rotina do sistema que lê a coluna CST da planilha — os outros
# comandos (importar_icms_por_ncm, importar_pis_cofins_por_ncm_cst) passam a
# ler Produto.cst_saida, gravado aqui, em vez de reparsear a planilha cada um
# por conta própria (mesmo padrão que origem_mercadoria_cadastro já usa hoje).
#
# ATENÇÃO (transitório): até a Etapa 5 do roteiro (preencher_impostos_saida
# parar de ler a planilha) rodar, preenchimento_impostos_saida.py continua com
# sua própria leitura de CST (carregar_cst_da_planilha) — as 2 rotinas
# convivem lendo a mesma coluna, gravando o mesmo valor. Redundante, não
# incorreto; será removido na Etapa 5.
#
# Leitura/normalização de planilha duplicada de propósito a partir de
# preenchimento_impostos_saida.py — mesmo padrão já usado no resto do projeto
# (_normalizar_codigo_celula já está duplicada em importacao_icms_ncm.py,
# importacao_pis_cofins_ncm_cst.py e preenchimento_impostos_saida.py), pra
# cada módulo de comando ficar autocontido.
#
# Regra de fallback (igual à já usada pra cst_saida antes desta decisão): EAN
# fora da planilha nesta rodada não tem o campo tocado, mantém o valor antigo.

import shutil

import openpyxl
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.empresa import obter_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from produtos.models import Produto

CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Arquivos usados para Popular Banco/Impostos Saida/TABELA SAIDA POR UF MAGAZINE.xlsx',
    EMPRESA_SAMVALE: 'Arquivos usados para Popular Banco/Impostos Saida/TABELA SAIDA POR UF SAMVALE.xlsx',
}

COLUNA_EAN = 'Cód Barras'
COLUNA_CST = 'CST'  # mesma coluna que os outros 2 comandos liam antes desta decisão


# Função Objetivo: Lê a planilha Busca Legal (cabeçalho de 2 linhas), devolvendo 1 dicionário por linha de dado.
# Explicação em detalhe: duplicada de preenchimento_impostos_saida.py — linha
# 1 é o grupo (descartada), linha 2 é o nome real da coluna.
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


# Função Objetivo: Normaliza um código textual (EAN, CST) lido da célula.
# Explicação em detalhe: duplicada de preenchimento_impostos_saida.py — se o
# Excel converteu o código pra número (perde o formato texto), remove o ".0"
# residual do float. Nunca faz padding de zero à esquerda: melhor não casar
# com nada (sem correspondência) do que casar errado.
def _normalizar_codigo_celula(valor):
    if valor is None:
        return None
    if isinstance(valor, float):
        texto = str(int(valor)) if valor.is_integer() else str(valor)
    else:
        texto = str(valor)
    texto = texto.strip()
    return texto or None


# Função Objetivo: Orquestra o preenchimento de Produto.cst_saida a partir da
# planilha Busca Legal — único campo tocado por este comando.
class PreenchedorCstProdutos:

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

    # Função Objetivo: Carrega em memória os produtos já existentes, só com id/ean/cst_saida.
    def carregar_produtos_existentes(self):
        self.produtos_por_ean = {
            produto.ean: produto
            for produto in Produto.objects.only('id', 'ean', 'cst_saida')
        }

    # Função Objetivo: Lê a planilha linha a linha e atualiza cst_saida em memória — quem tem
    # linha nesta rodada, com CST preenchido, tem o campo sobrescrito; quem não tem, fica intocado.
    def processar_planilha(self):
        eans_ja_processados = set()

        for linha_bruta in ler_linhas_planilha_impostos_saida(self.caminho_planilha):
            ean = _normalizar_codigo_celula(linha_bruta.get(COLUNA_EAN))
            cst = _normalizar_codigo_celula(linha_bruta.get(COLUNA_CST))

            if not ean:
                self.sem_ean_na_planilha += 1
                continue

            if ean in eans_ja_processados:
                self.eans_duplicados_na_planilha += 1
                continue
            eans_ja_processados.add(ean)

            if ean not in self.produtos_por_ean:
                self.sem_produto_correspondente += 1
                self.eans_sem_produto.append(ean)
                continue

            if cst is None:
                continue  # planilha trouxe a linha mas sem CST — não toca no produto

            produto = self.produtos_por_ean[ean]
            produto.cst_saida = cst
            self.produtos_para_atualizar.append(produto)
            self.atualizados += 1

    # Função Objetivo: Grava tudo no banco em lote, 1 única vez.
    def salvar(self):
        if self.produtos_para_atualizar:
            Produto.objects.bulk_update(self.produtos_para_atualizar, ['cst_saida'], batch_size=BATCH_SIZE_PADRAO)

    # Função Objetivo: Roda o preenchimento inteiro — planilha até o banco.
    def rodar(self):
        self.carregar_produtos_existentes()
        self.processar_planilha()
        self.salvar()
        return self


# Função Objetivo: Cria o Console com 1 coluna de margem abaixo da largura
# detectada do terminal (duplicada de importacao_icms_ncm.py/
# preenchimento_impostos_saida.py — mesmo motivo: cada módulo autocontido).
def _console_com_margem():
    largura_detectada = shutil.get_terminal_size(fallback=(80, 24)).columns
    return Console(width=max(largura_detectada - 1, 20))


# Função Objetivo: Ponto de entrada chamado pelo Command.
def preencher_cst_produtos(stdout, style):
    console = _console_com_margem()

    console.print('[bold]CST dos Produtos[/bold] — lendo planilha Busca Legal...')

    preenchedor = PreenchedorCstProdutos().rodar()

    tabela = Table(title='CST dos Produtos — Resultado')
    tabela.add_column('Métrica')
    tabela.add_column('Quantidade', justify='right')
    tabela.add_row('Produtos com cst_saida atualizado nesta rodada', str(preenchedor.atualizados))
    tabela.add_row('Linhas sem EAN na planilha (ignoradas)', str(preenchedor.sem_ean_na_planilha))
    tabela.add_row(
        'EAN duplicado na planilha (mantida a 1ª ocorrência)', str(preenchedor.eans_duplicados_na_planilha),
    )
    tabela.add_row(
        'EAN da planilha sem produto correspondente no banco', str(preenchedor.sem_produto_correspondente),
        style='yellow' if preenchedor.sem_produto_correspondente else None,
    )
    console.print()
    console.print(tabela)

    console.print()
    console.print(Panel(
        f'[bold]Produtos com cst_saida atualizado nesta rodada:[/bold] {preenchedor.atualizados}',
        title='CST dos Produtos — Concluído',
        border_style='green',
    ))

    if preenchedor.eans_sem_produto:
        console.print()
        console.print(Panel(
            Columns(preenchedor.eans_sem_produto, equal=True, expand=True),
            title=(
                f'{len(preenchedor.eans_sem_produto)} EAN(s) da planilha sem Produto '
                f'correspondente no banco — conferir'
            ),
            border_style='yellow',
        ))

    stdout.write(style.SUCCESS(
        f'[CST DOS PRODUTOS] Concluído — {preenchedor.atualizados} produto(s) com cst_saida '
        f'atualizado nesta rodada.'
    ))