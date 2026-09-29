# scripts_exploracao_ML/investigar_item_price_zero_MLB455841.py

# Função Objetivo: Investigar por que apareceu "item_price=0.00" no log de popular_banco pro
# MLB455841 — testar 2 hipóteses:
#
#   Hipótese A (esperado/inofensivo): resolver_preco_com_frete_dinamico() (goal_seek.py)
#   SEMPRE testa faixa.preco_min como 1ª tentativa de cada faixa candidata (a "estimativa"
#   antes de resolver o preço de verdade) — NUNCA usa custo_produto como item_price
#   diretamente (ver linha ~185 de goal_seek.py: "frete = consultar_frete(faixa.preco_min)").
#   As faixas candidatas vêm ordenadas por preco_min ASCENDENTE (filtrar_faixas_frete(),
#   formula_precificacao.py) — a mais barata da tabela real tem preco_min=R$0,00 (faixa
#   "0 a 18,99", ver FAIXAS_PRECO em buscar_e_testar_candidatos_diversos_frete_via_api.py).
#   Essa faixa só fica de fora de faixas_validas quando faixa.preco_max (R$18,99) < custo_
#   produto — ou seja, item_price=0.00 aparecer no log significa que custo_produto <=
#   R$18,99 (não precisa ser ZERO — qualquer produto barato nessa faixa gera exatamente esse
#   mesmo log, sempre, é o comportamento NORMAL do motor).
#
#   Hipótese B (dado com problema): custo_produto está genuinamente ZERADO no banco (Produto.
#   custo = 0, ex: produto recém-importado do ERP sem custo preenchido ainda) — nesse caso
#   TODA faixa é "válida" (preco_max >= 0 sempre verdade), e a 1ª tentativa também cairia em
#   item_price=0.00, mas por ausência de dado, não por produto barato de verdade.
#
# Esse script busca o produto/variação reais do MLB(s) informado(s), imprime custo_produto
# direto do banco, REPRODUZ a filtragem de faixas exatamente como formula_precificacao.py/
# goal_seek.py fazem hoje (mesma condição de peso+regime+preco_max>=custo), mostra qual foi a
# 1ª faixa realmente testada — e cruza com o histórico em GradePrecificacaoML (resolvida ou
# não) pra confirmar se a busca convergiu normalmente depois desse 1º probe.
#
# Regime assumido: SEM_FRETE_GRATIS_RAPIDO — é o default de DadosDimensaoFrete quando
# `regime=None` (formula_precificacao.py, __init__), usado pelo caminho Frente A (API real)
# em _tentar_resolver_preco_via_api(). Mostra o outro regime também, só pra referência.
#
# Só leitura no banco — nenhuma chamada à API, nenhuma escrita em lugar nenhum, além do JSON
# de saída.
#
# Uso: python -u "scripts_exploracao_ML/investigar_item_price_zero_MLB455841.py" [opções]
# --empresa: MB ou SV — default MB.
# --mlb: MLB(s) a investigar, separados por vírgula. Default: MLB455841 (o caso do log).

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
from mercado_livre.models import AnuncioMercadoLivre, FreteML
from precificacao.models import GradePrecificacaoML

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

