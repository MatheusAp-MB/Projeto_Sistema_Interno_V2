# tiktok/funcoes_auxiliares/promocao/processador_promocao_tiktok.py

# Função Objetivo: Cruza o arquivo baixado do TikTok Shop com os preços já calculados
# (GradePrecificacaoTiktok), pra gerar os arquivos de subida de promoção prontos.
# Explicação em detalhe: diferente da Shopee, o TikTok usa 2 SKUs por produto na
# plataforma — o SKU real (Com Afiliado) e o mesmo SKU com "1" na frente (Sem Afiliado).
# Essa associação existe SÓ na plataforma, não no nosso banco — por isso o casamento
# tenta o SKU direto primeiro, e só tenta remover o "1" se não achar.

from dataclasses import dataclass
from decimal import Decimal
from core.funcoes_auxiliares.conversao_valores_externos import para_decimal_seguro, para_int_seguro

TOLERANCIA_CENTAVOS = Decimal('0.05')


@dataclass
class LinhaArquivoTiktok:
    product_id: str
    sku_id: str
    seller_sku: str
    preco_atual: Decimal
    estoque_plataforma: int


@dataclass
class ResultadoProdutoTiktok:
    categoria: str  # 'pronto' | 'divergente' | 'novo' | 'nao_encontrado' | 'estoque_inconsistente'
    sku: str
    titulo: str
    marca: str
    tipo: str  # 'sem_afiliado' | 'com_afiliado' — só None quando categoria='nao_encontrado'
    estoque_sistema: int
    linha_arquivo: object = None
    grade: object = None
    # * [EXPLICAÇÃO] → "Por" final, sempre preenchido em categoria='pronto' — venha de
    #                  onde vier (grade.preco no modo Grade, ou calculado a partir do
    #                  arquivo + desconto no modo Arquivo). O gerador de Excel lê SÓ este
    #                  campo, nunca grade.preco direto — assim não precisa saber qual modo
    #                  gerou o resultado.
    preco_final: Decimal = None


# Função Objetivo: Calcula o "Por" a partir do preço já correto na plataforma + desconto manual.
# Explicação em detalhe: usada só no modo Arquivo — o preço de referência ("De") já é o que
# está na plataforma (o usuário confirmou 100% de confiança nele, precificado por fora do
# sistema), então não existe cálculo de margem/Grade aqui, só desconto direto.
def calcular_preco_com_desconto(preco_referencia, desconto_percentual):
    fator = Decimal('1') - (desconto_percentual / Decimal('100'))
    return (preco_referencia * fator).quantize(Decimal('0.01'))


