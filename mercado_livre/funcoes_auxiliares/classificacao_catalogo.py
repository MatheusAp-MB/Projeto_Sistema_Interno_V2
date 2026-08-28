# * [RESUMO] → Lógica de classificação e agrupamento de anúncios por SKU,
#              respeitando a hierarquia: Página de Catálogo → Base →
#              Catálogos, e Anúncios Simples separados.
#
#              VOCABULÁRIO PADRONIZADO:
#              - SKU: identifica o Produto (ERP)
#              - MLB: identifica o AnuncioMercadoLivre (agrupador —
#                     status, tipo, catálogo, logística vêm daqui)
#              - Variação: identifica o VariacaoAnuncioMercadoLivre —
#                     a unidade individual real, SEMPRE existe pelo
#                     menos 1 por MLB (mesmo sem variação de cor/tamanho)
#              - Folha: o nó final da árvore = 1 Variação = 1 card na tela.
#                     Um MLB com 20 variações gera 20 folhas/cards.

import json as jsonlib
from collections import defaultdict
from django.db.models import Q
from django.db.models.functions import Coalesce
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre
import math

def parsear_item_relations(valor):
    if isinstance(valor, list):
        return valor
    if isinstance(valor, str):
        try:
            return jsonlib.loads(valor)
        except Exception:
            return []
    return []


def classificar_catalogo(registro):
    """
    Regra de classificação (só 2 campos, sem depender de item_relations):
        catalog_product_id vazio        -> Simples
        catalog_listing = True          -> Catálogo
        catalog_listing = False         -> Base

    item_relations serve só pra descobrir QUEM é par de quem dentro da
    mesma Página de Catálogo — não decide o tipo do anúncio (isso já é
    feito à parte, ver montar_estrutura_de_sku()).

    Único lugar dessa regra no repositório (26/08/2026, ponto 04) — antes
    vivia duplicada em
    core/management/commands/popular_banco_suporte/importar_anuncios_ml.py,
    reimplementada de forma independente com o mesmo resultado.

    `registro` é um dict cru vindo de detalhes_mlbs.json (chaves
    catalog_product_id/catalog_listing) — usado na importação pro banco
    (importar_anuncios_ml.py) e, futuramente, na geração de
    dados_completos_por_sku.json (ponto 05, buscar_dados_sku_completo.py).
    """
    if not registro.get('catalog_product_id'):
        return TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo.SIMPLES
    if registro.get('catalog_listing') is True:
        return TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo.CATALOGO
    return TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo.BASE


def encontrar_fecho_transitivo(sku_alvo, registros):
    """
    Fecho transitivo: parte do SKU e expande por catalog_product_id +
    item_relations até fechar toda a rede de MLBs relacionados, mesmo que
    algum membro tenha SKU divergente ou ausente (ex: MLB de Catálogo sem
    o SELLER_SKU preenchido, mas ligado à Base via item_relations).

    Migrado de classificar_por_sku.py (ponto 05) sem alteração de lógica.
    Não foi reaproveitado o agrupamento por Produto.sku do banco de
    propósito: VariacaoAnuncioMercadoLivre.sku_ml tem bug já documentado
    (variações aparecem com o SKU do pai) e o agrupamento por banco não
    segue item_relations pra achar membro com SKU divergente — só este
    fecho transitivo, sobre o JSON bruto, cobre esse caso.
    """
    registros_idx = {r["mlb"]: r for r in registros}
    relacionados = {r["mlb"] for r in registros if r.get("sku") == sku_alvo}

    if not relacionados:
        return relacionados

    mudou = True
    while mudou:
        mudou = False
        cpids_atuais = {
            registros_idx[mlb].get("catalog_product_id")
            for mlb in relacionados
            if registros_idx[mlb].get("catalog_product_id")
        }

        for r in registros:
            mlb = r["mlb"]
            if mlb in relacionados:
                continue
            if r.get("catalog_product_id") in cpids_atuais:
                relacionados.add(mlb)
                mudou = True
                continue
            relacoes = parsear_item_relations(r.get("item_relations"))
            if any(rel.get("id") in relacionados for rel in relacoes):
                relacionados.add(mlb)
                mudou = True

        for mlb in list(relacionados):
            relacoes = parsear_item_relations(registros_idx[mlb].get("item_relations"))
            for rel in relacoes:
                par = rel.get("id")
                if par and par not in relacionados and par in registros_idx:
                    relacionados.add(par)
                    mudou = True

    return relacionados


