# scripts_exploracao_ML/testar_goal_seek_via_api_chinelo.py

# Função Objetivo: Testa se o goal seek via API (Opção 2 da Frente A) chega no mesmo
# resultado que o sistema real (Opção 1, tabela FreteML) — ou em algo mais correto, nos
# casos onde a tabela local não tem o teto de metade do preço (< R$19).
#
# Não reimplementa NENHUMA conta: instancia a mesma classe de produção
# (FormulaPrecificacao, a mesma que calcular_grade_precificacao_ml usa) e o mesmo motor
# genérico (resolver_preco_por_margem, goal_seek.py) que o sistema real usa. A ÚNICA
# variável trocada entre Opção 1 e Opção 2 é de onde vem `frete_todas` — banco local vs.
# API ao vivo — com produto, dimensão, fixo, taxa e margem IDÊNTICOS nas 2, pra isolar
# só essa diferença.
#
# Opção 2, por faixa de preço candidata: 1ª chamada com o PISO da faixa (estimativa,
# suficiente pra qualquer faixa exceto R$0-18,99, onde o frete depende do preço exato
# por causa do teto de metade do preço) -> resolve com resolver_preco_por_margem ->
# 2ª chamada (confirmação) com o preco_90 REAL calculado -> se bater, fechado; se não
# bater, corrige só aquela faixa com o valor confirmado e refaz a busca.
#
# Escopo desta rodada: só o Chinelo Nuvem Sandália Ortopédica Fly Feet
# (F7899947307029.001), só Clássico, conta MB. Só leitura no banco e na API —
# nenhuma escrita em lugar nenhum.

import os
import sys
import json
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

from produtos.models import Produto
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem
from mercado_livre.models import (
    FreteML, TipoDeAnuncioMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre,
    VariacaoAnuncioMercadoLivre,
)
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from precificacao.funcoes_auxiliares.mercado_livre.formula_precificacao import FormulaPrecificacao
from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_por_margem

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"
EAN_CHINELO = "7899947307029"  # F7899947307029.001 — SKU comum é F(ean).001
# ========================================

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / "goal_seek_via_api_chinelo_resultado.json"


@dataclass
class FaixaFreteSimulada:
    """Mesma interface que resolver_preco_por_margem espera de qualquer faixa de frete
    (.peso_min/.peso_max/.preco_min/.preco_max/.valor) — só que .valor vem de uma
    chamada real à API, não do banco (FreteML)."""
    peso_min: Decimal
    peso_max: Decimal
    preco_min: Decimal
    preco_max: Decimal
    valor: Decimal


def _formatar_dimensao(valor):
    """Decimal -> string pro formato que a API espera (13.00 -> '13', 13.50 -> '13.5')."""
    inteiro = valor.to_integral_value()
    if valor == inteiro:
        return str(int(inteiro))
    return str(valor.normalize())


def buscar_list_cost_via_api(user_id, category_id, item_price, dimensions_str):
    """Receita validada em 22/09 — free_shipping SEMPRE 'false', sem logistic_type."""
    endpoint = f"/users/{user_id}/shipping_options/free"
    params = {
        "dimensions": dimensions_str,
        "item_price": str(item_price),
        "verbose": "true",
        "condition": "new",
        "category_id": category_id,
        "listing_type_id": TipoAnuncio.CLASSICO,
        "mode": "me2",
        "free_shipping": "false",
    }
    resposta = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params,
        nome_log="testar_goal_seek_via_api_chinelo",
    )
    corpo = resposta.json()
    list_cost = corpo.get("coverage", {}).get("all_country", {}).get("list_cost")
    if list_cost is None:
        raise ErroAPI(f"API não retornou list_cost pra item_price={item_price} — resposta: {corpo}")
    return Decimal(str(list_cost))


