# scripts_exploracao_ML/testar_matriz_frete_gratis_via_api.py

# Função Objetivo: Valida se buscar_list_cost_via_api (API real de frete do Mercado Livre)
# reproduz um valor de frete conhecido, pra qualquer produto — não só o Inseticida Dipil.
# Testa as 4 combinações Clássico/Premium x sem/com frete grátis pra confirmar que o
# parâmetro `free_shipping` da API é mesmo o que decide qual das 2 tabelas reais de frete
# volta (Tabela 1 "por conta do comprador" x Tabela 2 "oferecer frete grátis"), e se isso
# varia por tipo de anúncio.
#
# Dimensões e gabarito são 100% parametrizados via linha de comando — nenhum valor fixo
# no código além dos defaults de dimensão, que reproduzem o caso já confirmado em 23/09
# (ver Checkpoint Frente A, Seção 11): 20x20x9cm, 0,4kg físico (embalagem do Inseticida
# Dipil, EAN 7898026081454). Gabarito não tem default — é opcional, e só é comparado
# quando informado; sem ele, o script mostra o list_cost obtido, sem checar contra nada.
#
# Não reimplementa o motor de goal seek nem a comparação Opção 1 x Opção 2 (isso já existe
# em testar_goal_seek_via_api.py, pra outro problema — resolver PREÇO pra bater margem).
# Aqui o preço já é conhecido (o preço real do anúncio, vindo do banco) — o que está sendo
# testado é só se list_cost bate com o gabarito (quando informado), não uma resolução de
# margem.
#
# O peso enviado é sempre o FÍSICO, nunca o faturável já calculado, de propósito: é a
# própria API que calcula o peso cúbico a partir de AxLxC e escolhe o maior, exatamente como
# resolver_dimensoes_efetivas faz localmente. Mandar o físico cru testa esse cálculo do
# lado da API também, em vez de assumir que bate.
#
# Uso: python -u "scripts_exploracao_ML/testar_matriz_frete_gratis_via_api.py" [opções]
# --empresa: MB (Magazine) ou SV (Samvale) — default MB.
# --ean: EAN do produto — default o Inseticida Dipil já confirmado (7898026081454).
# --altura / --largura / --comprimento: dimensões declaradas, em cm — default 20 / 20 / 9.
# --peso-fisico: peso físico declarado, em kg — default 0.4.
# --esperado-sem-frete-gratis / --esperado-com-frete-gratis: gabarito conhecido (R$) pra
#   comparar, cada um opcional e independente — sem a flag, o resultado daquela combinação
#   só é exibido, nunca comparado.
#
# Só leitura no banco e na API — nenhuma escrita em lugar nenhum.

import os
import sys
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
from produtos.models import Produto
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

# ==== ARGUMENTOS DE LINHA DE COMANDO ====
parser = argparse.ArgumentParser(
    description='Testa se buscar_list_cost_via_api reproduz um valor de frete conhecido, '
                 'pra qualquer produto (Clássico/Premium x sem/com frete grátis).'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB',
                     help='Empresa/conta ML — MB (Magazine) ou SV (Samvale). Default: MB.')
parser.add_argument('--ean', default='7898026081454',
                     help='EAN do produto a testar. Default: Inseticida Dipil (7898026081454).')
parser.add_argument('--altura', type=Decimal, default=Decimal('20'),
                     help='Altura declarada, em cm. Default: 20.')
parser.add_argument('--largura', type=Decimal, default=Decimal('20'),
                     help='Largura declarada, em cm. Default: 20.')
parser.add_argument('--comprimento', type=Decimal, default=Decimal('9'),
                     help='Comprimento declarado, em cm. Default: 9.')
parser.add_argument('--peso-fisico', type=Decimal, default=Decimal('0.4'),
                     help='Peso físico declarado, em kg. Default: 0.4.')
parser.add_argument('--esperado-sem-frete-gratis', type=Decimal, default=None,
                     help='Gabarito (R$) pra comparar o resultado sem frete grátis, se '
                          'houver um valor real já confirmado. Sem essa flag, o resultado '
                          'daquela combinação só é exibido, sem comparação.')
parser.add_argument('--esperado-com-frete-gratis', type=Decimal, default=None,
                     help='Gabarito (R$) pra comparar o resultado com frete grátis, se '
                          'houver um valor real já confirmado. Sem essa flag, o resultado '
                          'daquela combinação só é exibido, sem comparação.')
