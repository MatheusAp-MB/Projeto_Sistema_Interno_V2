# core/management/commands/popular_banco_suporte/organizar_e_verificar_divergencias_dimensoes_envio.py

# Função Objetivo: Organiza as dimensões de envio (ERP + ML) em ordem consistente e persiste
# nos 2 models, e compara os 2 lados pra detectar divergência por MLB.
# Explicação em detalhe: pra cada VariacaoAnuncioMercadoLivre, calcula obter_dimensoes_envio()
# dos 2 lados (Produto via variacao.produto, e a própria Variação) e grava os campos
# "_ordenada_cm" nos 2 models — única fonte usada depois por qualquer cálculo que precise de
# eixos consistentes (resolver_dimensao_produto, resolver_dimensoes_efetivas, calculo_margem).
# ERP é sempre a fonte da verdade; este comando só sinaliza divergência, nunca corrige nada
# sozinho. Roda depois de PRODUTOS ERP e DIMENSÕES DECLARADAS ML, e ANTES de qualquer GRADE
# (que já depende dos campos "_ordenada_cm" calculados aqui). Pode rodar sozinho a qualquer
# momento (via o comando fino em commands/), sempre recalculando do zero — idempotente.
#
# * [EXPLICAÇÃO] → Correção (11/09/2026) — Produto sem NENHUMA VariacaoAnuncioMercadoLivre
#                  nunca era visitado aqui (o loop original só percorre variações), então
#                  altura/largura/comprimento_ordenada_cm ficavam None pra sempre — mesmo com
#                  embalagem certinha no ERP. Isso quebrava exatamente o caso que a linha de
#                  fallback da Grade (variacao=None, "sempre calculado, mesmo sem MLB
#                  publicado") foi feita pra cobrir: sem esses campos, o fallback também caía
#                  em SEM CÁLCULO. Confirmado em produção (11/09/2026): 198/198 produtos
#                  MAGAZINE e 198/198 SAMVALE em "dimensão zerada" eram exatamente esse caso —
#                  zero exceções com erro real de cadastro. `processar_produtos_sem_variacao`
#                  fecha essa lacuna: processa direto do lado Produto (só ERP, sem lado ML pra
#                  comparar — não há variação nenhuma), reaproveitando o mesmo
#                  obter_dimensoes_envio() que o loop principal já usa.

from mercado_livre.models import VariacaoAnuncioMercadoLivre
from produtos.models import Produto
from mercado_livre.funcoes_auxiliares.comparador_dimensao_envio import (
    SituacaoDimensaoEnvio, comparar_dimensoes_envio,
)
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO


# Função Objetivo: Processa 1 variação — organiza as dimensões dos 2 lados e decide a situação.
class ProcessadorDivergenciaDimensaoEnvio:

    def __init__(self, variacao):
        self.variacao = variacao
        self.situacao = None
        self.dimensoes_produto = None
        self.dimensoes_variacao = None

    # Função Objetivo: Roda o processamento inteiro desta variação, na ordem certa.
    def processar(self):
        self.dimensoes_variacao = self.variacao.obter_dimensoes_envio()

        if self.variacao.produto is None:
            self.situacao = SituacaoDimensaoEnvio.SEM_PRODUTO_VINCULADO
            return self

        self.dimensoes_produto = self.variacao.produto.obter_dimensoes_envio()
        self.situacao = comparar_dimensoes_envio(self.dimensoes_produto, self.dimensoes_variacao)
        return self

    # Função Objetivo: Aplica as dimensões ordenadas calculadas no objeto Produto (em memória).
    def aplicar_no_produto(self):
        produto = self.variacao.produto
        produto.altura_ordenada_cm = self.dimensoes_produto.dimensao_menor
        produto.largura_ordenada_cm = self.dimensoes_produto.dimensao_media
        produto.comprimento_ordenada_cm = self.dimensoes_produto.dimensao_maior

    # Função Objetivo: Aplica as dimensões ordenadas + situação no objeto Variação (em memória).
    def aplicar_na_variacao(self):
        self.variacao.altura_ordenada_cm = self.dimensoes_variacao.dimensao_menor
        self.variacao.largura_ordenada_cm = self.dimensoes_variacao.dimensao_media
        self.variacao.comprimento_ordenada_cm = self.dimensoes_variacao.dimensao_maior
        self.variacao.situacao_dimensao_envio = self.situacao