def montar_frete_todas_opcao2_estimativa(faixas_reais_da_faixa_de_peso, user_id, category_id,
                                          dimensions_str, custo_produto):
    """1 chamada de API por faixa de preço candidata, usando o PISO da faixa. Pula faixas
    cujo teto já é menor que o custo do produto — mesma regra que resolver_preco_por_margem
    aplicaria de qualquer forma, antecipada aqui só pra não gastar chamada de API à toa."""
    faixas_simuladas = []
    for faixa_real in sorted(faixas_reais_da_faixa_de_peso, key=lambda f: f.preco_min):
        if faixa_real.preco_max is not None and faixa_real.preco_max < custo_produto:
            continue

        preco_teste = faixa_real.preco_min if faixa_real.preco_min > 0 else Decimal('0.01')
        valor = buscar_list_cost_via_api(user_id, category_id, preco_teste, dimensions_str)

        faixas_simuladas.append(FaixaFreteSimulada(
            peso_min=faixa_real.peso_min, peso_max=faixa_real.peso_max,
            preco_min=faixa_real.preco_min, preco_max=faixa_real.preco_max,
            valor=valor,
        ))
    return faixas_simuladas


def resolver_com_confirmacao(fixo, taxa_percentual, margem_alvo_fracao, custo_produto, rebate_valor,
                              frete_todas_estimativa, user_id, category_id, dimensions_str):
    """Roda resolver_preco_por_margem (motor real, sem reimplementar nada) com os valores
    estimados, confirma o resultado com uma chamada real no preco_90 calculado, e corrige
    + refaz a busca só se a confirmação divergir da estimativa."""
    resultado = resolver_preco_por_margem(
        fixo=fixo, taxa_percentual=taxa_percentual, margem_alvo_fracao=margem_alvo_fracao,
        custo_produto=custo_produto, faixas_frete_candidatas=frete_todas_estimativa,
        rebate_valor=rebate_valor,
    )
    if resultado is None:
        return {"resolvida": False, "rodadas": 1,
                "motivo": "nenhuma faixa (estimativa) gerou solução consistente"}

    preco_90 = resultado["preco_calculado"]
    faixa_resolvida = resultado["faixa_frete"]

    valor_confirmado = buscar_list_cost_via_api(user_id, category_id, preco_90, dimensions_str)

    if valor_confirmado == resultado["frete_usado"]:
        return {"resolvida": True, "rodadas": 1, "confirmado_sem_ajuste": True, **resultado}

    frete_todas_corrigida = [
        FaixaFreteSimulada(f.peso_min, f.peso_max, f.preco_min, f.preco_max,
                            valor_confirmado if f is faixa_resolvida else f.valor)
        for f in frete_todas_estimativa
    ]
    resultado_2 = resolver_preco_por_margem(
        fixo=fixo, taxa_percentual=taxa_percentual, margem_alvo_fracao=margem_alvo_fracao,
        custo_produto=custo_produto, faixas_frete_candidatas=frete_todas_corrigida,
        rebate_valor=rebate_valor,
    )
    if resultado_2 is None:
        return {"resolvida": False, "rodadas": 2,
                "motivo": "estimativa resolveu, mas o valor confirmado no preço real invalidou a faixa e nenhuma outra fechou",
                "estimativa_descartada": {**resultado, "valor_confirmado_que_invalidou": str(valor_confirmado)}}

    return {
        "resolvida": True, "rodadas": 2, "confirmado_sem_ajuste": False,
        "valor_estimado_1a_rodada": str(resultado["frete_usado"]),
        "valor_confirmado_no_preco_real": str(valor_confirmado),
        **resultado_2,
    }


