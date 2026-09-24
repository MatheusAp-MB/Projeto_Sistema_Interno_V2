# integracao_mercado_livre/servicos/sincronizar_categorias_ml.py
#
# Baixa o dump completo de categorias do ML (GET /sites/MLB/categories/all)
# e popula/atualiza CategoriaMercadoLivre.
#
# Roda por empresa porque este sistema usa 1 banco físico por empresa
# (EmpresaRouter, core/database_router.py) — não existe hoje nenhuma
# tabela compartilhada entre Magazine e Samvale além dos apps de infra
# do Django. A árvore de categorias é idêntica nos 2 bancos, mas fica
# gravada duas vezes (mesmo padrão de buscar_frete_real_ml.py).
#
# Usa os 2 headers de controle de versão do ML (X-Content-Created /
# X-Content-MD5, confirmados na doc oficial "Dump de categorias") pra
# não reprocessar o dump inteiro sem necessidade — se o MD5 não mudou
# desde a última carga NESTE banco, pula.
#
# Carga em 2 passadas, porque cada categoria referencia seu pai
# (categoria_pai) e o dump não vem ordenado por profundidade:
#   1ª passada — grava/atualiza todas as categorias, SEM setar categoria_pai
#                (a FK apontaria pra uma linha que ainda não existe).
#   2ª passada — com todas as linhas já existindo, seta categoria_pai de
#                cada uma em lote (bulk_update).

from decimal import Decimal, InvalidOperation
from pathlib import Path

from rich.console import Console

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api
from core.empresa import PREFIXO_ENV_POR_EMPRESA
from mercado_livre.models import CategoriaMercadoLivre, EstadoDumpCategoriasMercadoLivre

console = Console()

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/
TAMANHO_LOTE = 500

CAMPOS_ATUALIZAVEIS = [
    "nome", "categoria_raiz_id", "nivel", "caminho_completo", "e_folha",
    "aceita_novo_anuncio", "status_categoria", "tipo_atributos",
    "condicoes_aceitas", "preco_minimo", "preco_maximo", "vertical",
    "limite_titulo", "limite_subtitulo", "limite_descricao",
    "limite_fotos", "limite_fotos_variacao", "limite_variacoes",
    "catalog_domain", "atualizado_em",
]


def _decimal_ou_none(valor):
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        return None


def _extrair_campos(category_id: str, detalhe: dict) -> dict:
    settings = detalhe.get("settings") or {}
    caminho = detalhe.get("path_from_root") or []

    return {
        "category_id": category_id,
        "nome": detalhe.get("name") or "",
        "categoria_raiz_id": caminho[0]["id"] if caminho else category_id,
        "nivel": len(caminho) or 1,
        "caminho_completo": " > ".join(p["name"] for p in caminho) or (detalhe.get("name") or ""),
        "e_folha": not bool(detalhe.get("children_categories")),
        "aceita_novo_anuncio": settings.get("listing_allowed", True),
        "status_categoria": settings.get("status") or "",
        "tipo_atributos": detalhe.get("attribute_types") or "",
        "condicoes_aceitas": settings.get("item_conditions") or [],
        "preco_minimo": _decimal_ou_none(settings.get("minimum_price")),
        "preco_maximo": _decimal_ou_none(settings.get("maximum_price")),
        "vertical": settings.get("vertical"),
        "limite_titulo": settings.get("max_title_length"),
        "limite_subtitulo": settings.get("max_sub_title_length"),
        "limite_descricao": settings.get("max_description_length"),
        "limite_fotos": settings.get("max_pictures_per_item"),
        "limite_fotos_variacao": settings.get("max_pictures_per_item_var"),
        "limite_variacoes": settings.get("max_variations_allowed"),
        "catalog_domain": settings.get("catalog_domain"),
    }


def _parent_id(detalhe: dict):
    caminho = detalhe.get("path_from_root") or []
    return caminho[-2]["id"] if len(caminho) >= 2 else None


def sincronizar_categorias_ml(empresa: str, forcar: bool = False) -> dict:
    """
    Ponto único de entrada. Baixa o dump (se mudou, ou se forcar=True) e
    popula/atualiza CategoriaMercadoLivre no banco da empresa ativa.
    Precisa rodar com a empresa já ativa (definir_empresa_ativa) — quem
    chama isso é o management command, igual ao padrão de buscar_frete_real_ml.
    """
    conta = PREFIXO_ENV_POR_EMPRESA[empresa]
    pasta_logs = RAIZ_APP / "logs" / empresa.title()

    console.print("Baixando dump de categorias (GET /sites/MLB/categories/all)...")
    resposta = chamar_api(
        "GET", "/sites/MLB/categories/all",
        pasta_logs=pasta_logs, conta=conta,
        nome_log="sincronizar_categorias_ml",
    )

    md5_novo = resposta.headers.get("X-Content-MD5")
    gerado_em_novo = resposta.headers.get("X-Content-Created")

    estado_atual = EstadoDumpCategoriasMercadoLivre.objects.order_by("-baixado_em").first()
    if not forcar and estado_atual and estado_atual.md5 == md5_novo:
        console.print(f"[yellow]MD5 igual ao último dump processado ({estado_atual.baixado_em}) — nada a fazer.[/yellow]")
        return {"atualizado": False, "motivo": "md5_inalterado", "md5": md5_novo}

    dados = resposta.json()
    total = len(dados)
    console.print(f"Dump baixado: {total} categorias. Gravando...")

    # 1ª passada — upsert de todos os campos, exceto categoria_pai.
    objetos = [CategoriaMercadoLivre(**_extrair_campos(cid, detalhe)) for cid, detalhe in dados.items()]
    CategoriaMercadoLivre.objects.bulk_create(
        objetos,
        update_conflicts=True,
        update_fields=CAMPOS_ATUALIZAVEIS,
        unique_fields=["category_id"],
        batch_size=TAMANHO_LOTE,
    )
    console.print(f"[green]1ª passada ok[/green] — {total} categorias gravadas/atualizadas (sem hierarquia ainda).")

    # 2ª passada — agora que toda categoria já existe na tabela, seta o pai.
    todas = {c.category_id: c for c in CategoriaMercadoLivre.objects.all()}
    for cid, detalhe in dados.items():
        todas[cid].categoria_pai_id = _parent_id(detalhe)

    CategoriaMercadoLivre.objects.bulk_update(
        list(todas.values()), ["categoria_pai_id"], batch_size=TAMANHO_LOTE
    )
    console.print("[green]2ª passada ok[/green] — hierarquia (categoria_pai) setada em todas as linhas.")

    EstadoDumpCategoriasMercadoLivre.objects.create(
        gerado_em_ml=gerado_em_novo,
        md5=md5_novo,
        total_categorias=total,
    )

    console.print(f"[bold green]Concluído ({empresa}).[/bold green] {total} categorias sincronizadas.")
    return {"atualizado": True, "total": total, "md5": md5_novo}