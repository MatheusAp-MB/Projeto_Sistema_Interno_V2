# scripts_exploracao_ML/comparar_comissao_real_vs_flat_via_api.py

# Função Objetivo: Compara a comissão REAL retornada pelo endpoint de estimativa pré-venda
# do Mercado Livre (GET /sites/{SITE_ID}/listing_prices) contra o valor FIXO configurado hoje
# em ConfiguracaoTipoAnuncioMercadoLivre.comissao (1 valor único por tipo_anuncio, sem
# variação por categoria) — pra medir o tamanho real da divergência antes de qualquer decisão
# de arquitetura (ver Checkpoint - Investigação da Comissão Real de Venda via API do Mercado
# Livre, Seção 6, 23/09/2026).
#
# Só interessa a comissão PRÉ-VENDA (sale_fee_amount / sale_fee_details.percentage_fee do
# listing_prices) — comissão pós-venda (order_items[].sale_fee) e reconciliação (billing) NÃO
# são objeto deste script, por decisão explícita de Matheus (ver mesmo checkpoint, Seção 6).
#
# 2ª rodada (24/09): a 1ª bateria (Seção 7 do checkpoint) achou 5 casos Premium com comissão
# fora da faixa documentada (10-14% Clássico / 15-19% Premium, doc "Costos de Venta", Frente A
# Seção 9) — 13,5%-14% em anúncios Premium, exatamente dentro da faixa de CLÁSSICO. Suspeita:
# a API pode estar tratando esses anúncios como um tipo diferente do que foi pedido. Esta
# versão adiciona 3 validações pra investigar isso:
#   1. Captura o listing_type_id que a API REALMENTE usou (vem na própria resposta) e compara
#      com o que foi enviado — expõe qualquer divergência silenciosa.
#   2. Checa automaticamente se o percentual retornado cai dentro da faixa documentada
#      (Clássico 10-14% / Premium 15-19%) — sinaliza os casos fora como suspeitos.
#   3. Modo --mlbs: testa MLBs específicos direto do próprio anúncio real (/items/{mlb}), sem
#      passar pelo banco local — inclui um gabarito conhecido (MLB3519337227, validado contra
#      uma tela real do Simulador de Custos do ML, não contra a nossa própria API) pra uma
#      validação com fonte de verdade independente.
#
# Cada MLB testado gera até 2 chamadas: 1x /items/{mlb} pra pegar category_id/listing_type_id
# (cacheado por MLB, igual aos scripts de frete) + 1x /sites/{SITE_ID}/listing_prices com
# price/category_id/listing_type_id. Uma 2ª chamada de listing_prices (repetida, mesmos
# parâmetros) é feita pra uma amostra menor dos candidatos, só no modo normal (sem --mlbs), pra
# checar estabilidade do valor dentro da mesma sessão.
#
# Não passa logistic_type/shipping_mode de propósito: pela doc, esses parâmetros afetam
# sale_fee_details.fixed_fee (componente de custo de envio embutido na comissão em certos
# casos), não o percentage_fee — que é o que interessa comparar contra o flat. fixed_fee ainda
# é capturado e mostrado na tabela, só não é o critério de comparação.
#
# Amostra (modo normal, sem --mlbs): MLBs reais ativos com preco_atual preenchido, espalhados
# por preço (do mais barato ao mais caro) e balanceados entre Clássico/Premium — não filtra por
# categoria porque o ERP não guarda category_id do ML (só um campo de texto livre, achado já
# confirmado na Frente A); a diversidade de categoria vem naturalmente de pegar produtos
# distintos reais.
#
# Uso: python -u "scripts_exploracao_ML/comparar_comissao_real_vs_flat_via_api.py" [opções]
# --empresa: MB (Magazine) ou SV (Samvale) — default MB.
# --limite: máximo de MLBs testados via API, no modo normal (ignorado com --mlbs). Default: 30.
# --repetir-verificacao: quantos dos candidatos testados recebem uma 2ª chamada idêntica pra
#   checar estabilidade do valor, no modo normal (ignorado com --mlbs). Default: 5.
# --mlbs: lista de MLBs específicos separados por vírgula (ex: MLB123,MLB456) — testa só eles,
#   direto do próprio anúncio real via API, ignorando --limite e a amostragem do banco.
#
# Só leitura no banco e na API — nenhuma escrita em lugar nenhum, além do JSON de saída (mesmo
# padrão dos outros scripts de exploração).

