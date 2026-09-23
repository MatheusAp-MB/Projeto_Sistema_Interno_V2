# scripts_exploracao_ML/buscar_e_testar_candidatos_diversos_frete_via_api.py

# Função Objetivo: Busca no banco produtos reais espalhados pelas faixas de peso/preço da
# tabela oficial de frete do Mercado Livre (mesma tabela real de 30 faixas de peso x 8 faixas
# de preço já usada em investigar_frete_validacao_tabela_completa.py, extraída de
# Tabela_Frete_Mercado_Livre.xlsx), priorizando candidatos perto de uma borda de faixa —
# e já testa cada um via buscar_simulacao_frete_via_api, mostrando os resultados numa
# bateria só. Cada chamada guarda não só o list_cost, mas também o billable_weight (peso
# faturável que a PRÓPRIA API calculou) e o discount da resposta — pra poder comparar direto
# com o peso faturável calculado localmente (candidato.peso_faturavel_kg) sem precisar rodar
# de novo quando aparecer alguma divergência perto de borda de faixa.
#
# Sem frete grátis (Tabela 1, "por conta do comprador") é comparado contra o valor esperado
# calculado a partir da tabela real, com o teto de metade do preço aplicado pra item_price 
# R$19 (regra oficial do doc "Custos dos Envios no Mercado Livre"). Com frete grátis
# (Tabela 2) é testado mas só informativo — ainda não temos a tabela completa dela, só a
# célula peso 0,5-1kg x preço 0-18,99 já confirmada antes (R$14,45, ver Checkpoint Frente A,
# Seção 11).
#
# Fonte do dado de dimensão/peso/preço: VariacaoAnuncioMercadoLivre (declarado no próprio
# anúncio do ML), não o ERP — mesmo motivo já usado em testar_matriz_frete_gratis_via_api.py:
# é o que o Simulador de custos usa de verdade. Só considera anúncio com status ativo e os 4
# campos declarados (altura/largura/comprimento/peso) + preço todos preenchidos.
#
# Estratégia de seleção — candidato ganha 1+ "motivo" quando:
#   - cai perto (dentro de --margem-borda-peso-kg) do limite inferior ou superior da faixa
#     de peso faturável em que se encaixa;
#   - cai perto (dentro de --margem-borda-preco) do limite inferior ou superior da faixa de
#     preço em que se encaixa;
#   - o preço está perto (dentro de --margem-limiar-negocio) de R$19 (teto de metade do
#     preço) ou R$79 (opcional de frete grátis) — os 2 limiares de negócio já discutidos
#     nesse projeto;
#   - o peso cúbico domina o físico, ou o físico domina o cúbico (razão >=
#     --razao-minima-cubico-fisico) — estressa o max() que a própria API faz.
# Candidatos "com motivo" são priorizados (até 2 por faixa de peso numa 1ª passada, pra não
# deixar 1 faixa só consumir o --limite inteiro; o resto do --limite é preenchido livremente
# depois). Faixas de peso que nenhum candidato "com motivo" cobriu ganham 1 candidato
# qualquer (motivo "cobertura_faixa_peso"), se existir produto real naquela faixa — cobertura
# de faixa de PESO é garantida assim; cobertura de faixa de PREÇO é oportunista (só via
# motivo), não garantida.
#
# Cada candidato selecionado gera até 3 chamadas à API (1x /items pra category_id, cacheado
# por MLB — 2x shipping_options/free, sem/com frete grátis). Com o --limite default (50),
# isso é até ~151 chamadas — pode levar alguns minutos.
#
# Uso: python -u "scripts_exploracao_ML/buscar_e_testar_candidatos_diversos_frete_via_api.py" [opções]
# --empresa: MB (Magazine) ou SV (Samvale) — default MB.
# --limite: máximo de candidatos testados de fato via API. Default: 50.
# --margem-borda-peso-kg: distância (kg) até o limite de faixa de peso pra contar como
#   "borda". Default: 0.05.
# --margem-borda-preco: distância (R$) até o limite de faixa de preço pra contar como
#   "borda". Default: 1.00.
# --margem-limiar-negocio: distância (R$) até R$19/R$79 pra contar como candidato desses
#   limiares. Default: 2.00.
# --razao-minima-cubico-fisico: razão mínima peso cúbico/físico (ou o inverso) pra contar
#   como "domina". Default: 1.5.
#
# Só leitura no banco e na API — nenhuma escrita em lugar nenhum, além do JSON de saída
# (mesmo padrão dos outros scripts de exploração).

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
from produtos.models import Produto
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

# ==== ARGUMENTOS DE LINHA DE COMANDO ====
parser = argparse.ArgumentParser(
    description='Busca candidatos reais espalhados pelas faixas de peso/preço da tabela '
                 'real de frete do ML (priorizando bordas) e já testa cada um via API.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB',
                     help='Empresa/conta ML — MB (Magazine) ou SV (Samvale). Default: MB.')
