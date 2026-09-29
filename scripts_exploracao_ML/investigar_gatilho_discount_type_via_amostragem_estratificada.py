# scripts_exploracao_ML/investigar_gatilho_discount_type_via_amostragem_estratificada.py

# Função Objetivo: Descobrir, com produtos REAIS e diversos (peso faturável x categoria-raiz x
# tipo logístico), o que determina discount.type vir "mandatory" (esperado) ou "fs_optional"
# (ainda não explicado) na resposta de /shipping_options/free pra item_price < R$79.
#
# A investigação anterior (investigar_reputacao_seller_status_abaixo_79.py) já descartou
# seller_status / seller_type / reputation / free_shipping como causa — nenhuma dessas
# variantes mudou o resultado em 3 preços fixos já confirmados como "fs_optional" (R$15,
# R$35, R$65), testados com 2 dimensões fixas (caixa sintética 5x5x5cm/8500g e o Chinelo
# F7899947307029.001, dimensões reais). Esse script ataca de um ângulo diferente: em vez de
# variar parâmetro da CHAMADA, varia o PRODUTO (categoria, peso faturável, tipo logístico do
# anúncio) — pra ver se o gatilho está do lado do produto/categoria/logística.
#
# 2 passadas, propositalmente complementares:
#
#   PASSE 1 (amostragem ampla) — até --limite candidatos reais diversos (estratificados por
#   faixa de peso faturável x categoria-raiz x tipo logístico), cada 1 testado 1x no próprio
#   preço atual (só quem tem preco_atual < R$79 entra no pool). Cruza discount.type contra
#   cada dimensão de estratificação — mostra ONDE (se em algum lugar) fs_optional se
#   concentra.
#
#   PASSE 2 (controle cruzado) — até --candidatos-controle candidatos diversos (mesmo
#   critério), cada 1 testado nos MESMOS 3 preços fixos já usados na investigação anterior
#   (R$15/R$35/R$65). Isola o PREÇO (fica fixo) da dimensão/categoria/logística (varia) — o
#   oposto do Passe 1. Se fs_optional aparecer em TODO mundo nesses 3 preços, independente do
#   produto, o gatilho é só preço (ou conta, já quase descartado). Se aparecer "mandatory" em
#   algum candidato num desses preços, o produto/categoria/logística importa — e a coluna do
#   Passe 1/2 onde a divisão aparecer é a pista.
#
# O script só CRUZA os dados e imprime as tabelas — a leitura/conclusão é manual, como de
# costume nesta pasta.
#
# Fonte do dado: VariacaoAnuncioMercadoLivre (dimensão/peso/preço declarados, mesmo motivo de
# sempre — é o que o Simulador de custos do ML usa de verdade), já com a categoria FK
# preenchida no banco — evita 1 chamada a /items por candidato só pra pegar category_id
# (diferente de buscar_e_testar_candidatos_diversos_frete_via_api.py, que precisa chamar
# /items porque nem sempre tinha a FK; aqui a Frente A já exige categoria preenchida pra ser
# elegível, mesma regra de _tentar_resolver_preco_via_api em formula_precificacao.py).
#
# Cada candidato do Passe 1 gera 1 chamada; cada candidato do Passe 2 gera até 3 (1 por
# preço fixo). Com os defaults (40 + 10x3), isso é até 70 chamadas.
#
# Só leitura no banco e na API — nenhuma escrita em lugar nenhum, além do JSON de saída.
#
# Uso: python -u "scripts_exploracao_ML/investigar_gatilho_discount_type_via_amostragem_estratificada.py" [opções]
# --empresa: MB ou SV — default MB.
# --limite: máximo de candidatos testados no Passe 1. Default: 40.
# --candidatos-controle: máximo de candidatos testados no Passe 2. Default: 10.

import os
import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass
from decimal import Decimal
from collections import defaultdict, Counter


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

# ==== ARGUMENTOS DE LINHA DE COMANDO ====
parser = argparse.ArgumentParser(
    description='Investiga o que determina discount.type (mandatory x fs_optional) abaixo '
                 'de R$79, variando produto/categoria/logística real em vez de parâmetro da chamada.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB',
                     help='Empresa/conta ML — MB (Magazine) ou SV (Samvale). Default: MB.')
parser.add_argument('--limite', type=int, default=40,
                     help='Máximo de candidatos testados no Passe 1 (amostragem ampla). Default: 40.')
parser.add_argument('--candidatos-controle', type=int, default=10,
                     help='Máximo de candidatos testados no Passe 2 (controle cruzado, 3 preços '
                          'fixos cada). Default: 10.')
args = parser.parse_args()

