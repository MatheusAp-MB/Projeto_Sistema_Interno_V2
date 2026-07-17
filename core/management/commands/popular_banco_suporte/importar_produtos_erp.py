# core/management/commands/popular_banco_suporte/importar_produtos_ml.py

# Função Objetivo: Popula e enriquece Produto, unificando as 2 fontes que
# antes eram 2 arquivos separados (rascunho + enriquecimento).
# Explicação em detalhe: Fase Rascunho — garante que TODO SKU que existe
# de verdade no Mercado Livre (detalhes_mlbs.json) tenha um Produto, cruzando
# com a planilha simples do ERP (Produtos_do_ML_Sysemp.xlsx) pra achar o EAN.
# Cobre o caso real confirmado pelo usuário: produto pode estar ativo no ERP
# e nem ser trabalhado no ML, ou pausado no ML mesmo ativo no ERP — "ativo"
# tem sentido diferente nas 2 fontes. Fase Enriquecimento — sobrescreve com
# dado mais completo vindo do Relatorio_Completo_ERP.xlsx (só produtos
# ativos no ERP), incluindo dimensão/custo/peso_cubado que o rascunho não tem.
#
# Reescrito em POO (16/07) — 3 classes:
#   LinhaProdutoRascunho    → 1 SKU do ML cruzado com a planilha simples
#   LinhaProdutoCompleto    → 1 linha da planilha completa, já validada
#   ImportadorProdutos      → o processo inteiro, do arquivo ao banco

import json
import pandas as pd
from decimal import Decimal
from produtos.models import Produto
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from core.management.commands.popular_banco_suporte.parser_data import ParserData

CAMINHO_LISTA_ML = 'Arquivos_API/detalhes_mlbs.json'
CAMINHO_ERP_SIMPLES = 'Arquivos_de_Importação/Produtos_do_ML_Sysemp.xlsx'
CAMINHO_ERP_COMPLETO = 'Arquivos_de_Importação/Relatorio_Completo_ERP.xlsx'

COLUNAS_ERP_COMPLETO = [
    'Codigo Auxiliar', 'Codigo de Barras', 'Codigo do Fabricante',
    'Detalhes do Produto', 'Categoria', 'Estoque', 'Marca',
    'Peso Bruto', 'Altura', 'Largura', 'Comprimento',
    'Embalagem Altura', 'Embalagem Largura', 'Embalagem Comprimento', 'Emablagem Peso',
    'Custo', 'ncm', 'URL 1', 'Ultima Compra', 'dt_cadastro',
]

FATOR_PESO_CUBADO = Decimal('6000')
LIMITE_DIMENSAO_CM = Decimal('9999.99')
LIMITE_PESO_CUBADO_KG = Decimal('99999.999')





# Função Objetivo: Representa 1 SKU do ML cruzado com a planilha simples.
class LinhaProdutoRascunho:

    # * [EXPLICAÇÃO] → Lista os nomes de campo como CONSTANTE da classe —
    #                  evita instanciar um objeto "vazio" só pra descobrir
    #                  as chaves (frágil: quebra se algum método interno
    #                  tentar ler dado real de um objeto sem dado nenhum).
    CAMPOS_PRODUTO = ['sku', 'cod_fabricante', 'titulo', 'categoria', 'estoque', 'marca', 'imagem_url']

    # Função Objetivo: Recebe o SKU, a linha da planilha simples, e o conversor compartilhado.
    def __init__(self, sku, linha_erp_simples, conversor):
        self.sku = sku
        self.linha_erp_simples = linha_erp_simples
        self.conversor = conversor
        self.ean = None
        self.tem_ean = False

    # Função Objetivo: Extrai o EAN e diz se essa linha pode virar Produto.
    # Explicação em detalhe: sem EAN não dá pra casar com nada — a linha é
    # descartada (contada, nunca silenciosamente ignorada).
    def extrair_ean(self):
        if self.linha_erp_simples is None or pd.isna(self.linha_erp_simples.get('Código de Barras')):
            self.tem_ean = False
            return
        self.ean = str(self.linha_erp_simples['Código de Barras']).strip()
        self.tem_ean = True

    # Função Objetivo: Roda o único passo necessário, na ordem certa.
    def transformar_linha_em_produto(self):
        self.extrair_ean()
        return self

    # Função Objetivo: Devolve os campos prontos pro Produto(**isso).
    # Explicação em detalhe: custo/dimensões viram placeholder zero aqui —
    # a fase de Enriquecimento (LinhaProdutoCompleto) é quem preenche com
    # dado real, quando o produto também existir na planilha completa.
    def para_dict_produto(self):
        linha = self.linha_erp_simples
        return dict(
            sku=self.sku,
            cod_fabricante=self.conversor.para_texto(linha.get('Código Fabricante')),
            titulo=self.conversor.para_texto(linha.get('Descrição do Produto'), self.sku),
            categoria=self.conversor.para_texto(linha.get('Categoria')),
            estoque=int(self.conversor.para_decimal(linha.get('Estoque'), padrao=0)),
            marca=self.conversor.para_texto(linha.get('Marca')),
            imagem_url=self.conversor.para_texto(linha.get('Imagem 1')),
        )

    # Função Objetivo: Devolve os campos placeholder obrigatórios na criação.
    def para_dict_placeholder_criacao(self):
        return dict(
            custo=Decimal('0'),
            peso_produto_sem_embalar=Decimal('0'),
            altura_produto_sem_embalar=Decimal('0'),
            largura_produto_sem_embalar=Decimal('0'),
            comprimento_produto_sem_embalar=Decimal('0'),
        )