parser = argparse.ArgumentParser(
    description='Investiga item_price=0.00 no log da Frente A — reproduz a filtragem de '
                 'faixas de goal_seek.py/formula_precificacao.py pro(s) MLB informado(s).'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB', help='Empresa/conta ML. Default: MB.')
parser.add_argument('--mlb', default='MLB455841', help='MLB(s) a investigar, separados por vírgula. Default: MLB455841.')
args = parser.parse_args()

CONTA = args.empresa
MLBS = [m.strip() for m in args.mlb.split(',') if m.strip()]

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"investigacao_item_price_zero_{CONTA}.json"

FRETE_ML_TODAS = list(FreteML.objects.all())  # mesma fonte/ordering real de produção — só leitura


def resolver_dimensao_efetiva(variacao, produto):
    """Reproduz (simplificado, só pro que este diagnóstico precisa) o critério de
    origem_dimensao já documentado no model GradePrecificacaoML: usa a dimensão DECLARADA no
    ML quando existe (os 4 campos preenchidos), cai pro produto do ERP (após embalado) como
    fallback — mesmo critério, sem reimplementar DimensoesEfetivas por inteiro."""
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
    """MESMA condição de filtrar_faixas_frete() (formula_precificacao.py) — peso fechado nos
    2 lados, filtrado por regime, ordenado por preco_min ascendente."""
    return sorted(
        (f for f in FRETE_ML_TODAS
         if f.regime == regime and f.peso_min <= peso_kg and (f.peso_max is None or f.peso_max >= peso_kg)),
        key=lambda f: f.preco_min,
    )


def faixas_validas_reais(faixas_candidatas, custo_produto):
    """MESMA condição de resolver_preco_com_frete_dinamico()/resolver_preco_por_margem()
    (goal_seek.py) — pula faixa cujo teto é menor que o custo do produto."""
    return [f for f in faixas_candidatas if f.preco_max is None or f.preco_max >= custo_produto]


resultado_geral = {}

for mlb in MLBS:
    console.print(Panel(f'[bold]Investigando {mlb}[/bold] — conta {CONTA}', border_style='blue'))

    anuncio = AnuncioMercadoLivre.objects.filter(mlb=mlb).select_related('tipo_de_anuncio').first()
    if anuncio is None:
        parecidos = list(AnuncioMercadoLivre.objects.filter(mlb__icontains=mlb).values_list('mlb', flat=True)[:10])
        if len(parecidos) == 1:
            console.print(f'[yellow]{mlb} não bateu exato, mas achei 1 MLB parecido no banco: {parecidos[0]} — usando ele.[/yellow]')
            anuncio = AnuncioMercadoLivre.objects.filter(mlb=parecidos[0]).select_related('tipo_de_anuncio').first()
        else:
            console.print(f'[bold red]{mlb} não encontrado no banco (conta {CONTA}).[/bold red]')
            if parecidos:
                console.print(f'[yellow]MLBs parecidos encontrados (confira qual é o certo): {", ".join(parecidos)}[/yellow]\n')
                resultado_geral[mlb] = {"erro": "MLB não encontrado exato", "parecidos": parecidos}
            else:
                console.print('[yellow]Nenhum MLB parecido encontrado tampouco — confere se o código do log está completo '
                               '(MLBs normalmente têm ~10 dígitos, ex: MLB2603222486) e se é da conta certa (--empresa).[/yellow]\n')
                resultado_geral[mlb] = {"erro": "MLB não encontrado no banco"}
            continue

    variacoes = anuncio.variacoes.select_related('produto', 'categoria').all()
    if not variacoes:
        console.print(f'[bold red]{mlb} não tem nenhuma variação cadastrada. Pulando.[/bold red]\n')
        resultado_geral[mlb] = {"erro": "sem variações cadastradas"}
        continue

    resultado_mlb = {"variacoes": []}

    for v in variacoes:
        produto = v.produto
        if produto is None:
            console.print(f'[yellow]Variação {v.variacao_id} sem produto vinculado (SET_NULL) — pulando.[/yellow]')
            continue

        custo_produto = produto.custo
        altura, largura, comprimento, peso_fisico, origem_dimensao = resolver_dimensao_efetiva(v, produto)

        tabela_produto = Table(title=f'Variação {v.variacao_id} — {produto.titulo}')
        tabela_produto.add_column('Campo')
        tabela_produto.add_column('Valor')
        tabela_produto.add_row('EAN / SKU', f'{produto.ean} / {produto.sku}')
        tabela_produto.add_row('custo (Produto.custo)', f'R$ {custo_produto}')
        tabela_produto.add_row('custo_com_boni', f'R$ {produto.custo_com_boni}' if produto.custo_com_boni is not None else '(vazio)')
        tabela_produto.add_row('ativo_no_erp', str(produto.ativo_no_erp))
        tabela_produto.add_row('cadastrado_erp_em', str(produto.cadastrado_erp_em))
        tabela_produto.add_row('preco_atual (variação)', f'R$ {v.preco_atual}' if v.preco_atual is not None else '(vazio)')
        tabela_produto.add_row('categoria', f'{v.categoria.category_id} ({v.categoria.nome})' if v.categoria else '(sem categoria)')
        tabela_produto.add_row('origem da dimensão usada aqui', origem_dimensao)
        tabela_produto.add_row('altura x largura x comprimento (cm)', f'{altura} x {largura} x {comprimento}' if altura else '(sem dimensão)')
        tabela_produto.add_row('peso físico (kg)', str(peso_fisico) if peso_fisico else '(sem dimensão)')
        console.print(tabela_produto)

        resultado_variacao = {
            "variacao_id": v.variacao_id, "ean": produto.ean, "sku": produto.sku, "titulo": produto.titulo,
            "custo_produto": custo_produto, "custo_com_boni": produto.custo_com_boni,
            "ativo_no_erp": produto.ativo_no_erp, "cadastrado_erp_em": str(produto.cadastrado_erp_em),
            "preco_atual": v.preco_atual, "origem_dimensao_usada": origem_dimensao,
            "regimes": {},
        }

        if peso_fisico is None:
            console.print('[bold red]Sem dimensão (nem ML nem ERP) — não dá pra reproduzir a filtragem de faixas.[/bold red]\n')
            resultado_variacao["erro_dimensao"] = "sem dimensão declarada em nenhuma fonte"
            resultado_mlb["variacoes"].append(resultado_variacao)
            continue

        peso_cubado = (altura * largura * comprimento) / Decimal('6000')
        peso_faturavel = max(peso_fisico, peso_cubado)
        resultado_variacao["peso_fisico_kg"] = peso_fisico
        resultado_variacao["peso_cubado_kg"] = peso_cubado
        resultado_variacao["peso_faturavel_kg"] = peso_faturavel

        for regime, regime_label in [(FreteML.Regime.SEM_FRETE_GRATIS_RAPIDO, 'Sem Frete Grátis Rápido (default/API real)'),
                                      (FreteML.Regime.COM_FRETE_GRATIS_RAPIDO, 'Com Frete Grátis Rápido (referência)')]:
            candidatas = faixas_candidatas_reais(peso_faturavel, regime)
            validas = faixas_validas_reais(candidatas, custo_produto)

            tabela_regime = Table(title=f'Regime: {regime_label}')
            tabela_regime.add_column('#')
            tabela_regime.add_column('preco_min')
            tabela_regime.add_column('preco_max')
            tabela_regime.add_column('valor (frete)')
            tabela_regime.add_column('válida? (preco_max >= custo_produto)')
            for i, f in enumerate(candidatas, start=1):
                tabela_regime.add_row(str(i), f'R$ {f.preco_min}', f'R$ {f.preco_max}' if f.preco_max is not None else '(sem teto)',
                                       f'R$ {f.valor}', 'sim' if f in validas else 'não')
            console.print(tabela_regime)

            primeira_faixa_testada = validas[0] if validas else None
            if primeira_faixa_testada is not None:
                bate_com_log = primeira_faixa_testada.preco_min == 0
                console.print(f'  → 1ª tentativa real do goal-seek nesse regime: '
                               f'consultar_frete(item_price={primeira_faixa_testada.preco_min})'
                               + (' [bold green](bate com o log — item_price=0.00)[/bold green]' if bate_com_log else ''))
            else:
                console.print('  → [yellow]Nenhuma faixa válida nesse regime (nenhuma faixa cobre esse peso, ou '
                               'todas têm preco_max < custo_produto) — a busca via API cairia direto pro fallback de tabela.[/yellow]')

            resultado_variacao["regimes"][regime.value] = {
                "faixas_candidatas": len(candidatas),
                "faixas_validas": len(validas),
                "primeira_faixa_testada_preco_min": primeira_faixa_testada.preco_min if primeira_faixa_testada else None,
            }

        # ---- Cruza com GradePrecificacaoML — a busca convergiu depois desse 1º probe? ----
        linhas_grade = GradePrecificacaoML.objects.filter(produto=produto, variacao=v)
        tabela_grade = Table(title='GradePrecificacaoML — linhas já calculadas pra este produto/variação')
        tabela_grade.add_column('Tipo anúncio')
        tabela_grade.add_column('Margem')
        tabela_grade.add_column('Resolvida?')
        tabela_grade.add_column('Motivo (se não resolvida)')
        tabela_grade.add_column('Preço calculado')
        tabela_grade.add_column('Origem frete')
        tabela_grade.add_column('Calculado em')
        linhas_grade_serializadas = []
        for linha in linhas_grade:
            tabela_grade.add_row(
                linha.get_tipo_anuncio_display(), linha.get_margem_display(), str(linha.resolvida),
                linha.motivo_nao_resolvida or '—', f'R$ {linha.preco}' if linha.preco is not None else '—',
                linha.origem_frete or '—', str(linha.calculado_em),
            )
            linhas_grade_serializadas.append({
                "tipo_anuncio": linha.tipo_anuncio, "margem": linha.margem, "resolvida": linha.resolvida,
                "motivo_nao_resolvida": linha.motivo_nao_resolvida, "preco": linha.preco,
                "origem_frete": linha.origem_frete, "calculado_em": str(linha.calculado_em),
            })
        console.print(tabela_grade)
        resultado_variacao["grade_precificacao_ml"] = linhas_grade_serializadas

        # ---- Conclusão pra esta variação ----
        custo_baixo = custo_produto <= Decimal('18.99')
        custo_zerado = custo_produto == Decimal('0')
        alguma_resolvida = any(l["resolvida"] for l in linhas_grade_serializadas)
        if custo_zerado:
            conclusao = ('Hipótese B CONFIRMADA (também) — custo_produto está literalmente R$0,00 no banco. '
                         'Vale checar se é produto recém-importado do ERP sem custo preenchido ainda.')
        elif custo_baixo:
            conclusao = (f'Hipótese A CONFIRMADA — custo_produto (R$ {custo_produto}) é <= R$18,99, então a faixa '
                         '"0 a 18,99" (preco_min=R$0,00) é válida e é sempre a 1ª testada. item_price=0.00 no log '
                         'é o comportamento NORMAL/esperado do motor pra produto barato, não indica problema.')
        else:
            conclusao = (f'Nenhuma das 2 hipóteses bate como esperado — custo_produto (R$ {custo_produto}) é '
                         '> R$18,99, então a faixa "0 a 18,99" não deveria ser válida hoje. Precisa investigar '
                         'mais (talvez o log seja de uma execução anterior, com custo diferente do atual).')
        if alguma_resolvida:
            conclusao += (' A busca convergiu normalmente em pelo menos 1 combinação (resolvida=True) — o probe '
                          'em item_price=0.00 foi transitório/inofensivo.')
        console.print(Panel(conclusao, border_style='green' if (custo_baixo or custo_zerado) else 'red'))
        resultado_variacao["conclusao"] = conclusao

        resultado_mlb["variacoes"].append(resultado_variacao)

    resultado_geral[mlb] = resultado_mlb
    console.print()


def _serializar(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f'Tipo não serializável: {type(obj)}')


with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(resultado_geral, f, ensure_ascii=False, indent=2, default=_serializar)

console.print(f'\nResultado completo salvo em: {CAMINHO_SAIDA}')
console.print('Suba esse arquivo (ou cole as tabelas acima) na conversa pra eu analisar.')