parser.add_argument('--limite', type=int, default=50,
                     help='Máximo de candidatos a testar de fato via API. Default: 50.')
parser.add_argument('--margem-borda-peso-kg', type=Decimal, default=Decimal('0.05'),
                     help='Distância (kg) até o limite de faixa de peso pra contar como '
                          '"borda". Default: 0.05 (50g).')
parser.add_argument('--margem-borda-preco', type=Decimal, default=Decimal('1.00'),
                     help='Distância (R$) até o limite de faixa de preço pra contar como '
                          '"borda". Default: 1.00.')
parser.add_argument('--margem-limiar-negocio', type=Decimal, default=Decimal('2.00'),
                     help='Distância (R$) até R$19 ou R$79 pra contar como candidato desses '
                          'limiares. Default: 2.00.')
parser.add_argument('--razao-minima-cubico-fisico', type=Decimal, default=Decimal('1.5'),
                     help='Razão mínima entre peso cúbico e peso físico (ou o inverso) pra '
                          'contar como caso onde um domina o outro. Default: 1.5 (50%% maior).')
args = parser.parse_args()

CONTA = args.empresa

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])
# * [EXPLICAÇÃO] → Mesmo motivo dos outros scripts: sem isso o Django cai no banco default,
#                  e pra --empresa SV isso leria dado do MB silenciosamente.

LIMITE_CANDIDATOS = args.limite
MARGEM_BORDA_PESO_KG = args.margem_borda_peso_kg
MARGEM_BORDA_PRECO = args.margem_borda_preco
MARGEM_LIMIAR_NEGOCIO = args.margem_limiar_negocio
RAZAO_MINIMA_CUBICO_FISICO = args.razao_minima_cubico_fisico
MAX_POR_FAIXA_PESO_NA_1A_PASSADA = 2  # não deixa 1 faixa sozinha consumir o --limite inteiro

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"bateria_candidatos_diversos_frete_{CONTA}.json"

