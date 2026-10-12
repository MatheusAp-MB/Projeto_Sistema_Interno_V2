# scripts_exploracao_ML/conferir_contagem_do_hub_contra_a_previsao_de_ruptura.py
#
# Função Objetivo: CONFERIR, com o seu banco real, por que o número de anúncios do Hub de Anúncios (tela "Anúncios — Mercado Livre") e o da Previsão de Ruptura de estoque não batem, nos dois filtros que você comparou:
# FULL (logística FULL) e FORA DO FULL (as 6 logísticas Coleta, Agência, Flex Puro, Legado, Correios, Por nossa conta). Para cada filtro o script mostra a conta do Hub, a conta da Previsão e, anúncio por anúncio, QUEM está
# só de um lado e POR QUÊ. Não corrige nada: só mostra.
#
# O QUE O SCRIPT FAZ (só leitura: SELECT; NENHUMA chamada ao Mercado Livre nem ao ERP; nada é gravado no banco):
#   1) Lado do Hub: roda a MESMA função da tela (listar_skus_filtrados) com o filtro de logística e monta a árvore de cada SKU (montar_estrutura_de_sku) para ver exatamente quais anúncios aparecem e quantas VARIAÇÕES cada um tem.
#   2) Lado da Previsão: roda as MESMAS funções que montam as duas listas (ruptura_lista._entidades e ruptura_lista_fora._entidades, a partir do mesmo cadastro em lote) e conta as linhas "Anúncio (MLB)" e "Produto (SKU)".
#   3) Compara os dois conjuntos de MLB e explica cada diferença (motivo + título + logística + classificação de catálogo).
#   4) Guarda tudo em JSON (scripts_exploracao_ML/exploracao_contagem_do_hub_contra_a_previsao_de_ruptura_<CONTA>.json, sobrescrito a cada execução).
#
# COMO LER O RESULTADO:
#   - "Número da tela do Hub" é o que a tela chama de "anúncios": o Hub SOMA VARIAÇÕES (um anúncio com 3 variações conta 3) e, quando um filtro está ativo, puxa a Base de Catálogo junto de um filho que passa, mesmo que a
#     logística da Base seja outra. A Previsão conta MLBs distintos. Por isso os dois números podem diferir mesmo com a regra de "quem entra" igual: a linha "MLBs distintos no Hub" é a comparação justa.
#   - "Só no Hub" costuma ser Base de Catálogo puxada por um filho. "Só na Previsão" é anúncio que passa no filtro de logística mas o Hub não mostra (veja a classificação de catálogo no motivo).
#   - A Previsão só enxerga variações com MLB preenchido; o Hub agrupa por SKU do Produto, SKU do ML ou MLB (variação sem Produto no ERP também vira "SKU" no Hub): a linha de SKUs mostra quantos são desse tipo.
#
# * [EXPLICAÇÃO] → Este script NÃO reimplementa a regra de nenhuma das duas telas: ele chama as funções delas. Se um dia as regras mudarem, a conferência acompanha sozinha.

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, "manage.py")):
            sys.path.insert(0, caminho_atual)
            return caminho_atual
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError("Não foi possível encontrar manage.py subindo a partir deste script.")


_RAIZ_DO_PROJETO = Path(_adicionar_raiz_do_projeto_ao_path())

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "projeto_sistema_interno_mb_sv.settings")
django.setup()

from rich import box
from rich.console import Console
from rich.table import Table

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from gestao_ruptura.funcoes_auxiliares import ruptura_lista as lista_full
from gestao_ruptura.funcoes_auxiliares import ruptura_lista_fora as lista_fora
from gestao_vendas.funcoes_auxiliares.lista_vendas_ml import unidades_por_dia_da_origem
from mercado_livre.funcoes_auxiliares.badges import BADGES_LOGISTICA
from mercado_livre.funcoes_auxiliares.logistica_do_anuncio import LOGISTICA_FULL
from mercado_livre.funcoes_auxiliares.classificacao_catalogo import carregar_variacoes_por_sku, listar_skus_filtrados, montar_estrutura_de_sku

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                          # "MB" (Magazine) ou "SV" (Samvale): decide o banco
LINHAS_NA_TELA = 15                   # quantos anúncios de cada diferença mostrar na tela (o JSON leva todos)
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