import os
import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass
from decimal import Decimal


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

SITE_ID = 'MLB'  # as 2 empresas (MB/SV) operam só no site Brasil

# ==== ARGUMENTOS DE LINHA DE COMANDO ====
parser = argparse.ArgumentParser(
    description='Compara a comissão real (listing_prices) contra o valor fixo configurado '
                 '(ConfiguracaoTipoAnuncioMercadoLivre.comissao) — só a camada pré-venda.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB',
                     help='Empresa/conta ML — MB (Magazine) ou SV (Samvale). Default: MB.')
parser.add_argument('--limite', type=int, default=30,
                     help='Máximo de MLBs a testar de fato via API, no modo normal. Default: 30.')
parser.add_argument('--repetir-verificacao', type=int, default=5,
                     help='Quantos dos candidatos testados recebem uma 2ª chamada idêntica, '
                          'no modo normal. Default: 5.')
parser.add_argument('--mlbs', type=str, default=None,
                     help='Lista de MLBs específicos separados por vírgula (ex: MLB123,MLB456) '
                          '— testa só eles, direto do anúncio real via API, ignorando --limite '
                          'e a amostragem do banco.')
args = parser.parse_args()

CONTA = args.empresa

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])
# * [EXPLICAÇÃO] → Mesmo motivo dos outros scripts: sem isso o Django cai no banco default, e
#                  pra --empresa SV isso leria dado do MB silenciosamente.

LIMITE_CANDIDATOS = args.limite
QTD_REPETIR_VERIFICACAO = args.repetir_verificacao
MLBS_DIRECIONADOS = [m.strip() for m in args.mlbs.split(',') if m.strip()] if args.mlbs else None

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
SUFIXO_SAIDA = "direcionado" if MLBS_DIRECIONADOS else CONTA
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"comparacao_comissao_real_vs_flat_{SUFIXO_SAIDA}.json"

# Faixa documentada oficialmente (doc "Costos de Venta", já registrada no Checkpoint Frente A,
# Seção 9) — usada pra sinalizar resultados suspeitos, não como regra rígida (a doc já avisa
# que existe variação por categoria dentro dessas faixas).
FAIXA_DOCUMENTADA_POR_TIPO = {
    TipoDeAnuncioMercadoLivre.TipoAnuncio.CLASSICO: (Decimal('10'), Decimal('14')),
    TipoDeAnuncioMercadoLivre.TipoAnuncio.PREMIUM: (Decimal('15'), Decimal('19')),
}

# Gabarito conhecido — validado contra uma tela REAL do Simulador de Custos do Mercado Livre
# (não contra a nossa própria API), enviada por Matheus. Fonte independente, pra validação
# forte quando esse MLB específico aparecer num teste (normal ou --mlbs).
GABARITO_CONHECIDO = {
    "MLB3519337227": {
        "percentage_fee_esperado": Decimal('11'),
        "sale_fee_amount_esperado": Decimal('39.42'),
        "price_usado_na_tela": Decimal('358.35'),
        "fonte": "Simulador de Custos — tela real, print enviado por Matheus",
    },
}


# ==== Comissão flat configurada hoje, por tipo_anuncio (o que estamos comparando) ====
COMISSAO_FLAT_POR_TIPO = {
    config.tipo_anuncio: config.comissao
    for config in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()
}
if not COMISSAO_FLAT_POR_TIPO:
    console.print('[bold red]Nenhuma ConfiguracaoTipoAnuncioMercadoLivre encontrada — nada pra comparar.[/bold red]')
    sys.exit(1)


