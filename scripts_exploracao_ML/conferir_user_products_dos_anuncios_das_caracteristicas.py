# scripts_exploracao_ML/conferir_user_products_dos_anuncios_das_caracteristicas.py
#
# Função Objetivo: RESPONDER, com o seu banco real, uma pergunta que decide como a tela "Características dos anúncios" vai LER e ENVIAR: os anúncios do MESMO produto (SKU) compartilham o mesmo User Product (MLBU)?
# Por que importa: a documentação oficial de User Products (pasta Fontes do vault, atualizada em 17/06/2026) diz que um PUT em /items que muda as características do User Product é REPLICADO pelo Mercado Livre, de forma assíncrona,
# para TODOS os anúncios ligados ao mesmo User Product (campos replicados: title, family_name, attributes, pictures, domain_id, catalog_product_id, condition, available_quantity). Se os anúncios de um SKU compartilham MLBU, um único
# envio poderia bastar; hoje a tela faz 1 envio + 1 leitura de volta POR anúncio. Não corrige nada: só mostra.
#
# O QUE O SCRIPT FAZ (só leitura: SELECT; NENHUMA chamada ao Mercado Livre nem ao ERP; nada é gravado no banco):
#   1) PARTE 1 — SKU de teste: lista os anúncios que a tela mostra para esse SKU, o MLBU de cada um, quais anúncios da tela dividem o mesmo MLBU e QUAIS OUTROS anúncios do banco (inclusive os de catálogo, que a tela não mostra)
#      têm o mesmo MLBU.
#   2) PARTE 2 — conta toda: com a MESMA regra de "quem entra na tela" (consultar_anuncios_elegiveis), conta quantos SKUs têm MLBU compartilhado entre anúncios da tela, quantos envios (PUT) sobrariam se a replicação valesse entre
#      anúncios do mesmo MLBU, e quantos MLBUs da tela também aparecem em anúncios de fora da tela.
#   3) Guarda tudo em JSON (scripts_exploracao_ML/exploracao_user_products_dos_anuncios_das_caracteristicas_<CONTA>.json, sobrescrito a cada execução).
#
# COMO LER O RESULTADO (limites do dado — leia antes de concluir):
#   - O banco só tem o MLBU (user_product_id) que a API mandou na ÚLTIMA importação dos anúncios. MLBU vazio quer dizer "o banco não sabe", não "o anúncio não tem User Product".
#   - O banco NÃO guarda family_name, family_id nem a etiqueta user_product_seller do vendedor. Para confirmar a etiqueta seria preciso 1 chamada GET /users (não feita aqui, de propósito).
#   - A linha "envios se a replicação valesse" é uma HIPÓTESE de conta (junta anúncios que dividem MLBU); ela só vale se o Mercado Livre realmente replicar entre esses anúncios, o que ainda será conferido na API em outro passo.
#   - A tela mostra 1 linha por anúncio (MLB), e a variação é o nível do User Product: um anúncio com várias variações tem vários MLBUs; o script junta anúncios que dividam QUALQUER MLBU.
#
# * [EXPLICAÇÃO] → Este script NÃO reimplementa a regra de "quais anúncios entram na tela": chama a mesma função da tela (consultar_anuncios_elegiveis). Se a regra mudar, a conferência acompanha sozinha.

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


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

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                          # "MB" (Magazine) ou "SV" (Samvale): decide o banco
SKU_DE_TESTE = "F7908050719121.001"   # o produto da sua tela de teste (13 anúncios na tela)
LINHAS_NA_TELA = 20                   # quantas linhas de cada lista mostrar na tela (o JSON leva todas)
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

from mercado_livre.funcoes_auxiliares.caracteristicas_ml import consultar_anuncios_elegiveis
from mercado_livre.models import VariacaoAnuncioMercadoLivre

console = Console()
CAMINHO_JSON = Path(__file__).resolve().parent / f"exploracao_user_products_dos_anuncios_das_caracteristicas_{CONTA}.json"
TAMANHO_DO_LOTE_DE_MLBU = 500

ROTULO_CLASSIFICACAO = {"simples": "simples", "base": "base de catálogo", "catalogo": "catálogo", None: "sem tipo"}


# Função Objetivo: MLBU limpo: texto sem espaços, ou None quando o banco não tem (vazio ou nulo).
def _limpar_mlbu(valor):
    texto = (valor or "").strip()
    return texto or None


