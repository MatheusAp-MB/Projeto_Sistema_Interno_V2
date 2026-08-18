# core/management/commands/popular_banco_suporte/importar_produtos_erp.py

# Função Objetivo: Popula e enriquece Produto — direto do ERP, sem
# intermediário nenhum.
# Explicação em detalhe: até 15/08, este comando criava o Produto a partir
# do JSON do Mercado Livre e só depois enriquecia com o ERP — na prática,
# era o marketplace que decidia quais produtos existiam no sistema. Isso
# foi identificado como incorreto: o ERP é a única fonte da verdade sobre
# quais produtos existem (ver decisão "Produto Nasce Exclusivamente do ERP"
# no vault) — um produto só existe aqui porque está cadastrado no ERP,
# nunca porque apareceu num anúncio de marketplace.
#
# Lê os 2 relatórios de cadastro do ERP (Ativos + Inativos — juntos, são
# 100% do cadastro de produtos da empresa) e cria/atualiza Produto
# diretamente a partir deles. O status ativo/inativo vem da coluna real
# "Inativo" de cada linha (nunca do nome do arquivo) — ver campo
# `Produto.ativo_no_erp`.
#
# Reescrito em POO (16/07, unificado 15/08) — 2 classes:
#   LinhaProdutoERP     → 1 linha de qualquer um dos 2 relatórios do ERP
#   ImportadorProdutos  → o processo inteiro, dos 2 arquivos ao banco

from decimal import Decimal
from produtos.models import Produto
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from core.management.commands.popular_banco_suporte.parser_data import ParserData
from core.management.commands.popular_banco_suporte.leitor_planilha_erp import ler_linhas_planilha_erp
from core.empresa import obter_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE

# * [EXPLICAÇÃO] → Fim do comentar/descomentar manual (17/08/2026) — o
#                  caminho certo agora é resolvido sozinho a partir da
#                  empresa ativa (sessão web ou --empresa no terminal).
CAMINHOS_ERP_POR_EMPRESA = {
    EMPRESA_MAGAZINE: {
        'ativos': 'Arquivos usados para Popular Banco/Produtos ERP/Relatorio_Todos_Produtos_Ativos_Tela_Cadastro_Produtos_ERP_MB.xlsx',
        'inativos': 'Arquivos usados para Popular Banco/Produtos ERP/Relatorio_Todos_Produtos_Inativos_Tela_Cadastro_Produtos_ERP_MB.xlsx',
    },
    EMPRESA_SAMVALE: {
        'ativos': 'Arquivos usados para Popular Banco/Produtos ERP/Relatorio_Todos_Produtos_Ativos_Tela_Cadastro_Produtos_ERP_SV.xlsx',
        'inativos': 'Arquivos usados para Popular Banco/Produtos ERP/Relatorio_Todos_Produtos_Inativos_Tela_Cadastro_Produtos_ERP_SV.xlsx',
    },
}


FATOR_PESO_CUBADO = Decimal('6000')
LIMITE_DIMENSAO_CM = Decimal('9999.99')
LIMITE_PESO_CUBADO_KG = Decimal('99999.999')