# Tabela real completa, extraída de Tabela_Frete_Mercado_Livre.xlsx — MESMA tabela já usada
# em investigar_frete_validacao_tabela_completa.py (copiada aqui porque os scripts dessa
# pasta são independentes entre si, nenhum importa do outro).
TABELA_FRETE = [
    {"nome": "Até 0,3 kg",        "peso_min": 0,   "peso_max": 0.3, "precos": [5.65, 6.85, 8.15, 12.95, 14.95, 16.95, 19.05, 21.65]},
    {"nome": "De 0,3 a 0,5 kg",   "peso_min": 0.3, "peso_max": 0.5, "precos": [5.95, 6.95, 8.25, 13.85, 16.15, 18.15, 20.45, 23.25]},
    {"nome": "De 0,5 a 1 kg",     "peso_min": 0.5, "peso_max": 1,   "precos": [6.05, 7.15, 8.45, 14.45, 16.85, 19.05, 21.35, 24.45]},
    {"nome": "De 1 a 1,5 kg",     "peso_min": 1,   "peso_max": 1.5, "precos": [6.15, 7.35, 8.65, 14.75, 17.15, 19.45, 21.75, 25.45]},
    {"nome": "De 1,5 a 2 kg",     "peso_min": 1.5, "peso_max": 2,   "precos": [6.25, 7.45, 8.75, 15.05, 17.65, 19.85, 22.25, 25.55]},
    {"nome": "De 2 a 3 kg",       "peso_min": 2,   "peso_max": 3,   "precos": [6.35, 8.65, 9.15, 16.45, 19.15, 21.65, 24.35, 27.05]},
    {"nome": "De 3 a 4 kg",       "peso_min": 3,   "peso_max": 4,   "precos": [6.45, 8.75, 9.75, 17.85, 20.75, 23.35, 26.35, 29.25]},
    {"nome": "De 4 a 5 kg",       "peso_min": 4,   "peso_max": 5,   "precos": [6.55, 8.85, 10.25, 19.75, 22.85, 26.05, 29.25, 32.45]},
    {"nome": "De 5 a 6 kg",       "peso_min": 5,   "peso_max": 6,   "precos": [6.65, 8.95, 10.35, 25.95, 29.15, 33.35, 36.45, 40.85]},
    {"nome": "De 6 a 7 kg",       "peso_min": 6,   "peso_max": 7,   "precos": [6.75, 9.05, 10.45, 27.55, 31.65, 36.75, 40.85, 45.25]},
    {"nome": "De 7 a 8 kg",       "peso_min": 7,   "peso_max": 8,   "precos": [6.85, 9.25, 10.55, 29.45, 34.35, 39.25, 44.15, 49.35]},
    {"nome": "De 8 a 9 kg",       "peso_min": 8,   "peso_max": 9,   "precos": [6.95, 9.35, 10.65, 30.25, 35.25, 40.35, 45.35, 50.75]},
    {"nome": "De 9 a 10 kg",      "peso_min": 9,   "peso_max": 10,  "precos": [7.05, 9.45, 10.85, 38.25, 45.05, 51.95, 58.75, 65.85]},
    {"nome": "De 10 a 11 kg",     "peso_min": 10,  "peso_max": 11,  "precos": [7.05, 9.65, 11.05, 41.65, 48.55, 55.45, 62.35, 69.35]},
    {"nome": "De 11 a 13 kg",     "peso_min": 11,  "peso_max": 13,  "precos": [7.15, 10.05, 11.45, 42.55, 49.75, 56.85, 63.85, 70.95]},
    {"nome": "De 13 a 15 kg",     "peso_min": 13,  "peso_max": 15,  "precos": [7.25, 10.25, 11.65, 45.55, 52.95, 60.55, 68.15, 75.65]},
    {"nome": "De 15 a 17 kg",     "peso_min": 15,  "peso_max": 17,  "precos": [7.35, 10.45, 11.85, 48.95, 56.55, 64.05, 71.35, 79.35]},
    {"nome": "De 17 a 20 kg",     "peso_min": 17,  "peso_max": 20,  "precos": [7.45, 10.65, 12.05, 55.15, 64.35, 73.55, 82.75, 91.95]},
    {"nome": "De 20 a 25 kg",     "peso_min": 20,  "peso_max": 25,  "precos": [7.65, 11.05, 12.25, 64.55, 75.75, 85.45, 96.25, 106.85]},
    {"nome": "De 25 a 30 kg",     "peso_min": 25,  "peso_max": 30,  "precos": [7.75, 11.25, 12.45, 66.45, 76.05, 86.25, 97.15, 107.85]},
    {"nome": "De 30 a 40 kg",     "peso_min": 30,  "peso_max": 40,  "precos": [7.85, 11.45, 12.65, 68.35, 79.65, 89.75, 100.05, 107.95]},
    {"nome": "De 40 a 50 kg",     "peso_min": 40,  "peso_max": 50,  "precos": [7.95, 11.65, 12.85, 70.95, 81.85, 92.85, 103.45, 111.65]},
    {"nome": "De 50 a 60 kg",     "peso_min": 50,  "peso_max": 60,  "precos": [8.05, 11.85, 13.05, 75.55, 87.25, 99.05, 110.25, 119.05]},
    {"nome": "De 60 a 70 kg",     "peso_min": 60,  "peso_max": 70,  "precos": [8.15, 12.05, 13.25, 80.95, 93.75, 105.95, 118.05, 127.45]},
    {"nome": "De 70 a 80 kg",     "peso_min": 70,  "peso_max": 80,  "precos": [8.25, 12.25, 13.45, 84.65, 97.95, 110.75, 123.35, 133.15]},
    {"nome": "De 80 a 90 kg",     "peso_min": 80,  "peso_max": 90,  "precos": [8.35, 12.45, 13.65, 94.05, 108.35, 122.95, 136.95, 147.85]},
    {"nome": "De 90 a 100 kg",    "peso_min": 90,  "peso_max": 100, "precos": [8.45, 12.65, 13.85, 107.45, 124.85, 140.45, 156.45, 168.85]},
    {"nome": "De 100 a 125 kg",   "peso_min": 100, "peso_max": 125, "precos": [8.55, 12.85, 14.05, 120.15, 138.95, 156.95, 174.85, 188.85]},
    {"nome": "De 125 a 150 kg",   "peso_min": 125, "peso_max": 150, "precos": [8.65, 12.85, 14.25, 127.45, 147.05, 166.55, 185.55, 200.35]},
    {"nome": "Mais de 150 kg",    "peso_min": 150, "peso_max": None, "precos": [8.75, 12.85, 14.45, 167.05, 193.35, 218.45, 243.45, 262.85]},
]

# Faixas de preço na MESMA ordem das colunas de TABELA_FRETE["precos"] — limites explícitos
# (a versão original em investigar_frete_validacao_tabela_completa.py só tinha um preço de
# teste representativo por coluna, não os limites; aqui os limites são o ponto principal).
FAIXAS_PRECO = [
    {"chave": "0_a_18.99",       "preco_min": Decimal('0'),   "preco_max": Decimal('18.99'), "indice_coluna": 0},
    {"chave": "19_a_48.99",      "preco_min": Decimal('19'),  "preco_max": Decimal('48.99'), "indice_coluna": 1},
    {"chave": "49_a_78.99",      "preco_min": Decimal('49'),  "preco_max": Decimal('78.99'), "indice_coluna": 2},
    {"chave": "79_a_99.99",      "preco_min": Decimal('79'),  "preco_max": Decimal('99.99'), "indice_coluna": 3},
    {"chave": "100_a_119.99",    "preco_min": Decimal('100'), "preco_max": Decimal('119.99'), "indice_coluna": 4},
    {"chave": "120_a_149.99",    "preco_min": Decimal('120'), "preco_max": Decimal('149.99'), "indice_coluna": 5},
    {"chave": "150_a_199.99",    "preco_min": Decimal('150'), "preco_max": Decimal('199.99'), "indice_coluna": 6},
    {"chave": "a_partir_de_200", "preco_min": Decimal('200'), "preco_max": None, "indice_coluna": 7},
]