# Função Objetivo: Quantos GRUPOS de anúncios sobram quando se juntam os que dividem QUALQUER MLBU. Entrada: {anuncio_id: {mlbus}}. Anúncio sem MLBU fica sozinho no seu grupo.
def _contar_grupos(mlbus_por_anuncio):
    pai = {anuncio: anuncio for anuncio in mlbus_por_anuncio}

    def achar(anuncio):
        while pai[anuncio] != anuncio:
            pai[anuncio] = pai[pai[anuncio]]
            anuncio = pai[anuncio]
        return anuncio

    primeiro_dono = {}
    for anuncio, mlbus in mlbus_por_anuncio.items():
        for mlbu in mlbus:
            if mlbu in primeiro_dono:
                pai[achar(anuncio)] = achar(primeiro_dono[mlbu])
            else:
                primeiro_dono[mlbu] = anuncio
    return len({achar(anuncio) for anuncio in pai})


# Função Objetivo: Outras variações do banco (de fora da lista dada) que têm algum dos MLBUs dados. Em lotes, para a lista do IN não ficar enorme.
def _variacoes_de_fora_com_os_mlbus(mlbus, anuncios_de_dentro):
    mlbus = list(mlbus)
    for inicio in range(0, len(mlbus), TAMANHO_DO_LOTE_DE_MLBU):
        lote = mlbus[inicio:inicio + TAMANHO_DO_LOTE_DE_MLBU]
        consulta = (
            VariacaoAnuncioMercadoLivre.objects
            .filter(mlbu__in=lote)
            .exclude(anuncio__in=anuncios_de_dentro)
            .values_list(
                "mlbu", "anuncio__mlb", "produto_id", "anuncio__eh_fossil_migracao",
                "anuncio__tipo_de_anuncio__classificacao_catalogo", "anuncio__tipo_de_anuncio__status",
            )
        )
        yield from consulta


def _rotulo_de_fora(classificacao, fossil, status):
    partes = [ROTULO_CLASSIFICACAO.get(classificacao, str(classificacao))]
    if fossil:
        partes.append("fóssil de migração")
    if status:
        partes.append(str(status))
    return ", ".join(partes)


# ─── PARTE 1: O SKU DE TESTE ────────────────────────────────────────────

def parte_1_sku_de_teste():
    anuncios = list(consultar_anuncios_elegiveis([SKU_DE_TESTE]).order_by("mlb"))
    console.rule(f"[bold]PARTE 1 — SKU {SKU_DE_TESTE} (conta {CONTA})")
    console.print(f"Anúncios que a tela mostra para este SKU: [bold]{len(anuncios)}[/bold]")
    if not anuncios:
        console.print("[yellow]Nenhum anúncio elegível para este SKU nesta conta. Confira CONTA e SKU_DE_TESTE no topo do script.[/yellow]")
        return {"sku": SKU_DE_TESTE, "n_anuncios_na_tela": 0}

    variacoes = list(
        VariacaoAnuncioMercadoLivre.objects
        .filter(anuncio__in=anuncios, produto_id=SKU_DE_TESTE)
        .values_list("anuncio_id", "anuncio__mlb", "variacao_id", "mlbu")
    )
    mlbus_por_anuncio = defaultdict(set)
    mlb_por_anuncio = {}
    anuncios_por_mlbu = defaultdict(set)
    for anuncio_id, mlb, _variacao_id, mlbu in variacoes:
        mlb_por_anuncio[anuncio_id] = mlb
        mlbu = _limpar_mlbu(mlbu)
        mlbus_por_anuncio[anuncio_id]  # garante a chave mesmo sem MLBU
        if mlbu:
            mlbus_por_anuncio[anuncio_id].add(mlbu)
            anuncios_por_mlbu[mlbu].add(mlb)

    sem_mlbu = sorted(mlb for anuncio_id, mlb in mlb_por_anuncio.items() if not mlbus_por_anuncio[anuncio_id])
    de_fora = defaultdict(list)
    for mlbu, mlb, sku, fossil, classificacao, status in _variacoes_de_fora_com_os_mlbus(anuncios_por_mlbu, anuncios):
        de_fora[mlbu].append({"mlb": mlb, "sku": sku, "rotulo": _rotulo_de_fora(classificacao, fossil, status)})

    tabela = Table(box=box.SIMPLE_HEAVY, show_lines=False)
    tabela.add_column("MLBU")
    tabela.add_column("Anúncios DA TELA com esse MLBU")
    tabela.add_column("Outros anúncios do banco com esse MLBU (fora da tela)")
    for mlbu in sorted(anuncios_por_mlbu):
        fora = "; ".join(f"{o['mlb']} ({o['rotulo']}{'' if o['sku'] == SKU_DE_TESTE else ', SKU ' + str(o['sku'])})" for o in de_fora.get(mlbu, [])) or "—"
        tabela.add_row(mlbu, ", ".join(sorted(anuncios_por_mlbu[mlbu])), fora)
    console.print(tabela)

    grupos = _contar_grupos(mlbus_por_anuncio)
    compartilhados = {mlbu: sorted(mlbs) for mlbu, mlbs in anuncios_por_mlbu.items() if len(mlbs) > 1}
    console.print(f"MLBUs diferentes entre os anúncios da tela: [bold]{len(anuncios_por_mlbu)}[/bold]")
    console.print(f"MLBUs que 2 ou mais anúncios DA TELA dividem: [bold]{len(compartilhados)}[/bold]")
    console.print(f"Anúncios da tela sem MLBU no banco ({len(sem_mlbu)}): {', '.join(sem_mlbu) or '—'}")
    console.print(f"Envios hoje (1 por anúncio): [bold]{len(anuncios)}[/bold]  |  grupos se a replicação valesse entre anúncios do mesmo MLBU: [bold]{grupos}[/bold]")
    return {
        "sku": SKU_DE_TESTE,
        "n_anuncios_na_tela": len(anuncios),
        "anuncios_por_mlbu": {mlbu: sorted(mlbs) for mlbu, mlbs in sorted(anuncios_por_mlbu.items())},
        "mlbus_compartilhados_na_tela": compartilhados,
        "anuncios_sem_mlbu": sem_mlbu,
        "outros_anuncios_com_o_mesmo_mlbu": dict(de_fora),
        "grupos_se_a_replicacao_valesse": grupos,
    }