CONTA = args.empresa
LIMITE_PASSE_1 = args.limite
LIMITE_PASSE_2 = args.candidatos_controle
MAX_POR_ESTRATO_PASSE_1 = 2  # não deixa 1 estrato só consumir o --limite inteiro (mesma ideia de buscar_e_testar)
PRECOS_CONTROLE = [Decimal('15.00'), Decimal('35.00'), Decimal('65.00')]  # mesmos 3 já confirmados
                                                                            # "fs_optional" na investigação anterior

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"investigacao_gatilho_discount_type_{CONTA}.json"

# Tabela de faixas de PESO — só nome + limites (fechada só no limite superior, mesma
# convenção empírica já validada em buscar_e_testar_candidatos_diversos_frete_via_api.py) —
# usada aqui só pra ESTRATIFICAR/EXIBIR, não pra calcular frete (esse script não compara
# valor de frete, só discount.type).
TABELA_PESO = [
    {"nome": "Até 0,3 kg",      "peso_max": Decimal('0.3')},
    {"nome": "De 0,3 a 0,5 kg", "peso_max": Decimal('0.5')},
    {"nome": "De 0,5 a 1 kg",   "peso_max": Decimal('1')},
    {"nome": "De 1 a 1,5 kg",   "peso_max": Decimal('1.5')},
    {"nome": "De 1,5 a 2 kg",   "peso_max": Decimal('2')},
    {"nome": "De 2 a 3 kg",     "peso_max": Decimal('3')},
    {"nome": "De 3 a 4 kg",     "peso_max": Decimal('4')},
    {"nome": "De 4 a 5 kg",     "peso_max": Decimal('5')},
    {"nome": "De 5 a 6 kg",     "peso_max": Decimal('6')},
    {"nome": "De 6 a 7 kg",     "peso_max": Decimal('7')},
    {"nome": "De 7 a 8 kg",     "peso_max": Decimal('8')},
    {"nome": "De 8 a 9 kg",     "peso_max": Decimal('9')},
    {"nome": "De 9 a 10 kg",    "peso_max": Decimal('10')},
    {"nome": "Acima de 10 kg",  "peso_max": None},
]

FAIXAS_PRECO = [
    {"chave": "0_a_18.99",  "preco_min": Decimal('0'),   "preco_max": Decimal('18.99')},
    {"chave": "19_a_48.99", "preco_min": Decimal('19'),  "preco_max": Decimal('48.99')},
    {"chave": "49_a_78.99", "preco_min": Decimal('49'),  "preco_max": Decimal('78.99')},
    {"chave": "79_ou_mais", "preco_min": Decimal('79'),  "preco_max": None},
]


def encontrar_faixa_peso(peso_kg):
    for linha in TABELA_PESO:
        if linha['peso_max'] is None or peso_kg <= linha['peso_max']:
            return linha['nome']
    return TABELA_PESO[-1]['nome']


def encontrar_faixa_preco(preco):
    for faixa in FAIXAS_PRECO:
        if faixa['preco_max'] is None:
            if preco >= faixa['preco_min']:
                return faixa['chave']
        elif faixa['preco_min'] <= preco <= faixa['preco_max']:
            return faixa['chave']
    return None


def _formatar_dimensao(valor):
    inteiro = valor.to_integral_value()
    if valor == inteiro:
        return str(int(inteiro))
    return str(valor.normalize())


def montar_dimensions_str(altura_cm, largura_cm, comprimento_cm, peso_fisico_kg):
    f = _formatar_dimensao
    peso_gramas = int((peso_fisico_kg * Decimal('1000')).to_integral_value())
    return f'{f(altura_cm)}x{f(largura_cm)}x{f(comprimento_cm)},{peso_gramas}'


@dataclass
class CandidatoAnalisado:
    ean: str
    sku: str
    mlb: str
    tipo_anuncio: str
    tipo_label: str
    tipo_logistico: str
    tipo_logistico_label: str
    category_id: str
    categoria_raiz_id: str
    categoria_nome: str
    classificacao_catalogo: str
    flex: bool
    altura_cm: Decimal
    largura_cm: Decimal
    comprimento_cm: Decimal
    peso_fisico_kg: Decimal
    peso_cubado_kg: Decimal
    peso_faturavel_kg: Decimal
    faixa_peso_nome: str
    item_price: Decimal
    faixa_preco_chave: str
    estrato: tuple = None


def calcular_peso_cubado_kg(altura_cm, largura_cm, comprimento_cm):
    return (altura_cm * largura_cm * comprimento_cm) / Decimal('6000')