def buscar_category_id_e_tipo(mlb):
    """Busca category_id E listing_type_id direto do próprio anúncio real (/items/{mlb}) —
    usado no modo --mlbs, pra eliminar qualquer diferença entre o que está cadastrado
    localmente e o que a API realmente vê hoje. Também devolve o price atual do anúncio."""
    resposta = chamar_api("GET", f"/items/{mlb}", pasta_logs=PASTA_LOGS, conta=CONTA,
                           nome_log="comparar_comissao_real_vs_flat_via_api")
    corpo = resposta.json()
    return {
        "category_id": corpo["category_id"],
        "listing_type_id": corpo["listing_type_id"],
        "price": Decimal(str(corpo["price"])),
    }


def buscar_category_id(mlb):
    """Só pega category_id — usado no modo normal (amostra do banco), onde o price e o
    listing_type_id já vêm do banco local."""
    resposta = chamar_api("GET", f"/items/{mlb}", pasta_logs=PASTA_LOGS, conta=CONTA,
                           nome_log="comparar_comissao_real_vs_flat_via_api")
    return resposta.json()["category_id"]


def buscar_listing_prices(price, category_id, listing_type_id):
    """GET /sites/{SITE_ID}/listing_prices — comissão estimada pré-venda pra um price +
    category_id + listing_type_id. Não passa logistic_type/shipping_mode de propósito (ver
    cabeçalho do arquivo). Captura o listing_type_id que a API devolve na própria resposta,
    pra confirmar (ou não) que ela usou o mesmo tipo que foi enviado."""
    endpoint = f"/sites/{SITE_ID}/listing_prices"
    params = {
        "price": str(price),
        "category_id": category_id,
        "listing_type_id": listing_type_id,
    }
    resposta = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params,
        nome_log="comparar_comissao_real_vs_flat_via_api",
    )
    corpo = resposta.json()
    if isinstance(corpo, list):
        # * [EXPLICAÇÃO] → confirmado na 1ª rodada (24/09): a resposta veio como objeto único
        #                  nos 30 testes feitos — mas mantém essa defesa por precaução.
        if not corpo:
            raise ErroAPI(f"listing_prices não retornou nenhum resultado pra price={price}, "
                           f"category_id={category_id}, listing_type_id={listing_type_id}")
        corpo = corpo[0]
    if "sale_fee_amount" not in corpo:
        raise ErroAPI(f"listing_prices sem sale_fee_amount — resposta: {corpo}")
    detalhes = corpo.get("sale_fee_details") or {}
    return {
        "sale_fee_amount": Decimal(str(corpo["sale_fee_amount"])),
        "percentage_fee": Decimal(str(detalhes["percentage_fee"])) if detalhes.get("percentage_fee") is not None else None,
        "fixed_fee": Decimal(str(detalhes["fixed_fee"])) if detalhes.get("fixed_fee") is not None else None,
        "listing_type_id_retornado": corpo.get("listing_type_id"),
    }


@dataclass
class CandidatoComissao:
    """Objeto de processo — 1 MLB selecionado pra teste (via amostra do banco ou via --mlbs).
    Nunca salvo no banco."""
    ean: str
    sku: str
    mlb: str
    tipo_anuncio: str    # 'gold_special' / 'gold_pro' — valor cru, pro parâmetro da API
    tipo_label: str      # 'Clássico' / 'Premium' — só exibição
    item_price: Decimal
    category_id: str | None = None  # já conhecido de antemão só no modo --mlbs