def _formatar_dimensao(valor):
    """Decimal -> string pro formato que a API espera (13.00 -> '13', 13.50 -> '13.5')."""
    inteiro = valor.to_integral_value()
    if valor == inteiro:
        return str(int(inteiro))
    return str(valor.normalize())


def calcular_peso_cubado_kg(altura_cm, largura_cm, comprimento_cm):
    return (altura_cm * largura_cm * comprimento_cm) / Decimal('6000')


def encontrar_faixa_peso(peso_faturavel_kg):
    for linha in TABELA_FRETE:
        peso_min = Decimal(str(linha['peso_min']))
        if linha['peso_max'] is None:
            if peso_faturavel_kg >= peso_min:
                return linha
        else:
            peso_max = Decimal(str(linha['peso_max']))
            if peso_min <= peso_faturavel_kg < peso_max:
                return linha
    return None


def encontrar_faixa_preco(item_price):
    for faixa in FAIXAS_PRECO:
        if faixa['preco_max'] is None:
            if item_price >= faixa['preco_min']:
                return faixa
        elif faixa['preco_min'] <= item_price <= faixa['preco_max']:
            return faixa
    return None


def calcular_gabarito_tabela_1(faixa_peso, faixa_preco, item_price):
    """Valor esperado pra Tabela 1 (sem frete grátis), com o teto de metade do preço (regra
    oficial do doc, item_price < R$19) — devolve (valor_esperado, teto_foi_aplicado)."""
    valor_nominal = Decimal(str(faixa_peso['precos'][faixa_preco['indice_coluna']]))
    if item_price < Decimal('19'):
        valor_com_teto = min(valor_nominal, item_price / 2)
        return valor_com_teto, (valor_com_teto != valor_nominal)
    return valor_nominal, False


def montar_motivos(peso_fisico_kg, peso_cubado_kg, peso_faturavel_kg, faixa_peso, item_price, faixa_preco):
    motivos = []

    if (peso_faturavel_kg - Decimal(str(faixa_peso['peso_min']))) <= MARGEM_BORDA_PESO_KG:
        motivos.append('borda_peso_inferior')
    if faixa_peso['peso_max'] is not None:
        if (Decimal(str(faixa_peso['peso_max'])) - peso_faturavel_kg) <= MARGEM_BORDA_PESO_KG:
            motivos.append('borda_peso_superior')

    if (item_price - faixa_preco['preco_min']) <= MARGEM_BORDA_PRECO:
        motivos.append('borda_preco_inferior')
    if faixa_preco['preco_max'] is not None:
        if (faixa_preco['preco_max'] - item_price) <= MARGEM_BORDA_PRECO:
            motivos.append('borda_preco_superior')

    if abs(item_price - Decimal('19')) <= MARGEM_LIMIAR_NEGOCIO:
        motivos.append('perto_de_r19')
    if abs(item_price - Decimal('79')) <= MARGEM_LIMIAR_NEGOCIO:
        motivos.append('perto_de_r79')

    if peso_fisico_kg > 0 and (peso_cubado_kg / peso_fisico_kg) >= RAZAO_MINIMA_CUBICO_FISICO:
        motivos.append('peso_cubico_domina')
    if peso_cubado_kg > 0 and (peso_fisico_kg / peso_cubado_kg) >= RAZAO_MINIMA_CUBICO_FISICO:
        motivos.append('peso_fisico_domina')

    return motivos


@dataclass
class RespostaSimulacaoFrete:
    """Objeto de processo — resposta relevante de 1 chamada a shipping_options/free (não só
    o list_cost final, também o billable_weight e o discount que a API calculou). Nunca
    salvo no banco."""
    list_cost: Decimal
    billable_weight_g: int | None
    discount: dict | None


def buscar_simulacao_frete_via_api(user_id, category_id, item_price, dimensions_str, tipo_anuncio, frete_gratis):
    """Mesma chamada de sempre (endpoint e params idênticos aos outros scripts), mas agora
    devolve billable_weight e discount junto com o list_cost — não só o valor final, mas o
    peso faturável que a PRÓPRIA API calculou, pra comparar com o nosso cálculo local
    (candidato.peso_faturavel_kg) nos casos de divergência perto de borda de faixa."""
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
        nome_log="buscar_e_testar_candidatos_diversos_frete_via_api",
    )
    corpo = resposta.json()
    coverage = corpo.get("coverage", {}).get("all_country", {})
    list_cost = coverage.get("list_cost")
    if list_cost is None:
        raise ErroAPI(
            f"API não retornou list_cost pra item_price={item_price}, tipo={tipo_anuncio}, "
            f"free_shipping={frete_gratis} — resposta: {corpo}"
        )
    return RespostaSimulacaoFrete(
        list_cost=Decimal(str(list_cost)),
        billable_weight_g=coverage.get("billable_weight"),
        discount=coverage.get("discount"),
    )