def _decimal_para_str(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _decimal_para_str(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_para_str(v) for v in obj]
    if hasattr(obj, 'preco_min'):  # FaixaFreteSimulada ou FreteML
        return f"peso {obj.peso_min}-{obj.peso_max} / preco {obj.preco_min}-{obj.preco_max} = R${obj.valor}"
    return obj


# ========== Fluxo principal ==========

console.print(Panel('[bold]Goal Seek via API — Opção 1 (tabela local) x Opção 2 (API)[/bold]\n'
                     'Chinelo Nuvem Sandália Ortopédica Fly Feet — Clássico — conta MB',
                     border_style='blue'))

produto = Produto.objects.get(ean=EAN_CHINELO)
dim = resolver_dimensoes_efetivas(produto, variacao=None)
if dim is None:
    console.print('[bold red]Produto sem dimensão de embalagem suficiente no ERP — abortando.[/bold red]')
    sys.exit(1)

variacao_qualquer = VariacaoAnuncioMercadoLivre.objects.filter(produto=produto).select_related('anuncio').first()
if variacao_qualquer is None:
    console.print('[bold red]Produto sem nenhum MLB publicado no banco — não dá pra buscar '
                   'category_id. Abortando.[/bold red]')
    sys.exit(1)
mlb_referencia = variacao_qualquer.anuncio.mlb

try:
    resposta_me = chamar_api("GET", "/users/me", pasta_logs=PASTA_LOGS, conta=CONTA,
                              nome_log="testar_goal_seek_via_api_chinelo")
    user_id = resposta_me.json()["id"]

    resposta_item = chamar_api("GET", f"/items/{mlb_referencia}", pasta_logs=PASTA_LOGS, conta=CONTA,
                                nome_log="testar_goal_seek_via_api_chinelo")
    category_id = resposta_item.json()["category_id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro buscando user_id/category_id: {erro}[/bold red]')
    sys.exit(1)

dimensions_str = (
    f"{_formatar_dimensao(dim.altura)}x{_formatar_dimensao(dim.largura)}x{_formatar_dimensao(dim.comprimento)},"
    f"{int((dim.peso * 1000).to_integral_value())}"
)

tabela_contexto = Table(title='Produto e contexto resolvidos', show_header=False, box=None, padding=(0, 2))
tabela_contexto.add_column(style='dim')
tabela_contexto.add_column()
tabela_contexto.add_row('SKU / EAN', f'{produto.sku} / {produto.ean}')
tabela_contexto.add_row('Custo', f'R$ {produto.custo}')
tabela_contexto.add_row('Peso físico / cúbico', f'{dim.peso_fisico}kg / {dim.peso_cubico}kg')
tabela_contexto.add_row('Peso faturável (usado)', f'[bold]{dim.peso}kg[/bold]')
tabela_contexto.add_row('Dimensões (AxLxC)', f'{dim.altura}x{dim.largura}x{dim.comprimento}cm')
tabela_contexto.add_row('MLB usado pra category_id', mlb_referencia)
tabela_contexto.add_row('category_id', category_id)
tabela_contexto.add_row('dimensions (parâmetro da API)', dimensions_str)
console.print(tabela_contexto)

config_geral = ConfiguracaoOperacional.obter()
faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))
config_tipo_classico = ConfiguracaoTipoAnuncioMercadoLivre.objects.get(tipo_anuncio=TipoAnuncio.CLASSICO)
frete_todas_ml_real = list(FreteML.objects.all())

margens = [
    ('minima', config_tipo_classico.margem_minima),
    ('padrao', config_tipo_classico.margem_padrao),
    ('maxima', config_tipo_classico.margem_maxima),
    ('competicao', config_tipo_classico.margem_competicao),
]

# ---------- Opção 1: baseline real do sistema (tabela local FreteML) ----------
console.print(Panel('[bold]Opção 1 — tabela local (FreteML)[/bold]', border_style='cyan'))
resultados_opcao1 = {}
for margem_chave, margem_valor in margens:
    formula = FormulaPrecificacao(
        produto=produto, dimensoes_efetivas=dim, config_tipo=config_tipo_classico,
        config_geral=config_geral, margem_alvo_percentual=margem_valor,
        frete_todas=frete_todas_ml_real, faixas_armazenagem=faixas_armazenagem,
    ).calcular()
    resultados_opcao1[margem_chave] = formula

if not resultados_opcao1['padrao'].resolvida:
    console.print('[bold red]Opção 1 (baseline) não resolveu nem a margem padrão — produto '
                   'provavelmente sem impostos_entrada sincronizados no ERP. Abortando.[/bold red]')
    sys.exit(1)

