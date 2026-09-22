# scripts_exploracao_ML/testar_goal_seek_via_api.py

# Função Objetivo: Testa se o goal seek via API (Opção 2 da Frente A) chega no mesmo
# resultado que o sistema real (Opção 1, tabela FreteML) — passo a passo, lado a lado,
# pra provar que bate por desenho e não por coincidência. Roda pra Clássico E Premium
# automaticamente, pra qualquer produto/empresa passado via linha de comando.
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
# Passo a passo: pra cada tipo (Clássico/Premium), os passos que NÃO dependem da margem
# (Custo final/Coleta/Armazenagem/FIXO/Taxa) são a MESMA fonte nas 2 opções por desenho
# (fixo/taxa nunca dependem de onde vem o frete) — mostrados 1x, não comparados. Os que
# DEPENDEM da margem/frete (Denominador/Faixa escolhida/Frete usado/Preço exato/Preço
# final/Margem obtida) vêm de 2 caminhos de código independentes — tabela local (dentro
# de FormulaPrecificacao.passos(), já usado no modal de auditoria real) vs. chamada de
# API ao vivo (dentro do detalhamento que resolver_preco_por_margem já devolve) — e são
# comparados linha a linha, com ✓/✗ explícito.
#
# Uso: python -u "scripts_exploracao_ML/testar_goal_seek_via_api.py" --empresa MB --ean 7899947307029
# --empresa: MB (Magazine) ou SV (Samvale) — default MB.
# --ean: EAN do produto — default o Chinelo já testado antes (7899947307029).
#
# Só leitura no banco e na API — nenhuma escrita em lugar nenhum.

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

# ==== ARGUMENTOS DE LINHA DE COMANDO ====
parser = argparse.ArgumentParser(
    description='Testa goal seek via API (Opção 2) x tabela local (Opção 1), Clássico e '
                 'Premium, passo a passo lado a lado.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB',
                     help='Empresa/conta ML — MB (Magazine) ou SV (Samvale). Default: MB.')
parser.add_argument('--ean', default='7899947307029',
                     help='EAN do produto a testar. Default: Chinelo Nuvem (7899947307029).')
args = parser.parse_args()

CONTA = args.empresa
EAN_PRODUTO = args.ean

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])
# * [EXPLICAÇÃO] → Sem isso, EmpresaRouter não opina sobre qual banco usar (fica None) e o
#                  Django cai no banco default — pra --empresa SV isso leria os dados do MB
#                  silenciosamente, sem erro nenhum. Tem que vir ANTES de qualquer query.

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
TIPOS_ANUNCIO = [
    (TipoAnuncio.CLASSICO, 'Clássico'),
    (TipoAnuncio.PREMIUM, 'Premium'),
]

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / f"goal_seek_via_api_{EAN_PRODUTO}_{CONTA}_resultado.json"


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


def buscar_list_cost_via_api(user_id, category_id, item_price, dimensions_str, tipo_anuncio):
    """Receita validada em 22/09 — free_shipping SEMPRE 'false', sem logistic_type."""
    endpoint = f"/users/{user_id}/shipping_options/free"
    params = {
        "dimensions": dimensions_str,
        "item_price": str(item_price),
        "verbose": "true",
        "condition": "new",
        "category_id": category_id,
        "listing_type_id": tipo_anuncio,
        "mode": "me2",
        "free_shipping": "false",
    }
    resposta = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params,
        nome_log="testar_goal_seek_via_api",
    )
    corpo = resposta.json()
    list_cost = corpo.get("coverage", {}).get("all_country", {}).get("list_cost")
    if list_cost is None:
        raise ErroAPI(
            f"API não retornou list_cost pra item_price={item_price} (tipo={tipo_anuncio}) — resposta: {corpo}"
        )
    return Decimal(str(list_cost))


def montar_frete_todas_opcao2_estimativa(faixas_reais_da_faixa_de_peso, user_id, category_id,
                                          dimensions_str, custo_produto, tipo_anuncio):
    """1 chamada de API por faixa de preço candidata, usando o PISO da faixa. Pula faixas
    cujo teto já é menor que o custo do produto — mesma regra que resolver_preco_por_margem
    aplicaria de qualquer forma, antecipada aqui só pra não gastar chamada de API à toa."""
    faixas_simuladas = []
    for faixa_real in sorted(faixas_reais_da_faixa_de_peso, key=lambda f: f.preco_min):
        if faixa_real.preco_max is not None and faixa_real.preco_max < custo_produto:
            continue

        preco_teste = faixa_real.preco_min if faixa_real.preco_min > 0 else Decimal('0.01')
        valor = buscar_list_cost_via_api(user_id, category_id, preco_teste, dimensions_str, tipo_anuncio)

        faixas_simuladas.append(FaixaFreteSimulada(
            peso_min=faixa_real.peso_min, peso_max=faixa_real.peso_max,
            preco_min=faixa_real.preco_min, preco_max=faixa_real.preco_max,
            valor=valor,
        ))
    return faixas_simuladas


