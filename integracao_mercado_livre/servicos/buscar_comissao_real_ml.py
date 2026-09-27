# integracao_mercado_livre/servicos/buscar_comissao_real_ml.py
#
# Busca a Comissão Real de cada MLB (via API do Mercado Livre —
# GET /items/{mlb} + GET /sites/MLB/listing_prices, endpoint validado
# dígito a dígito em 24/09/2026 contra o Simulador de Custos real do
# ML — ver Checkpoint - Investigação da Comissão Real de Venda via API
# do Mercado Livre, seção 8) e grava em VariacaoAnuncioMercadoLivre.
# comissao_real_percentual / .comissao_real_valor /
# .comissao_real_preco_usado / .comissao_real_atualizado_em.
#
# Não confundir com Comissão Aproximada
# (ConfiguracaoTipoAnuncioMercadoLivre.comissao, manual, só por
# tipo_anuncio) — essa aqui é a real, por MLB, dependente do preço
# vigente no momento da consulta.
#
# 2 chamadas por MLB (não por variação): GET /items/{mlb} — pra pegar
# category_id, listing_type_id e o price ATUAL do anúncio direto da
# fonte (nunca o preco_atual do banco local, que pode estar
# desatualizado) — e GET /sites/MLB/listing_prices com esses 3 dados.
# O resultado de /items/{mlb} é cacheado por MLB dentro da mesma
# execução — se o mesmo MLB tiver 2+ variações (mesmo padrão de
# frete_real, que também é por MLB salvo redundantemente em cada
# variação), a 2ª chamada de /items não se repete.
#
# Granularidade em 3 níveis (Matheus, 24/09) — mesmo motivo do frete:
# chamada de API é cara e demorada.
#   - Universal (nem --produto nem --mlb): só processa variações que
#     aparecem em pelo menos 1 linha de GradePrecificacaoML (relevantes
#     pra precificação hoje) — mesmo filtro que buscar_frete_real_ml
#     já usa.
#   - Por produto (--produto <sku>): todas as variações (Clássico e
#     Premium) daquele produto — ignora o filtro de Grade, porque o
#     alvo já foi escto_sku: str | None = None, mlb: str | None = None) -> dict:
    """
    Ponto único de entrada. Busca a Comissão Real (API do ML) — universal,
    por produto ou por MLB (produto_sku/mlb mutuamente exclusivos) — grava
    direto em VariacaoAnuncioMercadoLivre e recalcula a Comissão Média
    (Produto/Categoria) só pra quem foi tocado nesse run. Precisa rodar com
    a empresa já ativa (definir_empresa_ativa) — quem chama isso é o
    management command, igual ao padrão de buscar_frete_real_ml.
    """
    pasta_logs = _caminho_pasta_logs(empresa)
    api_ml = ApiMercadoLivre(pasta_logs=pasta_logs, empresa=empresa)

    variacoes = list(_montar_queryset(produto_sku, mlb))
    total = len(variacoes)

    alvo = f'MLB {mlb}' if mlb else (f'produto {produto_sku}' if produto_sku else 'universal (relevantes pra precificação)')
    console.print(f"Variações a processar ({empresa}, {alvo}): {total}\n")

    if total == 0:
        console.print("[yellow]Nenhuma variação encontrada pra esse escopo — nada a fazer.[/yellow]")
        return {"empresa": empresa, "total": 0, "com_sucesso": 0, "com_erro": 0, "resultados": [],
                "produtos_recalculados": 0, "categorias_recalculadas": 0}

    resultados = []
    com_sucesso = 0
    com_erro = 0
    cache_item_info = {}
    produtos_tocados = set()
    categorias_tocadas = set()
    inicio_execucao = time.perf_counter()

    grupos = [variacoes[i:i + TAMANHO_GRUPO_EXIBICAO] for i in range(0, total, TAMANHO_GRUPO_EXIBICAO)]
    processadas = 0

    for indice_grupo, grupo in enumerate(grupos, start=1):
        decorrido = time.perf_counter() - inicio_execucao
        console.print(
            f"[bold]GRUPO {indice_grupo}/{len(grupos)}[/bold]  "
            f"({processadas}/{total} no total  •  {com_sucesso} com sucesso  •  {decorrido:.0f}s decorridos)"
        )

        for variacao in grupo:
            mlb_atual = variacao.anuncio.mlb

            try:
                resultado = buscar_comissao_real_variacao(variacao, api_ml, cache_item_info)
            except (ErroAPI, ErroAutenticacaoAPI) as e:
                resultado = {"mlb": mlb_atual, "sucesso": False, "motivo": str(e)}

            resultados.append(resultado)

            if resultado["sucesso"]:
                com_sucesso += 1
                console.print(f"  ✓ {mlb_atual:<20} {resultado['percentual']}% (R$ {resultado['valor']:.2f})")
                if variacao.produto_id:
                    produtos_tocados.add(variacao.produto_id)
                if variacao.categoria_id:
                    categorias_tocadas.add(variacao.categoria_id)
            else:
                com_erro += 1
                console.print(f"  [red]✗ {mlb_atual:<20} {resultado['motivo']}[/red]")

            processadas += 1

    duracao_total = time.perf_counter() - inicio_execucao

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green]")
    console.print(f"Com sucesso: {com_sucesso}/{total}  •  Com erro: {com_erro}/{total}")
    console.print(
        f"Tempo total: {duracao_total:.1f}s  •  "
        f"Chamadas a /items economizadas por cache: {total - len(cache_item_info)}"
    )

    if com_erro:
        console.print("\n[yellow]Itens com erro (comissão real anterior, se existia, foi mantida sem alteração):[/yellow]")
        for r in resultados:
            if not r["sucesso"]:
                console.print(f"  {r['mlb']}: {r['motivo']}")

    recalculo = recalcular_comissao_media(
        produto_ids=produtos_tocados, categoria_ids=categorias_tocadas,
    )
    console.print(
        f"\n[bold]Comissão Média recalculada:[/bold] "
        f"{recalculo['produtos_atualizados']} produto(s) · {recalculo['categorias_atualizadas']} categoria(s)"
    )

    return {
        "empresa": empresa,
        "total": total,
        "com_sucesso": com_sucesso,
        "com_erro": com_erro,
        "duracao_total_segundos": round(duracao_total, 2),
        "resultados": resultados,
        "produtos_recalculados": recalculo['produtos_atualizados'],
        "categorias_recalculadas": recalculo['categorias_atualizadas'],
    }   