@dataclass
class ResultadoComissao:
    """Objeto de processo — resultado das chamadas à API pra 1 candidato. Nunca salvo no
    banco."""
    candidato: CandidatoComissao
    comissao_flat_percentual: Decimal | None
    sale_fee_amount: Decimal | None
    percentage_fee_api: Decimal | None
    fixed_fee_api: Decimal | None
    listing_type_id_retornado: str | None
    valor_estimado_pelo_flat: Decimal | None
    diferenca_absoluta: Decimal | None
    percentage_fee_api_repeticao: Decimal | None  # só preenchido pros candidatos re-testados
    erro: str | None

    @property
    def diverge_do_flat(self) -> bool | None:
        """Compara o PERCENTUAL retornado pela API contra o percentual flat configurado —
        não é igualdade exata de centavos, é igualdade de percentual (2 casas)."""
        if self.percentage_fee_api is None or self.comissao_flat_percentual is None:
            return None
        return self.percentage_fee_api.quantize(Decimal('0.01')) != self.comissao_flat_percentual.quantize(Decimal('0.01'))

    @property
    def instavel_na_repeticao(self) -> bool | None:
        """True quando a 2ª chamada (mesmos parâmetros exatos) devolveu percentage_fee
        diferente da 1ª — sinal direto de que o valor NÃO é cacheável com confiança."""
        if self.percentage_fee_api_repeticao is None or self.percentage_fee_api is None:
            return None
        return self.percentage_fee_api_repeticao != self.percentage_fee_api

    @property
    def listing_type_id_bate(self) -> bool | None:
        """True quando o listing_type_id que a API REALMENTE usou (retornado na resposta) é
        igual ao que foi ENVIADO (candidato.tipo_anuncio) — False aqui é o sinal concreto de
        que a API está silenciosamente tratando o anúncio como um tipo diferente do pedido."""
        if self.listing_type_id_retornado is None:
            return None
        return self.listing_type_id_retornado == self.candidato.tipo_anuncio

    @property
    def dentro_da_faixa_documentada(self) -> bool | None:
        """Checa se percentage_fee_api cai dentro da faixa oficial documentada pro tipo_anuncio
        ENVIADO (10-14% Clássico / 15-19% Premium, doc Costos de Venta) — sinaliza suspeita,
        não prova erro (a doc já avisa que existe variação por categoria dentro da faixa)."""
        if self.percentage_fee_api is None:
            return None
        faixa = FAIXA_DOCUMENTADA_POR_TIPO.get(self.candidato.tipo_anuncio)
        if faixa is None:
            return None
        minimo, maximo = faixa
        return minimo <= self.percentage_fee_api <= maximo

    @property
    def gabarito_bate(self) -> bool | None:
        """Compara contra GABARITO_CONHECIDO quando o MLB testado é um dos que têm fonte
        independente confirmada (tela real do Simulador de Custos, não a nossa API)."""
        gabarito = GABARITO_CONHECIDO.get(self.candidato.mlb)
        if gabarito is None or self.percentage_fee_api is None:
            return None
        return self.percentage_fee_api.quantize(Decimal('0.01')) == gabarito['percentage_fee_esperado'].quantize(Decimal('0.01'))


# ========== Montagem dos candidatos ==========

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
Status = TipoDeAnuncioMercadoLivre.Status


def _tipo_label(tipo_anuncio_valor):
    return 'Clássico' if tipo_anuncio_valor == TipoAnuncio.CLASSICO else 'Premium'


def montar_candidatos_direcionados(lista_mlbs):
    """Modo --mlbs: busca cada MLB direto do próprio anúncio real (/items/{mlb}) — category_id,
    listing_type_id e price vêm de lá, não do banco local. Preenche cache_category_id de
    brinde, já que a chamada já devolveu o category_id."""
    candidatos = []
    cache = {}
    for mlb in lista_mlbs:
        try:
            info = buscar_category_id_e_tipo(mlb)
        except (ErroAPI, ErroAutenticacaoAPI) as erro:
            console.print(f'[bold red]Erro buscando {mlb} direto da API: {erro}[/bold red]')
            continue
        tipo_anuncio_valor = info['listing_type_id']
        candidatos.append(CandidatoComissao(
            ean='(direto)', sku='(direto)', mlb=mlb,
            tipo_anuncio=tipo_anuncio_valor, tipo_label=_tipo_label(tipo_anuncio_valor),
            item_price=info['price'], category_id=info['category_id'],
        ))
        cache[mlb] = info['category_id']
    return candidatos, cache


def montar_candidatos_da_amostra():
    """Modo normal: MLBs reais ativos com preco_atual preenchido, do banco local."""
    variacoes = (
        VariacaoAnuncioMercadoLivre.objects
        .filter(
            preco_atual__isnull=False,
            produto__isnull=False,
            anuncio__tipo_de_anuncio__status=Status.ATIVO,
        )
        .select_related('anuncio', 'anuncio__tipo_de_anuncio', 'produto')
    )

    candidatos = []
    for variacao in variacoes:
        item_price = variacao.preco_atual
        if item_price <= 0:
            continue

        tipo_anuncio_valor = variacao.anuncio.tipo_de_anuncio.tipo_anuncio
        if tipo_anuncio_valor not in COMISSAO_FLAT_POR_TIPO:
            continue  # sem config flat pra comparar — não deveria acontecer, mas não trava o script

        candidatos.append(CandidatoComissao(
            ean=variacao.produto.ean,
            sku=variacao.produto.sku,
            mlb=variacao.anuncio.mlb,
            tipo_anuncio=tipo_anuncio_valor,
            tipo_label=_tipo_label(tipo_anuncio_valor),
            item_price=item_price,
        ))
    return candidatos