def resolver_com_confirmacao(fixo, taxa_percentual, margem_alvo_fracao, custo_produto, rebate_valor,
                              frete_todas_estimativa, user_id, category_id, dimensions_str, tipo_anuncio):
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

    valor_confirmado = buscar_list_cost_via_api(user_id, category_id, preco_90, dimensions_str, tipo_anuncio)

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
    return obj


def processar_tipo(tipo_anuncio, tipo_label, produto, dim, dimensions_str, user_id, category_id,
                    frete_todas_ml_real, config_geral, faixas_armazenagem):
    """Roda Opção 1 e Opção 2 pras 4 margens de 1 tipo de anúncio (Clássico ou Premium),
    mostra o passo a passo lado a lado, e devolve o resultado pronto pro JSON final."""
    console.print(Panel(f'[bold]{tipo_label}[/bold]', border_style='yellow'))

    try:
        config_tipo = ConfiguracaoTipoAnuncioMercadoLivre.objects.get(tipo_anuncio=tipo_anuncio)
    except ConfiguracaoTipoAnuncioMercadoLivre.DoesNotExist:
        console.print(f'[bold red]{tipo_label}: sem ConfiguracaoTipoAnuncioMercadoLivre cadastrada '
                       f'pra essa empresa — pulando {tipo_label}.[/bold red]\n')
        return None

    margens = [
        ('minima', config_tipo.margem_minima),
        ('padrao', config_tipo.margem_padrao),
        ('maxima', config_tipo.margem_maxima),
        ('competicao', config_tipo.margem_competicao),
    ]

    # ---------- Opção 1: baseline real do sistema (tabela local FreteML) ----------
    console.print(Panel('[bold]Opção 1 — tabela local (FreteML)[/bold]', border_style='cyan'))
    resultados_opcao1 = {}
    for margem_chave, margem_valor in margens:
        formula = FormulaPrecificacao(
            produto=produto, dimensoes_efetivas=dim, config_tipo=config_tipo,
            config_geral=config_geral, margem_alvo_percentual=margem_valor,
            frete_todas=frete_todas_ml_real, faixas_armazenagem=faixas_armazenagem,
        ).calcular()
        resultados_opcao1[margem_chave] = formula

    if not resultados_opcao1['padrao'].resolvida:
        console.print(f'[bold red]{tipo_label}: Opção 1 (baseline) não resolveu nem a margem padrão — '
                       f'produto provavelmente sem impostos_entrada sincronizados no ERP. '
                       f'Pulando {tipo_label}.[/bold red]\n')
        return None

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
    console.print(f'[dim]{len(faixas_reais_da_faixa_de_peso)} faixas de preço na faixa de peso do produto '
                  f'(peso={dim.peso}kg) — montando estimativa via API pra {tipo_label}...[/dim]')

    try:
        frete_todas_opcao2_estimativa = montar_frete_todas_opcao2_estimativa(
            faixas_reais_da_faixa_de_peso, user_id, category_id, dimensions_str, custo_produto, tipo_anuncio,
        )
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        console.print(f'[bold red]{tipo_label}: erro montando faixas via API: {erro}[/bold red]\n')
        return None

    tabela_faixas_api = Table(title=f'Faixas testadas na API — {tipo_label} (estimativa, preço = piso da faixa)', box=None)
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
                tipo_anuncio=tipo_anuncio,
            )
        except (ErroAPI, ErroAutenticacaoAPI) as erro:
            resultados_opcao2[margem_chave] = {"resolvida": False, "erro": str(erro)}

    # ---------- Passos que NÃO dependem da margem (mesma fonte nas 2 opções, por desenho) ----------
    i_padrao = resultados_opcao1['padrao'].intermediarios
    tabela_passos_fixos = Table(
        title=f'{tipo_label} — passos que NÃO dependem da margem/frete (fixo/taxa)',
        box=None,
    )
    tabela_passos_fixos.add_column('Passo')
    tabela_passos_fixos.add_column('Fórmula')
    tabela_passos_fixos.add_column('Valor', justify='right')
    tabela_passos_fixos.add_row('1. Custo final', 'custo + IPI + frete CIF/FOB', f'R$ {i_padrao.custo_final}')
    tabela_passos_fixos.add_row('2. Coleta', 'metro_cúbico × fator_coleta', f'R$ {i_padrao.coleta}')
    tabela_passos_fixos.add_row('3. Armazenagem', f'origem: {i_padrao.armazenagem_origem}', f'R$ {i_padrao.armazenagem}')
    tabela_passos_fixos.add_row('4. FIXO', 'coleta + armazenagem + custo_final − créditos', f'R$ {i_padrao.fixo}')
    tabela_passos_fixos.add_row('5. Taxa', 'comissão + ICMS saída + PIS + COFINS', f'{i_padrao.taxa_percentual}%')
    console.print(tabela_passos_fixos)
    console.print('[dim]Calculado 1x (margem Padrão) e reaproveitado igual nas 4 margens e nas 2 opções — '
                   'não depende de onde vem o frete, então não entra na comparação lado a lado abaixo '
                   '(é o mesmo número usado nas 2, não uma segunda conta independente).[/dim]\n')

    # ---------- Passos que DEPENDEM da margem/frete — lado a lado, Opção 1 x Opção 2 ----------
    resultado_por_margem = {}
    for margem_chave, margem_valor in margens:
        f1 = resultados_opcao1[margem_chave]
        r2 = resultados_opcao2[margem_chave]

        if not f1.resolvida:
            console.print(f'[bold red]{tipo_label} / {margem_chave}: Opção 1 não resolveu.[/bold red]')
        if not r2.get('resolvida'):
            console.print(f'[bold red]{tipo_label} / {margem_chave}: Opção 2 não resolveu — '
                           f'{r2.get("motivo") or r2.get("erro") or "motivo desconhecido"}[/bold red]')

        d1 = f1.intermediarios if f1.resolvida else None
        d2 = r2.get('detalhamento') if r2.get('resolvida') else None

        faixa1 = f'{d1.faixa_frete_preco_min}–{d1.faixa_frete_preco_max}' if d1 else None
        faixa2 = f'{r2["faixa_frete"].preco_min}–{r2["faixa_frete"].preco_max}' if r2.get('resolvida') else None
        frete1 = f1.saida.frete_usado if f1.resolvida else None
        frete2 = r2.get('frete_usado') if r2.get('resolvida') else None
        exato1 = d1.preco_exato_antes_arredondar if d1 else None
        exato2 = d2['preco_exato_antes_arredondar'] if d2 else None
        final1 = f1.saida.preco_final if f1.resolvida else None
        final2 = r2.get('preco_calculado') if r2.get('resolvida') else None
        margem_obtida1 = f1.saida.margem_percentual_obtida if f1.resolvida else None
        margem_obtida2 = r2.get('margem_percentual_obtida') if r2.get('resolvida') else None
        denom1 = d1.denominador if d1 else None
        denom2 = d2['denominador'] if d2 else None

        tabela_passos = Table(
            title=f'{tipo_label} — {margem_chave.capitalize()} (meta {margem_valor}%) '
                  f'— passos dependentes da margem/frete'
        )
        tabela_passos.add_column('Passo')
        tabela_passos.add_column('Opção 1 (tabela local)', justify='right')
        tabela_passos.add_column('Opção 2 (API)', justify='right')
        tabela_passos.add_column('Bate?', justify='center')

        def _linha(rotulo, v1, v2):
            bate = (v1 is not None and v2 is not None and v1 == v2)
            marca = '[bold green]✓[/bold green]' if bate else '[bold red]✗[/bold red]'
            tabela_passos.add_row(rotulo, '—' if v1 is None else str(v1), '—' if v2 is None else str(v2), marca)
            return bate

        _linha('6. Denominador', denom1, denom2)
        _linha('7. Faixa de frete escolhida', faixa1, faixa2)
        _linha('8. Frete usado (R$)', frete1, frete2)
        _linha('9. Preço exato (antes de arredondar)', exato1, exato2)
        _linha('10. Preço final (RoundUp90)', final1, final2)
        bateu_margem = _linha('11. Margem % obtida', margem_obtida1, margem_obtida2)

        console.print(tabela_passos)
        console.print()

        bateu = (
            f1.resolvida and r2.get('resolvida')
            and final1 == final2 and frete1 == frete2
        )

        resultado_por_margem[margem_chave] = {
            'margem_alvo_percentual': margem_valor,
            'opcao_1': (
                {
                    'resolvida': True,
                    'preco_calculado': final1, 'frete_usado': frete1,
                    'margem_percentual_obtida': margem_obtida1, 'faixa_preco': faixa1,
                } if f1.resolvida else {'resolvida': False}
            ),
            'opcao_2': (
                {
                    'resolvida': True,
                    'preco_calculado': final2, 'frete_usado': frete2,
                    'margem_percentual_obtida': margem_obtida2, 'faixa_preco': faixa2,
                    'rodadas_ate_confirmar': r2['rodadas'],
                } if r2.get('resolvida') else {
                    'resolvida': False,
                    'motivo': r2.get('motivo') or r2.get('erro') or 'motivo desconhecido',
                }
            ),
            'bateu': bateu,
        }

    # ---------- Resumo compacto ----------
    linhas_df = []
    for margem_chave, dados in resultado_por_margem.items():
        o1 = dados['opcao_1']
        o2 = dados['opcao_2']
        linhas_df.append({
            'Margem': margem_chave.capitalize(),
            'Meta %': dados['margem_alvo_percentual'],
            'Opção 1 — Preço': o1.get('preco_calculado'),
            'Opção 1 — Frete': o1.get('frete_usado'),
            'Opção 2 — Preço': o2.get('preco_calculado'),
            'Opção 2 — Frete': o2.get('frete_usado'),
            'Rodadas (Opção 2)': o2.get('rodadas_ate_confirmar'),
            'Motivo (se Opção 2 falhou)': o2.get('motivo'),
            'Status': 'IGUAL' if dados['bateu'] else 'DIFERENTE',
        })
    df_resumo = pd.DataFrame(linhas_df)
    tabela_resumo = Table(title=f'Resumo — {tipo_label}')
    for coluna in df_resumo.columns:
        justify = 'left' if coluna in ('Margem', 'Status', 'Motivo (se Opção 2 falhou)') else 'right'
        tabela_resumo.add_column(coluna, justify=justify)
    for _, linha in df_resumo.iterrows():
        valores = [str(linha[coluna]) if pd.notna(linha[coluna]) else '—' for coluna in df_resumo.columns]
        estilo = 'bold green' if linha['Status'] == 'IGUAL' else 'bold red'
        tabela_resumo.add_row(*valores, style=estilo)
    console.print(tabela_resumo)
    console.print()

    return {
        'fixo': fixo, 'taxa_percentual': taxa_percentual, 'rebate_valor': rebate_valor,
        'margens': resultado_por_margem,
    }