def calcular_ponteiro_termometro(score):
    score = max(0, min(100, score or 0))
    angulo_graus = 180 - (score / 100 * 180)
    angulo_rad = math.radians(angulo_graus)
    x = 30 + 22 * math.cos(angulo_rad)
    y = 30 - 22 * math.sin(angulo_rad)
    return f'{x:.1f}', f'{y:.1f}'

CORTE_SCORE_VERMELHO_AMARELO = 33
CORTE_SCORE_AMARELO_VERDE = 66


def calcular_ponto_arco(porcentagem, raio=26, centro_x=30, centro_y=30):
    angulo_graus = 180 - (porcentagem / 100 * 180)
    angulo_rad = math.radians(angulo_graus)
    x = centro_x + raio * math.cos(angulo_rad)
    y = centro_y - raio * math.sin(angulo_rad)
    return f'{x:.1f}', f'{y:.1f}'


def montar_arcos_termometro():
    inicio = calcular_ponto_arco(0)
    corte1 = calcular_ponto_arco(CORTE_SCORE_VERMELHO_AMARELO)
    corte2 = calcular_ponto_arco(CORTE_SCORE_AMARELO_VERDE)
    fim = calcular_ponto_arco(100)

    return {
        'vermelho': f'M {inicio[0]} {inicio[1]} A 26 26 0 0 1 {corte1[0]} {corte1[1]}',
        'amarelo':  f'M {corte1[0]} {corte1[1]} A 26 26 0 0 1 {corte2[0]} {corte2[1]}',
        'verde':    f'M {corte2[0]} {corte2[1]} A 26 26 0 0 1 {fim[0]} {fim[1]}',
    }