# ─── PARTE 2: A CONTA TODA ──────────────────────────────────────────────

def parte_2_conta_toda():
    console.rule(f"[bold]PARTE 2 — todos os SKUs da tela (conta {CONTA})")
    elegiveis = consultar_anuncios_elegiveis()
    linhas = list(
        VariacaoAnuncioMercadoLivre.objects
        .filter(anuncio__in=elegiveis, produto__isnull=False)
        .values_list("produto_id", "anuncio_id", "anuncio__mlb", "mlbu")
    )

    mlbus_por_anuncio_por_sku = defaultdict(lambda: defaultdict(set))
    skus_por_mlbu = defaultdict(set)
    anuncios_por_mlbu = defaultdict(set)
    n_variacoes_com_mlbu = 0
    for sku, anuncio_id, _mlb, mlbu in linhas:
        mlbus_por_anuncio_por_sku[sku][anuncio_id]  # garante a chave mesmo sem MLBU
        mlbu = _limpar_mlbu(mlbu)
        if mlbu:
            n_variacoes_com_mlbu += 1
            mlbus_por_anuncio_por_sku[sku][anuncio_id].add(mlbu)
            skus_por_mlbu[mlbu].add(sku)
            anuncios_por_mlbu[mlbu].add(anuncio_id)

    n_anuncios = sum(len(anuncios) for anuncios in mlbus_por_anuncio_por_sku.values())
    classes = Counter()
    exemplos_que_compartilham = []
    envios_hoje = 0
    envios_se_replicasse = 0
    for sku, mlbus_por_anuncio in mlbus_por_anuncio_por_sku.items():
        n = len(mlbus_por_anuncio)
        grupos = _contar_grupos(mlbus_por_anuncio)
        envios_hoje += n
        envios_se_replicasse += grupos
        n_sem = sum(1 for mlbus in mlbus_por_anuncio.values() if not mlbus)
        if n_sem == n:
            classes["nenhum anúncio do SKU tem MLBU no banco"] += 1
        elif grupos < n - n_sem or any(len(anuncios_por_mlbu[m] & set(mlbus_por_anuncio)) > 1 for mlbus in mlbus_por_anuncio.values() for m in mlbus):
            classes["há MLBU dividido por 2+ anúncios da tela"] += 1
            exemplos_que_compartilham.append({"sku": sku, "anuncios_na_tela": n, "grupos": grupos})
        elif n_sem:
            classes["cada anúncio com MLBU tem o seu; outros sem MLBU"] += 1
        else:
            classes["todos têm MLBU e cada anúncio tem o seu"] += 1

    mlbus_da_tela = set(skus_por_mlbu)
    de_fora = Counter()
    mlbus_com_gente_de_fora = set()
    for mlbu, _mlb, _sku, fossil, classificacao, status in _variacoes_de_fora_com_os_mlbus(mlbus_da_tela, elegiveis):
        de_fora[_rotulo_de_fora(classificacao, fossil, status)] += 1
        mlbus_com_gente_de_fora.add(mlbu)
    mlbus_entre_skus = {mlbu: sorted(skus) for mlbu, skus in skus_por_mlbu.items() if len(skus) > 1}

    resumo = Table(box=box.SIMPLE_HEAVY, show_header=False)
    resumo.add_column("")
    resumo.add_column("", justify="right")
    resumo.add_row("SKUs com anúncio na tela", f"{len(mlbus_por_anuncio_por_sku)}")
    resumo.add_row("Anúncios na tela (MLB)", f"{n_anuncios}")
    resumo.add_row("Variações lidas", f"{len(linhas)}  (com MLBU no banco: {n_variacoes_com_mlbu})")
    resumo.add_row("MLBUs diferentes na tela", f"{len(mlbus_da_tela)}")
    resumo.add_row("MLBUs divididos por 2+ anúncios da tela", f"{sum(1 for m, a in anuncios_por_mlbu.items() if len(a) > 1)}")
    resumo.add_row("MLBUs que aparecem em SKUs diferentes", f"{len(mlbus_entre_skus)}")
    resumo.add_row("MLBUs da tela que também existem em anúncios de FORA da tela", f"{len(mlbus_com_gente_de_fora)}")
    resumo.add_row("Envios hoje (1 por anúncio da tela)", f"{envios_hoje}")
    resumo.add_row("Envios se a replicação valesse entre anúncios do mesmo MLBU (hipótese)", f"{envios_se_replicasse}")
    console.print(resumo)

    tabela_classes = Table(box=box.SIMPLE_HEAVY, title="Como cada SKU fica")
    tabela_classes.add_column("Situação do SKU")
    tabela_classes.add_column("SKUs", justify="right")
    for nome, quantidade in classes.most_common():
        tabela_classes.add_row(nome, str(quantidade))
    console.print(tabela_classes)

    if de_fora:
        tabela_fora = Table(box=box.SIMPLE_HEAVY, title="Anúncios de FORA da tela que dividem MLBU com a tela")
        tabela_fora.add_column("Tipo")
        tabela_fora.add_column("Variações", justify="right")
        for rotulo, quantidade in de_fora.most_common():
            tabela_fora.add_row(rotulo, str(quantidade))
        console.print(tabela_fora)

    if exemplos_que_compartilham:
        tabela_exemplos = Table(box=box.SIMPLE_HEAVY, title=f"SKUs onde anúncios da tela dividem MLBU (até {LINHAS_NA_TELA})")
        tabela_exemplos.add_column("SKU")
        tabela_exemplos.add_column("Anúncios na tela", justify="right")
        tabela_exemplos.add_column("Grupos", justify="right")
        for exemplo in sorted(exemplos_que_compartilham, key=lambda e: e["grupos"] - e["anuncios_na_tela"])[:LINHAS_NA_TELA]:
            tabela_exemplos.add_row(exemplo["sku"], str(exemplo["anuncios_na_tela"]), str(exemplo["grupos"]))
        console.print(tabela_exemplos)

    return {
        "n_skus": len(mlbus_por_anuncio_por_sku),
        "n_anuncios_na_tela": n_anuncios,
        "n_variacoes": len(linhas),
        "n_variacoes_com_mlbu": n_variacoes_com_mlbu,
        "n_mlbus_na_tela": len(mlbus_da_tela),
        "situacao_dos_skus": dict(classes),
        "envios_hoje": envios_hoje,
        "envios_se_a_replicacao_valesse": envios_se_replicasse,
        "mlbus_em_skus_diferentes": mlbus_entre_skus,
        "anuncios_de_fora_que_dividem_mlbu_com_a_tela": dict(de_fora),
        "skus_com_mlbu_dividido_na_tela": exemplos_que_compartilham,
    }


def main():
    resultado = {"conta": CONTA, "parte_1_sku_de_teste": parte_1_sku_de_teste(), "parte_2_conta_toda": parte_2_conta_toda()}
    CAMINHO_JSON.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nResultado completo gravado em: {CAMINHO_JSON}")


if __name__ == "__main__":
    main()