@dataclass
class CandidatoAnalisado:
    """Objeto de processo — 1 VariacaoAnuncioMercadoLivre com dado declarado completo, já
    com peso faturável/faixas calculados. Nunca salvo no banco."""
    ean: str
    sku: str
    mlb: str
    tipo_anuncio: str   # 'gold_special' / 'gold_pro' — valor cru, pro parâmetro da API
    tipo_label: str      # 'Clássico' / 'Premium' — só exibição
    altura_cm: Decimal
    largura_cm: Decimal
    comprimento_cm: Decimal
    peso_fisico_kg: Decimal
    peso_cubado_kg: Decimal
    peso_faturavel_kg: Decimal
    faixa_peso: dict
    item_price: Decimal
    faixa_preco: dict
    motivos: list


@dataclass
class ResultadoTesteCandidato:
    """Objeto de processo — resultado das chamadas à API pra 1 candidato selecionado. Nunca
    salvo no banco."""
    candidato: CandidatoAnalisado
    sem_fg_obtido: Decimal | None
    sem_fg_esperado: Decimal | None
    sem_fg_teto_aplicado: bool
    sem_fg_billable_weight_g: int | None
    sem_fg_discount: dict | None
    com_fg_obtido: Decimal | None
    com_fg_billable_weight_g: int | None
    com_fg_discount: dict | None
    erro: str | None

    @property
    def sem_fg_bate(self) -> bool | None:
        if self.sem_fg_obtido is None or self.sem_fg_esperado is None:
            return None
        return self.sem_fg_obtido == self.sem_fg_esperado

    @property
    def peso_faturavel_api_kg(self) -> Decimal | None:
        """Peso faturável que a PRÓPRIA API calculou (billable_weight da resposta, em
        gramas, convertido pra kg com 3 casas) — pra comparar direto com o peso faturável
        calculado localmente (candidato.peso_faturavel_kg, também arredondado a 3 casas na
        hora da comparação) e confirmar ou derrubar a hipótese de diferença de
        arredondamento nas bordas de faixa."""
        if self.sem_fg_billable_weight_g is None:
            return None
        return (Decimal(self.sem_fg_billable_weight_g) / Decimal('1000')).quantize(Decimal('0.001'))


# ========== Fluxo principal ==========

console.print(Panel(
    '[bold]Busca e Teste de Candidatos Diversos — Bateria de Frete via API[/bold]\n'
    f'Conta {CONTA} — cobrindo o máximo de faixas de peso/preço reais, priorizando bordas',
    border_style='blue',
))

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
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
        anuncio__tipo_de_anuncio__status=Status.ATIVO,
    )
    .select_related('anuncio', 'anuncio__tipo_de_anuncio', 'produto')
)

candidatos = []
for variacao in variacoes:
    altura_cm = variacao.altura_declarada_cm
    largura_cm = variacao.largura_declarada_cm
    comprimento_cm = variacao.comprimento_declarado_cm
    peso_fisico_kg = variacao.peso_declarado_kg
    item_price = variacao.preco_atual

    if altura_cm <= 0 or largura_cm <= 0 or comprimento_cm <= 0 or peso_fisico_kg <= 0 or item_price <= 0:
        continue  # dado declarado presente mas zerado/inválido — não dá pra calcular nada útil

    peso_cubado_kg = calcular_peso_cubado_kg(altura_cm, largura_cm, comprimento_cm)
    peso_faturavel_kg = max(peso_fisico_kg, peso_cubado_kg)

    faixa_peso = encontrar_faixa_peso(peso_faturavel_kg)
    faixa_preco = encontrar_faixa_preco(item_price)
    if faixa_peso is None or faixa_preco is None:
        continue  # não deveria acontecer (tabela cobre 0 a infinito), mas não trava o script à toa

    motivos = montar_motivos(peso_fisico_kg, peso_cubado_kg, peso_faturavel_kg, faixa_peso, item_price, faixa_preco)

    candidatos.append(CandidatoAnalisado(
        ean=variacao.produto.ean,
        sku=variacao.produto.sku,
        mlb=variacao.anuncio.mlb,
        tipo_anuncio=variacao.anuncio.tipo_de_anuncio.tipo_anuncio,
        tipo_label='Clássico' if variacao.anuncio.tipo_de_anuncio.tipo_anuncio == TipoAnuncio.CLASSICO else 'Premium',
        altura_cm=altura_cm, largura_cm=largura_cm, comprimento_cm=comprimento_cm,
        peso_fisico_kg=peso_fisico_kg, peso_cubado_kg=peso_cubado_kg, peso_faturavel_kg=peso_faturavel_kg,
        faixa_peso=faixa_peso, item_price=item_price, faixa_preco=faixa_preco,
        motivos=motivos,
    ))

