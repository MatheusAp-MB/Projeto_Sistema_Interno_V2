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
# Cada MLB testado gera até 2 chamadas: 1x /items/{mlb} pra pegar category_id (cacheado por
# MLB, igual aos scripts de frete) + 1x /sites/{SITE_ID}/listing_prices com price=preco_atual,
# category_id, listing_type_id. Uma 2ª chamada de listing_prices (repetida, mesmos parâmetros)
# é feita pra uma amostra menor dos candidatos, só pra checar estabilidade do valor dentro da
# mesma sessão — a doc oficial avisa que "o mesmo produto pode ter comissões diferentes em
# momentos distintos", então uma divergência aqui já seria sinal de que o valor não é
# cacheável com confiança.
#
# Não passa logistic_type/shipping_mode de propósito: pela doc, esses parâmetros afetam
# sale_fee_details.fixed_fee (componente de custo de envio embutido na comissão em certos
# casos), não o percentage_fee — que é o que interessa comparar contra o flat. fixed_fee
# ainda é capturado e mostrado na tabela, só não é o critério de comparação.
#
# Incerteza registrada: não há confirmação 100% segura, só pela doc lida, se a resposta de
# listing_prices vem sempre como objeto único ou às vezes como lista — o código trata os 2
# formatos (pega o 1º item se vier lista), mas isso não foi validado contra uma chamada real
# ainda. Primeira rodada do script serve também pra esclarecer isso.
#
# Amostra: MLBs reais ativos com preco_atual preenchido, espalhados por preço (do mais barato
# ao mais caro) e balanceados entre Clássico/Premium — não filtra por categoria porque o ERP
# não guarda category_id do ML (só um campo de texto livre, achado já confirmado na Frente A);
# a diversidade de categoria vem naturalmente de pegar produtos distintos reais.
#
# Uso: python -u "scripts_exploracao_ML/comparar_comissao_real_vs_flat_via_api.py" [opções]
# --empresa: MB (Magazine) ou SV (Samvale) — default MB.
# --limite: máximo de MLBs testados via API. Default: 30.
# --repetir-verificacao: quantos dos candidatos testados recebem uma 2ª chamada idêntica pra
#   checar estabilidade do valor. Default: 5.
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
                     help='Máximo de MLBs a testar de fato via API. Default: 30.')
parser.add_argument('--repetir-verificacao', type=int, default=5,
                     help='Quantos dos candidatos testados recebem uma 2ª chamada idêntica, '
                          'pra checar estabilidade do valor dentro da mesma sessão. Default: 5.')
args = parser.parse_args()

CONTA = args.empresa

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])
# * [EXPLICAÇÃO] → Mesmo motivo dos outros scripts: sem isso o Django cai no banco default, e
#                  pra --empresa SV isso leria dado do MB silenciosamente.

LIMITE_CANDIDATOS = args.limite
QTD_REPETIR_VERIFICACAO = args.repetir_verificacao

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"comparacao_comissao_real_vs_flat_{CONTA}.json"


# ==== Comissão flat configurada hoje, por tipo_anuncio (o que estamos comparando) ====
COMISSAO_FLAT_POR_TIPO = {
    config.tipo_anuncio: config.comissao
    for config in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()
}
if not COMISSAO_FLAT_POR_TIPO:
    console.print('[bold red]Nenhuma ConfiguracaoTipoAnuncioMercadoLivre encontrada — nada pra comparar.[/bold red]')
    sys.exit(1)


def buscar_category_id(mlb):
    """Só pega category_id — mesma chamada /items/{mlb} já usada nos scripts de frete."""
    resposta = chamar_api("GET", f"/items/{mlb}", pasta_logs=PASTA_LOGS, conta=CONTA,
                           nome_log="comparar_comissao_real_vs_flat_via_api")
    return resposta.json()["category_id"]


def buscar_listing_prices(price, category_id, listing_type_id):
    """GET /sites/{SITE_ID}/listing_prices — comissão estimada pré-venda pra um price +
    category_id + listing_type_id. Não passa logistic_type/shipping_mode de propósito (ver
    cabeçalho do arquivo)."""
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
        # * [EXPLICAÇÃO] → incerteza registrada no cabeçalho do arquivo: a doc não deixa 100%
        #                  claro se a resposta vem sempre como objeto único ou às vezes como
        #                  lista. Como sempre mandamos listing_type_id explícito, esperamos 1
        #                  único resultado — mas cobre o formato caso venha em lista mesmo assim.
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
    }


@dataclass
class CandidatoComissao:
    """Objeto de processo — 1 VariacaoAnuncioMercadoLivre selecionada pra teste. Nunca salvo
    no banco."""
    ean: str
    sku: str
    mlb: str
    tipo_anuncio: str    # 'gold_special' / 'gold_pro' — valor cru, pro parâmetro da API
    tipo_label: str      # 'Clássico' / 'Premium' — só exibição
    item_price: Decimal