def _espalhar(lista, quantidade):
    """Pega até `quantidade` itens espalhados uniformemente pela lista ordenada por preço
    (não só os N primeiros) — maximiza a variação de preço testada."""
    if not lista or quantidade <= 0:
        return []
    if len(lista) <= quantidade:
        return lista
    passo = len(lista) / quantidade
    return [lista[int(i * passo)] for i in range(quantidade)]


# ========== Fluxo principal ==========

if MLBS_DIRECIONADOS:
    console.print(Panel(
        '[bold]Comparação de Comissão — Validação Direcionada (MLBs específicos)[/bold]\n'
        f'Conta {CONTA} — testando {len(MLBS_DIRECIONADOS)} MLB(s) direto do anúncio real',
        border_style='blue',
    ))
    selecionados, cache_category_id = montar_candidatos_direcionados(MLBS_DIRECIONADOS)
    if not selecionados:
        console.print('[bold red]Nenhum MLB direcionado pôde ser carregado — nada pra testar.[/bold red]')
        sys.exit(1)
    QTD_REPETIR_VERIFICACAO = 0  # modo direcionado não faz checagem de estabilidade por default
else:
    console.print(Panel(
        '[bold]Comparação de Comissão — Real (API, listing_prices) x Flat (configuração atual)[/bold]\n'
        f'Conta {CONTA} — só camada pré-venda, pra decidir se vale substituir/complementar o valor fixo',
        border_style='blue',
    ))
    candidatos = montar_candidatos_da_amostra()
    if not candidatos:
        console.print('[bold red]Nenhum candidato encontrado com preço/anúncio ativo — nada pra testar.[/bold red]')
        sys.exit(1)
    console.print(f'{len(candidatos)} candidato(s) com dado completo encontrado(s) no catálogo.\n')

    classicos = sorted([c for c in candidatos if c.tipo_anuncio == TipoAnuncio.CLASSICO], key=lambda c: c.item_price)
    premiums = sorted([c for c in candidatos if c.tipo_anuncio == TipoAnuncio.PREMIUM], key=lambda c: c.item_price)
    metade = LIMITE_CANDIDATOS // 2
    selecionados = _espalhar(classicos, metade) + _espalhar(premiums, LIMITE_CANDIDATOS - metade)
    selecionados.sort(key=lambda c: c.item_price)
    cache_category_id = {}

tabela_selecao = Table(title=f'Candidatos selecionados pra teste ({len(selecionados)})')
tabela_selecao.add_column('EAN')
tabela_selecao.add_column('MLB')
tabela_selecao.add_column('Tipo')
tabela_selecao.add_column('Preço', justify='right')
for c in selecionados:
    tabela_selecao.add_row(c.ean, c.mlb, c.tipo_label, f'R$ {c.item_price}')
console.print(tabela_selecao)

indices_para_repetir = set(
    int(i * (len(selecionados) / QTD_REPETIR_VERIFICACAO))
    for i in range(min(QTD_REPETIR_VERIFICACAO, len(selecionados)))
) if QTD_REPETIR_VERIFICACAO > 0 and selecionados else set()

console.print(f'\nTestando {len(selecionados)} candidato(s) via API '
              f'({len(indices_para_repetir)} com verificação de estabilidade em dobro)...\n')

resultados = []