if not candidatos:
    console.print('[bold red]Nenhum candidato encontrado com dimensão/peso/preço declarados e anúncio ativo — '
                   'nada pra testar.[/bold red]')
    sys.exit(1)

console.print(f'{len(candidatos)} candidato(s) com dado completo encontrado(s) no catálogo.\n')

# ---- Seleção: até MAX_POR_FAIXA_PESO_NA_1A_PASSADA "com motivo" por faixa de peso primeiro
#      (garante amplitude), depois preenche o resto do --limite livremente, depois cobre
#      faixas de peso que ainda ficaram sem nenhum candidato. ----
candidatos_com_motivo = sorted([c for c in candidatos if c.motivos], key=lambda c: len(c.motivos), reverse=True)
candidatos_sem_motivo = [c for c in candidatos if not c.motivos]

selecionados = []
contagem_por_faixa_peso = {}
faixas_peso_cobertas = set()

for c in candidatos_com_motivo:
    if len(selecionados) >= LIMITE_CANDIDATOS:
        break
    nome_faixa = c.faixa_peso['nome']
    if contagem_por_faixa_peso.get(nome_faixa, 0) >= MAX_POR_FAIXA_PESO_NA_1A_PASSADA:
        continue
    selecionados.append(c)
    contagem_por_faixa_peso[nome_faixa] = contagem_por_faixa_peso.get(nome_faixa, 0) + 1
    faixas_peso_cobertas.add(nome_faixa)

if len(selecionados) < LIMITE_CANDIDATOS:
    ja_selecionados_ids = {id(c) for c in selecionados}
    for c in candidatos_com_motivo:
        if len(selecionados) >= LIMITE_CANDIDATOS:
            break
        if id(c) in ja_selecionados_ids:
            continue
        selecionados.append(c)
        faixas_peso_cobertas.add(c.faixa_peso['nome'])

if len(selecionados) < LIMITE_CANDIDATOS:
    candidato_por_faixa_sem_motivo = {}
    for c in candidatos_sem_motivo:
        candidato_por_faixa_sem_motivo.setdefault(c.faixa_peso['nome'], c)

    for linha in TABELA_FRETE:
        if len(selecionados) >= LIMITE_CANDIDATOS:
            break
        nome_faixa = linha['nome']
        if nome_faixa in faixas_peso_cobertas:
            continue
        candidato_cobertura = candidato_por_faixa_sem_motivo.get(nome_faixa)
        if candidato_cobertura is None:
            continue
        candidato_cobertura.motivos = ['cobertura_faixa_peso']
        selecionados.append(candidato_cobertura)
        faixas_peso_cobertas.add(nome_faixa)

selecionados.sort(key=lambda c: (Decimal(str(c.faixa_peso['peso_min'])), c.item_price))

tabela_selecao = Table(title=f'Candidatos selecionados pra teste ({len(selecionados)}/{len(candidatos)} encontrados)')
tabela_selecao.add_column('Motivo(s)')
tabela_selecao.add_column('EAN')
tabela_selecao.add_column('MLB')
tabela_selecao.add_column('Tipo')
tabela_selecao.add_column('Peso fat. (kg)', justify='right')
tabela_selecao.add_column('Faixa de peso')
tabela_selecao.add_column('Preço', justify='right')
tabela_selecao.add_column('Faixa de preço')
for c in selecionados:
    tabela_selecao.add_row(
        ', '.join(c.motivos), c.ean, c.mlb, c.tipo_label,
        f'{c.peso_faturavel_kg.quantize(Decimal("0.001"))}',
        c.faixa_peso['nome'], f'R$ {c.item_price}', c.faixa_preco['chave'],
    )
console.print(tabela_selecao)

# ---- Testa cada selecionado via API ----
try:
    resposta_me = chamar_api("GET", "/users/me", pasta_logs=PASTA_LOGS, conta=CONTA,
                              nome_log="buscar_e_testar_candidatos_diversos_frete_via_api")
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro buscando user_id: {erro}[/bold red]')
    sys.exit(1)

console.print(f'\nTestando {len(selecionados)} candidato(s) via API (até 3 chamadas cada)...\n')

cache_category_id = {}
resultados = []

