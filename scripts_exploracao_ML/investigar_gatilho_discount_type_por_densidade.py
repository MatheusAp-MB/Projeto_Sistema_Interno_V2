# scripts_exploracao_ML/investigar_gatilho_discount_type_por_densidade.py

# Função Objetivo: Testar a hipótese de DENSIDADE (peso físico ÷ volume) como gatilho de
# discount.type == "fs_optional", depois que investigar_gatilho_discount_type_via_amostragem_
# estratificada.py rodou 70 chamadas (40 no Passe 1 + 30 no Passe 2) com produtos REAIS
# diversos (categoria/peso/logística/preço) e devolveu "mandatory" em 100% dos casos — 0
# "fs_optional" — contradizendo investigar_reputacao_seller_status_abaixo_79.py, que achou
# "fs_optional" de forma 100% reproduzível nos MESMOS 3 preços (R$15/R$35/R$65), mas só com 2
# dimensões testadas: caixa sintética 5x5x5cm com peso FORÇADO em 8500g, e o Chinelo real
# (13x28x39cm, peso declarado 601g).
#
# A diferença entre os 2 grupos: a caixa sintética tem densidade ABSURDAMENTE alta (8500g ÷
# 125cm³ ≈ 68 g/cm³, mais denso que aço) e o Chinelo tem densidade MUITO baixa (601g ÷
# 14.196cm³ ≈ 0,042 g/cm³) — os 2 extremos opostos. Produto real de catálogo tende a ter
# densidade "normal" (nem oco nem compacto demais), o que bate com o motivo de nenhum dos 70
# candidatos reais (dimensão E peso reais, sem forçar nada) ter caído em fs_optional.
#
# Esse script testa a densidade como variável isolada, controlando categoria/tipo logístico
# (usa category_id/tipo_anuncio de produtos REAIS diversos, não 1 item de referência fixo
# como o script anterior) — mantém a DIMENSÃO real de cada candidato, mas testa o PESO em 3
# variantes sintéticas: baseline (peso real declarado — esperado "mandatory", checagem de
# sanidade), densidade muito baixa (~0,02 g/cm³) e densidade muito alta (~40 g/cm³) — no
# mesmo preço fixo (R$35, meio da faixa onde fs_optional já foi confirmado antes). Mesma
# natureza de simulação que os scripts anteriores já usavam com caixa sintética — endpoint
# read-only de simulação de frete, nenhum anúncio/pedido real é criado ou alterado.
#
# Só leitura no banco e na API — nenhuma escrita em lugar nenhum, além do JSON de saída.
#
# Uso: python -u "scripts_exploracao_ML/investigar_gatilho_discount_type_por_densidade.py" [opções]
# --empresa: MB ou SV — default MB.
# --candidatos: quantos produtos reais diversos usar como base de dimensão/categoria. Default: 10.
# --preco-teste: preço fixo pra todos os testes. Default: 35.00.
# --densidade-baixa: g/cm³ pro teste de densidade muito baixa. Default: 0.02.
# --densidade-alta: g/cm³ pro teste de densidade muito alta. Default: 40.

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
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

parser = argparse.ArgumentParser(
    description='Testa densidade (peso/volume) como gatilho de discount.type == fs_optional, '
                'usando dimensão+categoria de produtos reais diversos com peso sintético.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB', help='Empresa/conta ML. Default: MB.')
parser.add_argument('--candidatos', type=int, default=10, help='Quantos produtos reais diversos usar. Default: 10.')
parser.add_argument('--preco-teste', type=Decimal, default=Decimal('35.00'), help='Preço fixo pra todos os testes. Default: 35.00.')
parser.add_argument('--densidade-baixa', type=Decimal, default=Decimal('0.02'), help='g/cm³ pro teste de densidade muito baixa. Default: 0.02.')
parser.add_argument('--densidade-alta', type=Decimal, default=Decimal('40'), help='g/cm³ pro teste de densidade muito alta. Default: 40.')
args = parser.parse_args()

CONTA = args.empresa
N_CANDIDATOS = args.candidatos
PRECO_TESTE = args.preco_teste
DENSIDADE_BAIXA = args.densidade_baixa
DENSIDADE_ALTA = args.densidade_alta

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"investigacao_gatilho_discount_type_densidade_{CONTA}.json"


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
    '[bold]Investigação do Gatilho de discount.type — Hipótese de Densidade[/bold]\n'
    f'Conta {CONTA} — dimensão/categoria reais e diversas, peso sintético em 3 densidades, preço fixo R$ {PRECO_TESTE}',
    border_style='blue',
))

Status = TipoDeAnuncioMercadoLivre.Status
TipoLogistico = TipoDeAnuncioMercadoLivre.TipoLogistico

variacoes = (
    VariacaoAnuncioMercadoLivre.objects
    .filter(
        altura_declarada_cm__isnull=False, largura_declarada_cm__isnull=False,
        comprimento_declarado_cm__isnull=False, peso_declarado_kg__isnull=False,
        produto__isnull=False, categoria__isnull=False,
        anuncio__tipo_de_anuncio__status=Status.ATIVO,
    )
    .select_related('anuncio', 'anuncio__tipo_de_anuncio', 'produto', 'categoria')
)

