# scripts_exploracao_ML/investigar_item_price_zero_varredura_completa.py

# Função Objetivo: Substituto pra investigar_item_price_zero_MLB455841.py quando o MLB
# original do log não é mais localizável (log rotacionado/sobrescrito) — em vez de 1 caso
# específico, varre TODO o catálogo elegível pra Frente A e testa as 2 hipóteses em massa:
#
#   Hipótese A (esperado/inofensivo): item_price=0.00 aparece no log de qualquer produto cujo
#   custo_produto seja <= R$18,99 — é o comportamento NORMAL do motor (ver goal_seek.py,
#   resolver_preco_com_frete_dinamico(): a 1ª tentativa de cada faixa candidata é sempre
#   consultar_frete(faixa.preco_min), nunca custo_produto; a faixa mais barata da tabela real
#   tem preco_min=R$0,00 e só fica de fora quando seu teto, R$18,99, é menor que o custo).
#
#   Hipótese B (dado com problema): custo_produto está genuinamente ZERADO no banco (Produto.
#   custo = 0) — mesmo sintoma no log, causa diferente (ausência de dado, não produto barato).
#
# Pra cada variação elegível (categoria preenchida, dimensão resolvível — ML declarada ou ERP
# como fallback), reproduz a MESMA filtragem de faixas de formula_precificacao.py/goal_seek.py
# (peso fechado nos 2 lados + regime + preco_max >= custo_produto), descobre se a 1ª faixa
# válida tem preco_min=0 (ou seja, geraria o mesmo "item_price=0.00" no log) — e cruza com
# GradePrecificacaoML pra separar "gerou o log mas convergiu bem" de "gerou o log e nunca
# resolveu" (esse 2º grupo é o que merece atenção de verdade).
#
# Regime assumido: SEM_FRETE_GRATIS_RAPIDO (default de DadosDimensaoFrete, mesmo caminho da
# Frente A / API real).
#
# Só leitura no banco — nenhuma chamada à API, nenhuma escrita em lugar nenhum, além do JSON
# de saída.
#
# Uso: python -u "scripts_exploracao_ML/investigar_item_price_zero_varredura_completa.py" [opções]
# --empresa: MB ou SV — default MB.
# --mostrar-no-console: máximo de linhas problemáticas exibidas na tabela do terminal
#   (a lista completa sempre vai pro JSON). Default: 30.

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
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML
from precificacao.models import GradePrecificacaoML

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

parser = argparse.ArgumentParser(
    description='Varre o catálogo inteiro testando a hipótese de que item_price=0.00 no log '
                 'da Frente A é comportamento normal pra produto com custo <= R$18,99.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB', help='Empresa/conta ML. Default: MB.')
parser.add_argument('--mostrar-no-console', type=int, default=30,
                     help='Máximo de linhas problemáticas exibidas na tabela do terminal. Default: 30.')
args = parser.parse_args()

CONTA = args.empresa
MOSTRAR_NO_CONSOLE = args.mostrar_no_console

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"investigacao_item_price_zero_varredura_{CONTA}.json"

FRETE_ML_TODAS = list(FreteML.objects.all())  # mesma fonte/ordering real de produção — só leitura


def resolver_dimensao_efetiva(variacao, produto):
    """Mesmo critério de investigar_item_price_zero_MLB455841.py — ML declarado primeiro,
    ERP (após embalado) como fallback."""
    if (variacao.altura_declarada_cm and variacao.largura_declarada_cm
            and variacao.comprimento_declarado_cm and variacao.peso_declarado_kg):
        return (variacao.altura_declarada_cm, variacao.largura_declarada_cm,
                variacao.comprimento_declarado_cm, variacao.peso_declarado_kg, 'variacao_ml')
    p = produto
    if (p.altura_produto_apos_embalado and p.largura_produto_apos_embalado
            and p.comprimento_produto_apos_embalado and p.peso_produto_apos_embalado):
        return (p.altura_produto_apos_embalado, p.largura_produto_apos_embalado,
                p.comprimento_produto_apos_embalado, p.peso_produto_apos_embalado, 'produto_erp')
    return (None, None, None, None, 'sem_dimensao')


def faixas_candidatas_reais(peso_kg, regime):
    return sorted(
        (f for f in FRETE_ML_TODAS
         if f.regime == regime and f.peso_min <= peso_kg and (f.peso_max is None or f.peso_max >= peso_kg)),
        key=lambda f: f.preco_min,
    )


def faixas_validas_reais(faixas_candidatas, custo_produto):
    return [f for f in faixas_candidatas if f.preco_max is None or f.preco_max >= custo_produto]


console.print(Panel(
    '[bold]Varredura Completa — item_price=0.00 na Frente A[/bold]\n'
    f'Conta {CONTA} — testando a Hipótese A (produto barato, normal) x B (custo zerado, dado com problema)',
    border_style='blue',
))

Status = TipoDeAnuncioMercadoLivre.Status
REGIME = FreteML.Regime.SEM_FRETE_GRATIS_RAPIDO

variacoes = (
    VariacaoAnuncioMercadoLivre.objects
    .filter(produto__isnull=False, categoria__isnull=False, anuncio__tipo_de_anuncio__status=Status.ATIVO)
    .select_related('anuncio', 'produto', 'categoria')
)

total_elegiveis = 0
sem_dimensao = 0
resultado_por_variacao = []

console.print('Processando variações elegíveis (isso pode levar um tempo se o catálogo for grande)...\n')

