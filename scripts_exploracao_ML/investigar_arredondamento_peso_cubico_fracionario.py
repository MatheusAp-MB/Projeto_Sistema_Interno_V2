# scripts_exploracao_ML/investigar_arredondamento_peso_cubico_fracionario.py

# Função Objetivo: Descobrir qual convenção de arredondamento a API do Mercado Livre usa pro
# peso cúbico FRACIONÁRIO (peso cúbico = altura×largura×comprimento÷6000, quase sempre um
# número com várias casas decimais, já que altura/largura/comprimento têm 2 casas decimais em
# cm) — comparando o billable_weight que a PRÓPRIA API devolve contra o peso faturável
# calculado localmente sob 3 convenções de arredondamento diferentes (mais próximo, teto,
# truncado — todas pro grama mais próximo) — e checando se a convenção escolhida muda de fato
# a FAIXA de peso de FreteML selecionada (ou só o número exibido, sem mudar o frete cobrado).
#
# Prioriza candidatos reais onde:
#   1) o peso cúbico DOMINA o físico (é ele que vira o faturável);
#   2) o peso cúbico é FRACIONÁRIO no grama (altura×largura×comprimento÷6 não é um inteiro
#      exato de gramas — só aí existe ambiguidade de arredondamento pra falar a verdade);
#   3) o resultado (sob a convenção "mais próximo") cai perto (dentro de --margem-borda-kg)
#      de uma fronteira de faixa de peso — só aí a convenção realmente PODE mudar qual faixa
#      é selecionada (longe de fronteira, qualquer convenção cai na mesma faixa).
# Candidatos que já batem os 3 critérios são testados primeiro; se sobrar --limite, completa
# com candidatos que só batem 1)+2) (fracionário e dominante, mas longe de fronteira — ainda
# útil pra confirmar a convenção da API, só não muda o resultado final).
#
# Cada candidato selecionado gera 1 chamada à API (sem frete grátis, no preço atual real do
# anúncio — mesmo caminho usado por _tentar_resolver_preco_via_api em produção).
#
# Só leitura no banco e na API — nenhuma escrita em lugar nenhum, além do JSON de saída.
#
# Uso: python -u "scripts_exploracao_ML/investigar_arredondamento_peso_cubico_fracionario.py" [opções]
# --empresa: MB ou SV — default MB.
# --limite: máximo de candidatos testados via API. Default: 20.
# --margem-borda-kg: distância (kg) até a fronteira de faixa de peso pra priorizar um
#   candidato como "perto de fronteira" (onde a convenção de arredondamento pode mudar o
#   resultado). Default: 0.05 (50g) — mesmo default já usado em
#   buscar_e_testar_candidatos_diversos_frete_via_api.py.

import os
import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR


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
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

parser = argparse.ArgumentParser(
    description='Descobre a convenção de arredondamento de peso cúbico fracionário usada pela '
                 'API do ML, comparando billable_weight real contra 3 convenções locais.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB', help='Empresa/conta ML. Default: MB.')
parser.add_argument('--limite', type=int, default=20, help='Máximo de candidatos testados via API. Default: 20.')
parser.add_argument('--margem-borda-kg', type=Decimal, default=Decimal('0.05'),
                     help='Distância (kg) até a fronteira de faixa de peso pra priorizar como "perto de fronteira". Default: 0.05.')
args = parser.parse_args()

CONTA = args.empresa
LIMITE = args.limite
MARGEM_BORDA_KG = args.margem_borda_kg

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"investigacao_arredondamento_peso_cubico_{CONTA}.json"

FRETE_ML_TODAS = list(FreteML.objects.all())  # mesma fonte/ordering real de produção — só leitura

# Fronteiras de faixa de peso REAIS (fechada só no limite superior — convenção empírica já
# validada em buscar_e_testar_candidatos_diversos_frete_via_api.py) — usadas aqui só pra achar
# a distância até a fronteira mais próxima.
LIMITES_FAIXA_PESO_KG = [
    Decimal('0.3'), Decimal('0.5'), Decimal('1'), Decimal('1.5'), Decimal('2'), Decimal('3'),
    Decimal('4'), Decimal('5'), Decimal('6'), Decimal('7'), Decimal('8'), Decimal('9'),
    Decimal('10'), Decimal('11'), Decimal('13'), Decimal('15'), Decimal('17'), Decimal('20'),
    Decimal('25'), Decimal('30'), Decimal('40'), Decimal('50'), Decimal('60'), Decimal('70'),
    Decimal('80'), Decimal('90'), Decimal('100'), Decimal('125'), Decimal('150'),
]

