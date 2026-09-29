# scripts_exploracao_ML/investigar_gatilho_discount_type_por_categoria_referencia.py

# Função Objetivo: A hipótese de densidade (peso/volume) acabou de ser REFUTADA —
# investigar_gatilho_discount_type_por_densidade.py testou 10 produtos reais diversos em 3
# densidades cada (real, ~0,02 g/cm³, ~40 g/cm³), 30/30 deram "mandatory", incluindo os 2
# extremos que deveriam replicar a densidade da caixa sintética (68 g/cm³) e do Chinelo
# (0,042 g/cm³) do teste original. Com densidade e uma amostra de 100 chamadas diversas
# (categoria/peso/logística/preço) TODAS "mandatory", sobra 1 variável que nunca foi isolada:
# o teste original (investigar_reputacao_seller_status_abaixo_79.py) sempre usou o MESMO
# item de referência fixo (MLB6296787236) pra pegar category_id/listing_type_id/condition —
# tanto na caixa sintética quanto no Chinelo, e em todas as 5 variantes de parâmetro (a-f)
# testadas lá. Ou seja, a ÚNICA coisa em comum entre os 2 testes que deram "fs_optional" e
# nenhum dos ~100 testes que deram "mandatory" é essa categoria/listing_type específica.
#
# Esse script isola essa variável: busca category_id/listing_type_id/condition reais de
# MLB6296787236 via API (mesma chamada do script original), e testa essa combinação com
# VÁRIAS dimensões diferentes (formas distintas entre si, densidade "razoável" — não
# reintroduz o extremo já descartado) nos mesmos 3 preços de controle (R$15/R$35/R$65) — se
# "fs_optional" persistir em TODAS as dimensões, é a categoria (ou algo atrelado a ela,
# listing_type/condition) que causa o gatilho, não o formato do pacote. Também procura, no
# catálogo próprio (MB/SV), produtos reais que já estejam nessa MESMA category_id, com preço
# < R$79, e testa no preço/dimensão reais deles — checagem independente, sem nada sintético.
#
# Só leitura no banco e na API — nenhuma escrita em lugar nenhum, além do JSON de saída.
#
# Uso: python -u "scripts_exploracao_ML/investigar_gatilho_discount_type_por_categoria_referencia.py" [opções]
# --empresa: MB ou SV — default MB.
# --item-referencia: MLB usado como fonte de category_id/listing_type_id/condition. Default: MLB6296787236
#   (o mesmo item de investigar_reputacao_seller_status_abaixo_79.py).
# --precos-teste: preços fixos pra testar, separados por vírgula. Default: 15.00,35.00,65.00.

import os
import sys
import json
import argparse
from pathlib import Path
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
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, CategoriaMercadoLivre

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

parser = argparse.ArgumentParser(
    description='Isola a categoria/listing_type do item de referência da investigação '
                'anterior como possível gatilho de discount.type == fs_optional.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB', help='Empresa/conta ML. Default: MB.')
parser.add_argument('--item-referencia', default='MLB6296787236',
                     help='MLB usado como fonte de category_id/listing_type_id/condition. Default: MLB6296787236.')
parser.add_argument('--precos-teste', default='15.00,35.00,65.00',
                     help='Preços fixos a testar, separados por vírgula. Default: 15.00,35.00,65.00.')
args = parser.parse_args()

CONTA = args.empresa
ITEM_REFERENCIA = args.item_referencia
PRECOS_TESTE = [Decimal(p.strip()) for p in args.precos_teste.split(',') if p.strip()]

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"investigacao_gatilho_discount_type_categoria_referencia_{CONTA}.json"


def _formatar_dimensao(valor):
    inteiro = valor.to_integral_value()
    if valor == inteiro:
        return str(int(inteiro))
    return str(valor.normalize())


def montar_dimensions_str(altura_cm, largura_cm, comprimento_cm, peso_gramas):
    f = _formatar_dimensao
    peso_gramas_int = int(Decimal(peso_gramas).to_integral_value())
    return f'{f(altura_cm)}x{f(largura_cm)}x{f(comprimento_cm)},{peso_gramas_int}'


