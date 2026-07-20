# shopee/funcoes_auxiliares/promocao/processador_promocao_shopee.py

# Função Objetivo: Cruza o arquivo baixado da Shopee com os preços já calculados no
# sistema (GradePrecificacaoShopee), pra gerar os arquivos de subida de promoção prontos.
# Explicação em detalhe: diferente do script Python externo, o "preço de desconto" NÃO é
# calculado aqui — já vem pronto do banco (preco_de_exibicao="De", preco="Por"). Esta
# classe só casa, categoriza e organiza.

from dataclasses import dataclass
from decimal import Decimal

TOLERANCIA_CENTAVOS = Decimal('0.05')


@dataclass
class LinhaArquivoShopee:
    id_produto: str
    id_variacao: str
    sku_referencia: str
    sku: str
    preco_atual: Decimal
    estoque_plataforma: int


@dataclass
class ResultadoProduto:
    categoria: str  # 'pronto' | 'divergente' | 'novo' | 'nao_encontrado' | 'estoque_inconsistente'
    sku: str
    titulo: str
    marca: str
    estoque_sistema: int
    linha_arquivo: object = None
    grade: object = None


class ProcessadorPromocaoShopee:

    # Função Objetivo: Recebe as marcas escolhidas, a margem de referência e o workbook já aberto.
    def __init__(self, marcas_selecionadas, margem, workbook_shopee):
        self.marcas_selecionadas = list(marcas_selecionadas)
        self.margem = margem
        self.workbook_shopee = workbook_shopee
        self.resultados = []

    # Função Objetivo: Lê o arquivo da Shopee, linha a linha, pelos nomes de coluna.
    def _ler_arquivo_shopee(self):
        ws = self.workbook_shopee.active
        cabecalho = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        indice_coluna = {nome: i for i, nome in enumerate(cabecalho) if nome}

        linhas = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(v is not None for v in row):
                continue

            preco = row[indice_coluna['Preço']]
            estoque = row[indice_coluna['Estoque do Vendedor']]

            linhas.append(LinhaArquivoShopee(
                id_produto=str(row[indice_coluna['ID do Produto']]),
                id_variacao=str(row[indice_coluna['Variante Identificador']]),
                sku_referencia=str(row[indice_coluna['SKU de referência']]) if row[indice_coluna['SKU de referência']] else None,
                sku=str(row[indice_coluna['SKU']]) if row[indice_coluna['SKU']] else None,
                preco_atual=Decimal(str(preco)) if preco is not None else None,
                estoque_plataforma=int(estoque) if estoque is not None else 0,
            ))
        return linhas

    # Função Objetivo: Monta {sku_do_produto: linha}, com fallback pra SKU de referência.
    def _montar_indice_por_sku(self, linhas):
        indice = {}
        for linha in linhas:
            if linha.sku:
                indice[linha.sku] = linha
        for linha in linhas:
            if linha.sku_referencia and linha.sku_referencia not in indice:
                indice[linha.sku_referencia] = linha
        return indice

    # Função Objetivo: Roda o cruzamento inteiro, categorizando cada produto.
    def processar(self):
        from produtos.models import Produto
        from precificacao.models import GradePrecificacaoShopee

        linhas_arquivo = self._ler_arquivo_shopee()
        indice_arquivo = self._montar_indice_por_sku(linhas_arquivo)

        produtos = Produto.objects.filter(marca__in=self.marcas_selecionadas)
        grades = {
            g.produto_id: g for g in
            GradePrecificacaoShopee.objects.filter(
                margem=self.margem, produto__marca__in=self.marcas_selecionadas,
            )
        }

        for produto in produtos:
            linha_arquivo = indice_arquivo.get(produto.sku)
            grade = grades.get(produto.id)

            if linha_arquivo is None:
                self.resultados.append(ResultadoProduto(
                    categoria='nao_encontrado', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, estoque_sistema=produto.estoque,
                ))
                continue

            if grade is None or grade.preco is None:
                self.resultados.append(ResultadoProduto(
                    categoria='novo', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, estoque_sistema=produto.estoque,
                    linha_arquivo=linha_arquivo,
                ))
                continue

            preco_atual = linha_arquivo.preco_atual or Decimal('0')
            diferenca = abs(preco_atual - grade.preco_de_exibicao)
            if diferenca > TOLERANCIA_CENTAVOS:
                self.resultados.append(ResultadoProduto(
                    categoria='divergente', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, estoque_sistema=produto.estoque,
                    linha_arquivo=linha_arquivo, grade=grade,
                ))
                continue

            # * [EXPLICAÇÃO] → Comparação BINÁRIA (tem estoque vs não tem),
            #                  não quantidade exata — decisão minha, ainda
            #                  não confirmada com o usuário (quantidade
            #                  exata sempre oscila entre a extração do
            #                  arquivo e o momento do upload).
            estoque_bate = (produto.estoque > 0) == (linha_arquivo.estoque_plataforma > 0)
            if not estoque_bate:
                self.resultados.append(ResultadoProduto(
                    categoria='estoque_inconsistente', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, estoque_sistema=produto.estoque,
                    linha_arquivo=linha_arquivo, grade=grade,
                ))
                continue

            self.resultados.append(ResultadoProduto(
                categoria='pronto', sku=produto.sku, titulo=produto.titulo,
                marca=produto.marca, estoque_sistema=produto.estoque,
                linha_arquivo=linha_arquivo, grade=grade,
            ))

        return self

    # Função Objetivo: Devolve a contagem por categoria, pra tela de resumo.
    def resumo_geral(self):
        contagem = {'pronto': 0, 'divergente': 0, 'novo': 0, 'nao_encontrado': 0, 'estoque_inconsistente': 0}
        for r in self.resultados:
            contagem[r.categoria] += 1
        return contagem

    # Função Objetivo: Devolve só os resultados de 1 marca.
    def resultados_por_marca(self, marca):
        return [r for r in self.resultados if r.marca == marca]

    # Função Objetivo: Devolve as marcas que realmente tiveram algum produto processado.
    def marcas_com_resultado(self):
        return sorted({r.marca for r in self.resultados})