def info_variacao(variacao, imagem_url=None, titulo_produto=None):
    from mercado_livre.funcoes_auxiliares.badges import (
        BADGES_STATUS, BADGES_TIPO_ANUNCIO, BADGES_LOGISTICA, badge_de, badge_flex,
    )

    anuncio = variacao.anuncio
    tipo = anuncio.tipo_de_anuncio if anuncio else None

    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo
    eh_catalogo = tipo and tipo.classificacao_catalogo == Classificacao.CATALOGO

    status_competicao = None
    status_competicao_label = None

    if eh_catalogo:
        arcos = None
        score_numerico = None
        ponteiro_x = ponteiro_y = None

        competicao = getattr(anuncio, 'competicao', None) if anuncio else None
        if competicao and competicao.status:
            status_competicao = competicao.status
            status_competicao_label = competicao.get_status_display()
    else:
        arcos = montar_arcos_termometro()
        qualidade = getattr(variacao, 'qualidade', None)
        score_numerico = qualidade.score if qualidade and qualidade.score is not None else 0
        ponteiro_x, ponteiro_y = calcular_ponteiro_termometro(score_numerico)

    # * [EXPLICAÇÃO] → Desconto só existe quando preco_original vier
    #                  preenchido E for maior que o preço atual (a API
    #                  só manda preco_original quando há promoção ativa
    #                  — confirmado com dado real antes de implementar).
    tem_desconto = bool(
        variacao.preco_original and variacao.preco_atual
        and variacao.preco_original > variacao.preco_atual
    )
    desconto_percentual = None
    if tem_desconto:
        desconto_percentual = round(
            (variacao.preco_original - variacao.preco_atual) / variacao.preco_original * 100
        )

    return {
        'mlb': anuncio.mlb if anuncio else None,
        'variacao_id': variacao.variacao_id,
        'id': variacao.id,
        'comportamento_ativo': variacao.comportamento_ativo,
        'sku_ml': variacao.sku_ml,
        'mlbu': variacao.mlbu,
        'titulo': anuncio.titulo_anuncio if anuncio else None,
        'permalink': anuncio.permalink if anuncio else None,
        'thumbnail_url': variacao.thumbnail_url,
        'imagem_principal_url': variacao.imagem_principal_url,
        'imagem_url': imagem_url,
        'titulo_produto': titulo_produto,
        'fotos': anuncio.fotos if anuncio else None,

        'estoque': variacao.estoque,

        'preco_atual': variacao.preco_atual,
        'preco_original': variacao.preco_original,
        'tem_desconto': tem_desconto,
        'desconto_percentual': desconto_percentual,
        'margem_atual_vs_original_pp': variacao.margem_atual_vs_original_pp,

        'score': score_numerico,
        'ponteiro_x': ponteiro_x,
        'ponteiro_y': ponteiro_y,
        'arco_vermelho': arcos['vermelho'] if arcos else None,
        'arco_amarelo': arcos['amarelo'] if arcos else None,
        'arco_verde': arcos['verde'] if arcos else None,
        'eh_catalogo': eh_catalogo,

        # * [EXPLICAÇÃO] → Badges vindas do registro único (badges.py) —
        #                  corrige de brinde o bug em que Logística só
        #                  distinguia FULL/Coleta (as outras 5 modalidades
        #                  caíam erradas como "Coleta").
        'badge_status': badge_de(BADGES_STATUS, tipo.status) if tipo else None,
        'badge_tipo_anuncio': badge_de(BADGES_TIPO_ANUNCIO, tipo.tipo_anuncio) if tipo else None,
        'badge_logistica': badge_de(BADGES_LOGISTICA, tipo.tipo_logistico) if tipo else None,
        'badge_flex': badge_flex(True) if (tipo and tipo.flex) else None,

        'status_competicao': status_competicao,
        'status_competicao_label': status_competicao_label,
    }


def faixa_do_score(score):
    if score is None:
        return None
    if score < CORTE_SCORE_VERMELHO_AMARELO:
        return 'ruim'
    if score < CORTE_SCORE_AMARELO_VERDE:
        return 'medio'
    return 'bom'


def _passa_filtros_compartilhados(tipo, filtros):
    # * [EXPLICAÇÃO] → Critérios que vivem em TipoDeAnuncioMercadoLivre,
    #                  compartilhados por todas as folhas do mesmo MLB.
    if not tipo:
        return not any([
            filtros.get('status'), filtros.get('tipos_anuncio'),
            filtros.get('tipos_logisticos'), filtros.get('catalogos'),
            filtros.get('flex'),
        ])

    if filtros.get('status') and tipo.status not in filtros['status']:
        return False
    if filtros.get('tipos_anuncio') and tipo.tipo_anuncio not in filtros['tipos_anuncio']:
        return False
    if filtros.get('tipos_logisticos') and tipo.tipo_logistico not in filtros['tipos_logisticos']:
        return False
    if filtros.get('catalogos') and tipo.classificacao_catalogo not in filtros['catalogos']:
        return False

    valores_flex = filtros.get('flex') or []
    if len(valores_flex) == 1 and tipo.flex != (valores_flex[0] == 'sim'):
        return False

    return True


def _passa_estoque(variacao, filtros):
    valores_estoque = filtros.get('estoque') or []
    if len(valores_estoque) != 1:
        return True
    tem_estoque = (variacao.estoque or 0) > 0
    return tem_estoque == (valores_estoque[0] == 'com')