# fixo/taxa/rebate não dependem da margem (só o denominador depende) — pego 1x da margem
# padrão e reaproveito nas 4, pra garantir que Opção 1 e Opção 2 usam EXATAMENTE os mesmos
# números, isolando só a origem do frete como variável.
custo_produto = produto.custo
fixo = resultados_opcao1['padrao'].intermediarios.fixo
taxa_percentual = resultados_opcao1['padrao'].intermediarios.taxa_percentual / Decimal('100')
rebate_valor = resultados_opcao1['padrao'].intermediarios.rebate_valor

# ---------- Opção 2: mesma fórmula, frete vindo da API ----------
console.print(Panel('[bold]Opção 2 — via API (chamadas reais ao Mercado Livre)[/bold]', border_style='magenta'))
faixas_reais_da_faixa_de_peso = [
    f for f in frete_todas_ml_real
    if f.peso_min <= dim.peso and (f.peso_max is None or f.peso_max >= dim.peso)
]
console.print(f'[dim]{len(faixas_reais_da_faixa_de_peso)} faixas de preço na faixa de peso do Chinelo '
              f'(peso={dim.peso}kg) — montando estimativa via API...[/dim]')

try:
    frete_todas_opcao2_estimativa = montar_frete_todas_opcao2_estimativa(
        faixas_reais_da_faixa_de_peso, user_id, category_id, dimensions_str, custo_produto,
    )
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f'[bold red]Erro montando faixas via API: {erro}[/bold red]')
    sys.exit(1)

tabela_faixas_api = Table(title='Faixas testadas na API (estimativa, preço = piso da faixa)', box=None)
tabela_faixas_api.add_column('Faixa de preço')
tabela_faixas_api.add_column('Preço testado', justify='right')
tabela_faixas_api.add_column('list_cost retornado', justify='right')
for faixa in frete_todas_opcao2_estimativa:
    preco_testado = faixa.preco_min if faixa.preco_min > 0 else Decimal('0.01')
    teto = 'sem teto' if faixa.preco_max is None else f'R$ {faixa.preco_max}'
    tabela_faixas_api.add_row(f'R$ {faixa.preco_min} a {teto}', f'R$ {preco_testado}', f'R$ {faixa.valor}')
console.print(tabela_faixas_api)
console.print(f'[dim]{len(faixas_reais_da_faixa_de_peso) - len(frete_todas_opcao2_estimativa)} faixas com '
              f'teto abaixo do custo (R$ {custo_produto}) foram puladas.[/dim]\n')

resultados_opcao2 = {}
for margem_chave, margem_valor in margens:
    try:
        resultados_opcao2[margem_chave] = resolver_com_confirmacao(
            fixo=fixo, taxa_percentual=taxa_percentual,
            margem_alvo_fracao=margem_valor / Decimal('100'), custo_produto=custo_produto,
            rebate_valor=rebate_valor, frete_todas_estimativa=frete_todas_opcao2_estimativa,
            user_id=user_id, category_id=category_id, dimensions_str=dimensions_str,
        )
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        resultados_opcao2[margem_chave] = {"resolvida": False, "erro": str(erro)}

# ---------- Comparação ----------
comparacao = {
    "contexto": {
        "produto_ean": EAN_CHINELO, "produto_sku": produto.sku, "produto_custo": custo_produto,
        "peso_faturavel_kg": dim.peso, "peso_fisico_kg": dim.peso_fisico, "peso_cubico_kg": dim.peso_cubico,
        "dimensoes_cm": f"{dim.altura}x{dim.largura}x{dim.comprimento}",
        "category_id": category_id, "mlb_referencia_category_id": mlb_referencia,
        "listing_type_id": TipoAnuncio.CLASSICO,
        "fixo": fixo, "taxa_percentual": taxa_percentual, "rebate_valor": rebate_valor,
    },
    "margens": {},
}

