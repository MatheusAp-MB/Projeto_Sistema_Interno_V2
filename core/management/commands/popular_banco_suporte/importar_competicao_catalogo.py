# core/management/commands/popular_banco_suporte/importar_competicao_catalogo.py

# Função Objetivo: Importa dados de competição de catálogo (price_to_win).
# Explicação em detalhe: mesmo arquivo dados_completos_por_sku.json usado pra
# Qualidade. Só processa MLBs com classificacao == 'catalogo' — outros tipos
# nem têm price_to_win chamado pela API.
#
# Reescrito em POO (16/07) — 2 classes:
#   LinhaCompeticaoMLB  → 1 item de catálogo, extrai o price_to_win
#   ImportadorCompeticao → o processo inteiro, do arquivo ao banco

import json
import time
from mercado_livre.models import AnuncioMercadoLivre, CompeticaoCatalogo
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.funcoes_auxiliares.contador_consultas import contar_consultas


# Função Objetivo: Representa 1 item de catálogo, extrai o price_to_win.
class LinhaCompeticaoMLB:

    CAMPOS_COMPETICAO = [
        'status', 'current_price', 'price_to_win', 'currency_id', 'visit_share',
        'competitors_sharing_first_place', 'consistent', 'catalog_product_id',
        'reason', 'boosts', 'winner', 'http_status', 'erro',
    ]

    # Função Objetivo: Recebe o bloco bruto do MLB.
    def __init__(self, mlb_dados):
        self.mlb_dados = mlb_dados
        self.mlb = None
        self.ptw = None
        self.info = None

    # Função Objetivo: Extrai o MLB e o bloco de price_to_win.
    def extrair_price_to_win(self):
        self.mlb = self.mlb_dados.get('mlb')
        self.ptw = self.mlb_dados.get('price_to_win', {})
        self.info = self.ptw.get('dados') if self.ptw.get('chamado') else None

    # Função Objetivo: Devolve os campos prontos pro CompeticaoCatalogo(**isso).
    def para_dict_competicao(self):
        info = self.info
        return dict(
            status=info.get('status') if info else None,
            current_price=info.get('current_price') if info else None,
            price_to_win=info.get('price_to_win') if info else None,
            currency_id=info.get('currency_id') if info else None,
            visit_share=info.get('visit_share') if info else None,
            competitors_sharing_first_place=info.get('competitors_sharing_first_place') if info else None,
            consistent=info.get('consistent') if info else None,
            catalog_product_id=info.get('catalog_product_id') if info else None,
            reason=info.get('reason') if info else None,
            boosts=info.get('boosts') if info else None,
            winner=info.get('winner') if info else None,
            http_status=self.ptw.get('http'),
            erro=self.ptw.get('erro'),
        )

    # Função Objetivo: Roda o passo acima.
    def processar(self):
        self.extrair_price_to_win()
        return self