for indice, candidato in enumerate(selecionados):
    prefixo = f'[{indice + 1}/{len(selecionados)}] {candidato.mlb} ({candidato.tipo_label}, R$ {candidato.item_price})'
    comissao_flat = COMISSAO_FLAT_POR_TIPO.get(candidato.tipo_anuncio)

    if candidato.category_id is not None:
        category_id = candidato.category_id  # já veio pronto do modo --mlbs
    elif candidato.mlb in cache_category_id:
        category_id = cache_category_id[candidato.mlb]
    else:
        try:
            category_id = buscar_category_id(candidato.mlb)
            cache_category_id[candidato.mlb] = category_id
        except (ErroAPI, ErroAutenticacaoAPI) as erro:
            console.print(f'{prefixo}: [bold red]erro buscando category_id: {erro}[/bold red]')
            resultados.append(ResultadoComissao(
                candidato=candidato, comissao_flat_percentual=comissao_flat,
                sale_fee_amount=None, percentage_fee_api=None, fixed_fee_api=None,
                listing_type_id_retornado=None,
                valor_estimado_pelo_flat=None, diferenca_absoluta=None,
                percentage_fee_api_repeticao=None, erro=str(erro),
            ))
            continue

    percentage_fee_api_repeticao = None
    sale_fee_amount = None
    percentage_fee_api = None
    fixed_fee_api = None
    listing_type_id_retornado = None
    erro_candidato = None
    try:
        resposta = buscar_listing_prices(candidato.item_price, category_id, candidato.tipo_anuncio)
        sale_fee_amount = resposta["sale_fee_amount"]
        percentage_fee_api = resposta["percentage_fee"]
        fixed_fee_api = resposta["fixed_fee"]
        listing_type_id_retornado = resposta["listing_type_id_retornado"]

        if indice in indices_para_repetir:
            try:
                resposta_repeticao = buscar_listing_prices(candidato.item_price, category_id, candidato.tipo_anuncio)
                percentage_fee_api_repeticao = resposta_repeticao["percentage_fee"]
            except (ErroAPI, ErroAutenticacaoAPI) as erro:
                console.print(f'    [yellow]erro na 2ª chamada de verificação: {erro}[/yellow]')
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        erro_candidato = str(erro)

    valor_estimado_pelo_flat = None
    diferenca_absoluta = None
    if comissao_flat is not None and sale_fee_amount is not None:
        valor_estimado_pelo_flat = (candidato.item_price * comissao_flat / 100).quantize(Decimal('0.01'))
        diferenca_absoluta = (sale_fee_amount - valor_estimado_pelo_flat).quantize(Decimal('0.01'))

    resultado = ResultadoComissao(
        candidato=candidato, comissao_flat_percentual=comissao_flat,
        sale_fee_amount=sale_fee_amount, percentage_fee_api=percentage_fee_api, fixed_fee_api=fixed_fee_api,
        listing_type_id_retornado=listing_type_id_retornado,
        valor_estimado_pelo_flat=valor_estimado_pelo_flat, diferenca_absoluta=diferenca_absoluta,
        percentage_fee_api_repeticao=percentage_fee_api_repeticao, erro=erro_candidato,
    )
    resultados.append(resultado)

    if resultado.erro:
        console.print(f'{prefixo}: [yellow]erro — {resultado.erro}[/yellow]')
    elif resultado.diverge_do_flat is True:
        console.print(f'{prefixo}: [bold red]✗ diverge — API {percentage_fee_api}% x flat {comissao_flat}% '
                       f'(diferença R$ {diferenca_absoluta})[/bold red]')
    elif resultado.diverge_do_flat is False:
        console.print(f'{prefixo}: [green]✓ igual ao flat ({percentage_fee_api}%)[/green]')
    else:
        console.print(f'{prefixo}: [dim]sem comparação possível[/dim]')

    if resultado.listing_type_id_bate is False:
        console.print(f'    [bold red]⚠ TIPO NÃO BATE: enviado {candidato.tipo_anuncio}, '
                       f'API confirmou ter usado {resultado.listing_type_id_retornado}[/bold red]')

    if resultado.dentro_da_faixa_documentada is False:
        faixa = FAIXA_DOCUMENTADA_POR_TIPO.get(candidato.tipo_anuncio)
        console.print(f'    [bold yellow]⚠ FORA DA FAIXA DOCUMENTADA: {percentage_fee_api}% fora de '
                       f'{faixa[0]}-{faixa[1]}% ({candidato.tipo_label})[/bold yellow]')

    if resultado.instavel_na_repeticao is True:
        console.print(f'    [bold yellow]⚠ INSTÁVEL na repetição: 1ª chamada {resultado.percentage_fee_api}%, '
                       f'2ª chamada {resultado.percentage_fee_api_repeticao}%[/bold yellow]')

    if candidato.mlb in GABARITO_CONHECIDO:
        gabarito = GABARITO_CONHECIDO[candidato.mlb]
        if resultado.gabarito_bate is True:
            console.print(f'    [bold green]✓ GABARITO CONHECIDO BATEU: {percentage_fee_api}% == '
                           f'{gabarito["percentage_fee_esperado"]}% esperado ({gabarito["fonte"]})[/bold green]')
        elif resultado.gabarito_bate is False:
            console.print(f'    [bold red]✗ GABARITO CONHECIDO NÃO BATEU: API deu {percentage_fee_api}%, '
                           f'esperado {gabarito["percentage_fee_esperado"]}% ({gabarito["fonte"]})[/bold red]')
            if candidato.item_price != gabarito['price_usado_na_tela']:
                console.print(f'    [dim]atenção: preço testado (R$ {candidato.item_price}) é diferente do '
                               f'preço da tela original (R$ {gabarito["price_usado_na_tela"]}) — pode ter mudado '
                               f'desde então[/dim]')