args = parser.parse_args()

CONTA = args.empresa
EAN_PRODUTO = args.ean

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])
# * [EXPLICAÇÃO] → Mesmo motivo do testar_goal_seek_via_api.py: sem isso o Django cai no
#                  banco default, e pra --empresa SV isso leria dado do MB silenciosamente.

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
TIPOS_ANUNCIO = [
    (TipoAnuncio.CLASSICO, 'Clássico'),
    (TipoAnuncio.PREMIUM, 'Premium'),
]

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"

# Dimensões e gabarito agora vêm 100% da linha de comando (ver argparse acima) — nada
# fixo aqui, pra permitir testar qualquer produto, não só o Inseticida Dipil.
ALTURA_CM = args.altura
LARGURA_CM = args.largura
COMPRIMENTO_CM = args.comprimento
PESO_FISICO_KG = args.peso_fisico

# Gabarito é opcional e independente por combinação — None quando a flag correspondente
# não foi passada, e nesse caso a combinação só é exibida, nunca comparada (ver .bate em
# ResultadoChecagem).
GABARITO_LIST_COST = {
    False: args.esperado_sem_frete_gratis,
    True: args.esperado_com_frete_gratis,
}


@dataclass
class ResultadoChecagem:
    """Objeto de processo — 1 linha da matriz testada, nunca salvo no banco."""
    tipo_label: str
    frete_gratis: bool
    item_price: Decimal
    list_cost_obtido: Decimal
    list_cost_esperado: Decimal | None

    @property
    def bate(self) -> bool | None:
        """None = sem gabarito informado pra essa combinação, nada a comparar."""
        if self.list_cost_esperado is None:
            return None
        return self.list_cost_obtido == self.list_cost_esperado


def _formatar_dimensao(valor):
    """Decimal -> string pro formato que a API espera (13.00 -> '13', 13.50 -> '13.5')."""
    inteiro = valor.to_integral_value()
    if valor == inteiro:
        return str(int(inteiro))
    return str(valor.normalize())


def buscar_list_cost_via_api(user_id, category_id, item_price, dimensions_str, tipo_anuncio, frete_gratis):
    """Igual à função de mesmo nome em testar_goal_seek_via_api.py, só que com
    `frete_gratis` como parâmetro explícito em vez de fixo em False — é exatamente esse
    parâmetro que este script existe pra testar, por isso não reimporta a versão fixa."""
    endpoint = f"/users/{user_id}/shipping_options/free"
    params = {
        "dimensions": dimensions_str,
        "item_price": str(item_price),
        "verbose": "true",
        "condition": "new",
        "category_id": category_id,
        "listing_type_id": tipo_anuncio,
        "mode": "me2",
        "free_shipping": "true" if frete_gratis else "false",
    }
    resposta = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params,
        nome_log="testar_matriz_frete_gratis_via_api",
    )
    corpo = resposta.json()
    list_cost = corpo.get("coverage", {}).get("all_country", {}).get("list_cost")
    if list_cost is None:
        raise ErroAPI(
            f"API não retornou list_cost pra item_price={item_price}, tipo={tipo_anuncio}, "
            f"free_shipping={frete_gratis} — resposta: {corpo}"
        )
    return Decimal(str(list_cost))


# ========== Fluxo principal ==========

console.print(Panel(f'[bold]Matriz de Frete via API — Clássico/Premium x Sem/Com Frete Grátis[/bold]\n'
                     f'EAN {EAN_PRODUTO} — conta {CONTA} — dimensões e gabarito informados por parâmetro',
                     border_style='blue'))

produto = Produto.objects.get(ean=EAN_PRODUTO)

try:
    resposta_me = chamar_api("GET", "/users/me", pasta_logs=PASTA_LOGS, conta=CONTA,
                              nome_log="testar_matriz_frete_gratis_via_api")
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro buscando user_id: {erro}[/bold red]')
    sys.exit(1)

dimensions_str = (
    f"{_formatar_dimensao(ALTURA_CM)}x{_formatar_dimensao(LARGURA_CM)}x{_formatar_dimensao(COMPRIMENTO_CM)},"
    f"{int((PESO_FISICO_KG * 1000).to_integral_value())}"
)

