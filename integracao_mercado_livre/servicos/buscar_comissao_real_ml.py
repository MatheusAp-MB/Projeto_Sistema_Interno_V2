# integracao_mercado_livre/servicos/buscar_comissao_real_ml.py
#
# Busca a Comissão Real de cada MLB (via API do Mercado Livre —
# GET /items/{mlb} + GET /sites/MLB/listing_prices, endpoint validado
# dígito a dígito em 24/09/2026 contra o Simulador de Custos real do
# ML — ver Checkpoint - Investigação da Comissão Real de Venda via API
# do Mercado Livre, seção 8) e grava em VariacaoAnuncioMercadoLivre.
# comissao_real_percentual / .comissao_real_valor /
# .comissao_real_preco_usado / .comissao_real_atualizado_em.
#
# Não confundir com Comissão Aproximada
# (ConfiguracaoTipoAnuncioMercadoLivre.comissao, manual, só por
# tipo_anuncio) — essa aqui é a real, por MLB, dependente do preço
# vigente no momento da consulta.
#
# 2 chamadas por MLB (não por variação): GET /items/{mlb} — pra pegar
# category_id, listing_type_id e o price ATUAL do anúncio direto da
# fonte (nunca o preco_atual do banco local, que pode estar
# desatualizado) — e GET /sites/MLB/listing_prices com esses 3 dados.
# O resultado de /items/{mlb} é cacheado por MLB dentro da mesma
# execução — se o mesmo MLB tiver 2+ variações (mesmo padrão de
# frete_real, que também é por MLB salvo redundantemente em cada
# variação), a 2ª chamada de /items não se repete.
#
# Granularidade em 3 níveis (Matheus, 24/09) — mesmo motivo do frete:
# chamada de API é cara e demorada.
#   - Universal (nem --produto nem --mlb): só processa variações que
#     aparecem em pelo menos 1 linha de GradePrecificacaoML (relevantes
#     pra precificação hoje) — mesmo filtro que buscar_frete_real_ml
#     já usa.
#   - Por produto (--produto <sku>): todas as variações (Clássico e
#     Premium) daquele produto — ignora o filtro de Grade, porque o
# integracao_mercado_livre/servicos/buscar_comissao_real_ml.py
#
# Busca a Comissão Real de cada MLB (via API do Mercado Livre —
# GET /items/{mlb} + GET /sites/MLB/listing_prices, endpoint validado
# dígito a dígito em 24/09/2026 contra o Simulador de Custos real do
# ML — ver Checkpoint - Investigação da Comissão Real de Venda via API
# do Mercado Livre, seção 8) e grava em VariacaoAnuncioMercadoLivre.
# comissao_real_percentual / .comissao_real_valor /
# .comissao_real_preco_usado / .comissao_real_atualizado_em.
#
# Não confundir com Comissão Aproximada
# (ConfiguracaoTipoAnuncioMercadoLivre.comissao, manual, só por
# tipo_anuncio) — essa aqui é a real, por MLB, dependente do preço
# vigente no momento da consulta.
#
# 2 chamadas por MLB (não por variação): GET /items/{mlb} — pra pegar
# category_id, listing_type_id e o price ATUAL do anúncio direto da
# fonte (nunca o preco_atual do banco local, que pode estar
# desatualizado) — e GET /sites/MLB/listing_prices com esses 3 dados.
# O resultado de /items/{mlb} é cacheado por MLB dentro da mesma
# execução — se o mesmo MLB tiver 2+ variações (mesmo padrão de
# frete_real, que também é por MLB salvo redundantemente em cada
# variação), a 2ª chamada de /items não se repete.
#
# Granularidade em 3 níveis (Matheus, 24/09) — mesmo motivo do frete:
# chamada de API é cara e demorada.
#   - Universal (nem --produto nem --mlb): só processa variações que
#     aparecem em pelo menos 1 linha de GradePrecificacaoML (relevantes
#     pra precificação hoje) — mesmo filtro que buscar_frete_real_ml
#     já usa.
#   - Por produto (--produto <sku>): todas as variações (Clássico e
#     Premium) daquele produto — ignora o filtro de Grade, porque o
#     alvo já foi escolhido explicitamente.
#   - Por MLB (--mlb <mlb>): só as variações daquele anúncio específico
#     — mesmo motivo, alvo explícito.
#
# NÃO mexe em GradePrecificacaoML (comissao_calculada/origem_comissao)
# — isso é responsabilidade do cálculo de precificação em si, que
# ainda vai precisar ser atualizado como próxima etapa pra ler essa
# Comissão Real (decisão de uso na fórmula segue em aberto).
#
# 25/09: ao fim da execução, recalcula automaticamente a Comissão
# Média (Produto e Categoria, ver recalcular_comissao_media.py) só
# pros produto_ids/categoria_ids TOCADOS nesse run (nunca "tudo") —
# snapshot completo pra cada um, sem Django signal, decisão explícita
# (risco de loop/bug em cascata). Só entra no conjunto "tocado" quem
# teve sucesso — erro não muda nada, então não precisa recalcular.
#
# Peça 4 da reforma estrutural (27/09/2026): a chamada à API e a
# leitura da resposta saíram daqui e foram pra
# api_mercado_livre.comissao_real_ml.ComissaoRealML (Contexto), por
# trás de ApiMercadoLivre (Facade) — mesmo padrão do frete. Este
# arquivo continua 100% dono do laço, do console, da persistência e
# do recálculo de Comissão Média — nada disso mudou de comportamento.
#
# Otimização de coleta (29/09/2026 — "por etapas", 3 das 4 frentes
# combinadas neste arquivo; a 4ª, reuso de conexão TCP/TLS em
# chamar_api(), segue em validação isolada e FORA deste diff até
# confirmar com dado real se resolve algo — ver
# scripts_exploracao_ML/ativar_pool_conexao.py):
#   1. Cache cross-produto pra /listing_prices, por
#      (price, category_id, listing_type_id) — 57,8% das chamadas da
#      última rodada real eram duplicatas exatas dessa tupla (medido
#      via log, 0 chamada nova); estabilidade validada ao vivo (5/5
#      combinações mais repetidas, 0 divergência em 3 repetições cada).
#      Continua não sendo por MLB (o cache antigo de /items continua
#      separado, por MLB) — mesmo "cache cross-produto" já usado pro
#      frete (Frente A, seção 20).
#   2. Paralelismo via ThreadPoolExecutor dentro de cada grupo de
#      TAMANHO_GRUPO_EXIBICAO variações — throughput de
#      /listing_prices sob carga validado em
#      scripts_exploracao_ML/teste_paralelismo_listing_prices.py:
#      satura em ~20 threads simultâneas (~19,5 req/s), 0 erro real.
#      Mesma correção de threading.local() já aplicada em
#      calcular_grade_precificacao_ml.py (29/09/2026): empresa ativa é
#      lida 1x na thread principal e repassada — cada worker chama
#      definir_empresa_ativa() como 1ª linha.
#   3. Escrita em banco por bulk_update() (1 chamada por grupo de
#      TAMANHO_GRUPO_EXIBICAO, batch_size=BATCH_SIZE_PADRAO) em vez de
#      variacao.save() individual por MLB. Trade-off consciente: antes,
#      um crash no meio da execução perdia no máximo a variação em
#      andamento (save por item); agora perde, no pior caso, o grupo
#      inteiro em andamento (até TAMANHO_GRUPO_EXIBICAO variações) —
#      grupos já processados continuam gravados, nada é perdido além
#      do grupo interrompido.
#   4. Retorno de buscar_comissao_real_ml() e
#      _processar_variacao_comissao() (antigo
#      buscar_comissao_real_variacao()) trocado de dict solto pra
#      @dataclass (RelatorioComissaoReal / ResultadoComissaoVariacao)
#      — "objeto de processo/domínio" (ver "Modelagem de Objeto e
#      Encapsulamento" no vault), mesmo padrão de
#      RelatorioDeSincronizacao (integracao_sysemp/servicos/
#      orquestrador.py) — pendência 3 já registrada em "Camadas do
#      Cliente Mercado Livre" no vault, aplicada aqui primeiro por ser
#      o domínio em otimização agora.