# Função Objetivo: Orquestra o processamento inteiro, de todas as variações até o banco.
class OrganizadorDivergenciaDimensaoEnvio:

    CAMPOS_VARIACAO = [
        'altura_ordenada_cm', 'largura_ordenada_cm', 'comprimento_ordenada_cm',
        'situacao_dimensao_envio',
    ]
    CAMPOS_PRODUTO = [
        'altura_ordenada_cm', 'largura_ordenada_cm', 'comprimento_ordenada_cm',
    ]

    def __init__(self, stdout):
        self.stdout = stdout
        self.variacoes = []
        self.variacoes_para_atualizar = []
        # * [EXPLICAÇÃO] → dict por pk, não lista — vários MLBs podem compartilhar o
        #                  mesmo Produto (mesmo SKU), e o cálculo do lado Produto é
        #                  idêntico pra todos eles; dedup evita bulk_update repetido
        #                  do mesmo produto várias vezes.
        self.produtos_para_atualizar = {}
        self.contagem_por_situacao = {estado.value: 0 for estado in SituacaoDimensaoEnvio}
        self.produtos_sem_variacao_processados = 0

    # Função Objetivo: Carrega todas as variações, com o produto já pré-carregado.
    def carregar_variacoes(self):
        self.variacoes = list(
            VariacaoAnuncioMercadoLivre.objects.select_related('produto').all()
        )

    # Função Objetivo: Processa cada variação, com barra de progresso.
    def processar_variacoes(self):
        total = len(self.variacoes)

        for indice, variacao in enumerate(self.variacoes, start=1):
            if indice % 500 == 0 or indice == total:
                self.stdout.write(f'    ... {indice}/{total} variações processadas')

            processador = ProcessadorDivergenciaDimensaoEnvio(variacao).processar()
            processador.aplicar_na_variacao()
            self.variacoes_para_atualizar.append(variacao)
            self.contagem_por_situacao[processador.situacao] += 1

            if processador.dimensoes_produto is not None:
                processador.aplicar_no_produto()
                self.produtos_para_atualizar[variacao.produto.pk] = variacao.produto

    # Função Objetivo: Processa direto do lado Produto os que não têm NENHUMA variação —
    # o loop acima nunca os alcança (só percorre VariacaoAnuncioMercadoLivre existente).
    # Explicação em detalhe: sem variação não há o que comparar nem SituacaoDimensaoEnvio pra
    # gravar (esse campo mora na Variação, que não existe aqui) — só organiza o lado ERP mesmo,
    # pra pelo menos a linha de fallback da Grade (variacao=None) ter dado de verdade pra
    # calcular, em vez de cair em "dimensão zerada" só por nunca ter sido visitada.
    def processar_produtos_sem_variacao(self):
        produtos_com_variacao_ids = {
            variacao.produto_id for variacao in self.variacoes if variacao.produto_id is not None
        }
        produtos_sem_variacao = Produto.objects.exclude(id__in=produtos_com_variacao_ids)

        for produto in produtos_sem_variacao.iterator():
            dimensoes = produto.obter_dimensoes_envio()
            produto.altura_ordenada_cm = dimensoes.dimensao_menor
            produto.largura_ordenada_cm = dimensoes.dimensao_media
            produto.comprimento_ordenada_cm = dimensoes.dimensao_maior
            self.produtos_para_atualizar[produto.pk] = produto
            self.produtos_sem_variacao_processados += 1

    # Função Objetivo: Grava tudo no banco em lote — 1 bulk_update por model.
    def salvar(self):
        if self.variacoes_para_atualizar:
            VariacaoAnuncioMercadoLivre.objects.bulk_update(
                self.variacoes_para_atualizar, self.CAMPOS_VARIACAO, batch_size=BATCH_SIZE_PADRAO
            )
        if self.produtos_para_atualizar:
            Produto.objects.bulk_update(
                list(self.produtos_para_atualizar.values()), self.CAMPOS_PRODUTO, batch_size=BATCH_SIZE_PADRAO
            )

    # Função Objetivo: Roda o processamento inteiro, do carregamento ao banco.
    def rodar(self):
        self.carregar_variacoes()
        self.processar_variacoes()
        self.processar_produtos_sem_variacao()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        linhas = [
            '[DIMENSÃO DE ENVIO — ORGANIZAR E COMPARAR] Concluído!',
            f'    Variações processadas: {len(self.variacoes_para_atualizar)}',
            f'    Produtos sem nenhuma variação (processados só pelo lado ERP): {self.produtos_sem_variacao_processados}',
            f'    Produtos com dimensão ordenada atualizada: {len(self.produtos_para_atualizar)}',
        ]
        for estado in SituacaoDimensaoEnvio:
            linhas.append(f'    {estado.label}: {self.contagem_por_situacao[estado.value]}')
        return '\n'.join(linhas)


# Função Objetivo: Ponto de entrada chamado pelo popular_banco (ou pelo comando fino solto).
def organizar_e_verificar_divergencias_dimensoes_envio(stdout, style):
    stdout.write('[DIMENSÃO DE ENVIO — ORGANIZAR E COMPARAR] Processando...')

    organizador = OrganizadorDivergenciaDimensaoEnvio(stdout)
    organizador.rodar()

    stdout.write(style.SUCCESS(organizador.relatorio()))