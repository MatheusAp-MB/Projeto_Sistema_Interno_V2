# integracao_mercado_livre/servicos/buscar_frete_real_ml.py
#
# Busca o frete REAL de cada MLB (via API do Mercado Livre —
# GET /users/{user_id}/shipping_options/free, endpoint validado em
# 21/09/2026) e grava em VariacaoAnuncioMercadoLivre.frete_real /
# .frete_real_atualizado_em. Só processa variações que aparecem em pelo
# menos 1 linha de GradePrecificacaoML (relevantes pra precificação hoje).
#
# 1 chamada por MLB — esse endpoint não tem multiget, então o ritmo é
# sequencial, igual buscar_mlbs.py (sem paralelismo, backoff de 429 fica
# por conta do chamar_api, como sempre).
#
# Cada sucesso grava na hora (variacao.save()) — não existe arquivo de
# progresso separado, porque não existe "lote perdido" se cair no meio:
# o que já rodou já está no banco. Um erro num item NUNCA apaga um
# frete_real anterior — só atualiza em caso de sucesso.
#
# NÃO mexe em GradePrecificacaoML (frete_calculado/origem_frete/frete_usado)
# — isso é responsabilidade do cálculo de precificação em si
# (calcular_grade_precificacao_ml.py), que ainda vai precisar ser
# atualizado como próxima etapa pra ler esse frete_real.

import os
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.utils import timezone
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, PREFIXO_ENV_POR_EMPRESA

console = Console()

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/

NOME_PASTA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Magazine',
    EMPRESA_SAMVALE: 'Samvale',
}

TAMANHO_GRUPO_EXIBICAO = 20  # quantas variações por bloco visual no console


def _pasta_empresa(empresa: str) -> str:
    if empresa not in NOME_PASTA_POR_EMPRESA:
        raise ValueError(f'Empresa inválida: "{empresa}". Use {list(NOME_PASTA_POR_EMPRESA)}.')
    return NOME_PASTA_POR_EMPRESA[empresa]


def _caminho_pasta_logs(empresa: str) -> Path:
    return RAIZ_APP / 'logs' / _pasta_empresa(empresa)


def _obter_user_id(conta: str) -> str:
    load_dotenv()
    user_id = os.getenv(f"{conta}_USER_ID")
    if not user_id:
        raise RuntimeError(
            f'{conta}_USER_ID não encontrado no .env da raiz do repo — '
            f'adicione a linha {conta}_USER_ID=seu_user_id_aqui.'
        )
    return user_id


# Função Objetivo: Extrai (valor, tipo_de_desconto) da resposta de shipping_options/free.
# Explicação em detalhe: coverage.all_country.list_cost é o campo validado na investigação —
# bate exatamente com o Resumo de Custos real do anúncio. discount.type só entra no log
# (mandatory/fs_optional/etc.) — não tem campo próprio no banco pra isso ainda.
def _extrair_frete_real(resposta_json: dict):
    coverage = resposta_json.get('coverage', {}) or {}
    all_country = coverage.get('all_country', {}) or {}
    list_cost = all_country.get('list_cost')
    discount = all_country.get('discount', {}) or {}
    tipo_desconto = discount.get('type')

    if list_cost is None:
        return None, tipo_desconto

    try:
        return Decimal(str(list_cost)), tipo_desconto
    except InvalidOperation:
        return None, tipo_desconto


# Função Objetivo: Busca e grava o frete real de 1 variação (1 chamada à API).
def buscar_frete_real_variacao(variacao, conta: str, user_id: str, pasta_logs: Path) -> dict:
    mlb = variacao.anuncio.mlb

    resposta = chamar_api(
        "GET", f"/users/{user_id}/shipping_options/free",
        pasta_logs=pasta_logs, conta=conta,
        params={"item_id": mlb, "verbose": "true"},
        nome_log="buscar_frete_real_ml",
    )
    valor, tipo_desconto = _extrair_frete_real(resposta.json())

    if valor is None:
        return {"mlb": mlb, "sucesso": False, "motivo": "resposta sem coverage.all_country.list_cost"}

    variacao.frete_real = valor
    variacao.frete_real_atualizado_em = timezone.now()
    variacao.save(update_fields=["frete_real", "frete_real_atualizado_em"])

    return {"mlb": mlb, "sucesso": True, "valor": valor, "discount_type": tipo_desconto}