# ---- Tabela final + resumo ----
console.print()
tabela_resultado = Table(title='Resultado — Comissão Real (API) x Comissão Flat (configuração atual)')
tabela_resultado.add_column('MLB')
tabela_resultado.add_column('Tipo enviado')
tabela_resultado.add_column('Tipo API')
tabela_resultado.add_column('Preço', justify='right')
tabela_resultado.add_column('% Flat', justify='right')
tabela_resultado.add_column('% API', justify='right')
tabela_resultado.add_column('Diverge?', justify='center')
tabela_resultado.add_column('Doc?', justify='center')
tabela_resultado.add_column('Diferença (R$)', justify='right')
tabela_resultado.add_column('Instável?', justify='center')

for r in resultados:
    c = r.candidato
    if r.erro:
        marca_diverge, estilo = '[bold red]erro[/bold red]', 'red'
    elif r.diverge_do_flat is True:
        marca_diverge, estilo = '[bold red]✗[/bold red]', 'bold red'
    elif r.diverge_do_flat is False:
        marca_diverge, estilo = '[bold green]✓[/bold green]', 'green'
    else:
        marca_diverge, estilo = '[dim]—[/dim]', 'dim'

    if r.listing_type_id_bate is False:
        marca_tipo = '[bold red]✗[/bold red]'
    elif r.listing_type_id_bate is True:
        marca_tipo = '[dim]✓[/dim]'
    else:
        marca_tipo = '—'

    if r.dentro_da_faixa_documentada is False:
        marca_doc = '[bold yellow]✗[/bold yellow]'
    elif r.dentro_da_faixa_documentada is True:
        marca_doc = '[dim]✓[/dim]'
    else:
        marca_doc = '—'

    if r.instavel_na_repeticao is True:
        marca_instavel = '[bold yellow]⚠[/bold yellow]'
    elif r.instavel_na_repeticao is False:
        marca_instavel = '[dim]—[/dim]'
    else:
        marca_instavel = ''

    tabela_resultado.add_row(
        c.mlb, c.tipo_anuncio, r.listing_type_id_retornado or '—', f'R$ {c.item_price}',
        f'{r.comissao_flat_percentual}%' if r.comissao_flat_percentual is not None else '—',
        f'{r.percentage_fee_api}%' if r.percentage_fee_api is not None else '—',
        marca_diverge, marca_doc,
        f'R$ {r.diferenca_absoluta}' if r.diferenca_absoluta is not None else '—',
        marca_instavel,
        style=estilo,
    )
console.print(tabela_resultado)