console.print(Panel(
    '[bold]Investigação do Gatilho de discount.type (mandatory x fs_optional)[/bold]\n'
    f'Conta {CONTA} — amostragem estratificada de produtos reais + controle cruzado com preços fixos',
    border_style='blue',
))

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
TipoLogistico = TipoDeAnuncioMercadoLivre.TipoLogistico
Status = TipoDeAnuncioMercadoLivre.Status

variacoes = (
    VariacaoAnuncioMercadoLivre.objects
    .filter(
        altura_declarada_cm__isnull=False,
        largura_declarada_cm__isnull=False,
        comprimento_declarado_cm__isnull=False,
        peso_declarado_kg__isnull=False,
        preco_atual__isnull=False,
        produto__isnull=False,
        categoria__isnull=False,
        anuncio__tipo_de_anuncio__status=Status.ATIVO,
    )
    .select_related('anuncio', 'anuncio__tipo_de_anuncio', 'produto', 'categoria')
)

candidatos = []
for v in variacoes:
    altura_cm, largura_cm, comprimento_cm = v.altura_declarada_cm, v.largura_declarada_cm, v.comprimento_declarado_cm
    peso_fisico_kg = v.peso_declarado_kg
    item_price = v.preco_atual

    if altura_cm <= 0 or largura_cm <= 0 or comprimento_cm <= 0 or peso_fisico_kg <= 0 or item_price <= 0:
        continue

    peso_cubado_kg = calcular_peso_cubado_kg(altura_cm, largura_cm, comprimento_cm)
    peso_faturavel_kg = max(peso_fisico_kg, peso_cubado_kg)
    faixa_peso_nome = encontrar_faixa_peso(peso_faturavel_kg)
    faixa_preco_chave = encontrar_faixa_preco(item_price)

    tipo_de_anuncio = v.anuncio.tipo_de_anuncio
    tipo_logistico_label = TipoLogistico(tipo_de_anuncio.tipo_logistico).label if tipo_de_anuncio.tipo_logistico else '—'

    c = CandidatoAnalisado(
        ean=v.produto.ean, sku=v.produto.sku, mlb=v.anuncio.mlb,
        tipo_anuncio=tipo_de_anuncio.tipo_anuncio,
        tipo_label='Clássico' if tipo_de_anuncio.tipo_anuncio == TipoAnuncio.CLASSICO else 'Premium',
        tipo_logistico=tipo_de_anuncio.tipo_logistico, tipo_logistico_label=tipo_logistico_label,
        category_id=v.categoria.category_id, categoria_raiz_id=v.categoria.categoria_raiz_id,
        categoria_nome=v.categoria.nome, classificacao_catalogo=tipo_de_anuncio.classificacao_catalogo,
        flex=tipo_de_anuncio.flex,
        altura_cm=altura_cm, largura_cm=largura_cm, comprimento_cm=comprimento_cm,
        peso_fisico_kg=peso_fisico_kg, peso_cubado_kg=peso_cubado_kg, peso_faturavel_kg=peso_faturavel_kg,
        faixa_peso_nome=faixa_peso_nome, item_price=item_price, faixa_preco_chave=faixa_preco_chave,
    )
    c.estrato = (faixa_peso_nome, c.categoria_raiz_id, c.tipo_logistico)
    candidatos.append(c)

if not candidatos:
    console.print('[bold red]Nenhum candidato com dado completo + categoria preenchida encontrado. Nada a fazer.[/bold red]')
    sys.exit(1)

console.print(f'{len(candidatos)} candidato(s) com dado completo (dimensão + categoria) encontrado(s).\n')

pool_abaixo_de_79 = [c for c in candidatos if c.item_price < Decimal('79')]
if not pool_abaixo_de_79:
    console.print('[bold red]Nenhum candidato com preco_atual < R$79 — não dá pra rodar o Passe 1 (o fenômeno só '
                   'existe nessa faixa). Abortando.[/bold red]')
    sys.exit(1)

console.print(f'{len(pool_abaixo_de_79)} candidato(s) com preco_atual < R$79 (pool do Passe 1).\n')


def selecionar_diverso(pool, limite, max_por_estrato):
    """Seleciona priorizando cobertura de estrato — até max_por_estrato por estrato numa 1ª
    passada, depois preenche o resto do limite livremente. Mesma lógica (simplificada, 1
    passada só) de buscar_e_testar_candidatos_diversos_frete_via_api.py."""
    selecionados = []
    contagem_por_estrato = {}
    for c in pool:
        if len(selecionados) >= limite:
            break
        if contagem_por_estrato.get(c.estrato, 0) >= max_por_estrato:
            continue
        selecionados.append(c)
        contagem_por_estrato[c.estrato] = contagem_por_estrato.get(c.estrato, 0) + 1
    if len(selecionados) < limite:
        ja_selecionados_ids = {id(c) for c in selecionados}
        for c in pool:
            if len(selecionados) >= limite:
                break
            if id(c) in ja_selecionados_ids:
                continue
            selecionados.append(c)
    return selecionados