tabela_contexto = Table(title='Produto e contexto resolvidos', show_header=False, box=None, padding=(0, 2))
tabela_contexto.add_column(style='dim')
tabela_contexto.add_column()
tabela_contexto.add_row('Empresa', CONTA)
tabela_contexto.add_row('SKU / EAN', f'{produto.sku} / {produto.ean}')
tabela_contexto.add_row('Dimensões (AxLxC, peso físico)', f'{ALTURA_CM}x{LARGURA_CM}x{COMPRIMENTO_CM}cm, {PESO_FISICO_KG}kg')
tabela_contexto.add_row('dimensions (parâmetro da API)', dimensions_str)
console.print(tabela_contexto)
console.print()

resultados = []
for tipo_anuncio, tipo_label in TIPOS_ANUNCIO:
    variacao = (
        VariacaoAnuncioMercadoLivre.objects
        .filter(produto=produto, anuncio__tipo_de_anuncio__tipo_anuncio=tipo_anuncio)
        .select_related('anuncio')
        .order_by('anuncio__mlb')
        .first()
    )
    if variacao is None:
        console.print(f'[bold red]{tipo_label}: nenhuma VariacaoAnuncioMercadoLivre encontrada pra esse '
                       f'produto — pulando {tipo_label}.[/bold red]')
        continue
    if variacao.preco_atual is None:
        console.print(f'[bold red]{tipo_label} (MLB {variacao.anuncio.mlb}): preco_atual não '
                       f'preenchido no banco — pulando {tipo_label}.[/bold red]')
        continue

    mlb = variacao.anuncio.mlb
    item_price = variacao.preco_atual

    try:
        resposta_item = chamar_api("GET", f"/items/{mlb}", pasta_logs=PASTA_LOGS, conta=CONTA,
                                    nome_log="testar_matriz_frete_gratis_via_api")
        category_id = resposta_item.json()["category_id"]
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        console.print(f'[bold red]{tipo_label} (MLB {mlb}): erro buscando category_id: {erro}[/bold red]')
        continue

    console.print(f'[dim]{tipo_label}: MLB {mlb}, preço R$ {item_price}, category_id {category_id}[/dim]')

    for frete_gratis in (False, True):
        try:
            list_cost = buscar_list_cost_via_api(
                user_id, category_id, item_price, dimensions_str, tipo_anuncio, frete_gratis,
            )
        except (ErroAPI, ErroAutenticacaoAPI) as erro:
            console.print(f'[bold red]{tipo_label} / frete_gratis={frete_gratis}: erro na API: {erro}[/bold red]')
            continue

        resultados.append(ResultadoChecagem(
            tipo_label=tipo_label,
            frete_gratis=frete_gratis,
            item_price=item_price,
            list_cost_obtido=list_cost,
            list_cost_esperado=GABARITO_LIST_COST[frete_gratis],
        ))

console.print()
tabela_resultado = Table(title='Resultado — list_cost via API x gabarito de tela real')
tabela_resultado.add_column('Tipo')
tabela_resultado.add_column('Frete grátis?')
tabela_resultado.add_column('Preço testado', justify='right')
tabela_resultado.add_column('list_cost obtido', justify='right')
tabela_resultado.add_column('Esperado (gabarito)', justify='right')
tabela_resultado.add_column('Bate?', justify='center')

for r in resultados:
    if r.bate is None:
        marca, estilo = '[dim]—[/dim]', 'dim'
        esperado_str = '[dim]sem gabarito[/dim]'
    elif r.bate:
        marca, estilo = '[bold green]✓[/bold green]', 'bold green'
        esperado_str = f'R$ {r.list_cost_esperado}'
    else:
        marca, estilo = '[bold red]✗[/bold red]', 'bold red'
        esperado_str = f'R$ {r.list_cost_esperado}'
    tabela_resultado.add_row(
        r.tipo_label,
        'Sim' if r.frete_gratis else 'Não',
        f'R$ {r.item_price}',
        f'R$ {r.list_cost_obtido}',
        esperado_str,
        marca,
        style=estilo,
    )
console.print(tabela_resultado)

resultados_com_gabarito = [r for r in resultados if r.bate is not None]
total_bateu = sum(1 for r in resultados_com_gabarito if r.bate)
total_sem_gabarito = len(resultados) - len(resultados_com_gabarito)
console.print(f'\n[dim]{total_bateu}/{len(resultados_com_gabarito)} combinações com gabarito informado '
              f'bateram.[/dim]')
if total_sem_gabarito:
    console.print(f'[dim]{total_sem_gabarito} combinações exibidas sem gabarito (nenhum valor esperado '
                  f'informado pra elas).[/dim]')