import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.utils import timezone
from rich.console import Console

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa, obter_empresa_ativa
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from mercado_livre.funcoes_auxiliares.recalcular_comissao_media import recalcular_comissao_media

console = Console()

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/

NOME_PASTA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Magazine',
    EMPRESA_SAMVALE: 'Samvale',
}

TAMANHO_GRUPO_EXIBICAO = 20  # quantas variações por bloco visual no console — também é o
                              # tamanho do lote de paralelismo e o boundary do bulk_update
                              # (ver nota de otimização 29/09/2026 no cabeçalho do arquivo)

# * [EXPLICAÇÃO] → throughput de /sites/MLB/listing_prices sob ThreadPoolExecutor validado em
#                  scripts_exploracao_ML/teste_paralelismo_listing_prices.py: satura em ~20
#                  threads simultâneas (~19,5 req/s), 0 erro real, 0 warning de 429 em nenhum
#                  nível testado (5/10/20/30/50). Mesmo teto já encontrado independentemente
#                  pro frete (Frente A, seção 23) — sinal de que é propriedade da conta/conexão,
#                  não do endpoint específico. /items/{mlb} usa o mesmo teto por extrapolação
#                  (mesma conta, mesmo domínio de API) — não testado isoladamente porque o
#                  cache por MLB já reduz muito o volume desse endpoint.
MAX_WORKERS_COMISSAO_REAL = 20