# Função Objetivo: Representa 1 linha de um dos relatórios do ERP, já validada.
class LinhaProdutoERP:

    # * [EXPLICAÇÃO] → Lista os nomes de campo como CONSTANTE da classe —
    #                  evita instanciar um objeto "vazio" só pra descobrir
    #                  as chaves (frágil: quebra se algum método interno
    #                  tentar ler dado real de um objeto sem dado nenhum).
    CAMPOS_PRODUTO = [
        'titulo', 'cod_fabricante', 'categoria', 'marca', 'ncm', 'estoque', 'custo',
        'ativo_no_erp',
        'peso_produto_sem_embalar', 'altura_produto_sem_embalar', 'largura_produto_sem_embalar',
        'comprimento_produto_sem_embalar', 'peso_produto_apos_embalado', 'altura_produto_apos_embalado',
        'largura_produto_apos_embalado', 'comprimento_produto_apos_embalado', 'peso_cubado',
        'imagem_url', 'ultima_compra', 'cadastrado_erp_em',
    ]

    # Função Objetivo: Recebe a linha (dict) já lida por ler_linhas_planilha_erp, o conversor e o parser de data.
    def __init__(self, linha_bruta, conversor, parser_data):
        self.linha_bruta = linha_bruta
        self.conversor = conversor
        self.parser_data = parser_data

        self.sku = None
        self.ean = None
        self.titulo = None
        self.cod_fabricante = None
        self.categoria = None
        self.marca = None
        self.ncm = None
        self.estoque = None
        self.custo = None
        self.ativo_no_erp = None
        self.imagem_url = None
        self.ultima_compra = None
        self.cadastrado_erp_em = None

        self.altura_sem_embalar = None
        self.largura_sem_embalar = None
        self.comprimento_sem_embalar = None
        self.peso_sem_embalar = None

        self.altura_embalagem = None
        self.largura_embalagem = None
        self.comprimento_embalagem = None
        self.peso_embalagem = None

        self.peso_cubado = None
        self.erro_dimensao = None

    # Função Objetivo: Extrai SKU, EAN, título, status ativo/inativo e os demais campos simples.
    def extrair_campos_basicos(self):
        self.sku = self.conversor.para_texto(self.linha_bruta.get('Codigo Auxiliar'))
        self.ean = self.conversor.para_texto(self.linha_bruta.get('Codigo de Barras'))
        # * [EXPLICAÇÃO] → Cadeia de fallback: "Detalhes do Produto" → SKU → EAN.
        #                  titulo é NOT NULL no banco (Produto.titulo), diferente do
        #                  SKU (opcional) — sem esse último elo, uma linha com "Detalhes
        #                  do Produto" E "Codigo Auxiliar" em branco ao mesmo tempo (visto
        #                  em dado real da Samvale, 17/08/2026) gera titulo=None e quebra
        #                  o bulk_create inteiro (até 100 produtos por lote,
        #                  BATCH_SIZE_PADRAO). EAN é garantido não-vazio aqui —
        #                  esta_valida() já descarta qualquer linha sem EAN antes de
        #                  chegar no banco.
        self.titulo = self.conversor.para_texto(
            self.linha_bruta.get('Detalhes do Produto'), self.sku or self.ean
        )
        self.cod_fabricante = self.conversor.para_texto(self.linha_bruta.get('Codigo do Fabricante'))
        self.categoria = self.conversor.para_texto(self.linha_bruta.get('Categoria'))
        self.marca = self.conversor.para_texto(self.linha_bruta.get('Marca'))
        self.ncm = self.conversor.para_texto(self.linha_bruta.get('ncm'))
        self.estoque = int(self.conversor.para_decimal(self.linha_bruta.get('Estoque'), padrao=0))
        self.custo = self.conversor.para_decimal(self.linha_bruta.get('Custo'), padrao=0)
        self.ativo_no_erp = self._extrair_ativo_no_erp()
        self.imagem_url = self.conversor.para_texto(self.linha_bruta.get('URL 1'))
        self.ultima_compra = self.parser_data.parsear(self.linha_bruta.get('Ultima Compra'))
        self.cadastrado_erp_em = self.parser_data.parsear(self.linha_bruta.get('dt_cadastro'))

    # Função Objetivo: Traduz a coluna real "Inativo" do ERP pro campo positivo `ativo_no_erp`.
    # Explicação em detalhe: convenção confirmada na planilha real — 'T' = inativo,
    # 'F' = ativo (mesma convenção de outras colunas booleanas do ERP, tipo
    # "disponivel"/"utiliza_os"). Invertido de propósito: o campo do sistema
    # é positivo (ativo_no_erp), não o duplo-negativo do ERP.
    def _extrair_ativo_no_erp(self):
        valor_inativo = self.linha_bruta.get('Inativo')
        return str(valor_inativo).strip().upper() != 'T'

    # Função Objetivo: Extrai altura/largura/comprimento/peso do produto puro.
    # Explicação em detalhe: o ERP entrega em metros (confirmado) — converte
    # aqui pra centímetros (×100), padrão único do sistema.
    def extrair_dimensoes_sem_embalar(self):
        self.altura_sem_embalar = self.conversor.para_decimal(self.linha_bruta.get('Altura'), padrao=0) * 100
        self.largura_sem_embalar = self.conversor.para_decimal(self.linha_bruta.get('Largura'), padrao=0) * 100
        self.comprimento_sem_embalar = self.conversor.para_decimal(self.linha_bruta.get('Comprimento'), padrao=0) * 100
        self.peso_sem_embalar = self.conversor.para_decimal(self.linha_bruta.get('Peso Bruto'), padrao=0)

    # Função Objetivo: Extrai altura/largura/comprimento/peso da embalagem.
    # Explicação em detalhe: mesma conversão m→cm, nas colunas "Embalagem *"
    # (inclui "Emablagem Peso" — erro de digitação real, confirmado, existente
    # na própria planilha do ERP). None quando a embalagem não foi cadastrada
    # ainda pra esse produto — nunca vira 0 disfarçado.
    def extrair_dimensoes_embalagem(self):
        altura = self.conversor.para_decimal(self.linha_bruta.get('Embalagem Altura'))
        largura = self.conversor.para_decimal(self.linha_bruta.get('Embalagem Largura'))
        comprimento = self.conversor.para_decimal(self.linha_bruta.get('Embalagem Comprimento'))
        peso = self.conversor.para_decimal(self.linha_bruta.get('Emablagem Peso'))

        self.altura_embalagem = altura * 100 if altura is not None else None
        self.largura_embalagem = largura * 100 if largura is not None else None
        self.comprimento_embalagem = comprimento * 100 if comprimento is not None else None
        self.peso_embalagem = peso

    # Função Objetivo: Detecta dimensão fisicamente absurda e marca o erro.
    # Explicação em detalhe: nunca corrige o valor sozinha — só marca
    # self.erro_dimensao e zera os 3 eixos da embalagem, pro usuário corrigir
    # na fonte (ERP). Limite: nenhuma embalagem real chega perto de 100m.
    def validar_dimensoes(self):
        dimensoes_com_erro = []
        for nome, valor in [
            ('altura da embalagem', self.altura_embalagem),
            ('comprimento da embalagem', self.comprimento_embalagem),
            ('largura da embalagem', self.largura_embalagem),
        ]:
            if valor is not None and valor > LIMITE_DIMENSAO_CM:
                dimensoes_com_erro.append(f'{nome}={valor}')

        if dimensoes_com_erro:
            self.erro_dimensao = f'SKU {self.sku}: {", ".join(dimensoes_com_erro)}'
            self.altura_embalagem = None
            self.largura_embalagem = None
            self.comprimento_embalagem = None

    # Função Objetivo: Calcula o peso cúbico a partir da embalagem.
    # Explicação em detalhe: fórmula padrão internacional de transportadoras
    # — (altura×largura×comprimento) ÷ 6000, sempre em centímetros. Também
    # protege contra o RESULTADO estourar o limite do campo, mesmo quando
    # cada dimensão individual pareceu razoável sozinha.
    def calcular_peso_cubado(self):
        tem_embalagem_completa = (
            self.altura_embalagem is not None
            and self.largura_embalagem is not None
            and self.comprimento_embalagem is not None
        )
        if not tem_embalagem_completa:
            return

        peso_cubado_calculado = (
            self.altura_embalagem * self.largura_embalagem * self.comprimento_embalagem
        ) / FATOR_PESO_CUBADO

        if peso_cubado_calculado <= LIMITE_PESO_CUBADO_KG:
            self.peso_cubado = peso_cubado_calculado
        else:
            self.erro_dimensao = (
                f'SKU {self.sku}: peso_cubado calculado ({peso_cubado_calculado:.0f}kg) a partir de '
                f'{self.altura_embalagem}×{self.largura_embalagem}×{self.comprimento_embalagem} cm '
                f'é fisicamente absurdo — verificar embalagem no ERP.'
            )

    # Função Objetivo: Roda todos os passos acima, na ordem certa.
    def transformar_linha_em_produto(self):
        self.extrair_campos_basicos()
        self.extrair_dimensoes_sem_embalar()
        self.extrair_dimensoes_embalagem()
        self.validar_dimensoes()
        self.calcular_peso_cubado()
        return self

    # Função Objetivo: Diz se essa linha tem o dado mínimo pra virar Produto.
    # Explicação em detalhe: sem EAN não dá pra casar com nada — a linha é
    # descartada (contada, nunca silenciosamente ignorada). SKU ausente não
    # desqualifica a linha (campo opcional no model), só fica registrado.
    def esta_valida(self):
        return bool(self.ean)

    # Função Objetivo: Devolve os campos prontos pro Produto(**isso).
    def para_dict_produto(self):
        return dict(
            titulo=self.titulo,
            cod_fabricante=self.cod_fabricante,
            categoria=self.categoria,
            marca=self.marca,
            ncm=self.ncm,
            estoque=self.estoque,
            custo=self.custo,
            ativo_no_erp=self.ativo_no_erp,
            peso_produto_sem_embalar=self.peso_sem_embalar,
            altura_produto_sem_embalar=self.altura_sem_embalar,
            largura_produto_sem_embalar=self.largura_sem_embalar,
            comprimento_produto_sem_embalar=self.comprimento_sem_embalar,
            peso_produto_apos_embalado=self.peso_embalagem,
            altura_produto_apos_embalado=self.altura_embalagem,
            largura_produto_apos_embalado=self.largura_embalagem,
            comprimento_produto_apos_embalado=self.comprimento_embalagem,
            peso_cubado=self.peso_cubado,
            imagem_url=self.imagem_url,
            ultima_compra=self.ultima_compra,
            cadastrado_erp_em=self.cadastrado_erp_em,
        )


