# core/management/commands/popular_banco_suporte/importar_dimensoes_declaradas_ml.py

# Função Objetivo: Grava as dimensões/peso declarados pelo vendedor no ML, por variação.
# Explicação em detalhe: lê o mesmo detalhes_mlbs.json já usado por Anúncios ML.
# Extrai os atributos SELLER_PACKAGE_HEIGHT/WIDTH/LENGTH/WEIGHT (~85,6% de
# preenchimento na base) — fallback pro atributo legado WEIGHT quando os 4
# novos estão ausentes. NÃO calcula frete_real nem faz nenhuma comparação —
# isso agora é responsabilidade de FormulaPrecificacao (ainda não
# implementada), recalculado por margem. Aqui só grava os 4 campos brutos
# declarados. Não filtra por status do anúncio (ativo/pausado/encerrado) —
# é dado do vendedor, independente do estado atual do anúncio.
# Substitui o comando de teste testar_dimensoes_declaradas.py.

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from mercado_livre.models import AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO

CAMINHO_DETALHES_MLBS = Path('Arquivos_API/detalhes_mlbs.json')


# Função Objetivo: Representa 1 registro do JSON, extrai a dimensão declarada.
class LinhaDimensaoDeclaradaMLB:

    CAMPOS_VARIACAO = [
        'altura_declarada_cm', 'largura_declarada_cm',
        'comprimento_declarado_cm', 'peso_declarado_kg',
    ]

    # Função Objetivo: Recebe o registro bruto do JSON.
    def __init__(self, registro):
        self.registro = registro
        self.mlb = None
        self.variacao_id = None

        self.altura = None
        self.largura = None
        self.comprimento = None
        self.peso_declarado_kg = None

        # * [EXPLICAÇÃO] → 'dimensao_completa' = pelo menos 1 dos 4 campos
        #                  SELLER_PACKAGE_* veio preenchido; 'so_peso_legado'
        #                  = os 4 vieram vazios, mas o atributo legado WEIGHT
        #                  existe; 'sem_dado' = nenhum dos 2 existe.
        self.estado = None

    # Função Objetivo: Extrai o MLB e o identificador da variação.
    def extrair_identificadores(self):
        self.mlb = self.registro.get('mlb')
        self.variacao_id = str(self.registro.get('variacao_id') or self.mlb)

    # Função Objetivo: Converte texto com unidade embutida em Decimal.
    # Explicação em detalhe: '19 cm' -> Decimal('19'), '550 g' -> Decimal('550').
    # None se vazio/inválido — nunca derruba a importação por 1 registro ruim.
    def _parsear_numero(self, texto):
        if not texto:
            return None
        try:
            primeira_parte = str(texto).strip().split()[0]
            return Decimal(primeira_parte.replace(',', '.'))
        except (InvalidOperation, IndexError, ValueError):
            return None

    # Função Objetivo: Extrai a dimensão declarada, com fallback pro peso legado.
    def extrair_dimensoes_declaradas(self):
        self.altura = self._parsear_numero(self.registro.get('attr_seller_package_height'))
        self.largura = self._parsear_numero(self.registro.get('attr_seller_package_width'))
        self.comprimento = self._parsear_numero(self.registro.get('attr_seller_package_length'))
        peso_g = self._parsear_numero(self.registro.get('attr_seller_package_weight'))
        self.peso_declarado_kg = (peso_g / 1000) if peso_g is not None else None

        if self.altura is None and self.largura is None and self.comprimento is None and self.peso_declarado_kg is None:
            peso_legado_g = self._parsear_numero(self.registro.get('attr_weight'))
            if peso_legado_g is not None:
                self.peso_declarado_kg = peso_legado_g / 1000
                self.estado = 'so_peso_legado'
            else:
                self.estado = 'sem_dado'
        else:
            self.estado = 'dimensao_completa'

    # Função Objetivo: Devolve os 4 campos prontos pra aplicar na variação.
    def para_dict_variacao(self):
        return dict(
            altura_declarada_cm=self.altura,
            largura_declarada_cm=self.largura,
            comprimento_declarado_cm=self.comprimento,
            peso_declarado_kg=self.peso_declarado_kg,
        )

    # Função Objetivo: Roda os passos acima, na ordem certa.
    def processar(self):
        self.extrair_identificadores()
        self.extrair_dimensoes_declaradas()
        return self