@dataclass
class ResultadoComissaoVariacao:
    """Resultado de 1 variação processada — objeto de processo/domínio (nunca salvo no
    banco), mesma filosofia de "Modelagem de Objeto e Encapsulamento" no vault. motivo só é
    preenchido quando sucesso=False; percentual/valor só quando sucesso=True."""
    mlb: str
    sucesso: bool
    percentual: Decimal | None = None
    valor: Decimal | None = None
    motivo: str | None = None


@dataclass
class RelatorioComissaoReal:
    """Contagens e tempo de 1 execução completa do orquestrador — devolvido no lugar do
    dict cru anterior, mesmo padrão de RelatorioDeSincronizacao
    (integracao_sysemp/servicos/orquestrador.py)."""
    empresa: str
    total: int = 0
    com_sucesso: int = 0
    com_erro: int = 0
    duracao_total_segundos: float = 0.0
    resultados: list[ResultadoComissaoVariacao] = field(default_factory=list)
    produtos_recalculados: int = 0
    categorias_recalculadas: int = 0
    chamadas_items_economizadas_por_cache: int = 0
    chamadas_listing_prices_economizadas_por_cache: int = 0

def _pasta_empresa(empresa: str) -> str:
    if empresa not in NOME_PASTA_POR_EMPRESA:
        raise ValueError(f'Empresa inválida: "{empresa}". Use {list(NOME_PASTA_POR_EMPRESA)}.')
    return NOME_PASTA_POR_EMPRESA[empresa]

def _caminho_pasta_logs(empresa: str) -> Path:
    return RAIZ_APP / 'logs' / _pasta_empresa(empresa)

# Função Objetivo: Busca a Comissão Real de 1 variação (até 2 chamadas à API — 1 cacheada por
# MLB via cache_item_info, a outra cacheada cross-produto via cache_listing_prices) e devolve o
# resultado SEM gravar no banco — a gravação agora é em lote (bulk_update), feita pelo chamador
# ao fim de cada grupo (ver buscar_comissao_real_ml).
def _processar_variacao_comissao(
    empresa_ativa: str, variacao, api_ml: ApiMercadoLivre, cache_item_info: dict, cache_listing_prices: dict,
) -> ResultadoComissaoVariacao:
    # * [EXPLICAÇÃO] → mesma correção já aplicada no paralelismo por produto em
    #                  calcular_grade_precificacao_ml.py (29/09/2026): core.empresa guarda a
    #                  empresa ativa em threading.local() — cada thread nova do
    #                  ThreadPoolExecutor nasce com esse estado vazio, mesmo a thread
    #                  principal já tendo chamado definir_empresa_ativa() antes. empresa_ativa
    #                  é lido 1x na thread principal (ver chamador) e repassado — barato,
    #                  chamado 1x por variação. Mantido aqui mesmo a gravação tendo saído do
    #                  worker (bulk_update ficou no chamador) — convenção defensiva do
    #                  projeto pra qualquer worker de ThreadPoolExecutor que toque dado de
    #                  empresa, direta ou indiretamente.
    definir_empresa_ativa(empresa_ativa)

    mlb = variacao.anuncio.mlb

    try:
        if mlb in cache_item_info:
            item_info = cache_item_info[mlb]
        else:
            item_info = api_ml.buscar_item_info(mlb)
            cache_item_info[mlb] = item_info

        chave_listing_prices = (item_info["price"], item_info["category_id"], item_info["listing_type_id"])
        if chave_listing_prices in cache_listing_prices:
            resultado_api = cache_listing_prices[chave_listing_prices]
        else:
            resultado_api = api_ml.buscar_listing_prices(
                price=item_info["price"], category_id=item_info["category_id"],
                listing_type_id=item_info["listing_type_id"],
            )
            cache_listing_prices[chave_listing_prices] = resultado_api
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        return ResultadoComissaoVariacao(mlb=mlb, sucesso=False, motivo=str(e))

    if resultado_api["percentage_fee"] is None:
        return ResultadoComissaoVariacao(
            mlb=mlb, sucesso=False, motivo="resposta sem sale_fee_details.percentage_fee",
        )

    variacao.comissao_real_percentual = resultado_api["percentage_fee"]
    variacao.comissao_real_valor = resultado_api["sale_fee_amount"]
    variacao.comissao_real_preco_usado = item_info["price"]
    variacao.comissao_real_atualizado_em = timezone.now()

    return ResultadoComissaoVariacao(
        mlb=mlb, sucesso=True,
        percentual=resultado_api["percentage_fee"], valor=resultado_api["sale_fee_amount"],
    )

