# scripts_exploracao_ML/baixar_dump_categorias_ml.py

# Função Objetivo: Baixa o dump completo de categorias do Mercado Livre (site MLB) via
# GET /sites/MLB/categories/all — endpoint confirmado na doc oficial ("Dump de categorias"),
# que devolve a árvore inteira numa resposta codificada com gzip, junto com 2 headers de
# controle de versão (X-Content-Created e X-Content-MD5).
#
# O objetivo AQUI não é popular nenhuma tabela ainda — é só inspecionar o formato real de
# cada entrada do dump, porque a doc oficial não mostra isso (só documenta o mecanismo de
# download). Precisamos saber: é uma lista achatada {id, name}, igual a /sites/MLB/categories,
# ou já vem com alguma informação de hierarquia (parent_id ou algo parecido)?
#
# Não grava nada no banco. Salva o dump completo em JSON (scripts_exploracao_ML/
# dump_categorias_mlb.json) pra consulta posterior, e imprime um resumo da estrutura.
#
# Uso: python -u "scripts_exploracao_ML/baixar_dump_categorias_ml.py" [--empresa MB|SV]
# --empresa: só define de qual conta pegar o token de autenticação — categorias do site MLB
#   não mudam entre MB e SV (é o mesmo Brasil pros dois). Default: MB.

import os
import sys
import json
import gzip
import argparse
from pathlib import Path


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
from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# ==== ARGUMENTOS DE LINHA DE COMANDO ====
parser = argparse.ArgumentParser(
    description='Baixa o dump completo de categorias do Mercado Livre (site MLB) e '
                'inspeciona o formato real de cada entrada.'
)
parser.add_argument('--empresa', choices=['MB', 'SV'], default='MB',
                     help='Conta usada só pra autenticação (categorias não variam '
                          'entre MB/SV). Default: MB.')
args = parser.parse_args()

CONTA = args.empresa
EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = Path(_PASTA_ATUAL) / "logs"
CAMINHO_SAIDA = Path(_PASTA_ATUAL) / "dump_categorias_mlb.json"


def main():
    console.print(Panel(
        "Baixando GET /sites/MLB/categories/all — pode demorar um pouco, é o dump inteiro.",
        title="Dump de Categorias ML", style="cyan"
    ))

    try:
        resposta = chamar_api(
            "GET", "/sites/MLB/categories/all",
            pasta_logs=PASTA_LOGS, conta=CONTA, nome_log="dump_categorias",
        )
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        console.print(f"[red]Erro ao baixar o dump: {e}[/red]")
        sys.exit(1)

    # ==== Headers de controle de versão (confirmados na doc oficial) ====
    console.print(Panel(
        f"Content-Encoding: {resposta.headers.get('Content-Encoding', '(ausente)')}\n"
        f"Content-Type: {resposta.headers.get('Content-Type', '(ausente)')}\n"
        f"Content-Length: {resposta.headers.get('Content-Length', '(ausente)')}\n"
        f"X-Content-Created: {resposta.headers.get('X-Content-Created', '(ausente)')}\n"
        f"X-Content-MD5: {resposta.headers.get('X-Content-MD5', '(ausente)')}",
        title="Headers da resposta", style="yellow"
    ))

    # ==== Parse do JSON — requests normalmente já descomprime gzip sozinho (via
    #      Content-Encoding), mas cai pro gzip manual se o .json() direto falhar ====
    try:
        dados = resposta.json()
        modo_parse = "direto (.json() — requests descomprimiu sozinho)"
    except Exception:
        try:
            dados = json.loads(gzip.decompress(resposta.content))
            modo_parse = "manual (gzip.decompress + json.loads)"
        except Exception as e:
            console.print(f"[red]Não consegui interpretar a resposta nem direto nem via gzip manual: {e}[/red]")
            console.print(f"Primeiros 200 bytes crus: {resposta.content[:200]!r}")
            sys.exit(1)

    console.print(f"[green]Parse OK — modo: {modo_parse}[/green]")

    # ==== Análise da estrutura ====
    tipo_raiz = type(dados).__name__
    console.print(f"\nTipo da raiz do JSON: [bold]{tipo_raiz}[/bold]")

    if isinstance(dados, list):
        total = len(dados)
        console.print(f"Total de categorias no dump: [bold]{total}[/bold]")

        # Checa quais chaves aparecem, olhando uma amostra maior (não só a 1ª entrada)
        chaves_por_entrada = [frozenset(item.keys()) for item in dados[:200] if isinstance(item, dict)]
        chaves_unicas = set(chaves_por_entrada)
        console.print(f"\nConjunto(s) de chaves encontrado(s) nas primeiras 200 entradas: "
                       f"{len(chaves_unicas)} formato(s) diferente(s)")
        for conjunto in chaves_unicas:
            console.print(f"  → {sorted(conjunto)}")

        tabela = Table(title="Amostra — primeiras 10 entradas")
        if dados:
            for chave in sorted(dados[0].keys()):
                tabela.add_column(chave)
            for item in dados[:10]:
                tabela.add_row(*[str(item.get(chave, "")) for chave in sorted(dados[0].keys())])
        console.print(tabela)

    elif isinstance(dados, dict):
        console.print(f"Chaves da raiz (objeto, não lista): {sorted(dados.keys())}")
        console.print(json.dumps(dados, ensure_ascii=False, indent=2)[:3000])

    # ==== Salva o dump completo pra consulta posterior ====
    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    console.print(f"\n[bold green]Dump completo salvo em:[/bold green] {CAMINHO_SAIDA}")


if __name__ == "__main__":
    main()