for indice, candidato in enumerate(selecionados, start=1):
    prefixo = f'[{indice}/{len(selecionados)}] {candidato.mlb} ({candidato.tipo_label}, {candidato.faixa_peso["nome"]}, R$ {candidato.item_price})'

    if candidato.mlb in cache_category_id:
        category_id = cache_category_id[candidato.mlb]
    else:
        try:
            resposta_item = chamar_api("GET", f"/items/{candidato.mlb}", pasta_logs=PASTA_LOGS, conta=CONTA,
                                        nome_log="buscar_e_testar_candidatos_diversos_frete_via_api")
            category_id = resposta_item.json()["category_id"]
            cache_category_id[candidato.mlb] = category_id
        except (ErroAPI, ErroAutenticacaoAPI) as erro:
            console.print(f'{prefixo}: [bold red]erro buscando category_id: {erro}[/bold red]')
            resultados.append(ResultadoTesteCandidato(
                candidato=candidato, sem_fg_obtido=None, sem_fg_esperado=None,
                sem_fg_teto_aplicado=False, com_fg_obtido=None, erro=str(erro),
            ))
            continue

    dimensions_str = (
        f"{_formatar_dimensao(candidato.altura_cm)}x{_formatar_dimensao(candidato.largura_cm)}"
        f"x{_formatar_dimensao(candidato.comprimento_cm)},"
        f"{int((candidato.peso_fisico_kg * 1000).to_integral_value())}"
    )

    sem_fg_esperado, teto_aplicado = calcular_gabarito_tabela_1(candidato.faixa_peso, candidato.faixa_preco, candidato.item_price)

    sem_fg_obtido = None
    sem_fg_billable_weight_g = None
    sem_fg_discount = None
    com_fg_obtido = None
    com_fg_billable_weight_g = None
    com_fg_discount = None
    erro_candidato = None
    try:
        resposta_sem_fg = buscar_simulacao_frete_via_api(
            user_id, category_id, candidato.item_price, dimensions_str, candidato.tipo_anuncio, frete_gratis=False,
        )
        sem_fg_obtido = resposta_sem_fg.list_cost
        sem_fg_billable_weight_g = resposta_sem_fg.billable_weight_g
        sem_fg_discount = resposta_sem_fg.discount
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        erro_candidato = str(erro)

    try:
        resposta_com_fg = buscar_simulacao_frete_via_api(
            user_id, category_id, candidato.item_price, dimensions_str, candidato.tipo_anuncio, frete_gratis=True,
        )
        com_fg_obtido = resposta_com_fg.list_cost
        com_fg_billable_weight_g = resposta_com_fg.billable_weight_g
        com_fg_discount = resposta_com_fg.discount
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        erro_candidato = erro_candidato or str(erro)

    resultado = ResultadoTesteCandidato(
        candidato=candidato, sem_fg_obtido=sem_fg_obtido, sem_fg_esperado=sem_fg_esperado,
        sem_fg_teto_aplicado=teto_aplicado,
        sem_fg_billable_weight_g=sem_fg_billable_weight_g, sem_fg_discount=sem_fg_discount,
        com_fg_obtido=com_fg_obtido,
        com_fg_billable_weight_g=com_fg_billable_weight_g, com_fg_discount=com_fg_discount,
        erro=erro_candidato,
    )
    resultados.append(resultado)

    if resultado.sem_fg_bate is True:
        console.print(f'{prefixo}: [green]✓ sem FG bateu (R$ {sem_fg_obtido})[/green]')
    elif resultado.sem_fg_bate is False:
        console.print(f'{prefixo}: [bold red]✗ sem FG NÃO bateu — obtido R$ {sem_fg_obtido}, esperado R$ {sem_fg_esperado}[/bold red]')
    else:
        console.print(f'{prefixo}: [yellow]erro ou sem resultado — {erro_candidato}[/yellow]')

# ---- Tabela final + resumo ----
console.print()
tabela_resultado = Table(title='Resultado da bateria — list_cost via API x tabela real de frete')
tabela_resultado.add_column('Motivo(s)')
tabela_resultado.add_column('MLB')
tabela_resultado.add_column('Tipo')
tabela_resultado.add_column('Faixa de peso')
tabela_resultado.add_column('Peso fat. nosso (kg)', justify='right')
tabela_resultado.add_column('Peso fat. API (kg)', justify='right')
tabela_resultado.add_column('Faixa de preço')
tabela_resultado.add_column('Preço', justify='right')
tabela_resultado.add_column('Sem FG obtido', justify='right')
tabela_resultado.add_column('Sem FG esperado', justify='right')
tabela_resultado.add_column('Bate?', justify='center')
tabela_resultado.add_column('Com FG obtido (informativo)', justify='right')

for r in resultados:
    c = r.candidato
    if r.erro:
        marca, estilo = '[bold red]erro[/bold red]', 'red'
    elif r.sem_fg_bate is True:
        marca, estilo = '[bold green]✓[/bold green]', 'bold green'
    elif r.sem_fg_bate is False:
        marca, estilo = '[bold red]✗[/bold red]', 'bold red'
    else:
        marca, estilo = '[dim]—[/dim]', 'dim'

    sem_fg_esperado_str = f'R$ {r.sem_fg_esperado}' if r.sem_fg_esperado is not None else '—'
    if r.sem_fg_teto_aplicado:
        sem_fg_esperado_str += ' (teto)'

    peso_nosso_quantizado = c.peso_faturavel_kg.quantize(Decimal('0.001'))
    peso_api_str = f'{r.peso_faturavel_api_kg}' if r.peso_faturavel_api_kg is not None else '—'
    if r.peso_faturavel_api_kg is not None and r.peso_faturavel_api_kg != peso_nosso_quantizado:
        peso_api_str = f'[bold yellow]{peso_api_str}[/bold yellow]'  # destaca quando diverge do nosso cálculo

    tabela_resultado.add_row(
        ', '.join(c.motivos), c.mlb, c.tipo_label, c.faixa_peso['nome'],
        f'{peso_nosso_quantizado}',
        peso_api_str,
        c.faixa_preco['chave'],
        f'R$ {c.item_price}',
        f'R$ {r.sem_fg_obtido}' if r.sem_fg_obtido is not None else '—',
        sem_fg_esperado_str,
        marca,
        f'R$ {r.com_fg_obtido}' if r.com_fg_obtido is not None else '—',
        style=estilo,
    )