for margem_chave, margem_valor in margens:
    f1 = resultados_opcao1[margem_chave]
    r2 = resultados_opcao2[margem_chave]

    linha_opcao1 = None
    if f1.resolvida:
        linha_opcao1 = {
            "preco_calculado": f1.saida.preco_final,
            "frete_usado": f1.saida.frete_usado,
            "margem_percentual_obtida": f1.saida.margem_percentual_obtida,
            "faixa_preco": f"{f1.intermediarios.faixa_frete_preco_min}-{f1.intermediarios.faixa_frete_preco_max}",
        }

    if r2.get("resolvida"):
        linha_opcao2 = {
            "resolvida": True,
            "preco_calculado": r2["preco_calculado"],
            "frete_usado": r2["frete_usado"],
            "margem_percentual_obtida": r2["margem_percentual_obtida"],
            "faixa_preco": f"{r2['faixa_frete'].preco_min}-{r2['faixa_frete'].preco_max}",
            "rodadas_ate_confirmar": r2["rodadas"],
        }
    else:
        linha_opcao2 = {
            "resolvida": False,
            "motivo": r2.get("motivo") or r2.get("erro") or "motivo desconhecido",
        }

    bateu = (
        linha_opcao1 is not None and linha_opcao2.get("resolvida")
        and linha_opcao1["preco_calculado"] == linha_opcao2["preco_calculado"]
        and linha_opcao1["frete_usado"] == linha_opcao2["frete_usado"]
    )

    comparacao["margens"][margem_chave] = {
        "margem_alvo_percentual": margem_valor,
        "opcao_1_tabela_local": linha_opcao1,
        "opcao_2_via_api": linha_opcao2,
        "bateu": bateu,
    }

linhas_df = []
for margem_chave, dados in comparacao["margens"].items():
    o1 = dados["opcao_1_tabela_local"]
    o2 = dados["opcao_2_via_api"]
    o2_resolvida = bool(o2 and o2.get("resolvida"))
    linhas_df.append({
        "Margem": margem_chave.capitalize(),
        "Meta %": dados["margem_alvo_percentual"],
        "Opção 1 — Preço": o1["preco_calculado"] if o1 else None,
        "Opção 1 — Frete": o1["frete_usado"] if o1 else None,
        "Opção 1 — Margem % obtida": o1["margem_percentual_obtida"] if o1 else None,
        "Opção 2 — Preço": o2["preco_calculado"] if o2_resolvida else None,
        "Opção 2 — Frete": o2["frete_usado"] if o2_resolvida else None,
        "Opção 2 — Margem % obtida": o2["margem_percentual_obtida"] if o2_resolvida else None,
        "Rodadas (Opção 2)": o2["rodadas_ate_confirmar"] if o2_resolvida else None,
        "Motivo (se Opção 2 falhou)": None if o2_resolvida else (o2["motivo"] if o2 else None),
        "Status": "IGUAL" if dados["bateu"] else "DIFERENTE",
    })
df_comparacao = pd.DataFrame(linhas_df)

tabela_final = Table(title='Comparação Opção 1 (tabela local) x Opção 2 (API) — Chinelo, Clássico')
for coluna in df_comparacao.columns:
    justify = 'left' if coluna in ('Margem', 'Status', 'Motivo (se Opção 2 falhou)') else 'right'
    tabela_final.add_column(coluna, justify=justify)
for _, linha in df_comparacao.iterrows():
    valores = [str(linha[coluna]) if pd.notna(linha[coluna]) else '—' for coluna in df_comparacao.columns]
    estilo = 'bold green' if linha['Status'] == 'IGUAL' else 'bold red'
    tabela_final.add_row(*valores, style=estilo)

console.print()
console.print(tabela_final)

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(_decimal_para_str(comparacao), f, ensure_ascii=False, indent=2)

console.print(f'\n[dim]Resultado completo salvo em:[/dim] {CAMINHO_SAIDA}')
console.print('[dim]Suba esse arquivo na conversa pra eu analisar.[/dim]')