# Função Objetivo: Orquestra a importação inteira, do arquivo ao banco.
class ImportadorDimensoesDeclaradas:

    # Função Objetivo: Recebe o caminho do JSON, o stdout, e zera os contadores.
    def __init__(self, caminho_json, stdout):
        self.caminho_json = caminho_json
        self.stdout = stdout

        self.registros = []
        self.anuncios_por_mlb = {}

        self.para_atualizar = []
        self.sem_anuncio = 0
        self.sem_variacao = 0
        self.com_dimensao_completa = 0
        self.com_so_peso_legado = 0
        self.sem_dimensao = 0

    # Função Objetivo: Lê o JSON de detalhes dos MLBs.
    def ler_json(self):
        with open(self.caminho_json, encoding='utf-8') as f:
            dados = json.load(f)
        self.registros = dados.get('registros', [])

    # Função Objetivo: Carrega em memória os anúncios/variações já existentes.
    def carregar_anuncios_existentes(self):
        self.anuncios_por_mlb = {
            a.mlb: a for a in AnuncioMercadoLivre.objects.prefetch_related('variacoes').all()
        }

    # Função Objetivo: Processa cada registro, com barra de progresso.
    def processar_registros(self):
        total = len(self.registros)

        for indice, registro in enumerate(self.registros, start=1):
            if indice % 500 == 0 or indice == total:
                self.stdout.write(f'    ... {indice}/{total} registros processados')

            linha = LinhaDimensaoDeclaradaMLB(registro).processar()

            anuncio = self.anuncios_por_mlb.get(linha.mlb)
            if not anuncio:
                self.sem_anuncio += 1
                continue

            variacao = next((v for v in anuncio.variacoes.all() if v.variacao_id == linha.variacao_id), None)
            if not variacao:
                self.sem_variacao += 1
                continue

            if linha.estado == 'sem_dado':
                self.sem_dimensao += 1
                continue
            elif linha.estado == 'so_peso_legado':
                self.com_so_peso_legado += 1
            else:
                self.com_dimensao_completa += 1

            for campo, valor in linha.para_dict_variacao().items():
                setattr(variacao, campo, valor)
            self.para_atualizar.append(variacao)

    # Função Objetivo: Grava tudo no banco em lote.
    def salvar(self):
        if self.para_atualizar:
            VariacaoAnuncioMercadoLivre.objects.bulk_update(
                self.para_atualizar, LinhaDimensaoDeclaradaMLB.CAMPOS_VARIACAO, batch_size=BATCH_SIZE_PADRAO
            )

    # Função Objetivo: Roda a importação inteira, do arquivo ao banco.
    def rodar_importacao_completa(self):
        self.ler_json()
        self.carregar_anuncios_existentes()
        self.processar_registros()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[DIMENSÕES DECLARADAS ML] Concluído!\n'
            f'    Variações atualizadas: {len(self.para_atualizar)}\n'
            f'    Com dimensão declarada: {self.com_dimensao_completa}\n'
            f'    Só peso legado (WEIGHT, sem dimensão): {self.com_so_peso_legado}\n'
            f'    Sem nenhum dado declarado: {self.sem_dimensao}\n'
            f'    Sem anúncio correspondente: {self.sem_anuncio}\n'
            f'    Sem variação correspondente: {self.sem_variacao}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_dimensoes_declaradas_ml(stdout, style, caminho_json=CAMINHO_DETALHES_MLBS):
    if not caminho_json.exists():
        stdout.write(style.WARNING(
            f'[DIMENSÕES DECLARADAS ML] Arquivo {caminho_json} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[DIMENSÕES DECLARADAS ML] Lendo {caminho_json}...')

    importador = ImportadorDimensoesDeclaradas(caminho_json, stdout)
    importador.rodar_importacao_completa()

    stdout.write(f'    {len(importador.registros)} registros no JSON')
    stdout.write(style.SUCCESS(importador.relatorio()))