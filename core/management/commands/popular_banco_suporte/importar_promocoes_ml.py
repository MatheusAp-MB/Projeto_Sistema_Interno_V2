# core/management/commands/popular_banco_suporte/importar_promocoes_ml.py

# Função Objetivo: Importa promoções do arquivo gerado pelo projeto da API.
# Explicação em detalhe: nunca mais lido ao vivo por nenhuma tela depois
# dessa importação existir (regra do projeto: tudo vem do banco, arquivo só
# serve pra popular).
#
# Reescrito em POO (16/07) — 2 classes:
#   LinhaPromocaoMLB    → 1 MLB, resolve a variação e checa o status
#   LinhaPromocao       → 1 promoção individual dentro daquele MLB
#   ImportadorPromocoes → o processo inteiro, do arquivo ao banco

import json
import time
from pathlib import Path
from mercado_livre.models import AnuncioMercadoLivre, PromocaoMercadoLivre
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.funcoes_auxiliares.contador_consultas import contar_consultas
from core.management.commands.popular_banco_suporte.parser_data import ParserData

CAMINHO_PROMOCOES = Path('Arquivos_API/promocoes_completo.json')


# Função Objetivo: Representa 1 promoção individual dentro de 1 MLB.
class LinhaPromocao:

    # Função Objetivo: Recebe o dict bruto da promoção e o parser de data.
    def __init__(self, promo_bruta, parser_data):
        self.promo_bruta = promo_bruta
        self.parser_data = parser_data
        self.chave_externa = None

    # Função Objetivo: Extrai a chave externa (id, ref_id, ou o próprio tipo).
    # Explicação em detalhe: PRICE_DISCOUNT não tem id nem ref_id na API —
    # usa o próprio tipo como fallback (só existe 1 PRICE_DISCOUNT por
    # variação de qualquer forma).
    def extrair_chave_externa(self):
        promo = self.promo_bruta
        self.chave_externa = promo.get('id') or promo.get('ref_id') or promo.get('type')
        return self.chave_externa

    # Função Objetivo: Devolve os campos prontos pro PromocaoMercadoLivre(**isso).
    def para_dict_promocao(self):
        promo = self.promo_bruta
        return dict(
            tipo=promo.get('type'),
            nome=promo.get('name'),
            status=promo.get('status'),
            preco_original=promo.get('original_price'),
            preco_avaliado=promo.get('price') or promo.get('suggested_discounted_price'),
            meli_percentage=promo.get('meli_percentage'),
            seller_percentage=promo.get('seller_percentage'),
            inicio_vigencia=self.parser_data.parsear(promo.get('start_date')),
            fim_vigencia=self.parser_data.parsear(promo.get('finish_date')),
        )

    # Função Objetivo: Roda o passo acima.
    def processar(self):
        self.extrair_chave_externa()
        return self


# Função Objetivo: Representa 1 MLB, resolve a variação e checa o status.
class LinhaPromocaoMLB:

    CAMPOS_PROMOCAO = [
        'tipo', 'nome', 'status', 'preco_original', 'preco_avaliado',
        'meli_percentage', 'seller_percentage', 'inicio_vigencia', 'fim_vigencia',
    ]

    # Função Objetivo: Recebe o MLB, o resultado bruto, e o parser de data.
    def __init__(self, mlb, resultado, parser_data):
        self.mlb = mlb
        self.resultado = resultado
        self.parser_data = parser_data
        self.variacao = None

    # Função Objetivo: Resolve a variação daquele anúncio (a primeira dela).
    # Explicação em detalhe: .first() NÃO usa o cache do prefetch_related
    # (comportamento conhecido do Django — só .all() usa) — sempre
    # dispararia 1 query nova por MLB, mesmo com tudo pré-carregado.
    # list(anuncio.variacoes.all())[0] usa o cache de verdade.
    def resolver_variacao(self, anuncio):
        variacoes_do_anuncio = list(anuncio.variacoes.all())
        self.variacao = variacoes_do_anuncio[0] if variacoes_do_anuncio else None
        return self.variacao

    # Função Objetivo: Diz se a chamada à API teve sucesso pra esse MLB.
    def chamada_teve_sucesso(self):
        return bool(self.resultado.get('chamado')) and self.resultado.get('http') == 200

    # Função Objetivo: Devolve a lista de promoções brutas desse MLB.
    def extrair_promocoes(self):
        return self.resultado.get('dados') or []