class ProcessadorPromocaoTiktok:

    # Função Objetivo: Recebe as marcas, 1 margem POR TIPO, e o (cabeçalho, linhas)
    # já lidos de forma robusta (ver core/funcoes_auxiliares/leitor_planilha_robusto.py).
    def __init__(self, marcas_selecionadas, margem_sem_afiliado, margem_com_afiliado, cabecalho_arquivo, linhas_arquivo):
        self.marcas_selecionadas = list(marcas_selecionadas)
        self.margem_por_tipo = {
            'sem_afiliado': margem_sem_afiliado,
            'com_afiliado': margem_com_afiliado,
        }
        self.cabecalho_arquivo = cabecalho_arquivo
        self.linhas_arquivo_bruto = linhas_arquivo
        self.resultados = []

    def _ler_arquivo_tiktok(self):
        indice_coluna = {nome: i for i, nome in enumerate(self.cabecalho_arquivo) if nome}

        linhas = []
        for row in self.linhas_arquivo_bruto:
            if not any(v is not None for v in row):
                continue

            preco = row[indice_coluna['Preço de varejo (moeda local)']]
            estoque = row[indice_coluna['Quantidade']]
            seller_sku = row[indice_coluna['SKU do vendedor']]

            if not seller_sku:
                continue

            linhas.append(LinhaArquivoTiktok(
                product_id=str(row[indice_coluna['ID do produto']]),
                sku_id=str(row[indice_coluna['ID do SKU']]),
                seller_sku=str(seller_sku),
                preco_atual=para_decimal_seguro(preco),
                estoque_plataforma=para_int_seguro(estoque),
            ))
        return linhas

    # Função Objetivo: Monta {seller_sku: linha}, direto — 1 linha por SKU da plataforma.
    def _montar_indice_por_seller_sku(self, linhas):
        return {linha.seller_sku: linha for linha in linhas}

    # Função Objetivo: Acha a linha do arquivo pro SKU real do produto, testando os 2 tipos.
    # Explicação em detalhe: tenta o SKU direto (Com Afiliado) primeiro; se não achar,
    # tenta "1" + SKU (Sem Afiliado). Confirmado pelo usuário — a associação é sempre
    # nessa ordem, "1" na frente é sempre Sem Afiliado.
    def _buscar_linha_e_tipo(self, sku_produto, indice_arquivo):
        linha_com_afiliado = indice_arquivo.get(sku_produto)
        if linha_com_afiliado:
            return linha_com_afiliado, 'com_afiliado'

        linha_sem_afiliado = indice_arquivo.get(f'1{sku_produto}')
        if linha_sem_afiliado:
            return linha_sem_afiliado, 'sem_afiliado'

        return None, None

    def processar(self):
        from produtos.models import Produto
        from precificacao.models import GradePrecificacaoTiktok

        linhas_arquivo = self._ler_arquivo_tiktok()
        indice_arquivo = self._montar_indice_por_seller_sku(linhas_arquivo)

        produtos = Produto.objects.filter(marca__in=self.marcas_selecionadas)
        grades = {
            (g.produto_id, g.tipo): g for g in
            GradePrecificacaoTiktok.objects.filter(
                produto__marca__in=self.marcas_selecionadas,
                margem__in=set(self.margem_por_tipo.values()),
            )
            if g.margem == self.margem_por_tipo[g.tipo]
        }

        for produto in produtos:
            linha_arquivo, tipo = self._buscar_linha_e_tipo(produto.sku, indice_arquivo)

            if linha_arquivo is None:
                self.resultados.append(ResultadoProdutoTiktok(
                    categoria='nao_encontrado', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, tipo=None, estoque_sistema=produto.estoque,
                ))
                continue

            grade = grades.get((produto.id, tipo))

            if grade is None or grade.preco is None:
                self.resultados.append(ResultadoProdutoTiktok(
                    categoria='novo', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, tipo=tipo, estoque_sistema=produto.estoque,
                    linha_arquivo=linha_arquivo,
                ))
                continue

            preco_atual = linha_arquivo.preco_atual or Decimal('0')
            diferenca = abs(preco_atual - grade.preco_de_exibicao)
            if diferenca > TOLERANCIA_CENTAVOS:
                self.resultados.append(ResultadoProdutoTiktok(
                    categoria='divergente', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, tipo=tipo, estoque_sistema=produto.estoque,
                    linha_arquivo=linha_arquivo, grade=grade,
                ))
                continue

            estoque_bate = (produto.estoque > 0) == (linha_arquivo.estoque_plataforma > 0)
            if not estoque_bate:
                self.resultados.append(ResultadoProdutoTiktok(
                    categoria='estoque_inconsistente', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, tipo=tipo, estoque_sistema=produto.estoque,
                    linha_arquivo=linha_arquivo, grade=grade,
                ))
                continue

            self.resultados.append(ResultadoProdutoTiktok(
                categoria='pronto', sku=produto.sku, titulo=produto.titulo,
                marca=produto.marca, tipo=tipo, estoque_sistema=produto.estoque,
                linha_arquivo=linha_arquivo, grade=grade, preco_final=grade.preco,
            ))

        return self

    # Função Objetivo: Modo alternativo — usa o preço já correto na plataforma (arquivo)
    # como referência, em vez da Grade do sistema.
    # Explicação em detalhe: usuário confirmou 100% de confiança no preço do arquivo (foi
    # precificado por fora do sistema) — por isso este modo NÃO verifica Grade, NÃO verifica
    # estoque, e NÃO bloqueia por divergência nenhuma. Só existe 1 caso que impede gerar
    # linha: o produto do catálogo simplesmente não aparece no arquivo (não tem o que gerar,
    # não é uma trava que dá pra tirar). Método separado, não mexe em processar() — o modo
    # Grade continua 100% intocado.
    def processar_modo_arquivo(self, desconto_percentual):
        linhas_arquivo = self._ler_arquivo_tiktok()
        indice_arquivo = self._montar_indice_por_seller_sku(linhas_arquivo)

        from produtos.models import Produto
        produtos = Produto.objects.filter(marca__in=self.marcas_selecionadas)

        for produto in produtos:
            linha_arquivo, tipo = self._buscar_linha_e_tipo(produto.sku, indice_arquivo)

            if linha_arquivo is None:
                self.resultados.append(ResultadoProdutoTiktok(
                    categoria='nao_encontrado', sku=produto.sku, titulo=produto.titulo,
                    marca=produto.marca, tipo=None, estoque_sistema=produto.estoque,
                ))
                continue

            preco_final = calcular_preco_com_desconto(linha_arquivo.preco_atual, desconto_percentual)

            self.resultados.append(ResultadoProdutoTiktok(
                categoria='pronto', sku=produto.sku, titulo=produto.titulo,
                marca=produto.marca, tipo=tipo, estoque_sistema=produto.estoque,
                linha_arquivo=linha_arquivo, preco_final=preco_final,
            ))

        return self

    def resumo_geral(self):
        contagem = {'pronto': 0, 'divergente': 0, 'novo': 0, 'nao_encontrado': 0, 'estoque_inconsistente': 0}
        for r in self.resultados:
            contagem[r.categoria] += 1
        return contagem

    def resultados_por_marca(self, marca):
        return [r for r in self.resultados if r.marca == marca]

    def marcas_com_resultado(self):
        return sorted({r.marca for r in self.resultados})