@dataclass
class ResultadoComissao:
    """Objeto de processo — resultado das chamadas à API pra 1 candidato. Nunca salvo no
    banco."""
    candidato: CandidatoComissao
    comissao_flat_percentual: Decimal | None
    sale_fee_amount: Decimal | None
    percentage_fee_api: Decimal | None
    fixed_fee_api: Decimal | None
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
        diferente da 1ª — sinal direto de que o valor NÃO é cacheável com confiança, exatamente
        o risco que a doc oficial já tinha avisado (ver Seção 3 do checkpoint)."""
        if self.percentage_fee_api_repeticao is None or self.percentage_fee_api is None:
            return None
        return self.percentage_fee_api_repeticao != self.percentage_fee_api


# ========== Fluxo principal ==========

console.print(Panel(
    '[bold]Comparação de Comissão — Real (API, listing_prices) x Flat (configuração atual)[/bold]\n'
    f'Conta {CONTA} — só camada pré-venda, pra decidir se vale substituir/complementar o valor fixo',
    border_style='blue',
))

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
Status = TipoDeAnuncioMercadoLivre.Status

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
        tipo_label='Clássico' if tipo_anuncio_valor == TipoAnuncio.CLASSICO else 'Premium',
        item_price=item_price,
    ))

if not candidatos:
    console.print('[bold red]Nenhum candidato encontrado com preço/anúncio ativo — nada pra testar.[/bold red]')
    sys.exit(1)

console.print(f'{len(candidatos)} candidato(s) com dado completo encontrado(s) no catálogo.\n')

# ---- Seleção: espalha por preço (mais barato ao mais caro) e balanceia Clássico/Premium ----
classicos = sorted([c for c in candidatos if c.tipo_anuncio == TipoAnuncio.CLASSICO], key=lambda c: c.item_price)
premiums = sorted([c for c in candidatos if c.tipo_anuncio == TipoAnuncio.PREMIUM], key=lambda c: c.item_price)


def _espalhar(lista, quantidade):
    """Pega até `quantidade` itens espalhados uniformemente pela lista ordenada por preço
    (não só os N primeiros) — maximiza a variação de preço testada, já que category_id não dá
    pra escolher de antemão (não existe no ERP, só vem do MLB real)."""
    if not lista or quantidade <= 0:
        return []
    if len(lista) <= quantidade:
        return lista
    passo = len(lista) / quantidade
    return [lista[int(i * passo)] for i in range(quantidade)]


metade = LIMITE_CANDIDATOS // 2
selecionados = _espalhar(classicos, metade) + _espalhar(premiums, LIMITE_CANDIDATOS - metade)
selecionados.sort(key=lambda c: c.item_price)

tabela_selecao = Table(title=f'Candidatos selecionados pra teste ({len(selecionados)}/{len(candidatos)} encontrados)')
tabela_selecao.add_column('EAN')
tabela_selecao.add_column('MLB')
tabela_selecao.add_column('Tipo')
tabela_selecao.add_column('Preço', justify='right')
for c in selecionados:
    tabela_selecao.add_row(c.ean, c.mlb, c.tipo_label, f'R$ {c.item_price}')
console.print(tabela_selecao)

# ---- Marca quais candidatos recebem a 2ª chamada de verificação (espalhados, não só os primeiros) ----
indices_para_repetir = set(
    int(i * (len(selecionados) / QTD_REPETIR_VERIFICACAO))
    for i in range(min(QTD_REPETIR_VERIFICACAO, len(selecionados)))
) if QTD_REPETIR_VERIFICACAO > 0 and selecionados else set()

console.print(f'\nTestando {len(selecionados)} candidato(s) via API '
              f'({len(indices_para_repetir)} com verificação de estabilidade em dobro)...\n')

cache_category_id = {}
resultados = []

for indice, candidato in enumerate(selecionados):
    prefixo = f'[{indice + 1}/{len(selecionados)}] {candidato.mlb} ({candidato.tipo_label}, R$ {candidato.item_price})'
    comissao_flat = COMISSAO_FLAT_POR_TIPO.get(candidato.tipo_anuncio)

    if candidato.mlb in cache_category_id:
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
                valor_estimado_pelo_flat=None, diferenca_absoluta=None,
                percentage_fee_api_repeticao=None, erro=str(erro),
            ))
            continue

    percentage_fee_api_repeticao = None
    sale_fee_amount = None
    percentage_fee_api = None
    fixed_fee_api = None
    erro_candidato = None
    try:
        resposta = buscar_listing_prices(candidato.item_price, category_id, candidato.tipo_anuncio)
        sale_fee_amount = resposta["sale_fee_amount"]
        percentage_fee_api = resposta["percentage_fee"]
        fixed_fee_api = resposta["fixed_fee"]

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

    if resultado.instavel_na_repeticao is True:
        console.print(f'    [bold yellow]⚠ INSTÁVEL na repetição: 1ª chamada {resultado.percentage_fee_api}%, '
                       f'2ª chamada {resultado.percentage_fee_api_repeticao}% (mesmos parâmetros exatos)[/bold yellow]')

# ---- Tabela final + resumo ----
console.print()
tabela_resultado = Table(title='Resultado — Comissão Real (API) x Comissão Flat (configuração atual)')
tabela_resultado.add_column('MLB')
tabela_resultado.add_column('Tipo')
tabela_resultado.add_column('Preço', justify='right')
tabela_resultado.add_column('% Flat', justify='right')
tabela_resultado.add_column('% API', justify='right')
tabela_resultado.add_column('Diverge?', justify='center')
tabela_resultado.add_column('R$ estimado (flat)', justify='right')
tabela_resultado.add_column('R$ sale_fee_amount (API)', justify='right')
tabela_resultado.add_column('Diferença (R$)', justify='right')
tabela_resultado.add_column('fixed_fee (API)', justify='right')
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

    if r.instavel_na_repeticao is True:
        marca_instavel = '[bold yellow]⚠[/bold yellow]'
    elif r.instavel_na_repeticao is False:
        marca_instavel = '[dim]—[/dim]'
    else:
        marca_instavel = ''

    tabela_resultado.add_row(
        c.mlb, c.tipo_label, f'R$ {c.item_price}',
        f'{r.comissao_flat_percentual}%' if r.comissao_flat_percentual is not None else '—',
        f'{r.percentage_fee_api}%' if r.percentage_fee_api is not None else '—',
        marca_diverge,
        f'R$ {r.valor_estimado_pelo_flat}' if r.valor_estimado_pelo_flat is not None else '—',
        f'R$ {r.sale_fee_amount}' if r.sale_fee_amount is not None else '—',
        f'R$ {r.diferenca_absoluta}' if r.diferenca_absoluta is not None else '—',
        f'R$ {r.fixed_fee_api}' if r.fixed_fee_api is not None else '—',
        marca_instavel,
        style=estilo,
    )
console.print(tabela_resultado)

total_com_resultado = sum(1 for r in resultados if r.diverge_do_flat is not None)
total_divergiu = sum(1 for r in resultados if r.diverge_do_flat is True)
divergencias = [r for r in resultados if r.diverge_do_flat is True]
testados_repeticao = [r for r in resultados if r.percentage_fee_api_repeticao is not None]
instaveis = [r for r in testados_repeticao if r.instavel_na_repeticao is True]

console.print(f'\n[bold]Comissão API x Flat:[/bold] {total_divergiu}/{total_com_resultado} candidatos com percentual DIFERENTE do flat configurado.')
if divergencias:
    maior_diferenca = max(divergencias, key=lambda r: abs(r.diferenca_absoluta))
    console.print(f'[bold]Maior diferença observada:[/bold] MLB {maior_diferenca.candidato.mlb} — '
                  f'R$ {maior_diferenca.diferenca_absoluta} (API {maior_diferenca.percentage_fee_api}% x '
                  f'flat {maior_diferenca.comissao_flat_percentual}%)')

console.print(f'[bold]Estabilidade (mesma chamada repetida):[/bold] {len(instaveis)}/{len(testados_repeticao)} '
              f'candidato(s) retornaram percentual DIFERENTE entre a 1ª e a 2ª chamada.')

if divergencias:
    console.print(f'\n[bold yellow]{len(divergencias)} candidato(s) com comissão real diferente do flat configurado:[/bold yellow]')
    for r in divergencias:
        c = r.candidato
        console.print(f'  [yellow]MLB {c.mlb} ({c.tipo_label}, R$ {c.item_price}): '
                       f'API {r.percentage_fee_api}% x flat {r.comissao_flat_percentual}% '
                       f'— diferença R$ {r.diferenca_absoluta}[/yellow]')
else:
    console.print('\n[green]Nenhuma divergência — todos os candidatos testados bateram com o percentual flat configurado.[/green]')

console.print('\n[dim]Ver Checkpoint - Investigação da Comissão Real de Venda via API do Mercado Livre, '
              'Seção 6, pro contexto completo e pra decisão de arquitetura ainda pendente.[/dim]')

# ---- Salva JSON com o detalhe completo ----


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Tipo não serializável: {type(obj)}')


saida = {
    "contexto": {
        "conta": CONTA,
        "limite": LIMITE_CANDIDATOS,
        "qtd_repetir_verificacao": QTD_REPETIR_VERIFICACAO,
        "total_candidatos_encontrados": len(candidatos),
        "total_selecionados": len(selecionados),
    },
    "resultados": [
        {
            "ean": r.candidato.ean,
            "sku": r.candidato.sku,
            "mlb": r.candidato.mlb,
            "tipo_anuncio": r.candidato.tipo_label,
            "item_price": r.candidato.item_price,
            "comissao_flat_percentual": r.comissao_flat_percentual,
            "sale_fee_amount": r.sale_fee_amount,
            "percentage_fee_api": r.percentage_fee_api,
            "fixed_fee_api": r.fixed_fee_api,
            "valor_estimado_pelo_flat": r.valor_estimado_pelo_flat,
            "diferenca_absoluta": r.diferenca_absoluta,
            "diverge_do_flat": r.diverge_do_flat,
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