# Faixas de preço — só pra achar o frete real de FreteML (2D: peso x preço) pra comparação.
FAIXAS_PRECO = [
    {"preco_min": Decimal('0'),   "preco_max": Decimal('18.99')},
    {"preco_min": Decimal('19'),  "preco_max": Decimal('48.99')},
    {"preco_min": Decimal('49'),  "preco_max": Decimal('78.99')},
    {"preco_min": Decimal('79'),  "preco_max": Decimal('99.99')},
    {"preco_min": Decimal('100'), "preco_max": Decimal('119.99')},
    {"preco_min": Decimal('120'), "preco_max": Decimal('149.99')},
    {"preco_min": Decimal('150'), "preco_max": Decimal('199.99')},
    {"preco_min": Decimal('200'), "preco_max": None},
]


def distancia_ate_fronteira_mais_proxima(peso_kg):
    distancias = [abs(peso_kg - limite) for limite in LIMITES_FAIXA_PESO_KG]
    return min(distancias) if distancias else None


def buscar_frete_real(peso_kg, preco, regime):
    """MESMA condição fechada-nos-2-lados que calcular_frete_producao_local() usa em
    buscar_e_testar_candidatos_diversos_frete_via_api.py — reproduz o que a PRODUÇÃO faria
    (não a convenção 'correta'), pra mostrar se a convenção de arredondamento muda o valor de
    frete de fato usado hoje."""
    candidatos = [
        f for f in FRETE_ML_TODAS
        if f.regime == regime and f.peso_min <= peso_kg and (f.peso_max is None or f.peso_max >= peso_kg)
        and f.preco_min <= preco and (f.preco_max is None or f.preco_max >= preco)
    ]
    return candidatos[0].valor if candidatos else None


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
    category_id: str
    altura_cm: Decimal
    largura_cm: Decimal
    comprimento_cm: Decimal
    peso_fisico_kg: Decimal
    peso_cubado_gramas_raw: Decimal   # sem arredondar — A×L×C÷6, em gramas
    peso_cubado_nearest_g: int
    peso_cubado_ceiling_g: int
    peso_cubado_floor_g: int
    item_price: Decimal
    distancia_fronteira_kg: Decimal
    perto_de_fronteira: bool
    prioridade: int  # 0 = perto de fronteira (melhor candidato), 1 = só fracionário+dominante


console.print(Panel(
    '[bold]Investigação do Arredondamento de Peso Cúbico Fracionário[/bold]\n'
    f'Conta {CONTA} — comparando billable_weight real da API contra 3 convenções locais',
    border_style='blue',
))

Status = TipoDeAnuncioMercadoLivre.Status