# Função Objetivo: Orquestra a importação inteira de Competição, do arquivo ao banco.
class ImportadorCompeticao:

    # Função Objetivo: Recebe o caminho do JSON, o stdout, e zera os contadores.
    def __init__(self, caminho_json, stdout):
        self.caminho_json = caminho_json
        self.stdout = stdout

        self.dados = None
        self.blocos_sku = []
        self.itens_catalogo = []
        self.nao_catalogo = 0

        self.anuncios_por_mlb = {}
        self.competicoes_existentes = {}

        self.para_criar = []
        self.para_atualizar = []
        self.sem_anuncio = 0
        self.avisos = []

        self.tempo_leitura = 0
        self.tempo_carga_banco = 0
        self.tempo_loop = 0
        self.tempo_salvar = 0

    # Função Objetivo: Lê o JSON e separa os itens de Catálogo dos demais.
    def ler_json_e_separar_catalogo(self):
        inicio = time.perf_counter()

        with open(self.caminho_json, encoding='utf-8') as f:
            self.dados = json.load(f)
        self.blocos_sku = self.dados.get('skus', [])

        for bloco in self.blocos_sku:
            for mlb_dados in bloco.get('mlbs', []):
                if mlb_dados.get('classificacao') == 'catalogo':
                    self.itens_catalogo.append(mlb_dados)
                else:
                    self.nao_catalogo += 1

        self.tempo_leitura = time.perf_counter() - inicio

    # Função Objetivo: Carrega em memória tudo que já existe no banco.
    # Explicação em detalhe: só carrega Anúncio dos MLBs de Catálogo — evita
    # carregar anúncios que nunca vão ser usados nesta etapa.
    def carregar_dados_existentes(self):
        inicio = time.perf_counter()

        mlbs_catalogo = [item.get('mlb') for item in self.itens_catalogo]
        self.anuncios_por_mlb = {
            a.mlb: a for a in AnuncioMercadoLivre.objects.filter(mlb__in=mlbs_catalogo)
        }
        self.competicoes_existentes = {
            c.anuncio_id: c
            for c in CompeticaoCatalogo.objects.filter(anuncio_id__in=[a.id for a in self.anuncios_por_mlb.values()])
        }

        self.tempo_carga_banco = time.perf_counter() - inicio

    # Função Objetivo: Processa cada item de catálogo, com barra de progresso.
    def processar_itens(self):
        inicio = time.perf_counter()
        total_itens = len(self.itens_catalogo)

        for indice, mlb_dados in enumerate(self.itens_catalogo, start=1):
            if indice % 300 == 0 or indice == total_itens:
                decorrido = time.perf_counter() - inicio
                self.stdout.write(f'    ... {indice}/{total_itens} MLBs de Catálogo processados ({decorrido:.1f}s)')

            linha = LinhaCompeticaoMLB(mlb_dados).processar()

            anuncio = self.anuncios_por_mlb.get(linha.mlb)
            if not anuncio:
                self.sem_anuncio += 1
                self.avisos.append(f'    [SEM ANÚNCIO] {linha.mlb} não encontrado no banco — pulado')
                continue

            dados_competicao = linha.para_dict_competicao()
            existente = self.competicoes_existentes.get(anuncio.id)
            if existente:
                for campo, valor in dados_competicao.items():
                    setattr(existente, campo, valor)
                if existente.pk and existente not in self.para_atualizar:
                    self.para_atualizar.append(existente)
            else:
                nova = CompeticaoCatalogo(anuncio=anuncio, **dados_competicao)
                self.para_criar.append(nova)
                self.competicoes_existentes[anuncio.id] = nova

        self.tempo_loop = time.perf_counter() - inicio

    # Função Objetivo: Grava tudo no banco em lote.
    def salvar(self):
        inicio = time.perf_counter()

        if self.para_criar:
            CompeticaoCatalogo.objects.bulk_create(self.para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.para_atualizar:
            CompeticaoCatalogo.objects.bulk_update(
                self.para_atualizar, LinhaCompeticaoMLB.CAMPOS_COMPETICAO, batch_size=BATCH_SIZE_PADRAO
            )

        self.tempo_salvar = time.perf_counter() - inicio

    # Função Objetivo: Roda a importação inteira, do arquivo ao banco.
    def rodar_importacao_completa(self):
        self.ler_json_e_separar_catalogo()
        self.carregar_dados_existentes()
        self.processar_itens()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self, tempo_total, total_consultas):
        return (
            f'[COMPETIÇÃO] Concluído em {tempo_total:.1f}s!\n'
            f'    Criados: {len(self.para_criar)}\n'
            f'    Atualizados: {len(self.para_atualizar)}\n'
            f'    Sem anúncio correspondente: {self.sem_anuncio}\n'
            f'    Ignorados (não são Catálogo): {self.nao_catalogo}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_competicao_catalogo(stdout, style, caminho_json):
    if not caminho_json.exists():
        stdout.write(style.WARNING(
            f'[COMPETIÇÃO] Arquivo {caminho_json} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[COMPETIÇÃO] Lendo {caminho_json}...')

    with contar_consultas() as contador:
        inicio_total = time.perf_counter()

        importador = ImportadorCompeticao(caminho_json, stdout)
        importador.rodar_importacao_completa()

        tempo_total = time.perf_counter() - inicio_total

    stdout.write(f'    {len(importador.blocos_sku)} SKU(s) no arquivo')
    stdout.write(f'  ⏱ Ler o JSON e separar itens de Catálogo: {importador.tempo_leitura:.1f}s')
    stdout.write(f'  ⏱ Carregar anúncios/competições existentes do banco: {importador.tempo_carga_banco:.1f}s')

    for aviso in importador.avisos:
        stdout.write(aviso)

    stdout.write(f'  ⏱ Loop de processamento (todos os MLBs de Catálogo): {importador.tempo_loop:.1f}s')
    stdout.write(f'  ⏱ Salvar no banco (bulk_create/bulk_update): {importador.tempo_salvar:.1f}s')
    stdout.write(f'  📊 Consultas ao banco (SQL) no total: {contador["total"]}')

    stdout.write(style.SUCCESS(importador.relatorio(tempo_total, contador['total'])))