# ========== Fluxo principal ==========

console.print(Panel(f'[bold]Goal Seek via API — Opção 1 (tabela local) x Opção 2 (API)[/bold]\n'
                     f'EAN {EAN_PRODUTO} — conta {CONTA} — Clássico e Premium, passo a passo',
                     border_style='blue'))

produto = Produto.objects.get(ean=EAN_PRODUTO)
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
                              nome_log="testar_goal_seek_via_api")
    user_id = resposta_me.json()["id"]

    resposta_item = chamar_api("GET", f"/items/{mlb_referencia}", pasta_logs=PASTA_LOGS, conta=CONTA,
                                nome_log="testar_goal_seek_via_api")
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
tabela_contexto.add_row('Empresa', CONTA)
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
frete_todas_ml_real = list(FreteML.objects.all())

resultados_por_tipo = {}
for tipo_anuncio, tipo_label in TIPOS_ANUNCIO:
    resultado_tipo = processar_tipo(
        tipo_anuncio, tipo_label, produto, dim, dimensions_str, user_id, category_id,
        frete_todas_ml_real, config_geral, faixas_armazenagem,
    )
    if resultado_tipo is not None:
        resultados_por_tipo[tipo_anuncio] = resultado_tipo

if not resultados_por_tipo:
    console.print('[bold red]Nenhum tipo de anúncio resolveu — nada pra salvar.[/bold red]')
    sys.exit(1)

comparacao = {
    "contexto": {
        "empresa": CONTA, "produto_ean": EAN_PRODUTO, "produto_sku": produto.sku,
        "produto_custo": produto.custo, "peso_faturavel_kg": dim.peso,
        "peso_fisico_kg": dim.peso_fisico, "peso_cubico_kg": dim.peso_cubico,
        "dimensoes_cm": f"{dim.altura}x{dim.largura}x{dim.comprimento}",
        "category_id": category_id, "mlb_referencia_category_id": mlb_referencia,
    },
    "tipos": {
        tipo_anuncio: {
            "fixo": r["fixo"], "taxa_percentual": r["taxa_percentual"], "rebate_valor": r["rebate_valor"],
            "margens": r["margens"],
        }
        for tipo_anuncio, r in resultados_por_tipo.items()
    },
}

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(_decimal_para_str(comparacao), f, ensure_ascii=False, indent=2)

console.print(f'\n[dim]Resultado completo salvo em:[/dim] {CAMINHO_SAIDA}')
console.print('[dim]Suba esse arquivo na conversa pra eu analisar.[/dim]')