FUSO = ZoneInfo("America/Sao_Paulo")
console = Console()
CAMINHO_JSON = Path(__file__).resolve().parent / f"exploracao_contagem_do_hub_contra_a_previsao_de_ruptura_{CONTA}.json"
# * [EXPLICAÇÃO] → As 6 logísticas do filtro vêm de onde o Hub as tira (os selos de badges.py, que viram as caixas de marcar da tela), NÃO da regra da Previsão: é isso que faz a comparação ser um teste de verdade. Se as duas
#                  fontes um dia discordarem (ex.: uma logística nova no modelo sem selo), este script mostra o anúncio que fica só de um lado.
LOGISTICAS_FORA = [logistica for logistica in BADGES_LOGISTICA if logistica != LOGISTICA_FULL]


# Função Objetivo: O dicionário de filtros que a tela do Hub monta a partir da URL (views.py), só com a logística preenchida.
def _filtros_do_hub(logisticas):
    chaves = ("marcas", "status", "tipos_anuncio", "catalogos", "flex", "estoque", "desconto", "conexao_erp", "faixas_score", "situacoes_competicao")
    return {**{c: [] for c in chaves}, "tipos_logisticos": list(logisticas)}


# Função Objetivo: Os anúncios que a árvore de UM SKU do Hub mostra: (papel, mlb, quantas variações). O Hub conta as variações de cada anúncio visível (é o que ele chama de "anúncios").
def _anuncios_visiveis(estrutura):
    for pagina in estrutura["paginas_catalogo"]:
        for base in pagina["anuncios_base"]:
            yield "base de catálogo", base["mlb"], len(base["folhas"])
            for filho in base["anuncios_catalogo"]:
                yield "catálogo (filho da base)", filho["mlb"], len(filho["folhas"])
        for orfao in pagina["anuncios_catalogo_orfaos"]:
            yield "catálogo sem base", orfao["mlb"], len(orfao["folhas"])
    for simples in estrutura["anuncios_simples"]:
        yield "simples", simples["mlb"], len(simples["folhas"])


# Função Objetivo: Lê o Hub com um filtro de logística, do jeito da tela: o número "anúncios" que ela mostra, os SKUs e, para cada (SKU, MLB) visível, o papel, as variações e a logística do anúncio.
def _ler_hub(logisticas):
    filtros = _filtros_do_hub(logisticas)
    skus, total_da_tela = listar_skus_filtrados(busca=None, filtros=filtros)
    variacoes_por_sku = carregar_variacoes_por_sku(skus=skus)
    pares = {}
    for sku, variacoes in variacoes_por_sku.items():
        estrutura = montar_estrutura_de_sku(sku, variacoes, filtros=filtros)
        if estrutura["total_anuncios"] <= 0:
            continue
        anuncios = {v.anuncio.mlb: v.anuncio for v in variacoes}
        for papel, mlb, n_variacoes in _anuncios_visiveis(estrutura):
            tipo = anuncios[mlb].tipo_de_anuncio
            pares[(sku, mlb)] = {"papel": papel, "variacoes": n_variacoes, "titulo": anuncios[mlb].titulo_anuncio or "",
                                 "logistica": tipo.tipo_logistico if tipo else None, "classificacao": tipo.classificacao_catalogo if tipo else None}
    return {"skus": set(skus), "total_da_tela": total_da_tela, "pares": pares}


# Função Objetivo: Lê a Previsão com as mesmas funções das duas listas: as chaves (MLB e SKU) de cada lista, a partir do cadastro em lote (`dados["cad"]`).
def _ler_previsao(dados):
    return {"full_mlb": {e["chave"] for e in lista_full._entidades("mlb", dados)}, "full_sku": {e["chave"] for e in lista_full._entidades("sku", dados)},
            "fora_mlb": {e["chave"] for e in lista_fora._entidades("mlb", dados)[0]}, "fora_sku": {e["chave"] for e in lista_fora._entidades("sku", dados)[0]}}