def _montar_queryset(produto_sku: str | None, mlb: str | None):
    from precificacao.models import GradePrecificacaoML
    from mercado_livre.models import VariacaoAnuncioMercadoLivre

    base = VariacaoAnuncioMercadoLivre.objects.select_related('anuncio', 'produto')

    if mlb:
        return base.filter(anuncio__mlb=mlb)
    if produto_sku:
        return base.filter(produto__sku=produto_sku)

    variacao_ids = (
        GradePrecificacaoML.objects
        .filter(variacao__isnull=False)
        .values_list('variacao_id', flat=True)
        .distinct()
    )
    return base.filter(id__in=variacao_ids)

def buscar_comissao_real_ml(empresa: str, produto_sku: str | None = None, mlb: str | None = None) -> RelatorioComissaoReal:
    """
    Ponto único de entrada. Busca a Comissão Real (API do ML) — universal,
    por produto ou por MLB (produto_sku/mlb mutuamente exclusivos) — grava
    direto em VariacaoAnuncioMercadoLivre e recalcula a Comissão Média
    (Produto/Categoria) só pra quem foi tocado nesse run. Precisa rodar com
    a empresa já ativa (definir_empresa_ativa) — quem chama isso é o
    management command, igual ao padrão de buscar_frete_real_ml.
    """
    from mercado_livre.models import VariacaoAnuncioMercadoLivre

    pasta_logs = _caminho_pasta_logs(empresa)
    api_ml = ApiMercadoLivre(pasta_logs=pasta_logs, empresa=empresa)

    variacoes = list(_montar_queryset(produto_sku, mlb))
    total = len(variacoes)

    alvo = f'MLB {mlb}' if mlb else (f'produto {produto_sku}' if produto_sku else 'universal (relevantes pra precificação)')
    console.print(f"Variações a processar ({empresa}, {alvo}): {total}\n")

    if total == 0:
        console.print("[yellow]Nenhuma variação encontrada pra esse escopo — nada a fazer.[/yellow]")
        return RelatorioComissaoReal(empresa=empresa, total=0)

    resultados: list[ResultadoComissaoVariacao] = []
    com_sucesso = 0
    com_erro = 0
    cache_item_info = {}
    cache_listing_prices = {}
    produtos_tocados = set()
    categorias_tocadas = set()
    inicio_execucao = time.perf_counter()

    empresa_ativa = obter_empresa_ativa()  # lido 1x na thread principal, repassado pra cada worker

    grupos = [variacoes[i:i + TAMANHO_GRUPO_EXIBICAO] for i in range(0, total, TAMANHO_GRUPO_EXIBICAO)]
    processadas = 0

    for indice_grupo, grupo in enumerate(grupos, start=1):
        decorrido = time.perf_counter() - inicio_execucao
        console.print(
            f"[bold]GRUPO {indice_grupo}/{len(grupos)}[/bold]  "
            f"({processadas}/{total} no total  •  {com_sucesso} com sucesso  •  {decorrido:.0f}s decorridos)"
        )

        variacoes_para_atualizar = []

        # * [EXPLICAÇÃO] → paralelismo dentro do grupo (29/09/2026) — as até
        #                  TAMANHO_GRUPO_EXIBICAO variações deste grupo rodam concorrentes,
        #                  throughput validado em teste_paralelismo_listing_prices.py. ATENÇÃO:
        #                  a ordem de conclusão (e portanto a ordem de exibição no console) NÃO
        #                  é mais a ordem original da lista — mesmo trade-off já aceito em
        #                  calcular_grade_precificacao_ml.py.
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_COMISSAO_REAL) as executor:
            futuros = {
                executor.submit(
                    _processar_variacao_comissao, empresa_ativa, variacao, api_ml, cache_item_info, cache_listing_prices,
                ): variacao
                for variacao in grupo
            }

            for futuro in as_completed(futuros):
                variacao = futuros[futuro]
                mlb_atual = variacao.anuncio.mlb

                try:
                    resultado = futuro.result()
                except Exception as e:
                    resultado = ResultadoComissaoVariacao(mlb=mlb_atual, sucesso=False, motivo=f"ERRO INESPERADO: {e}")

                resultados.append(resultado)

                if resultado.sucesso:
                    com_sucesso += 1
                    console.print(f"  ✓ {resultado.mlb:<20} {resultado.percentual}% (R$ {resultado.valor:.2f})")
                    variacoes_para_atualizar.append(variacao)
                    if variacao.produto_id:
                        produtos_tocados.add(variacao.produto_id)
                    if variacao.categoria_id:
                        categorias_tocadas.add(variacao.categoria_id)
                else:
                    com_erro += 1
                    console.print(f"  [red]✗ {resultado.mlb:<20} {resultado.motivo}[/red]")

                processadas += 1

        # * [EXPLICAÇÃO] → grava o grupo inteiro em 1 bulk_update (29/09/2026) em vez de
        #                  variacao.save() individual por MLB. Trade-off: antes, um crash no
        #                  meio da execução perdia no máximo a variação em andamento; agora
        #                  perde, no pior caso, o grupo inteiro em andamento (até
        #                  TAMANHO_GRUPO_EXIBICAO variações) — grupos já concluídos continuam
        #                  gravados normalmente, nada além do grupo interrompido é perdido.
        if variacoes_para_atualizar:
            VariacaoAnuncioMercadoLivre.objects.bulk_update(
                variacoes_para_atualizar,
                [
                    "comissao_real_percentual", "comissao_real_valor",
                    "comissao_real_preco_usado", "comissao_real_atualizado_em",
                ],
                batch_size=BATCH_SIZE_PADRAO,
            )

    duracao_total = time.perf_counter() - inicio_execucao

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green]")
    console.print(f"Com sucesso: {com_sucesso}/{total}  •  Com erro: {com_erro}/{total}")
    console.print(
        f"Tempo total: {duracao_total:.1f}s  •  "
        f"Chamadas a /items economizadas por cache: {total - len(cache_item_info)}  •  "
        f"Chamadas a /listing_prices economizadas por cache: {total - len(cache_listing_prices)}"
    )

    if com_erro:
        console.print("\n[yellow]Itens com erro (comissão real anterior, se existia, foi mantida sem alteração):[/yellow]")
        for r in resultados:
            if not r.sucesso:
                console.print(f"  {r.mlb}: {r.motivo}")

    recalculo = recalcular_comissao_media(
        produto_ids=produtos_tocados, categoria_ids=categorias_tocadas,
    )
    console.print(
        f"\n[bold]Comissão Média recalculada:[/bold] "
        f"{recalculo['produtos_atualizados']} produto(s) · {recalculo['categorias_atualizadas']} categoria(s)"
    )

    return RelatorioComissaoReal(
        empresa=empresa,
        total=total,
        com_sucesso=com_sucesso,
        com_erro=com_erro,
        duracao_total_segundos=round(duracao_total, 2),
        resultados=resultados,
        produtos_recalculados=recalculo['produtos_atualizados'],
        categorias_recalculadas=recalculo['categorias_atualizadas'],
        chamadas_items_economizadas_por_cache=total - len(cache_item_info),
        chamadas_listing_prices_economizadas_por_cache=total - len(cache_listing_prices),
    )   