console.print(Panel(
    '[bold]Investigação do Gatilho de discount.type — Categoria do Item de Referência[/bold]\n'
    f'Conta {CONTA} — isolando category_id/listing_type_id de {ITEM_REFERENCIA} de tudo mais',
    border_style='blue',
))

try:
    resposta_me = chamar_api("GET", "/users/me", pasta_logs=PASTA_LOGS, conta=CONTA,
                              nome_log="investigar_gatilho_discount_type_categoria_referencia")
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro buscando user_id: {erro}[/bold red]')
    sys.exit(1)

try:
    resposta_item = chamar_api("GET", f"/items/{ITEM_REFERENCIA}", pasta_logs=PASTA_LOGS, conta=CONTA,
                                nome_log="investigar_gatilho_discount_type_categoria_referencia")
    item = resposta_item.json()
    category_id_referencia = item.get("category_id")
    listing_type_id_referencia = item.get("listing_type_id")
    condition_referencia = item.get("condition", "new")
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro buscando {ITEM_REFERENCIA}: {erro}[/bold red]')
    sys.exit(1)

console.print(f'Item de referência {ITEM_REFERENCIA}: category_id={category_id_referencia}, '
              f'listing_type_id={listing_type_id_referencia}, condition={condition_referencia}\n')

categoria_local = CategoriaMercadoLivre.objects.filter(category_id=category_id_referencia).first()
if categoria_local:
    console.print(f'Categoria encontrada no dump local: {categoria_local.nome} '
                  f'(raiz {categoria_local.categoria_raiz_id}, caminho: {categoria_local.caminho_completo})\n')
else:
    console.print('[yellow]Categoria não encontrada no dump local (CategoriaMercadoLivre) — segue só com o category_id cru.[/yellow]\n')

# ---- Parte 1: mesma categoria/listing_type do item de referência, várias dimensões diferentes ----
# Formas bem distintas entre si, densidade "razoável" em todas (não reintroduz o extremo já
# descartado no script de densidade).
DIMENSOES_TESTE = [
    {"nome": "pequena/leve",  "altura": Decimal('10'), "largura": Decimal('10'), "comprimento": Decimal('10'), "peso_g": Decimal('300')},
    {"nome": "media",         "altura": Decimal('25'), "largura": Decimal('20'), "comprimento": Decimal('8'),  "peso_g": Decimal('900')},
    {"nome": "grande/pesada", "altura": Decimal('50'), "largura": Decimal('40'), "comprimento": Decimal('30'), "peso_g": Decimal('6000')},
    {"nome": "achatada",      "altura": Decimal('60'), "largura": Decimal('45'), "comprimento": Decimal('3'),  "peso_g": Decimal('700')},
]


def testar_com_categoria(category_id, listing_type_id, condition, dim, item_price):
    dimensions_str = montar_dimensions_str(dim["altura"], dim["largura"], dim["comprimento"], dim["peso_g"])
    endpoint = f"/users/{user_id}/shipping_options/free"
    params = {
        "dimensions": dimensions_str, "item_price": str(item_price), "verbose": "true",
        "condition": condition, "category_id": category_id, "listing_type_id": listing_type_id,
        "mode": "me2", "free_shipping": "false",
    }
    try:
        resposta = chamar_api("GET", endpoint, pasta_logs=PASTA_LOGS, conta=CONTA, params=params,
                               nome_log="investigar_gatilho_discount_type_categoria_referencia")
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        return {"erro": str(erro)}
    corpo = resposta.json()
    coverage = corpo.get("coverage", {}).get("all_country", {})
    discount = coverage.get("discount")
    return {
        "list_cost": coverage.get("list_cost"), "billable_weight_g": coverage.get("billable_weight"),
        "discount_type": discount.get("type") if isinstance(discount, dict) else None,
        "erro": None,
    }


console.print(f'Testando categoria/listing_type de {ITEM_REFERENCIA} x {len(DIMENSOES_TESTE)} dimensões x '
              f'{len(PRECOS_TESTE)} preços...\n')

resultados_parte1 = []
for dim in DIMENSOES_TESTE:
    for preco in PRECOS_TESTE:
        console.print(f'{dim["nome"]} @ R$ {preco}...')
        r = testar_com_categoria(category_id_referencia, listing_type_id_referencia, condition_referencia, dim, preco)
        resultados_parte1.append({"dimensao": dim["nome"], "preco": preco, "resultado": r})