# Função Objetivo: Orquestra a importação inteira de Promoções, do arquivo ao banco.
class ImportadorPromocoes:

    # Função Objetivo: Recebe o caminho do arquivo, o stdout, e zera os contadores.
    def __init__(self, caminho, stdout):
        self.caminho = caminho
        self.stdout = stdout
        self.parser_data = ParserData(origem='iso')

        self.dados = None
        self.promocoes_por_item = {}

        self.anuncios_por_mlb = {}
        self.promocoes_existentes = {}

        self.para_criar = []
        self.para_atualizar = []
        self.ids_ja_atualizados = set()
        self.sem_anuncio = 0
        self.sem_variacao = 0

        self.tempo_leitura = 0
        self.tempo_carga_banco = 0
        self.tempo_loop = 0
        self.tempo_salvar = 0

    # Função Objetivo: Lê o JSON de promoções.
    # Explicação em detalhe: só 'fase2_promocoes_por_item' é usado —
    # 'fase3_rosters_completos' é IGNORADO de propósito (investigado e
    # confirmado não confiável: traz duplicatas e omite itens reais).
    def ler_json(self):
        inicio = time.perf_counter()
        with open(self.caminho, encoding='utf-8') as f:
            self.dados = json.load(f)
        self.promocoes_por_item = self.dados.get('fase2_promocoes_por_item', {})
        self.tempo_leitura = time.perf_counter() - inicio

    # Função Objetivo: Carrega em memória tudo que já existe no banco.
    def carregar_dados_existentes(self):
        inicio = time.perf_counter()

        mlbs_texto = list(self.promocoes_por_item.keys())
        self.anuncios_por_mlb = {
            a.mlb: a for a in AnuncioMercadoLivre.objects.filter(mlb__in=mlbs_texto).prefetch_related('variacoes')
        }
        self.promocoes_existentes = {
            (p.variacao_id, p.chave_externa): p
            for p in PromocaoMercadoLivre.objects.all()
        }

        self.tempo_carga_banco = time.perf_counter() - inicio

    # Função Objetivo: Processa cada MLB e suas promoções, com barra de progresso.
    def processar_mlbs_e_promocoes(self):
        inicio = time.perf_counter()
        total_mlbs = len(self.promocoes_por_item)

        for indice, (mlb, resultado) in enumerate(self.promocoes_por_item.items(), start=1):
            if indice % 500 == 0 or indice == total_mlbs:
                decorrido = time.perf_counter() - inicio
                self.stdout.write(f'    ... {indice}/{total_mlbs} MLBs processados ({decorrido:.1f}s)')

            linha_mlb = LinhaPromocaoMLB(mlb, resultado, self.parser_data)

            anuncio = self.anuncios_por_mlb.get(mlb)
            if not anuncio:
                self.sem_anuncio += 1
                continue

            if not linha_mlb.resolver_variacao(anuncio):
                self.sem_variacao += 1
                continue

            if not linha_mlb.chamada_teve_sucesso():
                continue

            for promo_bruta in linha_mlb.extrair_promocoes():
                linha_promo = LinhaPromocao(promo_bruta, self.parser_data).processar()
                if not linha_promo.chave_externa:
                    continue

                dados_promo = linha_promo.para_dict_promocao()
                chave = (linha_mlb.variacao.id, linha_promo.chave_externa)
                existente = self.promocoes_existentes.get(chave)

                if existente:
                    for campo, valor in dados_promo.items():
                        setattr(existente, campo, valor)
                    # * [EXPLICAÇÃO] → Se ainda não tem PK, é objeto NOVO
                    #                  desta mesma rodada (mesma chave_
                    #                  externa apareceu 2x pro mesmo MLB —
                    #                  cenário real, já documentado:
                    #                  "múltiplas ofertas concorrentes pro
                    #                  mesmo item") — já vai ser salvo pelo
                    #                  bulk_create, não pode ir pro
                    #                  bulk_update.
                    if existente.pk and id(existente) not in self.ids_ja_atualizados:
                        self.para_atualizar.append(existente)
                        self.ids_ja_atualizados.add(id(existente))
                else:
                    nova = PromocaoMercadoLivre(
                        variacao=linha_mlb.variacao, chave_externa=linha_promo.chave_externa, **dados_promo
                    )
                    self.para_criar.append(nova)
                    self.promocoes_existentes[chave] = nova

        self.tempo_loop = time.perf_counter() - inicio

    # Função Objetivo: Grava tudo no banco em lote.
    def salvar(self):
        inicio = time.perf_counter()

        if self.para_criar:
            PromocaoMercadoLivre.objects.bulk_create(self.para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.para_atualizar:
            PromocaoMercadoLivre.objects.bulk_update(
                self.para_atualizar, LinhaPromocaoMLB.CAMPOS_PROMOCAO, batch_size=BATCH_SIZE_PADRAO
            )

        self.tempo_salvar = time.perf_counter() - inicio

    # Função Objetivo: Roda a importação inteira, do arquivo ao banco.
    def rodar_importacao_completa(self):
        self.ler_json()
        self.carregar_dados_existentes()
        self.processar_mlbs_e_promocoes()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self, tempo_total):
        return (
            f'[PROMOÇÕES ML] Concluído em {tempo_total:.1f}s!\n'
            f'    Promoções criadas: {len(self.para_criar)}\n'
            f'    Promoções atualizadas: {len(self.para_atualizar)}\n'
            f'    Sem anúncio correspondente: {self.sem_anuncio}\n'
            f'    Sem variação: {self.sem_variacao}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_promocoes_ml(stdout, style, caminho=CAMINHO_PROMOCOES):
    if not caminho.exists():
        stdout.write(style.WARNING(
            f'[PROMOÇÕES ML] Arquivo {caminho} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[PROMOÇÕES ML] Lendo {caminho}...')

    with contar_consultas() as contador:
        inicio_total = time.perf_counter()

        importador = ImportadorPromocoes(caminho, stdout)
        importador.rodar_importacao_completa()

        tempo_total = time.perf_counter() - inicio_total

    stdout.write(f'    {len(importador.promocoes_por_item)} MLB(s) no arquivo')
    stdout.write(f'  ⏱ Ler o JSON: {importador.tempo_leitura:.1f}s')
    stdout.write(f'  ⏱ Carregar anúncios/promoções existentes do banco: {importador.tempo_carga_banco:.1f}s')
    stdout.write(f'  ⏱ Loop de processamento (todos os MLBs): {importador.tempo_loop:.1f}s')
    stdout.write(f'  ⏱ Salvar no banco (bulk_create/bulk_update): {importador.tempo_salvar:.1f}s')
    stdout.write(f'  📊 Consultas ao banco (SQL) no total: {contador["total"]}')

    stdout.write(style.SUCCESS(importador.relatorio(tempo_total)))