# Função Objetivo: Representa 1 linha da planilha completa do ERP, já validada.
class LinhaProdutoCompleto:

    CAMPOS_PRODUTO = [
        'titulo', 'cod_fabricante', 'categoria', 'marca', 'ncm', 'estoque', 'custo',
        'peso_produto_sem_embalar', 'altura_produto_sem_embalar', 'largura_produto_sem_embalar',
        'comprimento_produto_sem_embalar', 'peso_produto_apos_embalado', 'altura_produto_apos_embalado',
        'largura_produto_apos_embalado', 'comprimento_produto_apos_embalado', 'peso_cubado',
        'imagem_url', 'ultima_compra', 'cadastrado_erp_em',
    ]

    # Função Objetivo: Recebe a linha bruta do pandas, o conversor e o parser de data.
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

    # Função Objetivo: Extrai SKU, EAN, título e os demais campos simples.
    def extrair_campos_basicos(self):
        self.sku = self.conversor.para_texto(self.linha_bruta.get('Codigo Auxiliar'))
        self.ean = self.conversor.para_texto(self.linha_bruta.get('Codigo de Barras'))
        self.titulo = self.conversor.para_texto(self.linha_bruta.get('Detalhes do Produto'), self.sku)
        self.cod_fabricante = self.conversor.para_texto(self.linha_bruta.get('Codigo do Fabricante'))
        self.categoria = self.conversor.para_texto(self.linha_bruta.get('Categoria'))
        self.marca = self.conversor.para_texto(self.linha_bruta.get('Marca'))
        self.ncm = self.conversor.para_texto(self.linha_bruta.get('ncm'))
        self.estoque = int(self.conversor.para_decimal(self.linha_bruta.get('Estoque'), padrao=0))
        self.custo = self.conversor.para_decimal(self.linha_bruta.get('Custo'), padrao=0)
        self.imagem_url = self.conversor.para_texto(self.linha_bruta.get('URL 1'))
        self.ultima_compra = self.parser_data.parsear(self.linha_bruta.get('Ultima Compra'))
        self.cadastrado_erp_em = self.parser_data.parsear(self.linha_bruta.get('dt_cadastro'))

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

    # Função Objetivo: Ordena os 2 conjuntos de dimensão sempre menor→maior.
    # Explicação em detalhe: a equipe nunca padronizou qual eixo é "altura" x
    # "largura" x "comprimento" entre as fontes — confirmado que fisicamente
    # não importa, só o conjunto de valores. Convenção: altura ≤ comprimento
    # ≤ largura.
    def padronizar_ordem_dimensoes(self):
        self.altura_sem_embalar, self.comprimento_sem_embalar, self.largura_sem_embalar = sorted(
            [self.altura_sem_embalar, self.largura_sem_embalar, self.comprimento_sem_embalar]
        )

        tem_embalagem_completa = (
            self.altura_embalagem is not None
            and self.largura_embalagem is not None
            and self.comprimento_embalagem is not None
        )
        if tem_embalagem_completa:
            self.altura_embalagem, self.comprimento_embalagem, self.largura_embalagem = sorted(
                [self.altura_embalagem, self.largura_embalagem, self.comprimento_embalagem]
            )

    # Função Objetivo: Detecta dimensão fisicamente absurda e marca o erro.
    # Explicação em detalhe: nunca corrige o valor sozinha — só marca
    # self.erro_dimensao e zera os 3 eixos da embalagem, pro usuário corrigir
    # na fonte (ERP). Limite: nenhuma embalagem real chega perto de 100m.
    def validar_dimensoes(self):
        dimensoes_com_erro = []
        for nome, valor in [
            ('menor dimensão da embalagem', self.altura_embalagem),
            ('dimensão intermediária da embalagem', self.comprimento_embalagem),
            ('maior dimensão da embalagem', self.largura_embalagem),
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
        self.padronizar_ordem_dimensoes()
        self.validar_dimensoes()
        self.calcular_peso_cubado()
        return self

    # Função Objetivo: Diz se essa linha tem dado mínimo pra virar Produto.
    def esta_valida(self):
        return bool(self.sku)

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


# Função Objetivo: Orquestra a importação inteira de Produtos, as 2 fases.
class ImportadorProdutos:

    # Função Objetivo: Recebe os 3 caminhos de arquivo e zera os contadores.
    def __init__(self, caminho_lista_ml=CAMINHO_LISTA_ML, caminho_erp_simples=CAMINHO_ERP_SIMPLES,
                 caminho_erp_completo=CAMINHO_ERP_COMPLETO):
        self.caminho_lista_ml = caminho_lista_ml
        self.caminho_erp_simples = caminho_erp_simples
        self.caminho_erp_completo = caminho_erp_completo

        self.skus_unicos_ml = set()
        self.erp_simples_por_sku = {}
        self.dataframe_erp_completo = None

        self.produtos_por_ean = {}
        self.eans_ja_enfileirados_para_criar = set()
        self.produtos_para_criar = []
        self.produtos_ja_atualizados = set()  # * ids Python (id()) já enfileirados
        self.produtos_para_atualizar = []

        self.criados_rascunho = 0
        self.atualizados_rascunho = 0
        self.sem_ean_rascunho = 0

        self.atualizados_completo = 0
        self.criados_completo = 0
        self.erros_dimensao = []

        self.conversor = ConversorCelulaExcel(origem='pandas')
        self.parser_data = ParserData(origem='excel_br')

    # Função Objetivo: Lê a lista real de SKUs existentes no Mercado Livre.
    def ler_lista_skus_ml(self):
        with open(self.caminho_lista_ml, encoding='utf-8') as f:
            dados = json.load(f)
        registros = dados.get('registros', [])
        self.skus_unicos_ml = {r.get('sku') for r in registros if r.get('sku')}

    # Função Objetivo: Lê a planilha simples do ERP (EAN, título, categoria...).
    def ler_planilha_erp_simples(self):
        df = pd.read_excel(self.caminho_erp_simples)
        df = df.rename(columns={'SKU na Plataforma': 'SKU'})
        df = df[[
            'SKU', 'Código de Barras', 'Código Fabricante',
            'Descrição do Produto', 'Categoria', 'Estoque', 'Marca', 'Imagem 1',
        ]]
        self.erp_simples_por_sku = {row['SKU']: row for _, row in df.iterrows()}

    # Função Objetivo: Lê a planilha completa do ERP (só produtos ativos).
    def ler_planilha_erp_completo(self):
        df = pd.read_excel(self.caminho_erp_completo)
        self.dataframe_erp_completo = df[COLUNAS_ERP_COMPLETO]

    # Função Objetivo: Carrega em memória os produtos já existentes no banco.
    def carregar_produtos_existentes(self):
        self.produtos_por_ean = {p.ean: p for p in Produto.objects.all()}

    # Função Objetivo: Garante que todo SKU do ML tenha um Produto (rascunho).
    # Explicação em detalhe: cruza cada SKU do ML com a planilha simples pra
    # achar o EAN — sem EAN, não dá pra casar com nada, é só contado.
    def garantir_existencia_rascunho(self):
        for sku in self.skus_unicos_ml:
            linha = LinhaProdutoRascunho(
                sku, self.erp_simples_por_sku.get(sku), self.conversor
            ).transformar_linha_em_produto()

            if not linha.tem_ean:
                self.sem_ean_rascunho += 1
                continue

            existente = self.produtos_por_ean.get(linha.ean)
            if existente:
                for campo, valor in linha.para_dict_produto().items():
                    setattr(existente, campo, valor)
                # * [EXPLICAÇÃO] → Se ainda não tem PK, é um produto criado
                #                  NESTA MESMA rodada (banco recém-criado,
                #                  sem histórico) — já vai ser salvo pelo
                #                  bulk_create no final, não pode ir pro
                #                  bulk_update (mesmo bug já corrigido em
                #                  Promoções/Qualidade/Competição, esquecido
                #                  aqui na unificação).
                if existente.pk and id(existente) not in self.produtos_ja_atualizados:
                    self.produtos_para_atualizar.append(existente)
                    self.produtos_ja_atualizados.add(id(existente))
                self.atualizados_rascunho += 1
            else:
                novo = Produto(
                    ean=linha.ean,
                    **linha.para_dict_produto(),
                    **linha.para_dict_placeholder_criacao(),
                )
                self.produtos_para_criar.append(novo)
                self.produtos_por_ean[linha.ean] = novo
                self.eans_ja_enfileirados_para_criar.add(linha.ean)
                self.criados_rascunho += 1

    # Função Objetivo: Sobrescreve com dado completo (dimensão/custo/peso_cubado).
    # Explicação em detalhe: casa por SKU (Codigo Auxiliar) primeiro; se não
    # achar, tenta por EAN — o SKU desta planilha nem sempre bate com
    # Produto.sku (fonte diferente, API do ML).
    def enriquecer_com_dado_completo(self):
        produtos_por_sku = {p.sku: p for p in self.produtos_por_ean.values() if p.sku}

        for _, linha_bruta in self.dataframe_erp_completo.iterrows():
            linha = LinhaProdutoCompleto(
                linha_bruta, self.conversor, self.parser_data
            ).transformar_linha_em_produto()
            if not linha.esta_valida():
                continue
            if linha.erro_dimensao:
                self.erros_dimensao.append(linha.erro_dimensao)

            existente = produtos_por_sku.get(linha.sku) or (
                self.produtos_por_ean.get(linha.ean) if linha.ean else None
            )

            if existente:
                for campo, valor in linha.para_dict_produto().items():
                    setattr(existente, campo, valor)
                # * [EXPLICAÇÃO] → Mesma proteção da fase de Rascunho — o
                #                  produto pode ter sido criado por ELA
                #                  mesma, nesta mesma rodada, ainda sem PK.
                if existente.pk and id(existente) not in self.produtos_ja_atualizados:
                    self.produtos_para_atualizar.append(existente)
                    self.produtos_ja_atualizados.add(id(existente))
                self.atualizados_completo += 1
                continue    

            if not linha.ean or linha.ean in self.eans_ja_enfileirados_para_criar:
                continue

            novo = Produto(sku=linha.sku, ean=linha.ean, **linha.para_dict_produto())
            self.produtos_para_criar.append(novo)
            self.produtos_por_ean[linha.ean] = novo
            self.eans_ja_enfileirados_para_criar.add(linha.ean)
            self.criados_completo += 1

    # Função Objetivo: Grava tudo no banco em lote, 1 única vez no final.
    def salvar(self):
        if self.produtos_para_criar:
            Produto.objects.bulk_create(self.produtos_para_criar, batch_size=BATCH_SIZE_PADRAO)

        if self.produtos_para_atualizar:
            # * [EXPLICAÇÃO] → união dos campos que QUALQUER uma das 2 fases
            #                  pode ter alterado — bulk_update precisa da
            #                  lista completa, mesmo que 1 produto só tenha
            #                  sido tocado por 1 das 2 fases.
            campos = sorted(set(LinhaProdutoRascunho.CAMPOS_PRODUTO) | set(LinhaProdutoCompleto.CAMPOS_PRODUTO))
            Produto.objects.bulk_update(self.produtos_para_atualizar, campos, batch_size=BATCH_SIZE_PADRAO)

    # Função Objetivo: Roda a importação inteira, as 2 fases, do arquivo ao banco.
    def rodar_importacao_completa(self):
        self.ler_lista_skus_ml()
        self.ler_planilha_erp_simples()
        self.ler_planilha_erp_completo()
        self.carregar_produtos_existentes()
        self.garantir_existencia_rascunho()
        self.enriquecer_com_dado_completo()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[PRODUTOS] Concluído!\n'
            f'    SKUs únicos no ML: {len(self.skus_unicos_ml)}\n'
            f'    Rascunho — criados: {self.criados_rascunho}, atualizados: {self.atualizados_rascunho}, sem EAN: {self.sem_ean_rascunho}\n'
            f'    Completo — criados: {self.criados_completo}, atualizados: {self.atualizados_completo}\n'
            f'    Dimensão de embalagem com erro de cadastro (ignorada): {len(self.erros_dimensao)}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_produtos_erp(stdout, style, caminho_json=CAMINHO_LISTA_ML):
    stdout.write('[PRODUTOS] Lendo lista do ML e planilhas do ERP...')

    importador = ImportadorProdutos(caminho_lista_ml=caminho_json).rodar_importacao_completa()

    stdout.write('')
    stdout.write(style.SUCCESS(importador.relatorio()))

    if importador.erros_dimensao:
        stdout.write(style.WARNING(
            '\n[DIMENSÕES DE EMBALAGEM COM ERRO DE CADASTRO NO ERP — CORRIGIR NA FONTE]'
        ))
        for erro in importador.erros_dimensao:
            stdout.write(style.WARNING(f'    {erro}'))