def selecionar_maxima_diversidade(pool, limite):
    """Passe 2 — prioriza estratos NUNCA vistos antes (não permite repetir estrato enquanto
    houver estrato novo disponível), pra maximizar cobertura de categoria/peso/logística com
    poucos candidatos."""
    selecionados = []
    estratos_vistos = set()
    for c in pool:
        if len(selecionados) >= limite:
            break
        if c.estrato in estratos_vistos:
            continue
        selecionados.append(c)
        estratos_vistos.add(c.estrato)
    if len(selecionados) < limite:
        ja_selecionados_ids = {id(c) for c in selecionados}
        for c in pool:
            if len(selecionados) >= limite:
                break
            if id(c) in ja_selecionados_ids:
                continue
            selecionados.append(c)
    return selecionados


selecionados_passe_1 = selecionar_diverso(pool_abaixo_de_79, LIMITE_PASSE_1, MAX_POR_ESTRATO_PASSE_1)
selecionados_passe_2 = selecionar_maxima_diversidade(candidatos, LIMITE_PASSE_2)  # sem filtro de preço — preço é fixado

tabela_selecao = Table(title=f'Passe 1 — {len(selecionados_passe_1)} candidato(s) selecionado(s)')
tabela_selecao.add_column('MLB')
tabela_selecao.add_column('Faixa peso')
tabela_selecao.add_column('Categoria raiz')
tabela_selecao.add_column('Tipo logístico')
tabela_selecao.add_column('Preço', justify='right')
for c in selecionados_passe_1:
    tabela_selecao.add_row(c.mlb, c.faixa_peso_nome, f'{c.categoria_raiz_id} ({c.categoria_nome})',
                            c.tipo_logistico_label, f'R$ {c.item_price}')
console.print(tabela_selecao)

tabela_controle = Table(title=f'Passe 2 — {len(selecionados_passe_2)} candidato(s) selecionado(s) (controle cruzado)')
tabela_controle.add_column('MLB')
tabela_controle.add_column('Faixa peso')
tabela_controle.add_column('Categoria raiz')
tabela_controle.add_column('Tipo logístico')
for c in selecionados_passe_2:
    tabela_controle.add_row(c.mlb, c.faixa_peso_nome, f'{c.categoria_raiz_id} ({c.categoria_nome})', c.tipo_logistico_label)
console.print(tabela_controle)

try:
    resposta_me = chamar_api("GET", "/users/me", pasta_logs=PASTA_LOGS, conta=CONTA,
                              nome_log="investigar_gatilho_discount_type")
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro buscando user_id: {erro}[/bold red]')
    sys.exit(1)


def testar_discount(candidato, item_price):
    dimensions_str = montar_dimensions_str(candidato.altura_cm, candidato.largura_cm,
                                            candidato.comprimento_cm, candidato.peso_fisico_kg)
    endpoint = f"/users/{user_id}/shipping_options/free"
    params = {
        "dimensions": dimensions_str,
        "item_price": str(item_price),
        "verbose": "true",
        "condition": "new",
        "category_id": candidato.category_id,
        "listing_type_id": candidato.tipo_anuncio,
        "mode": "me2",
        "free_shipping": "false",
    }
    try:
        resposta = chamar_api("GET", endpoint, pasta_logs=PASTA_LOGS, conta=CONTA, params=params,
                               nome_log="investigar_gatilho_discount_type")
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        return {"erro": str(erro)}
    corpo = resposta.json()
    coverage = corpo.get("coverage", {}).get("all_country", {})
    discount = coverage.get("discount")
    return {
        "list_cost": coverage.get("list_cost"),
        "billable_weight_g": coverage.get("billable_weight"),
        "discount_type": discount.get("type") if isinstance(discount, dict) else None,
        "discount_rate": discount.get("rate") if isinstance(discount, dict) else None,
        "discount_promoted_amount": discount.get("promoted_amount") if isinstance(discount, dict) else None,
        "erro": None,
    }


# ---- PASSE 1 ----
console.print('\n[bold]Rodando Passe 1 (amostragem ampla, preço próprio de cada candidato)...[/bold]\n')
resultados_passe_1 = []
for indice, c in enumerate(selecionados_passe_1, start=1):
    console.print(f'[{indice}/{len(selecionados_passe_1)}] {c.mlb} (R$ {c.item_price}, {c.faixa_peso_nome})...')
    r = testar_discount(c, c.item_price)
    resultados_passe_1.append({"candidato": c, "resultado": r})