# Função Objetivo: Orquestra a importação inteira de Produtos, dos 2 arquivos do ERP.
class ImportadorProdutos:

    # Função Objetivo: Recebe os 2 caminhos de arquivo (Ativos/Inativos) e zera os contadores.
    # Explicação em detalhe: sem argumento explícito, resolve sozinho a partir
    # da empresa ativa — nunca mais comentar/descomentar arquivo à mão.
    def __init__(self, caminho_erp_ativos=None, caminho_erp_inativos=None):
        if caminho_erp_ativos is None or caminho_erp_inativos is None:
            empresa = obter_empresa_ativa()
            if empresa is None:
                raise RuntimeError(
                    'Nenhuma empresa ativa — rode este comando com --empresa=MAGAZINE '
                    'ou --empresa=SAMVALE, ou escolha a empresa na tela do sistema.'
                )
            caminhos = CAMINHOS_ERP_POR_EMPRESA[empresa]
            caminho_erp_ativos = caminho_erp_ativos or caminhos['ativos']
            caminho_erp_inativos = caminho_erp_inativos or caminhos['inativos']

        self.caminho_erp_ativos = caminho_erp_ativos
        self.caminho_erp_inativos = caminho_erp_inativos

        self.produtos_por_ean = {}
        self.eans_ja_enfileirados_para_criar = set()
        self.produtos_para_criar = []
        self.produtos_ja_atualizados = set()  # * ids Python (id()) já enfileirados
        self.produtos_para_atualizar = []

        self.criados = 0
        self.atualizados = 0
        self.sem_ean = 0
        self.erros_dimensao = []

        self.conversor = ConversorCelulaExcel(origem='openpyxl')
        self.parser_data = ParserData(origem='excel_br')

    # Função Objetivo: Carrega em memória os produtos já existentes no banco.
    def carregar_produtos_existentes(self):
        self.produtos_por_ean = {p.ean: p for p in Produto.objects.all()}

    # Função Objetivo: Processa 1 arquivo do ERP inteiro (Ativos OU Inativos), linha a linha.
    # Explicação em detalhe: os 2 arquivos passam por aqui, um depois do outro
    # (ver rodar_importacao_completa) — a lógica de criar/atualizar é a mesma
    # pros 2, só muda o arquivo de origem.
    def processar_arquivo(self, caminho):
        for linha_bruta in ler_linhas_planilha_erp(caminho):
            linha = LinhaProdutoERP(linha_bruta, self.conversor, self.parser_data).transformar_linha_em_produto()

            if not linha.esta_valida():
                self.sem_ean += 1
                continue

            if linha.erro_dimensao:
                self.erros_dimensao.append(linha.erro_dimensao)

            existente = self.produtos_por_ean.get(linha.ean)
            if existente:
                for campo, valor in linha.para_dict_produto().items():
                    setattr(existente, campo, valor)
                # * [EXPLICAÇÃO] → Se ainda não tem PK, é um produto criado
                #                  NESTA MESMA rodada (banco recém-criado, ou
                #                  o mesmo EAN apareceu nos 2 arquivos — não
                #                  deveria acontecer, mas não quebra se
                #                  acontecer) — já vai ser salvo pelo
                #                  bulk_create no final, não pode ir pro
                #                  bulk_update.
                if existente.pk and id(existente) not in self.produtos_ja_atualizados:
                    self.produtos_para_atualizar.append(existente)
                    self.produtos_ja_atualizados.add(id(existente))
                self.atualizados += 1
                continue

            if linha.ean in self.eans_ja_enfileirados_para_criar:
                continue

            novo = Produto(sku=linha.sku, ean=linha.ean, **linha.para_dict_produto())
            self.produtos_para_criar.append(novo)
            self.produtos_por_ean[linha.ean] = novo
            self.eans_ja_enfileirados_para_criar.add(linha.ean)
            self.criados += 1

    # Função Objetivo: Grava tudo no banco em lote, 1 única vez no final.
    def salvar(self):
        if self.produtos_para_criar:
            Produto.objects.bulk_create(self.produtos_para_criar, batch_size=BATCH_SIZE_PADRAO)

        if self.produtos_para_atualizar:
            Produto.objects.bulk_update(
                self.produtos_para_atualizar, LinhaProdutoERP.CAMPOS_PRODUTO, batch_size=BATCH_SIZE_PADRAO
            )

    # Função Objetivo: Roda a importação inteira, os 2 arquivos, do ERP ao banco.
    def rodar_importacao_completa(self):
        self.carregar_produtos_existentes()
        self.processar_arquivo(self.caminho_erp_ativos)
        # self.processar_arquivo(self.caminho_erp_inativos)  # Desativado temporariamente (17/08/2026) — decisão do usuário: arquivo de Inativos não é útil agora. Não precisa nem existir em disco enquanto estiver assim. Reativar descomentando esta linha.
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[PRODUTOS ERP] Concluído!\n'
            f'    Criados: {self.criados}, atualizados: {self.atualizados}\n'
            f'    Linhas sem EAN (ignoradas, não dá pra casar com nada): {self.sem_ean}\n'
            f'    Dimensão de embalagem com erro de cadastro (ignorada): {len(self.erros_dimensao)}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_produtos_erp(stdout, style):
    stdout.write('[PRODUTOS ERP] Lendo relatórios de Ativos e Inativos do ERP...')

    importador = ImportadorProdutos().rodar_importacao_completa()

    stdout.write('')
    stdout.write(style.SUCCESS(importador.relatorio()))

    if importador.erros_dimensao:
        stdout.write(style.WARNING(
            '\n[DIMENSÕES DE EMBALAGEM COM ERRO DE CADASTRO NO ERP — CORRIGIR NA FONTE]'
        ))
        for erro in importador.erros_dimensao:
            stdout.write(style.WARNING(f'    {erro}'))