total_com_resultado = sum(1 for r in resultados if r.diverge_do_flat is not None)
total_divergiu = sum(1 for r in resultados if r.diverge_do_flat is True)
total_tipo_nao_bate = sum(1 for r in resultados if r.listing_type_id_bate is False)
total_fora_da_faixa = sum(1 for r in resultados if r.dentro_da_faixa_documentada is False)
testados_repeticao = [r for r in resultados if r.percentage_fee_api_repeticao is not None]
instaveis = [r for r in testados_repeticao if r.instavel_na_repeticao is True]

console.print(f'\n[bold]Comissão API x Flat:[/bold] {total_divergiu}/{total_com_resultado} candidatos com percentual DIFERENTE do flat configurado.')
console.print(f'[bold]listing_type_id enviado x devolvido pela API:[/bold] {total_tipo_nao_bate} candidato(s) com tipo DIFERENTE do que foi enviado.')
console.print(f'[bold]Fora da faixa documentada (Costos de Venta):[/bold] {total_fora_da_faixa} candidato(s).')
if testados_repeticao:
    console.print(f'[bold]Estabilidade (mesma chamada repetida):[/bold] {len(instaveis)}/{len(testados_repeticao)} '
                  f'candidato(s) retornaram percentual DIFERENTE entre a 1ª e a 2ª chamada.')

if total_tipo_nao_bate:
    console.print(f'\n[bold red]{total_tipo_nao_bate} candidato(s) com listing_type_id que a API NÃO confirmou como o enviado:[/bold red]')
    for r in resultados:
        if r.listing_type_id_bate is False:
            console.print(f'  [red]MLB {r.candidato.mlb}: enviado {r.candidato.tipo_anuncio}, '
                           f'API confirmou {r.listing_type_id_retornado}[/red]')

if total_fora_da_faixa:
    console.print(f'\n[bold yellow]{total_fora_da_faixa} candidato(s) com % fora da faixa documentada:[/bold yellow]')
    for r in resultados:
        if r.dentro_da_faixa_documentada is False:
            faixa = FAIXA_DOCUMENTADA_POR_TIPO.get(r.candidato.tipo_anuncio)
            console.print(f'  [yellow]MLB {r.candidato.mlb} ({r.candidato.tipo_label}): API {r.percentage_fee_api}%, '
                           f'faixa documentada {faixa[0]}-{faixa[1]}%[/yellow]')

console.print('\n[dim]Ver Checkpoint - Investigação da Comissão Real de Venda via API do Mercado Livre, '
              'Seção 7/8, pro contexto completo.[/dim]')

# ---- Salva JSON com o detalhe completo ----


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Tipo não serializável: {type(obj)}')


saida = {
    "contexto": {
        "conta": CONTA,
        "modo": "direcionado" if MLBS_DIRECIONADOS else "amostra",
        "mlbs_direcionados": MLBS_DIRECIONADOS,
        "limite": LIMITE_CANDIDATOS,
        "qtd_repetir_verificacao": QTD_REPETIR_VERIFICACAO,
        "total_selecionados": len(selecionados),
    },
    "resultados": [
        {
            "ean": r.candidato.ean,
            "sku": r.candidato.sku,
            "mlb": r.candidato.mlb,
            "tipo_anuncio_enviado": r.candidato.tipo_anuncio,
            "listing_type_id_retornado": r.listing_type_id_retornado,
            "listing_type_id_bate": r.listing_type_id_bate,
            "item_price": r.candidato.item_price,
            "comissao_flat_percentual": r.comissao_flat_percentual,
            "sale_fee_amount": r.sale_fee_amount,
            "percentage_fee_api": r.percentage_fee_api,
            "fixed_fee_api": r.fixed_fee_api,
            "valor_estimado_pelo_flat": r.valor_estimado_pelo_flat,
            "diferenca_absoluta": r.diferenca_absoluta,
            "diverge_do_flat": r.diverge_do_flat,
            "dentro_da_faixa_documentada": r.dentro_da_faixa_documentada,
            "gabarito_bate": r.gabarito_bate,
            "percentage_fee_api_repeticao": r.percentage_fee_api_repeticao,
            "instavel_na_repeticao": r.instavel_na_repeticao,
            "erro": r.erro,
        }
        for r in resultados
    ],
}

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2, default=_serializar)

console.print(f'\n[dim]Resultado completo salvo em: {CAMINHO_SAIDA}[/dim]')