# Função Objetivo: Por que este MLB está só no Hub? (a Previsão não o lista). `logisticas` é o filtro de logística usado no Hub.
def _motivo_so_no_hub(mlb, par, logisticas, anuncios_da_previsao):
    if par["logistica"] not in logisticas:
        return f"Base de Catálogo puxada pelo Hub junto de um filho que passa no filtro (o próprio anúncio tem logística {par['logistica']}, fora do filtro)"
    if mlb not in anuncios_da_previsao:
        return "não está no cadastro da Previsão (variação sem MLB?)"
    return "tem logística do filtro e o Hub mostra, mas a Previsão não lista (investigar)"


# Função Objetivo: Por que este MLB está só na Previsão? (o Hub não o mostra, embora a logística dele esteja no filtro).
def _motivo_so_na_previsao(anuncio):
    tipo = anuncio.get("tipo") or {}
    return (f"passa no filtro de logística ({tipo.get('tipo_logistico')}), mas o Hub não o mostra: classificação de catálogo '{tipo.get('classificacao_catalogo')}', "
            f"status '{tipo.get('status')}' (cascata Base↔Catálogo do Hub: ver classificacao_catalogo.montar_estrutura_de_sku)")


# Função Objetivo: A conta completa de UM filtro: números do Hub, números da Previsão e as diferenças com motivo.
def _conferir(nome, logisticas, mlbs_da_previsao, skus_da_previsao, cad):
    console.print(f"[bold]Lendo o Hub com o filtro {nome}...[/bold]")
    hub = _ler_hub(logisticas)
    pares = hub["pares"]
    mlbs_do_hub = {mlb for _, mlb in pares}
    anuncios = cad["anuncios"]
    so_no_hub = sorted(mlbs_do_hub - mlbs_da_previsao)
    so_na_previsao = sorted(mlbs_da_previsao - mlbs_do_hub)
    par_por_mlb = {}
    for (sku, mlb), par in pares.items():
        par_por_mlb.setdefault(mlb, {**par, "skus": []})["skus"].append(sku)
    diferencas_hub = [{"mlb": m, "skus": par_por_mlb[m]["skus"], "titulo": par_por_mlb[m]["titulo"], "papel": par_por_mlb[m]["papel"], "logistica": par_por_mlb[m]["logistica"],
                       "classificacao": par_por_mlb[m]["classificacao"], "motivo": _motivo_so_no_hub(m, par_por_mlb[m], logisticas, anuncios)} for m in so_no_hub]
    diferencas_previsao = [{"mlb": m, "skus": sorted(cad["candidatos"].get(m, {})), "titulo": anuncios[m]["titulo"], "logistica": (anuncios[m].get("tipo") or {}).get("tipo_logistico"),
                            "classificacao": (anuncios[m].get("tipo") or {}).get("classificacao_catalogo"), "motivo": _motivo_so_na_previsao(anuncios[m])} for m in so_na_previsao]
    chaves_sem_produto = sorted(s for s in hub["skus"] if s not in cad["por_sku"])
    resumo = {
        "filtro": nome, "logisticas": list(logisticas),
        "hub_numero_da_tela": hub["total_da_tela"], "hub_variacoes_visiveis": sum(p["variacoes"] for p in pares.values()), "hub_pares_sku_mlb": len(pares), "hub_mlbs_distintos": len(mlbs_do_hub),
        "hub_mlbs_em_mais_de_um_sku": len(pares) - len(mlbs_do_hub), "hub_skus": len(hub["skus"]), "hub_skus_sem_produto_no_erp": len(chaves_sem_produto),
        "previsao_mlbs": len(mlbs_da_previsao), "previsao_skus": len(skus_da_previsao),
        "so_no_hub": len(so_no_hub), "so_na_previsao": len(so_na_previsao),
        "so_no_hub_por_motivo": dict(Counter(d["motivo"] for d in diferencas_hub)), "so_na_previsao_por_motivo": dict(Counter(d["motivo"] for d in diferencas_previsao)),
        "skus_so_na_previsao": len(skus_da_previsao - hub["skus"]),
    }
    return resumo, {"so_no_hub": diferencas_hub, "so_na_previsao": diferencas_previsao, "chaves_do_hub_sem_produto_no_erp": chaves_sem_produto}