console.print(tabela_resultado)

faixas_peso_testadas = {r.candidato.faixa_peso['nome'] for r in resultados if r.sem_fg_obtido is not None}
faixas_preco_testadas = {r.candidato.faixa_preco['chave'] for r in resultados if r.sem_fg_obtido is not None}
total_com_resultado = sum(1 for r in resultados if r.sem_fg_bate is not None)
total_bateu = sum(1 for r in resultados if r.sem_fg_bate is True)
divergencias = [r for r in resultados if r.sem_fg_bate is False]

console.print(f'\n[bold]Cobertura:[/bold] {len(faixas_peso_testadas)}/{len(TABELA_FRETE)} faixas de peso testadas, '
              f'{len(faixas_preco_testadas)}/{len(FAIXAS_PRECO)} faixas de preço testadas.')
console.print(f'[bold]Sem frete grátis (contra a tabela real):[/bold] {total_bateu}/{total_com_resultado} bateram.')

if divergencias:
    console.print(f'\n[bold red]{len(divergencias)} divergência(s) encontrada(s) — possíveis pontos de quebra:[/bold red]')
    for r in divergencias:
        c = r.candidato
        peso_nosso_quantizado = c.peso_faturavel_kg.quantize(Decimal('0.001'))
        if r.peso_faturavel_api_kg is not None and r.peso_faturavel_api_kg != peso_nosso_quantizado:
            explicacao = (f'peso faturável divergiu — nosso cálculo: {peso_nosso_quantizado}kg, '
                           f'API calculou: {r.peso_faturavel_api_kg}kg')
        else:
            explicacao = 'peso faturável bateu com o nosso — divergência NÃO é de peso, investigar preço/desconto'
        console.print(f'  [red]MLB {c.mlb} — {c.faixa_peso["nome"]} x {c.faixa_preco["chave"]}: '
                       f'obtido R$ {r.sem_fg_obtido}, esperado R$ {r.sem_fg_esperado} — {explicacao}[/red]')
else:
    console.print('\n[green]Nenhuma divergência — todos os candidatos testados bateram com a tabela real.[/green]')

console.print('\n[dim]"Com FG" é só informativo — ainda não temos a tabela completa de frete grátis pra comparar '
              '(só a célula peso 0,5-1kg x preço 0-18,99 já foi confirmada, R$ 14,45).[/dim]')

# ---- Salva JSON com o detalhe completo ----


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Tipo não serializável: {type(obj)}')


saida = {
    "contexto": {
        "conta": CONTA,
        "limite": LIMITE_CANDIDATOS,
        "total_candidatos_encontrados": len(candidatos),
        "total_selecionados": len(selecionados),
    },
    "resultados": [
        {
            "motivos": r.candidato.motivos,
            "ean": r.candidato.ean,
            "sku": r.candidato.sku,
            "mlb": r.candidato.mlb,
            "tipo_anuncio": r.candidato.tipo_label,
            "dimensoes_cm": f'{r.candidato.altura_cm}x{r.candidato.largura_cm}x{r.candidato.comprimento_cm}',
            "peso_fisico_kg": r.candidato.peso_fisico_kg,
            "peso_cubado_kg": r.candidato.peso_cubado_kg,
            "peso_faturavel_kg_nosso": r.candidato.peso_faturavel_kg,
            "peso_faturavel_kg_api": r.peso_faturavel_api_kg,
            "faixa_peso": r.candidato.faixa_peso['nome'],
            "item_price": r.candidato.item_price,
            "faixa_preco": r.candidato.faixa_preco['chave'],
            "sem_fg_obtido": r.sem_fg_obtido,
            "sem_fg_esperado": r.sem_fg_esperado,
            "sem_fg_teto_aplicado": r.sem_fg_teto_aplicado,
            "sem_fg_bate": r.sem_fg_bate,
            "sem_fg_billable_weight_g": r.sem_fg_billable_weight_g,
            "sem_fg_discount": r.sem_fg_discount,
            "com_fg_obtido": r.com_fg_obtido,
            "com_fg_billable_weight_g": r.com_fg_billable_weight_g,
            "com_fg_discount": r.com_fg_discount,
            "erro": r.erro,
        }
        for r in resultados
    ],
}

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2, default=_serializar)

console.print(f'\n[dim]Resultado completo salvo em: {CAMINHO_SAIDA}[/dim]')