def _passa_desconto(variacao, filtros):
    valores_desconto = filtros.get('desconto') or []
    if len(valores_desconto) != 1:
        return True
    tem_desconto = bool(
        variacao.preco_original and variacao.preco_atual
        and variacao.preco_original > variacao.preco_atual
    )
    return tem_desconto == (valores_desconto[0] == 'com')


def _passa_conexao_erp(variacao, filtros):
    valores = filtros.get('conexao_erp') or []
    if len(valores) != 1:
        return True
    tem_conexao = variacao.produto_id is not None
    return tem_conexao == (valores[0] == 'com')


def _passa_categoria_estado(variacao, filtros):
    # * [EXPLICAÇÃO] → Substitui os antigos _passa_promocao_ativa/
    #                  _passa_promocao_candidata (modelo de 2 eixos
    #                  soltos, anterior aos 5 estados unificados).
    #                  categoria_estado já vem calculado em lote em
    #                  RecomendacaoPrecificacao, pro comportamento
    #                  ATIVO daquela variação — filtra sobre o prefetch
    #                  ('recomendacoes'), sem query nova por variação.
    valores = filtros.get('categorias_estado') or []
    if not valores:
        return True
    comportamento_ativo = variacao.comportamento_ativo
    recomendacao = next(
        (r for r in variacao.recomendacoes.all() if r.comportamento == comportamento_ativo),
        None
    )
    categoria = recomendacao.categoria_estado if recomendacao else None
    return categoria in valores


def _passa_comportamento(variacao, filtros):
    valores = filtros.get('comportamentos') or []
    if not valores:
        return True
    return variacao.comportamento_ativo in valores


def _passa_score_direto(variacao, filtros):
    faixas = filtros.get('faixas_score') or []
    if not faixas:
        return True
    qualidade = getattr(variacao, 'qualidade', None)
    score = qualidade.score if qualidade else None
    if score is None:
        return 'sem_dados' in faixas
    return faixa_do_score(score) in faixas


def _passa_competicao_direto(anuncio, filtros):
    valores = filtros.get('situacoes_competicao') or []
    if not valores:
        return True
    competicao = getattr(anuncio, 'competicao', None)
    if not competicao or not competicao.status:
        return False
    return competicao.status in valores


def _mlb_tem_folha_valida(variacoes_mlb, filtros):
    return any(
        _passa_estoque(v, filtros) and _passa_desconto(v, filtros)
        and _passa_conexao_erp(v, filtros) and _passa_categoria_estado(v, filtros)
        and _passa_comportamento(v, filtros)
        and _passa_score_direto(v, filtros)
        for v in variacoes_mlb
    )


def _base_passa_sozinha(tipo, variacoes_mlb, filtros):
    return _passa_filtros_compartilhados(tipo, filtros) and _mlb_tem_folha_valida(variacoes_mlb, filtros)


def _base_passa_score(variacoes_da_base, filtros):
    # * [EXPLICAÇÃO] → Isola só o critério de score da base, pra herança
    #                  do Catálogo (Opção B — Catálogo nunca usa o
    #                  próprio score real).
    faixas = filtros.get('faixas_score') or []
    if not faixas:
        return True
    return any(_passa_score_direto(v, filtros) for v in variacoes_da_base)


def _simples_passa(tipo, variacoes_mlb, filtros):
    if filtros.get('situacoes_competicao'):
        return False  # Simples não tem esse dado — exclusão automática
    return _base_passa_sozinha(tipo, variacoes_mlb, filtros)


def _catalogo_passa(tipo, anuncio, variacoes_mlb, filtros, variacoes_da_base_pareada):
    if not _passa_filtros_compartilhados(tipo, filtros):
        return False
    if not any(_passa_estoque(v, filtros) for v in variacoes_mlb):
        return False
    if not any(_passa_desconto(v, filtros) for v in variacoes_mlb):
        return False
    if not any(_passa_conexao_erp(v, filtros) for v in variacoes_mlb):
        return False
    if not any(_passa_categoria_estado(v, filtros) for v in variacoes_mlb):
        return False
    if not any(_passa_comportamento(v, filtros) for v in variacoes_mlb):
        return False
    if not _passa_competicao_direto(anuncio, filtros):
        return False

    faixas = filtros.get('faixas_score') or []
    if faixas:
        if variacoes_da_base_pareada is None:
            return False  # órfão — sem Base pra herdar o veredito de score
        if not _base_passa_score(variacoes_da_base_pareada, filtros):
            return False

    return True