# Função Objetivo: Mostra a conta de um filtro na tela, em uma tabela de números e uma de diferenças.
def _mostrar(resumo, detalhes):
    t = Table(title=f"Filtro {resumo['filtro']} — Hub × Previsão", box=box.SIMPLE_HEAVY, show_lines=False)
    t.add_column("O que se conta"), t.add_column("Valor", justify="right")
    linhas = [
        ("Número da tela do Hub (\"anúncios\": soma de variações visíveis)", resumo["hub_numero_da_tela"]), ("  variações visíveis (conferência do número acima)", resumo["hub_variacoes_visiveis"]),
        ("  pares (SKU, MLB) visíveis", resumo["hub_pares_sku_mlb"]), ("MLBs distintos no Hub", resumo["hub_mlbs_distintos"]),
        ("  MLBs que aparecem em mais de um SKU", resumo["hub_mlbs_em_mais_de_um_sku"]), ("MLBs na Previsão (lista Anúncio MLB)", resumo["previsao_mlbs"]),
        ("  só no Hub (a Previsão não lista)", resumo["so_no_hub"]), ("  só na Previsão (o Hub não mostra)", resumo["so_na_previsao"]),
        ("SKUs no Hub (chaves)", resumo["hub_skus"]), ("  chaves sem Produto no ERP (SKU do ML ou MLB)", resumo["hub_skus_sem_produto_no_erp"]),
        ("SKUs na Previsão (lista Produto)", resumo["previsao_skus"]), ("  SKUs na Previsão que não estão no Hub", resumo["skus_so_na_previsao"]),
    ]
    for rotulo, valor in linhas:
        t.add_row(rotulo, f"{valor:,}".replace(",", "."))
    console.print(t)
    for titulo, chave in (("Só no Hub", "so_no_hub"), ("Só na Previsão", "so_na_previsao")):
        itens = detalhes[chave]
        if not itens:
            console.print(f"[green]{titulo}: nenhum anúncio.[/green]")
            continue
        d = Table(title=f"{titulo}: {len(itens)} anúncio(s) (mostrando {min(len(itens), LINHAS_NA_TELA)})", box=box.SIMPLE)
        d.add_column("MLB"), d.add_column("SKU(s)"), d.add_column("Logística"), d.add_column("Catálogo"), d.add_column("Motivo", overflow="fold")
        for i in itens[:LINHAS_NA_TELA]:
            d.add_row(i["mlb"], ", ".join(i["skus"][:2]) + (f" +{len(i['skus']) - 2}" if len(i["skus"]) > 2 else ""), str(i["logistica"]), str(i.get("classificacao") or ""), i["motivo"])
        console.print(d)


def main():
    hoje = datetime.now(FUSO).date()
    console.print("[bold]Lendo o cadastro da Previsão (o mesmo que as listas usam)...[/bold]")
    dados = unidades_por_dia_da_origem(hoje - timedelta(days=30), hoje, "fora")
    previsao = _ler_previsao(dados)
    cad = dados["cad"]
    saida = {"conta": CONTA, "gerado_em": datetime.now(FUSO).isoformat(timespec="seconds"), "filtros": {}}
    sem_logistica = sorted(m for m, a in cad["anuncios"].items() if not lista_full.anuncio_fossil(a) and not lista_full.anuncio_e_do_full(a) and not lista_full.anuncio_e_de_fora_do_full(a))
    fosseis = sum(1 for a in cad["anuncios"].values() if lista_full.anuncio_fossil(a))
    for nome, logisticas, chave in (("FORA DO FULL (6 logísticas)", LOGISTICAS_FORA, "fora"), ("FULL", [LOGISTICA_FULL], "full")):
        resumo, detalhes = _conferir(nome, logisticas, previsao[f"{chave}_mlb"], previsao[f"{chave}_sku"], cad)
        _mostrar(resumo, detalhes)
        saida["filtros"][chave] = {"resumo": resumo, **detalhes}
    saida["anuncios_sem_logistica_no_banco"] = sem_logistica
    saida["anuncios_fosseis_no_cadastro"] = fosseis
    console.print(f"Anúncios sem logística conhecida no banco (nem Full nem fora): {len(sem_logistica)} · fósseis de migração: {fosseis} · logísticas que o Hub conhece: {', '.join(BADGES_LOGISTICA)}")
    CAMINHO_JSON.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"[bold]JSON salvo em[/bold] {CAMINHO_JSON}")


if __name__ == "__main__":
    main()