variacoes = (
    VariacaoAnuncioMercadoLivre.objects
    .filter(
        altura_declarada_cm__isnull=False, largura_declarada_cm__isnull=False,
        comprimento_declarado_cm__isnull=False, peso_declarado_kg__isnull=False,
        preco_atual__isnull=False, produto__isnull=False, categoria__isnull=False,
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

    peso_cubado_gramas_raw = (altura_cm * largura_cm * comprimento_cm) / Decimal('6')
    peso_cubado_kg_raw = peso_cubado_gramas_raw / Decimal('1000')

    if peso_cubado_kg_raw <= peso_fisico_kg:
        continue  # peso cúbico não domina — não é caso de interesse pra este script

    e_fracionario = peso_cubado_gramas_raw != peso_cubado_gramas_raw.to_integral_value()
    if not e_fracionario:
        continue  # peso cúbico já é um número inteiro de gramas — não existe ambiguidade

    peso_cubado_nearest_g = int(peso_cubado_gramas_raw.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    peso_cubado_ceiling_g = int(peso_cubado_gramas_raw.quantize(Decimal('1'), rounding=ROUND_CEILING))
    peso_cubado_floor_g = int(peso_cubado_gramas_raw.quantize(Decimal('1'), rounding=ROUND_FLOOR))

    peso_faturavel_nearest_kg = max(peso_fisico_kg, Decimal(peso_cubado_nearest_g) / Decimal('1000'))
    distancia = distancia_ate_fronteira_mais_proxima(peso_faturavel_nearest_kg)
    perto_de_fronteira = distancia is not None and distancia <= MARGEM_BORDA_KG

    tipo_de_anuncio = v.anuncio.tipo_de_anuncio
    candidatos.append(CandidatoAnalisado(
        ean=v.produto.ean, sku=v.produto.sku, mlb=v.anuncio.mlb, tipo_anuncio=tipo_de_anuncio.tipo_anuncio,
        category_id=v.categoria.category_id,
        altura_cm=altura_cm, largura_cm=largura_cm, comprimento_cm=comprimento_cm, peso_fisico_kg=peso_fisico_kg,
        peso_cubado_gramas_raw=peso_cubado_gramas_raw,
        peso_cubado_nearest_g=peso_cubado_nearest_g, peso_cubado_ceiling_g=peso_cubado_ceiling_g,
        peso_cubado_floor_g=peso_cubado_floor_g, item_price=item_price,
        distancia_fronteira_kg=distancia, perto_de_fronteira=perto_de_fronteira,
        prioridade=0 if perto_de_fronteira else 1,
    ))

if not candidatos:
    console.print('[bold red]Nenhum candidato com peso cúbico fracionário e dominante encontrado — nada a testar.[/bold red]')
    sys.exit(1)

console.print(f'{len(candidatos)} candidato(s) com peso cúbico fracionário E dominante encontrado(s) '
              f'({sum(1 for c in candidatos if c.perto_de_fronteira)} perto de fronteira de faixa).\n')

candidatos.sort(key=lambda c: (c.prioridade, c.distancia_fronteira_kg))
selecionados = candidatos[:LIMITE]

tabela_selecao = Table(title=f'Candidatos selecionados ({len(selecionados)}/{len(candidatos)} encontrados)')
tabela_selecao.add_column('MLB')
tabela_selecao.add_column('Peso físico (kg)', justify='right')
tabela_selecao.add_column('Peso cúbico raw (kg)', justify='right')
tabela_selecao.add_column('Nearest/Ceiling/Floor (g)', justify='right')
tabela_selecao.add_column('Dist. fronteira (kg)', justify='right')
tabela_selecao.add_column('Perto de fronteira?')
for c in selecionados:
    tabela_selecao.add_row(
        c.mlb, str(c.peso_fisico_kg), f'{(c.peso_cubado_gramas_raw / Decimal(1000)):.6f}',
        f'{c.peso_cubado_nearest_g}/{c.peso_cubado_ceiling_g}/{c.peso_cubado_floor_g}',
        f'{c.distancia_fronteira_kg:.3f}' if c.distancia_fronteira_kg is not None else '—',
        'sim' if c.perto_de_fronteira else 'não',
    )
console.print(tabela_selecao)

try:
    resposta_me = chamar_api("GET", "/users/me", pasta_logs=PASTA_LOGS, conta=CONTA,
                              nome_log="investigar_arredondamento_peso_cubico")
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro buscando user_id: {erro}[/bold red]')
    sys.exit(1)

console.print(f'\nTestando {len(selecionados)} candidato(s) via API...\n')

resultados = []
contagem_convencao_bateu = {"nearest": 0, "ceiling": 0, "floor": 0, "nenhuma": 0}

for indice, c in enumerate(selecionados, start=1):
    console.print(f'[{indice}/{len(selecionados)}] {c.mlb}...')
    dimensions_str = montar_dimensions_str(c.altura_cm, c.largura_cm, c.comprimento_cm, c.peso_fisico_kg)
    endpoint = f"/users/{user_id}/shipping_options/free"
    params = {
        "dimensions": dimensions_str, "item_price": str(c.item_price), "verbose": "true",
        "condition": "new", "category_id": c.category_id, "listing_type_id": c.tipo_anuncio,
        "mode": "me2", "free_shipping": "false",
    }
    try:
        resposta = chamar_api("GET", endpoint, pasta_logs=PASTA_LOGS, conta=CONTA, params=params,
                               nome_log="investigar_arredondamento_peso_cubico")
        corpo = resposta.json()
        coverage = corpo.get("coverage", {}).get("all_country", {})
        billable_weight_api_g = coverage.get("billable_weight")
        list_cost_api = coverage.get("list_cost")
        erro = None
    except (ErroAPI, ErroAutenticacaoAPI) as erro_api:
        billable_weight_api_g, list_cost_api = None, None
        erro = str(erro_api)

    convencao_que_bateu = None
    peso_fisico_g = int((c.peso_fisico_kg * Decimal('1000')).to_integral_value())
    if billable_weight_api_g is not None:
        candidatas_convencao = {
            "nearest": max(peso_fisico_g, c.peso_cubado_nearest_g),
            "ceiling": max(peso_fisico_g, c.peso_cubado_ceiling_g),
            "floor": max(peso_fisico_g, c.peso_cubado_floor_g),
        }
        for nome_convencao, valor in candidatas_convencao.items():
            if valor == billable_weight_api_g:
                convencao_que_bateu = nome_convencao
                break
        contagem_convencao_bateu[convencao_que_bateu or "nenhuma"] += 1

    faixa_preco_do_candidato = next(
        (fp for fp in FAIXAS_PRECO if fp['preco_min'] <= c.item_price and (fp['preco_max'] is None or c.item_price <= fp['preco_max'])),
        None,
    )
    frete_nearest, frete_da_convencao_api = None, None
    if faixa_preco_do_candidato is not None:
        peso_nearest_kg = Decimal(max(peso_fisico_g, c.peso_cubado_nearest_g)) / Decimal('1000')
        frete_nearest = buscar_frete_real(peso_nearest_kg, c.item_price, FreteML.Regime.SEM_FRETE_GRATIS_RAPIDO)
        if billable_weight_api_g is not None:
            peso_api_kg = Decimal(billable_weight_api_g) / Decimal('1000')
            frete_da_convencao_api = buscar_frete_real(peso_api_kg, c.item_price, FreteML.Regime.SEM_FRETE_GRATIS_RAPIDO)

    frete_diverge = (frete_nearest is not None and frete_da_convencao_api is not None
                      and frete_nearest != frete_da_convencao_api)

    resultados.append({
        "mlb": c.mlb, "peso_fisico_kg": c.peso_fisico_kg, "peso_cubado_raw_g": c.peso_cubado_gramas_raw,
        "nearest_g": c.peso_cubado_nearest_g, "ceiling_g": c.peso_cubado_ceiling_g, "floor_g": c.peso_cubado_floor_g,
        "perto_de_fronteira": c.perto_de_fronteira, "distancia_fronteira_kg": c.distancia_fronteira_kg,
        "billable_weight_api_g": billable_weight_api_g, "list_cost_api": list_cost_api,
        "convencao_que_bateu_com_api": convencao_que_bateu,
        "frete_com_nearest": frete_nearest, "frete_com_convencao_da_api": frete_da_convencao_api,
        "frete_diverge_por_causa_da_convencao": frete_diverge,
        "erro": erro,
    })

console.print('\n[bold]Resumo por candidato[/bold]')
tabela_resultado = Table(title='billable_weight da API x convenções locais')
tabela_resultado.add_column('MLB')
tabela_resultado.add_column('Nearest/Ceiling/Floor (g)', justify='right')
tabela_resultado.add_column('API (g)', justify='right')
tabela_resultado.add_column('Convenção que bateu')
tabela_resultado.add_column('Frete diverge?')
for r in resultados:
    tabela_resultado.add_row(
        r["mlb"], f'{r["nearest_g"]}/{r["ceiling_g"]}/{r["floor_g"]}',
        str(r["billable_weight_api_g"]) if r["billable_weight_api_g"] is not None else '(erro)',
        r["convencao_que_bateu_com_api"] or '(nenhuma bateu)',
        '[bold red]SIM[/bold red]' if r["frete_diverge_por_causa_da_convencao"] else 'não',
    )
console.print(tabela_resultado)

total_testado_convencao = sum(contagem_convencao_bateu.values())
console.print(Panel(
    f'Convenção que mais bateu com a API: nearest={contagem_convencao_bateu["nearest"]}, '
    f'ceiling={contagem_convencao_bateu["ceiling"]}, floor={contagem_convencao_bateu["floor"]}, '
    f'nenhuma={contagem_convencao_bateu["nenhuma"]} (de {total_testado_convencao} testado(s) com sucesso).\n'
    f'Candidato(s) onde a convenção de arredondamento MUDOU o frete de fato usado: '
    f'{sum(1 for r in resultados if r["frete_diverge_por_causa_da_convencao"])}.',
    border_style='green', title='Conclusão',
))


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Tipo não serializável: {type(obj)}')


saida = {
    "contexto": {"conta": CONTA, "limite": LIMITE, "margem_borda_kg": MARGEM_BORDA_KG},
    "contagem_convencao_bateu": contagem_convencao_bateu,
    "resultados": resultados,
}
with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2, default=_serializar)

console.print(f'\nResultado completo salvo em: {CAMINHO_SAIDA}')
console.print('Suba esse arquivo (ou cole as tabelas acima) na conversa pra eu analisar.')