for v in variacoes:
    produto = v.produto
    total_elegiveis += 1

    altura, largura, comprimento, peso_fisico, origem_dimensao = resolver_dimensao_efetiva(v, produto)
    if peso_fisico is None:
        sem_dimensao += 1
        continue

    custo_produto = produto.custo
    peso_cubado = (altura * largura * comprimento) / Decimal('6000')
    peso_faturavel = max(peso_fisico, peso_cubado)

    candidatas = faixas_candidatas_reais(peso_faturavel, REGIME)
    validas = faixas_validas_reais(candidatas, custo_produto)
    primeira_faixa = validas[0] if validas else None
    sinaliza_item_price_zero = primeira_faixa is not None and primeira_faixa.preco_min == 0

    if not sinaliza_item_price_zero:
        continue  # só nos interessam os que REALMENTE gerariam item_price=0.00 no log

    linhas_grade = list(GradePrecificacaoML.objects.filter(produto=produto, variacao=v).values(
        'tipo_anuncio', 'margem', 'resolvida', 'motivo_nao_resolvida'
    ))
    tem_linha_resolvida = any(l['resolvida'] for l in linhas_grade)
    tem_linha_nao_resolvida = any(not l['resolvida'] for l in linhas_grade)
    nunca_calculado = len(linhas_grade) == 0

    resultado_por_variacao.append({
        "mlb": v.anuncio.mlb, "ean": produto.ean, "sku": produto.sku, "titulo": produto.titulo,
        "custo_produto": custo_produto, "custo_zerado": custo_produto == Decimal('0'),
        "origem_dimensao": origem_dimensao, "peso_faturavel_kg": peso_faturavel,
        "tem_linha_resolvida": tem_linha_resolvida, "tem_linha_nao_resolvida": tem_linha_nao_resolvida,
        "nunca_calculado": nunca_calculado, "linhas_grade": linhas_grade,
    })

console.print(f'{total_elegiveis} variação(ões) elegível(is) pra Frente A (categoria + produto preenchidos).')
console.print(f'{sem_dimensao} sem dimensão resolvível (nem ML nem ERP) — excluída(s) da análise.')
console.print(f'{len(resultado_por_variacao)} variação(ões) geram item_price=0.00 no log hoje.\n')

custo_zerado = [r for r in resultado_por_variacao if r["custo_zerado"]]
so_nao_resolvida = [r for r in resultado_por_variacao if r["tem_linha_nao_resolvida"] and not r["tem_linha_resolvida"] and not r["nunca_calculado"]]
nunca_calculado_ainda = [r for r in resultado_por_variacao if r["nunca_calculado"]]
convergiu_bem = [r for r in resultado_por_variacao if r["tem_linha_resolvida"]]

console.print(Panel(
    f'De {len(resultado_por_variacao)} variação(ões) que geram item_price=0.00:\n'
    f'  • {len(convergiu_bem)} têm pelo menos 1 linha RESOLVIDA em GradePrecificacaoML — '
    f'[bold green]probe inofensivo, confirmado na prática[/bold green] (Hipótese A).\n'
    f'  • {len(so_nao_resolvida)} têm SÓ linhas NÃO resolvidas (nenhuma convergiu) — '
    f'[bold yellow]merece olhar individual[/bold yellow] (pode ou não ter relação com item_price=0.00).\n'
    f'  • {len(nunca_calculado_ainda)} ainda não têm nenhuma linha em GradePrecificacaoML '
    f'(nunca foram calculadas) — sem veredito ainda.\n'
    f'  • {len(custo_zerado)} têm custo_produto LITERALMENTE R$0,00 — [bold red]candidatos reais à '
    f'Hipótese B[/bold red] (dado de ERP ausente, vale checar).',
    title='Resumo', border_style='blue',
))

if custo_zerado:
    tabela_custo_zero = Table(title=f'Produtos com custo_produto = R$0,00 (Hipótese B — até {MOSTRAR_NO_CONSOLE} exibidos)')
    tabela_custo_zero.add_column('MLB')
    tabela_custo_zero.add_column('EAN')
    tabela_custo_zero.add_column('SKU')
    tabela_custo_zero.add_column('Título')
    for r in custo_zerado[:MOSTRAR_NO_CONSOLE]:
        tabela_custo_zero.add_row(r["mlb"], r["ean"], r["sku"] or '—', r["titulo"][:60])
    console.print(tabela_custo_zero)

if so_nao_resolvida:
    tabela_problema = Table(title=f'Variações com item_price=0.00 e NENHUMA linha resolvida (até {MOSTRAR_NO_CONSOLE} exibidos)')
    tabela_problema.add_column('MLB')
    tabela_problema.add_column('EAN')
    tabela_problema.add_column('Custo')
    tabela_problema.add_column('Motivos (não resolvida)')
    for r in so_nao_resolvida[:MOSTRAR_NO_CONSOLE]:
        motivos = ', '.join(sorted({l['motivo_nao_resolvida'] for l in r['linhas_grade'] if l['motivo_nao_resolvida']}))
        tabela_problema.add_row(r["mlb"], r["ean"], f'R$ {r["custo_produto"]}', motivos or '—')
    console.print(tabela_problema)


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Tipo não serializável: {type(obj)}')


saida = {
    "contexto": {"conta": CONTA, "total_elegiveis": total_elegiveis, "sem_dimensao": sem_dimensao},
    "resumo": {
        "total_gera_item_price_zero": len(resultado_por_variacao),
        "convergiu_bem": len(convergiu_bem), "so_nao_resolvida": len(so_nao_resolvida),
        "nunca_calculado_ainda": len(nunca_calculado_ainda), "custo_zerado": len(custo_zerado),
    },
    "detalhado": resultado_por_variacao,
}
with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2, default=_serializar)

console.print(f'\nResultado completo salvo em: {CAMINHO_SAIDA}')
console.print('Suba esse arquivo (ou cole os resumos das tabelas acima) na conversa pra eu analisar.')