def carregar_variacoes_por_sku(skus=None):
    # * [EXPLICAÇÃO] → Exclui MLBs "fósseis" de migração antiga de
    #                  variações (regra de negócio fixa, sempre ativa —
    #                  não é filtro opcional, é ruído sem ação possível).
    #                  prefetch_related('promocoes', 'recomendacoes')
    #                  evita N+1 nos filtros (_passa_categoria_estado
    #                  roda por variação, sobre o prefetch).
    qs = VariacaoAnuncioMercadoLivre.objects.select_related(
        'anuncio', 'anuncio__tipo_de_anuncio', 'anuncio__competicao', 'produto', 'qualidade'
    ).prefetch_related('promocoes', 'recomendacoes').exclude(anuncio__eh_fossil_migracao=True)

    if skus is not None:
        # * [EXPLICAÇÃO] → "skus" agora pode conter 3 tipos de chave
        #                  (SKU do Produto, SKU do ML, ou o próprio MLB),
        #                  dependendo de qual delas foi usada como
        #                  fallback pra cada Variação — bate com a mesma
        #                  ordem de prioridade usada no agrupamento abaixo.
        qs = qs.filter(
            Q(produto__sku__in=skus) |
            Q(produto__isnull=True, sku_ml__in=skus) |
            Q(produto__isnull=True, sku_ml__isnull=True, anuncio__mlb__in=skus)
        )

    variacoes_por_sku = defaultdict(list)
    for v in qs:
        # * [EXPLICAÇÃO] → Sem Produto vinculado (ERP não conectado ainda),
        #                  agrupa pelo SKU que o próprio ML mandou; se nem
        #                  isso existir, agrupa pelo MLB (nunca deixa a
        #                  variação "sem lar").
        chave = v.produto.sku if v.produto else (v.sku_ml or v.anuncio.mlb)
        variacoes_por_sku[chave].append(v)

    return variacoes_por_sku