tabela_parte1 = Table(title=f'Parte 1 — categoria/listing_type de {ITEM_REFERENCIA}, dimensão variando')
tabela_parte1.add_column('Dimensão')
for preco in PRECOS_TESTE:
    tabela_parte1.add_column(f'R$ {preco}')
for dim in DIMENSOES_TESTE:
    linha = [dim["nome"]]
    for preco in PRECOS_TESTE:
        r = next(x["resultado"] for x in resultados_parte1 if x["dimensao"] == dim["nome"] and x["preco"] == preco)
        linha.append(r.get("discount_type") or ('erro' if r.get('erro') else '(nenhum)'))
    tabela_parte1.add_row(*linha)
console.print(tabela_parte1)

# ---- Parte 2: produtos REAIS do próprio catálogo (MB/SV) na mesma category_id ----
Status = TipoDeAnuncioMercadoLivre.Status
candidatos_mesma_categoria = list(
    VariacaoAnuncioMercadoLivre.objects
    .filter(
        altura_declarada_cm__isnull=False, largura_declarada_cm__isnull=False,
        comprimento_declarado_cm__isnull=False, peso_declarado_kg__isnull=False,
        preco_atual__isnull=False, produto__isnull=False,
        categoria__category_id=category_id_referencia,
        preco_atual__lt=Decimal('79'),
        anuncio__tipo_de_anuncio__status=Status.ATIVO,
    )
    .select_related('anuncio', 'anuncio__tipo_de_anuncio', 'produto', 'categoria')[:15]
)

resultados_parte2 = []
if candidatos_mesma_categoria:
    console.print(f'\n{len(candidatos_mesma_categoria)} produto(s) REAL(is) do próprio catálogo na MESMA category_id '
                  f'({category_id_referencia}), preço < R$79 — testando no preço/dimensão reais deles...\n')
    for v in candidatos_mesma_categoria:
        dim = {"altura": v.altura_declarada_cm, "largura": v.largura_declarada_cm,
               "comprimento": v.comprimento_declarado_cm, "peso_g": v.peso_declarado_kg * Decimal('1000')}
        console.print(f'{v.anuncio.mlb} @ R$ {v.preco_atual}...')
        r = testar_com_categoria(category_id_referencia, v.anuncio.tipo_de_anuncio.tipo_anuncio, condition_referencia, dim, v.preco_atual)
        resultados_parte2.append({"mlb": v.anuncio.mlb, "ean": v.produto.ean, "preco": v.preco_atual, "resultado": r})

    tabela_parte2 = Table(title=f'Parte 2 — produtos reais do catálogo, mesma category_id ({category_id_referencia})')
    tabela_parte2.add_column('MLB')
    tabela_parte2.add_column('EAN')
    tabela_parte2.add_column('Preço', justify='right')
    tabela_parte2.add_column('discount.type')
    for r in resultados_parte2:
        tabela_parte2.add_row(r["mlb"], r["ean"], f'R$ {r["preco"]}',
                               r["resultado"].get("discount_type") or ('erro' if r["resultado"].get('erro') else '(nenhum)'))
    console.print(tabela_parte2)
else:
    console.print(f'\n[yellow]Nenhum produto do próprio catálogo (MB/SV) está cadastrado na category_id '
                  f'{category_id_referencia} com preço < R$79 — Parte 2 pulada, sem dado real pra testar.[/yellow]')


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Tipo não serializável: {type(obj)}')


saida = {
    "contexto": {
        "conta": CONTA, "item_referencia": ITEM_REFERENCIA,
        "category_id_referencia": category_id_referencia, "listing_type_id_referencia": listing_type_id_referencia,
        "condition_referencia": condition_referencia,
        "categoria_nome_local": categoria_local.nome if categoria_local else None,
        "categoria_raiz_id_local": categoria_local.categoria_raiz_id if categoria_local else None,
    },
    "parte1_dimensoes_variando": resultados_parte1,
    "parte2_produtos_reais_mesma_categoria": resultados_parte2,
}
with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2, default=_serializar)

console.print(f'\nResultado completo salvo em: {CAMINHO_SAIDA}')
console.print('Suba esse arquivo (ou cole as tabelas acima) na conversa pra eu analisar.')