# ---- PASSE 2 ----
console.print('\n[bold]Rodando Passe 2 (controle cruzado, 3 preços fixos por candidato)...[/bold]\n')
resultados_passe_2 = []
for indice, c in enumerate(selecionados_passe_2, start=1):
    linha = {"candidato": c, "por_preco": {}}
    for preco in PRECOS_CONTROLE:
        console.print(f'[{indice}/{len(selecionados_passe_2)}] {c.mlb} @ R$ {preco}...')
        linha["por_preco"][str(preco)] = testar_discount(c, preco)
    resultados_passe_2.append(linha)

# ---- Cruzamentos do Passe 1 ----
console.print('\n[bold]Resumo — Passe 1[/bold]')


def cruzar(chave_fn, titulo, nome_coluna):
    contagem = defaultdict(Counter)
    for item in resultados_passe_1:
        if item["resultado"].get("erro"):
            continue
        chave = chave_fn(item["candidato"])
        tipo = item["resultado"].get("discount_type") or "(nenhum discount)"
        contagem[chave][tipo] += 1
    tabela = Table(title=titulo)
    tabela.add_column(nome_coluna)
    tipos_vistos = sorted({t for c in contagem.values() for t in c})
    for t in tipos_vistos:
        tabela.add_column(t, justify='right')
    for chave in sorted(contagem.keys(), key=str):
        linha = [str(chave)] + [str(contagem[chave].get(t, 0)) for t in tipos_vistos]
        tabela.add_row(*linha)
    console.print(tabela)
    return {str(k): dict(v) for k, v in contagem.items()}


cruzamentos = {
    "por_faixa_preco": cruzar(lambda c: c.faixa_preco_chave, 'discount.type x faixa de preço', 'Faixa de preço'),
    "por_faixa_peso": cruzar(lambda c: c.faixa_peso_nome, 'discount.type x faixa de peso', 'Faixa de peso'),
    "por_tipo_logistico": cruzar(lambda c: c.tipo_logistico_label, 'discount.type x tipo logístico', 'Tipo logístico'),
    "por_categoria_raiz": cruzar(lambda c: f'{c.categoria_raiz_id} ({c.categoria_nome})', 'discount.type x categoria raiz', 'Categoria raiz'),
    "por_classificacao_catalogo": cruzar(lambda c: c.classificacao_catalogo, 'discount.type x classificação catálogo', 'Classificação catálogo'),
    "por_flex": cruzar(lambda c: c.flex, 'discount.type x flex', 'Flex'),
}

console.print('\n[bold]Resumo — Passe 2 (matriz candidato x preço fixo)[/bold]')
tabela_matriz = Table(title='discount.type por candidato, nos 3 preços de controle')
tabela_matriz.add_column('MLB')
tabela_matriz.add_column('Faixa peso')
tabela_matriz.add_column('Categoria raiz')
tabela_matriz.add_column('Tipo logístico')
for preco in PRECOS_CONTROLE:
    tabela_matriz.add_column(f'R$ {preco}')
for linha in resultados_passe_2:
    c = linha["candidato"]
    valores = []
    for preco in PRECOS_CONTROLE:
        r = linha["por_preco"][str(preco)]
        valores.append(r.get("discount_type") or ('erro' if r.get('erro') else '(nenhum)'))
    tabela_matriz.add_row(c.mlb, c.faixa_peso_nome, f'{c.categoria_raiz_id} ({c.categoria_nome})',
                           c.tipo_logistico_label, *valores)
console.print(tabela_matriz)

# ---- Salva JSON ----


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, CandidatoAnalisado):
        d = obj.__dict__.copy()
        d.pop('estrato', None)
        return d
    raise TypeError(f'Tipo não serializável: {type(obj)}')


saida = {
    "contexto": {"conta": CONTA, "limite_passe_1": LIMITE_PASSE_1, "candidatos_controle_passe_2": LIMITE_PASSE_2,
                 "precos_controle": [str(p) for p in PRECOS_CONTROLE]},
    "cruzamentos_passe_1": cruzamentos,
    "passe_1_detalhado": resultados_passe_1,
    "passe_2_detalhado": resultados_passe_2,
}
with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2, default=_serializar)

console.print(f'\nResultado completo salvo em: {CAMINHO_SAIDA}')
console.print('Suba esse arquivo (ou cole os resumos das tabelas acima) na conversa pra eu analisar.')