def montar_estrutura_de_sku(sku, variacoes, filtros=None):
    filtros = filtros or {}
    filtro_excecao_ativo = bool(filtros.get('faixas_score')) or bool(filtros.get('situacoes_competicao'))

    if not variacoes:
        return {'sku': sku, 'encontrado': False, 'paginas_catalogo': [], 'anuncios_simples': [], 'total_anuncios': 0}

    produto = variacoes[0].produto
    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

    variacoes_por_mlb = defaultdict(list)
    anuncio_por_mlb = {}
    for v in variacoes:
        anuncio_por_mlb[v.anuncio.mlb] = v.anuncio
        variacoes_por_mlb[v.anuncio.mlb].append(v)

    paginas = {}
    simples_mlbs = []

    for mlb, anuncio in anuncio_por_mlb.items():
        tipo = anuncio.tipo_de_anuncio
        classificacao = tipo.classificacao_catalogo if tipo else None

        if classificacao == Classificacao.SIMPLES or not anuncio.catalog_product_id:
            simples_mlbs.append(mlb)
            continue

        paginas.setdefault(anuncio.catalog_product_id, []).append(mlb)

    def folhas_do_mlb(mlb):
        return [
            info_variacao(
                v,
                imagem_url=produto.imagem_url if produto else None,
                titulo_produto=produto.titulo if produto else None,
            )
            for v in variacoes_por_mlb[mlb]
        ]

    total_visiveis = 0
    paginas_saida = []

    for cpid, mlbs_membros in paginas.items():
        bases_mlbs = [
            m for m in mlbs_membros
            if anuncio_por_mlb[m].tipo_de_anuncio
            and anuncio_por_mlb[m].tipo_de_anuncio.classificacao_catalogo == Classificacao.BASE
        ]
        catalogos_mlbs = [
            m for m in mlbs_membros
            if anuncio_por_mlb[m].tipo_de_anuncio
            and anuncio_por_mlb[m].tipo_de_anuncio.classificacao_catalogo == Classificacao.CATALOGO
        ]

        bases_saida = []
        catalogos_usados = set()

        for base_mlb in bases_mlbs:
            anuncio_base = anuncio_por_mlb[base_mlb]
            tipo_base = anuncio_base.tipo_de_anuncio
            variacoes_base = variacoes_por_mlb[base_mlb]

            relacoes = parsear_item_relations(anuncio_base.item_relations)
            filhos_ids = {r.get('id') for r in relacoes if isinstance(r, dict)}
            filhos_mlbs = [c for c in catalogos_mlbs if c in filhos_ids]
            catalogos_usados.update(filhos_mlbs)

            catalogos_filhos_saida = []
            for c in filhos_mlbs:
                anuncio_c = anuncio_por_mlb[c]
                tipo_c = anuncio_c.tipo_de_anuncio
                variacoes_c = variacoes_por_mlb[c]

                if _catalogo_passa(tipo_c, anuncio_c, variacoes_c, filtros, variacoes_base):
                    catalogos_filhos_saida.append({'mlb': c, 'folhas': folhas_do_mlb(c)})
                    total_visiveis += len(variacoes_c)


            base_passa_sozinha = _base_passa_sozinha(tipo_base, variacoes_base, filtros)

            if catalogos_filhos_saida:
                bases_saida.append({
                    'mlb': base_mlb,
                    'folhas': folhas_do_mlb(base_mlb),
                    'anuncios_catalogo': catalogos_filhos_saida,
                    'sem_catalogo_no_filtro': False,
                })
                total_visiveis += len(variacoes_base)
            elif base_passa_sozinha and not filtro_excecao_ativo:
                # * [EXPLICAÇÃO] → Aviso "nenhum catálogo atende ao filtro"
                #                  só faz sentido pros filtros gerais.
                #                  Quando Score ou Competição estão ativos,
                #                  essas regras vencem e a Base vazia
                #                  desaparece direto, sem aviso.
                bases_saida.append({
                    'mlb': base_mlb,
                    'folhas': folhas_do_mlb(base_mlb),
                    'anuncios_catalogo': [],
                    'sem_catalogo_no_filtro': True,
                })
                total_visiveis += len(variacoes_base)
            # * [EXPLICAÇÃO] → Nem base sozinha (ou filtro de exceção ativo),
            #                  nem catálogo algum passou: o grupo inteiro
            #                  some, nada a adicionar.

        orfaos_mlbs = [c for c in catalogos_mlbs if c not in catalogos_usados]
        orfaos_saida = []
        for o in orfaos_mlbs:
            anuncio_o = anuncio_por_mlb[o]
            tipo_o = anuncio_o.tipo_de_anuncio
            variacoes_o = variacoes_por_mlb[o]

            if _catalogo_passa(tipo_o, anuncio_o, variacoes_o, filtros, variacoes_da_base_pareada=None):
                orfaos_saida.append({'mlb': o, 'folhas': folhas_do_mlb(o)})
                total_visiveis += len(variacoes_o)

        if bases_saida or orfaos_saida:
            paginas_saida.append({
                'catalog_product_id': cpid,
                'anuncios_base': bases_saida,
                'anuncios_catalogo_orfaos': orfaos_saida,
            })

    simples_saida = []
    for m in simples_mlbs:
        anuncio_s = anuncio_por_mlb[m]
        tipo_s = anuncio_s.tipo_de_anuncio
        variacoes_s = variacoes_por_mlb[m]

        if _simples_passa(tipo_s, variacoes_s, filtros):
            simples_saida.append({'mlb': m, 'folhas': folhas_do_mlb(m)})
            total_visiveis += len(variacoes_s)

    return {
        'sku': sku,
        'encontrado': True,
        'marca': produto.marca if produto else None,
        'titulo_produto': produto.titulo if produto else None,
        'imagem_url': produto.imagem_url if produto else None,
        'sem_conexao_erp': produto is None,
        'total_anuncios': total_visiveis,
        'paginas_catalogo': paginas_saida,
        'anuncios_simples': simples_saida,
    }