candidatos_pool = []
estratos_vistos = set()
for v in variacoes:
    altura, largura, comprimento = v.altura_declarada_cm, v.largura_declarada_cm, v.comprimento_declarado_cm
    if altura <= 0 or largura <= 0 or comprimento <= 0:
        continue
    tipo_de_anuncio = v.anuncio.tipo_de_anuncio
    estrato = (v.categoria.categoria_raiz_id, tipo_de_anuncio.tipo_logistico)
    if estrato in estratos_vistos:
        continue
    estratos_vistos.add(estrato)
    candidatos_pool.append({
        "mlb": v.anuncio.mlb, "ean": v.produto.ean,
        "categoria_raiz_id": v.categoria.categoria_raiz_id, "categoria_nome": v.categoria.nome,
        "category_id": v.categoria.category_id, "tipo_anuncio": tipo_de_anuncio.tipo_anuncio,
        "tipo_logistico": TipoLogistico(tipo_de_anuncio.tipo_logistico).label if tipo_de_anuncio.tipo_logistico else '—',
        "altura_cm": altura, "largura_cm": largura, "comprimento_cm": comprimento,
        "peso_declarado_kg": v.peso_declarado_kg,
        "volume_cm3": altura * largura * comprimento,
    })
    if len(candidatos_pool) >= N_CANDIDATOS:
        break

if not candidatos_pool:
    console.print('[bold red]Nenhum candidato encontrado. Nada a testar.[/bold red]')
    sys.exit(1)

console.print(f'{len(candidatos_pool)} candidato(s) diverso(s) selecionado(s) (dimensão+categoria real, peso será sintético).\n')

tabela_selecao = Table(title='Candidatos base (dimensão + categoria reais)')
tabela_selecao.add_column('MLB')
tabela_selecao.add_column('Categoria raiz')
tabela_selecao.add_column('Tipo logístico')
tabela_selecao.add_column('Dimensão (cm)')
tabela_selecao.add_column('Volume (cm³)', justify='right')
tabela_selecao.add_column('Densidade real (g/cm³)', justify='right')
for c in candidatos_pool:
    densidade_real = (c["peso_declarado_kg"] * Decimal('1000')) / c["volume_cm3"]
    tabela_selecao.add_row(
        c["mlb"], f'{c["categoria_raiz_id"]} ({c["categoria_nome"]})', c["tipo_logistico"],
        f'{c["altura_cm"]}x{c["largura_cm"]}x{c["comprimento_cm"]}', f'{c["volume_cm3"]:.0f}',
        f'{densidade_real:.4f}',
    )
console.print(tabela_selecao)

try:
    resposta_me = chamar_api("GET", "/users/me", pasta_logs=PASTA_LOGS, conta=CONTA,
                              nome_log="investigar_gatilho_discount_type_densidade")
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro buscando user_id: {erro}[/bold red]')
    sys.exit(1)


def testar(candidato, peso_gramas, item_price):
    dimensions_str = montar_dimensions_str(candidato["altura_cm"], candidato["largura_cm"],
                                            candidato["comprimento_cm"], peso_gramas)
    endpoint = f"/users/{user_id}/shipping_options/free"
    params = {
        "dimensions": dimensions_str, "item_price": str(item_price), "verbose": "true",
        "condition": "new", "category_id": candidato["category_id"],
        "listing_type_id": candidato["tipo_anuncio"], "mode": "me2", "free_shipping": "false",
    }
    try:
        resposta = chamar_api("GET", endpoint, pasta_logs=PASTA_LOGS, conta=CONTA, params=params,
                               nome_log="investigar_gatilho_discount_type_densidade")
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


console.print(f'\nTestando {len(candidatos_pool)} candidato(s) x 3 densidades @ R$ {PRECO_TESTE}...\n')

resultados = []
for indice, c in enumerate(candidatos_pool, start=1):
    console.print(f'[{indice}/{len(candidatos_pool)}] {c["mlb"]}...')
    peso_baseline_g = c["peso_declarado_kg"] * Decimal('1000')
    peso_baixo_g = DENSIDADE_BAIXA * c["volume_cm3"]
    peso_alto_g = DENSIDADE_ALTA * c["volume_cm3"]

    r_baseline = testar(c, peso_baseline_g, PRECO_TESTE)
    r_baixo = testar(c, peso_baixo_g, PRECO_TESTE)
    r_alto = testar(c, peso_alto_g, PRECO_TESTE)

    resultados.append({
        "candidato": c, "peso_baseline_g": peso_baseline_g, "peso_baixo_g": peso_baixo_g, "peso_alto_g": peso_alto_g,
        "baseline": r_baseline, "densidade_baixa": r_baixo, "densidade_alta": r_alto,
    })

console.print('\n[bold]Resumo[/bold]')
tabela_resultado = Table(title=f'discount.type por densidade, @ R$ {PRECO_TESTE} (categoria/tipo logístico reais e diversos)')
tabela_resultado.add_column('MLB')
tabela_resultado.add_column('Categoria raiz')
tabela_resultado.add_column('Baseline (real)')
tabela_resultado.add_column(f'Densidade baixa ({DENSIDADE_BAIXA} g/cm³)')
tabela_resultado.add_column(f'Densidade alta ({DENSIDADE_ALTA} g/cm³)')
for r in resultados:
    c = r["candidato"]
    tabela_resultado.add_row(
        c["mlb"], f'{c["categoria_raiz_id"]}',
        r["baseline"].get("discount_type") or ('erro' if r["baseline"].get('erro') else '(nenhum)'),
        r["densidade_baixa"].get("discount_type") or ('erro' if r["densidade_baixa"].get('erro') else '(nenhum)'),
        r["densidade_alta"].get("discount_type") or ('erro' if r["densidade_alta"].get('erro') else '(nenhum)'),
    )
console.print(tabela_resultado)


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Tipo não serializável: {type(obj)}')


saida = {
    "contexto": {"conta": CONTA, "preco_teste": PRECO_TESTE, "densidade_baixa": DENSIDADE_BAIXA, "densidade_alta": DENSIDADE_ALTA},
    "resultados": resultados,
}
with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2, default=_serializar)

console.print(f'\nResultado completo salvo em: {CAMINHO_SAIDA}')
console.print('Suba esse arquivo (ou cole o resumo acima) na conversa pra eu analisar.')