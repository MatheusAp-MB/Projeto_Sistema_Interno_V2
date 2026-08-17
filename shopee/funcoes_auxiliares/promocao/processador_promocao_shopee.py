# shopee/funcoes_auxiliares/promocao/processador_promocao_shopee.py

# Função Objetivo: Cruza o arquivo baixado da Shopee com os preços já calculados no
# sistema (GradePrecificacaoShopee), pra gerar os arquivos de subida de promoção prontos.
# Explicação em detalhe: 2 modos, igual ao TikTok. Modo Grade (padrão): o "preço de
# desconto" já vem pronto do banco (preco_de_exibicao="De", preco="Por"), esta classe só
# casa, categoriza e organiza. Modo Arquivo: usa o preço já correto na plataforma como
# referência + desconto manual — ver processar_modo_arquivo.

from dataclasses import dataclass
from decimal import Decimal
from core.funcoes_auxiliares.conversao_valores_externos import para_decimal_seguro, para_int_seguro

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
    # * [EXPLICAÇÃO] → "Por" final, sempre preenchido em categoria='pronto' — venha de
    #                  onde vier (grade.preco no modo Grade, ou calculado a partir do
    #                  arquivo + desconto no modo Arquivo). O gerador de Excel lê SÓ este
    #                  campo, nunca grade.preco direto — assim não precisa saber qual modo
    #                  gerou o resultado. Mesmo padrão do TikTok.
    preco_final: Decimal = None


# Função Objetivo: Calcula o "Por" a partir do preço já correto na plataforma + desconto manual.
# Explicação em detalhe: usada só no modo Arquivo — o preço de referência ("De") já é o que
# está na plataforma (o usuário confirmou 100% de confiança nele, precificado por fora do
# sistema), então não existe cálculo de margem/Grade aqui, só desconto direto. Mesma função
# do TikTok (processador_promocao_tiktok.py) — duplicada de propósito, cada app independente.
def calcular_preco_com_desconto(preco_referencia, desconto_percentual):
    fator = Decimal('1') - (desconto_percentual / Decimal('100'))
    return (preco_referencia * fator).quantize(Decimal('0.01'))


class ProcessadorPromocaoShopee:

    # Função Objetivo: Recebe as marcas, a margem, e o (cabeçalho, linhas) já lidos
    # de forma robusta (ver core/funcoes_auxiliares/leitor_planilha_robusto.py).
    def __init__(self, marcas_selecionadas, margem, cabecalho_arquivo, linhas_arquivo):
        self.marcas_selecionadas = list(marcas_selecionadas)
        self.margem = margem
        self.cabecalho_arquivo = cabecalho_arquivo
        self.linhas_arquivo_bruto = linhas_arquivo
        self.resultados = []

    # Função Objetivo: Converte as linhas brutas (já lidas) em LinhaArquivoShopee.
    def _ler_arquivo_shopee(self):
        indice_coluna = {nome: i for i, nome in enumerate(self.cabecalho_arquivo) if nome}

        linhas = []
        for row in self.linhas_arquivo_bruto:
            if not any(v is not None for v in row):
                continue

            preco = row[indice_coluna['Preço']]
            estoque = row[indice_coluna['Estoque do Vendedor']]

            linhas.append(LinhaArquivoShopee(
                id_produto=str(row[indice_coluna['ID do Produto']]),
                id_variacao=str(row[indice_coluna['Variante Identificador']]),
                sku_referencia=str(row[indice_coluna['SKU de referência']]) if row[indice_coluna['SKU de referência']] else None,
                sku=str(row[indice_coluna['SKU']]) if row[indice_coluna['SKU']] else None,
                preco_atual=para_decimal_seguro(preco),
                estoque_plataforma=para_int_seguro(estoque),
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
                linha_arquivo=linha_arquivo, grade=grade, preco_final=grade.preco,
            ))

        return self

    # Função Objetivo: Modo alternativo — usa o preço já correto na plataforma (arquivo)
    # como referência, em vez da Grade do sistema.
    # Explicação em detalhe: usuário confirmou 100% de confiança no preço do arquivo (foi
    # precificado por fora do sistema) — por isso este modo NÃO verifica Grade, NÃO verifica
    # estoque, e NÃO bloqueia por divergência nenhuma. Só existe 1 caso que impede gerar
    # linha: o produto do catálogo simplesmente não aparece no arquivo. Método separado, não
    # mexe em processar() — o modo Grade continua 100% intocado. Mesmo padrão do TikTok
    # (processador_promocao_tiktok.py::processar_modo_arquivo).
    def processar_modo_arquivo(self, desconto_percentual):
        from produtos.models import Produto

        linhas_arquivo = self._ler_arquivo_shopee()
        indice_arquivo = self._montar_indice_por_sku(linhas_arquivo)

        produtos = Produto.objects.filter(marca__in=self.marcas_selecionadas)

        for produto in produtos:
            linha_arquivo = indice_arquivo.get(produto.sku)

            if linha_arquivo is None:
                self.resultados.append(ResultadoProduto(
                    categoria='nao_encontrado', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, estoque_sistema=produto.estoque,
                ))
                continue

            preco_final = calcular_preco_com_desconto(linha_arquivo.preco_atual, desconto_percentual)

            self.resultados.append(ResultadoProduto(
                categoria='pronto', sku=produto.sku, titulo=produto.titulo,
                marca=produto.marca, estoque_sistema=produto.estoque,
                linha_arquivo=linha_arquivo, preco_final=preco_final,
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