def classificar_todos_os_skus(filtros=None):
    variacoes_por_sku = carregar_variacoes_por_sku()
    return {
        sku: montar_estrutura_de_sku(sku, variacoes, filtros=filtros)
        for sku, variacoes in variacoes_por_sku.items()
    }


def listar_skus_filtrados(busca=None, filtros=None):
    filtros = filtros or {}

    qs = VariacaoAnuncioMercadoLivre.objects.exclude(
        anuncio__eh_fossil_migracao=True
    ).annotate(
        chave_sku=Coalesce('produto__sku', 'sku_ml', 'anuncio__mlb')
    )

    if busca:
        termos = busca.split()
        for termo in termos:
            qs = qs.filter(
                Q(produto__sku__icontains=termo) |
                Q(produto__marca__icontains=termo) |
                Q(produto__titulo__icontains=termo) |
                Q(produto__ean__icontains=termo) |
                Q(anuncio__mlb__icontains=termo) |
                Q(anuncio__titulo_anuncio__icontains=termo)
            )

    if filtros.get('marcas'):
        qs = qs.filter(produto__marca__in=filtros['marcas'])

    chaves_avancadas = [
        'status', 'tipos_anuncio', 'tipos_logisticos', 'catalogos',
        'flex', 'estoque', 'desconto', 'conexao_erp',
        'categorias_estado', 'comportamentos',
        'faixas_score', 'situacoes_competicao',
    ]

    tem_filtro_avancado = any(filtros.get(chave) for chave in chaves_avancadas)

    if not tem_filtro_avancado:
        # * [EXPLICAÇÃO] → Caminho rápido: sem filtro de folha ativo, não
        #                  precisa montar a árvore completa. Total de
        #                  anúncios aqui é só contar MLBs distintos.
        qs_final = qs
        skus = list(
            qs_final.values_list('chave_sku', flat=True)
            .distinct()
            .order_by('chave_sku')
        )
        total_anuncios = qs_final.values('anuncio_id').distinct().count()
        return skus, total_anuncios

    # * [EXPLICAÇÃO] → Caminho completo: precisa montar a árvore de cada
    #                  SKU candidato pra saber se sobrevive à cascata
    #                  Base↔Catálogo — evita o contador de SKUs divergir
    #                  do que aparece de fato na tela. Aproveita esse
    #                  mesmo cálculo pra somar o total real de anúncios.
    skus_candidatos = list(
        qs.values_list('chave_sku', flat=True)
        .distinct()
    )
    variacoes_por_sku = carregar_variacoes_por_sku(skus=skus_candidatos)

    skus_finais = []
    total_anuncios = 0
    for sku, variacoes in variacoes_por_sku.items():
        estrutura = montar_estrutura_de_sku(sku, variacoes, filtros=filtros)
        if estrutura['total_anuncios'] > 0:
            skus_finais.append(sku)
            total_anuncios += estrutura['total_anuncios']

    skus_finais.sort()
    return skus_finais, total_anuncios


def classificar_lote_de_skus(skus, filtros=None):
    variacoes_por_sku = carregar_variacoes_por_sku(skus=skus)
    return {
        sku: montar_estrutura_de_sku(sku, variacoes, filtros=filtros)
        for sku, variacoes in variacoes_por_sku.items()
    }