def buscar_frete_real_ml(empresa: str) -> dict:
    """
    Ponto único de entrada. Busca o frete real (API do ML) de cada
    variação que aparece em pelo menos 1 linha de GradePrecificacaoML,
    e grava direto em VariacaoAnuncioMercadoLivre. Precisa rodar com a
    empresa já ativa (definir_empresa_ativa) — quem chama isso é o
    management command, igual ao padrão de buscar_detalhes.
    """
    from precificacao.models import GradePrecificacaoML
    from mercado_livre.models import VariacaoAnuncioMercadoLivre

    conta = PREFIXO_ENV_POR_EMPRESA[empresa]
    user_id = _obter_user_id(conta)
    pasta_logs = _caminho_pasta_logs(empresa)

    variacao_ids = (
        GradePrecificacaoML.objects
        .filter(variacao__isnull=False)
        .values_list('variacao_id', flat=True)
        .distinct()
    )
    variacoes = list(
        VariacaoAnuncioMercadoLivre.objects
        .filter(id__in=variacao_ids)
        .select_related('anuncio')
    )

    total = len(variacoes)
    console.print(f"Variações a processar ({empresa}): {total}\n")

    resultados = []
    com_sucesso = 0
    com_erro = 0
    inicio_execucao = time.perf_counter()

    grupos = [variacoes[i:i + TAMANHO_GRUPO_EXIBICAO] for i in range(0, total, TAMANHO_GRUPO_EXIBICAO)]
    processadas = 0

    for indice_grupo, grupo in enumerate(grupos, start=1):
        decorrido = time.perf_counter() - inicio_execucao
        console.print(
            f"[bold]GRUPO {indice_grupo}/{len(grupos)}[/bold]  "
            f"({processadas}/{total} no total  •  {com_sucesso} com sucesso  •  {decorrido:.0f}s decorridos)"
        )

        with Progress(
            SpinnerColumn(finished_text="[green]✓[/green]"),
            TextColumn("[cyan]{task.description:<24}"),
            BarColumn(),
            TextColumn("{task.fields[resultado]}"),
            TimeElapsedColumn(),
        ) as progress:

            tarefas = [
                (variacao, progress.add_task(variacao.anuncio.mlb, total=1, resultado="⏳ na fila", start=False))
                for variacao in grupo
            ]

            for variacao, task_id in tarefas:
                progress.start_task(task_id)
                progress.update(task_id, resultado="")

                try:
                    resultado = buscar_frete_real_variacao(variacao, conta, user_id, pasta_logs)
                except (ErroAPI, ErroAutenticacaoAPI) as e:
                    resultado = {"mlb": variacao.anuncio.mlb, "sucesso": False, "motivo": str(e)}

                resultados.append(resultado)

                if resultado["sucesso"]:
                    com_sucesso += 1
                    progress.update(
                        task_id,
                        resultado=f"R$ {resultado['valor']:.2f} ({resultado.get('discount_type') or '?'})",
                    )
                else:
                    com_erro += 1
                    progress.update(task_id, resultado=f"[red]✗ {resultado['motivo']}[/red]")

                progress.update(task_id, completed=1)
                processadas += 1

    duracao_total = time.perf_counter() - inicio_execucao

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green]")
    console.print(f"Com sucesso: {com_sucesso}/{total}  •  Com erro: {com_erro}/{total}")
    console.print(f"Tempo total: {duracao_total:.1f}s")

    if com_erro:
        console.print("\n[yellow]Itens com erro (frete_real anterior, se existia, foi mantido sem alteração):[/yellow]")
        for r in resultados:
            if not r["sucesso"]:
                console.print(f"  {r['mlb']}: {r['motivo']}")

    return {
        "empresa": empresa,
        "total": total,
        "com_sucesso": com_sucesso,
        "com_erro": com_erro,
        "duracao_total_segundos": round(duracao_total, 2),
        "resultados": resultados,
    }