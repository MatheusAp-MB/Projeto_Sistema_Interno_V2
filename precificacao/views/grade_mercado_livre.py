# precificacao/views/grade_mercado_livre.py

from django.core.exceptions import ObjectDoesNotExist
from dataclasses import dataclass, field
from decimal import Decimal
from django.shortcuts import render
from precificacao.views.comum import (
    MARGENS_POR_CHAVE, _labels_do_tipo, FiltroPrecoExibido,
    LinhaMargemExibida, _opcoes_filtro_produto, _filtrar_paginar_produtos_grade,
)
from precificacao.views.modal_comum import (
    PassoFaixaFrete, PassoPrecoExato, ContraprovaVisao1,
    montar_tabela_percentuais, montar_valores_soltos, montar_tabela_itens_agrupada,
    montar_dimensao, montar_passos_1_a_6, montar_saida, montar_alertas,
    montar_visao_2_teardown,
)
from impostos.funcoes_auxiliares.entrada.badges_fiscais_produto import montar_badges_fiscais_produto

# * [EXPLICAÇÃO] → GradePrecificacaoML.tipo_anuncio usa 'classico'/
#                  'premium' (valores próprios, simples). URLs e os
#                  cards de fallback usam o código REAL do ML
#                  (TipoDeAnuncioMercadoLivre.TipoAnuncio =
#                  'gold_special'/'gold_pro'). Os 2 sentidos de
#                  tradução moram aqui, únicos, reaproveitados pelo
#                  card de MLB e pelo modal de detalhe.
TIPO_GRADE_PARA_ML = {'classico': 'gold_special', 'premium': 'gold_pro'}
TIPO_ML_PARA_GRADE = {v: k for k, v in TIPO_GRADE_PARA_ML.items()}

# * [EXPLICAÇÃO] → Traduz "prefixo de querystring" → (tipo_anuncio,
#                  margem) da GradePrecificacaoML (formato longo).
FAIXAS_PRECO_GRADE = {
    'classico_competicao': ('classico', 'competicao'),
    'classico_minima':     ('classico', 'minima'),
    'classico_padrao':     ('classico', 'padrao'),
    'classico_maxima':     ('classico', 'maxima'),
    'premium_competicao':  ('premium', 'competicao'),
    'premium_minima':      ('premium', 'minima'),
    'premium_padrao':      ('premium', 'padrao'),
    'premium_maxima':      ('premium', 'maxima'),
}


# Função Objetivo: Aplica 1 faixa de preço (tipo+margem) do ML — usada por _filtrar_paginar_produtos_grade.
def _aplicar_filtro_preco_ml(produtos_qs, dados_extra, minimo, maximo):
    tipo_valor_grade, margem_valor_grade = dados_extra
    condicoes = {
        'grade_precificacao_ml__variacao__isnull': True,
        'grade_precificacao_ml__tipo_anuncio': tipo_valor_grade,
        'grade_precificacao_ml__margem': margem_valor_grade,
    }
    if minimo:
        condicoes['grade_precificacao_ml__preco__gte'] = minimo
    if maximo:
        condicoes['grade_precificacao_ml__preco__lte'] = maximo
    return produtos_qs.filter(**condicoes)


# Função Objetivo: Representa 1 MLB real publicado, com suas 4 margens.
@dataclass
class CardMLB:
    mlb: str
    variacao_id: int
    prefixo: str
    tipo_valor: str
    badge: object
    origem_dimensao: str
    origem_dimensao_label: str
    eh_catalogo: bool
    titulo_anuncio: str
    imagem_url: str
    sku_ml: str
    sku_produto: str
    linhas: list = field(default_factory=list)

    # Função Objetivo: Monta 1 card a partir de 1 grupo de linhas (1 variação × 1 tipo).
    @classmethod
    def montar(cls, real_entry, produto, badge_classico, badge_premium, labels_classico, labels_premium, classificacao_catalogo):
        linhas_por_margem = real_entry['linhas_por_margem']
        tipo_grade = real_entry['tipo_anuncio']
        alguma_linha = next(iter(linhas_por_margem.values()))
        variacao = alguma_linha.variacao
        anuncio = variacao.anuncio
        eh_classico = tipo_grade == 'classico'
        labels = labels_classico if eh_classico else labels_premium
        tipo_de_anuncio = anuncio.tipo_de_anuncio

        return cls(
            mlb=anuncio.mlb,
            variacao_id=real_entry['variacao_id'],
            prefixo=tipo_grade,
            tipo_valor=TIPO_GRADE_PARA_ML[tipo_grade],
            badge=badge_classico if eh_classico else badge_premium,
            origem_dimensao=alguma_linha.origem_dimensao,
            origem_dimensao_label='Declarada no ML' if alguma_linha.origem_dimensao == 'variacao_ml' else 'Embalagem ERP',
            eh_catalogo=bool(tipo_de_anuncio and tipo_de_anuncio.classificacao_catalogo == classificacao_catalogo),
            titulo_anuncio=anuncio.titulo_anuncio or produto.titulo,
            imagem_url=variacao.imagem_principal_url or variacao.thumbnail_url or produto.imagem_url,
            sku_ml=variacao.sku_ml,
            sku_produto=produto.sku,
            linhas=LinhaMargemExibida.montar_bloco(linhas_por_margem, labels),
        )


# Função Objetivo: Representa 1 produto na árvore da Grade — fallback + MLBs reais.
@dataclass
class ItemGradeProduto:
    produto: object
    linhas_classico: list
    linhas_premium: list
    cards_simples_base: list
    cards_catalogo: list
    total_mlbs: int
    # * [EXPLICAÇÃO] → Badges fiscais explícitas (21/09/2026) — PIS/COFINS
    #                  saída (reduzido/integral) + ICMS entrada (integral/
    #                  reduzido/ST). Mesma classificação usada na tela de
    #                  Produto (aba Impostos) — badges_fiscais_produto.py.
    badges_fiscais: object

    # Função Objetivo: Monta 1 item completo a partir do produto e das linhas já agrupadas.
    @classmethod
    def montar(cls, produto, agrupador, badge_classico, badge_premium, labels_classico, labels_premium, classificacao_catalogo):
        fallback_classico = agrupador.fallback_de(produto.id, 'classico')
        fallback_premium = agrupador.fallback_de(produto.id, 'premium')
        reais = agrupador.reais_de(produto.id)

        cards_simples_base = []
        cards_catalogo = []
        for real_entry in reais:
            card = CardMLB.montar(
                real_entry, produto, badge_classico, badge_premium, labels_classico, labels_premium, classificacao_catalogo
            )
            if card.eh_catalogo:
                cards_catalogo.append(card)
            else:
                cards_simples_base.append(card)

        ORDEM_TIPO = {'classico': 0, 'premium': 1}
        cards_simples_base.sort(key=lambda c: ORDEM_TIPO.get(c.prefixo, 2))
        cards_catalogo.sort(key=lambda c: ORDEM_TIPO.get(c.prefixo, 2))

        # * [EXPLICAÇÃO] → Badges fiscais (21/09/2026) — impostos_entrada já
        #                  vem select_related por view_grade_precificacao_ml
        #                  (impostos_entrada + pis/cofins/icms/icms_st),
        #                  então este acesso não gera consulta extra.
        try:
            impostos_entrada_raw = produto.impostos_entrada
        except ObjectDoesNotExist:
            impostos_entrada_raw = None
        badges_fiscais = montar_badges_fiscais_produto(impostos_entrada_raw)

        return cls(
            produto=produto,
            linhas_classico=LinhaMargemExibida.montar_bloco(fallback_classico, labels_classico),
            linhas_premium=LinhaMargemExibida.montar_bloco(fallback_premium, labels_premium),
            cards_simples_base=cards_simples_base,
            cards_catalogo=cards_catalogo,
            total_mlbs=len(reais),
            badges_fiscais=badges_fiscais,
        )


# Função Objetivo: Agrupa as linhas soltas de GradePrecificacaoML (formato longo) em memória.
class AgrupadorLinhasGrade:

    def __init__(self, linhas):
        self._fallback = {}
        self._reais = {}

        grupos_por_chave = {}
        for linha in linhas:
            chave = (linha.produto_id, linha.variacao_id, linha.tipo_anuncio)
            grupos_por_chave.setdefault(chave, {})[linha.margem] = linha

        for (produto_id, variacao_id, tipo_anuncio), linhas_por_margem in grupos_por_chave.items():
            if variacao_id is None:
                self._fallback[(produto_id, tipo_anuncio)] = linhas_por_margem
            else:
                self._reais.setdefault(produto_id, []).append({
                    'variacao_id': variacao_id,
                    'tipo_anuncio': tipo_anuncio,
                    'linhas_por_margem': linhas_por_margem,
                })

    def fallback_de(self, produto_id, tipo_anuncio):
        return self._fallback.get((produto_id, tipo_anuncio), {})

    def reais_de(self, produto_id):
        return self._reais.get(produto_id, [])


# Função Objetivo: Representa tudo que a tela da Grade precisa pra se desenhar.
@dataclass
class ContextoGradePrecificacao:
    pagina: object
    busca: str
    por_pagina: int
    querystring_sem_pagina: str
    produtos_com_grade: list
    badge_classico: object
    badge_premium: object
    tipo_classico: str
    tipo_premium: str
    marcas_disponiveis: object
    categorias_disponiveis: object
    curvas_disponiveis: object
    filtros_selecionados: dict
    get_params: object
    filtros_preco_classico: list
    filtros_preco_premium: list


# Função Objetivo: Exibe a árvore de precificação por produto (fallback + MLBs reais).
def view_grade_precificacao_ml(request):
    from precificacao.models import GradePrecificacaoML
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre
    from mercado_livre.funcoes_auxiliares.badges import BADGES_TIPO_ANUNCIO, badge_de

    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

    filtros, pagina, querystring_sem_pagina = _filtrar_paginar_produtos_grade(
        request, 'grade_precificacao_ml', FAIXAS_PRECO_GRADE, _aplicar_filtro_preco_ml
    )

    # * [EXPLICAÇÃO] → select_related isolado, só pra esta view (ML) — pras
    #                  badges fiscais (21/09/2026). Aplicado depois da
    #                  paginação, direto no object_list já fatiado
    #                  (select_related não conflita com slice, só filter/
    #                  exclude/order_by conflitariam) — nunca em
    #                  _filtrar_paginar_produtos_grade, que é compartilhada
    #                  com os outros 5 marketplaces.
    pagina.object_list = pagina.object_list.select_related(
        'impostos_entrada', 'impostos_entrada__pis', 'impostos_entrada__cofins',
        'impostos_entrada__icms', 'impostos_entrada__icms_st',
    )

    produtos_ids = [p.id for p in pagina.object_list]
    linhas = GradePrecificacaoML.objects.filter(
        produto_id__in=produtos_ids
    ).select_related('variacao__anuncio__tipo_de_anuncio')

    agrupador = AgrupadorLinhasGrade(linhas)

    configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}
    labels_classico = _labels_do_tipo(configs, TipoAnuncio.CLASSICO)
    labels_premium = _labels_do_tipo(configs, TipoAnuncio.PREMIUM)

    badge_classico = badge_de(BADGES_TIPO_ANUNCIO, TipoAnuncio.CLASSICO)
    badge_premium = badge_de(BADGES_TIPO_ANUNCIO, TipoAnuncio.PREMIUM)

    produtos_com_grade = [
        ItemGradeProduto.montar(
            produto, agrupador, badge_classico, badge_premium,
            labels_classico, labels_premium, Classificacao.CATALOGO,
        )
        for produto in pagina.object_list
    ]

    contexto = ContextoGradePrecificacao(
        pagina=pagina,
        busca=filtros.busca,
        por_pagina=filtros.por_pagina,
        querystring_sem_pagina=querystring_sem_pagina,
        produtos_com_grade=produtos_com_grade,
        badge_classico=badge_classico,
        badge_premium=badge_premium,
        tipo_classico=TipoAnuncio.CLASSICO,
        tipo_premium=TipoAnuncio.PREMIUM,
        filtros_selecionados={
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        get_params=request.GET,
        filtros_preco_classico=FiltroPrecoExibido.montar_bloco(request, 'classico'),
        filtros_preco_premium=FiltroPrecoExibido.montar_bloco(request, 'premium'),
        **_opcoes_filtro_produto(),
    )

    return render(request, 'precificacao/estrutura_grade_precificacao_ml.html', vars(contexto))


# Função Objetivo: Contraprova da Visão 1 (14/09, corrigida 14/09) — chama calcular_margem() de
# verdade (mercado_livre/funcoes_auxiliares/calculo_margem.py), implementação SEPARADA e
# independente (já usada no Hub de Promoções), com o preço final já persistido. ÚNICA exceção
# ao "nunca recalcula ao vivo" desta tela — é só pra exibir a prova visual, nunca grava nem
# substitui o valor oficial da grade. Explicação em detalhe: taxa/FIXO/frete usados aqui são
# recalculados por DENTRO dessa função, não são os mesmos objetos da Visão 1 — por isso o
# template não tenta substituir número por número, só compara o resultado final.
#
# Correção 14/09/2026: passa `variacao` pra calcular_margem — sem isso, a dimensão usada aqui
# era sempre a do Produto ERP, mesmo quando o preço oficial foi calculado com a dimensão
# declarada no anúncio do ML (resolver_dimensoes_efetivas). Causava divergência real (não só
# arredondamento) pra qualquer produto com dimensão do ML diferente do ERP. Também calcula
# `bate`/`diferenca_valor` comparando contra `margem_valor_oficial` — antes o template mostrava
# "✓ Bate" fixo, sem checar nada de verdade.
def _montar_contraprova_visao_1(produto, preco_final, tipo_anuncio_grade, variacao, margem_valor_oficial):
    from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_margem
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre

    if not preco_final:
        return ContraprovaVisao1(disponivel=False, motivo_indisponivel='Sem preço final calculado.')

    tipo_ml = TIPO_GRADE_PARA_ML.get(tipo_anuncio_grade)
    config_tipo = ConfiguracaoTipoAnuncioMercadoLivre.objects.filter(tipo_anuncio=tipo_ml).first() if tipo_ml else None
    if not config_tipo:
        return ContraprovaVisao1(disponivel=False, motivo_indisponivel='Configuração do tipo de anúncio não encontrada.')

    resultado = calcular_margem(produto, preco_final, config_tipo=config_tipo, variacao=variacao)
    if not resultado:
        return ContraprovaVisao1(disponivel=False, motivo_indisponivel='Produto sem dados fiscais de entrada sincronizados, sem faixa de frete pra esse preço, ou sem dimensão/peso suficientes pra resolver a embalagem efetiva.')

    # * [EXPLICAÇÃO] → Tolerância de R$ 0,05: absorve ruído legítimo de
    #                  arredondamento entre 2 cadeias de conta Decimal
    #                  independentes — nunca pra esconder uma divergência real.
    diferenca_valor = None
    bate = False
    if margem_valor_oficial is not None:
        diferenca_valor = abs(resultado['margem_valor'] - margem_valor_oficial)
        bate = diferenca_valor <= Decimal('0.05')

    return ContraprovaVisao1(
        disponivel=True,
        margem_valor=resultado['margem_valor'],
        margem_percentual=resultado['margem_percentual'],
        bate=bate,
        diferenca_valor=diferenca_valor,
    )


# Função Objetivo: Representa tudo que o modal de auditoria precisa pra se desenhar.
@dataclass
class DetalheFormulaExibida:
    tipo_label: str
    margem_label: str
    sku: str
    ean: str
    custo: object
    custo_com_boni: object
    margem_alvo_percentual: object
    margem_obtida_percentual: object
    # * [EXPLICAÇÃO] → preço final e margem final EM R$ — direto, sem
    #                  precisar procurar dentro de `saida` por label.
    #                  Usados pela Fórmula completa (11/09).
    preco_final: object
    margem_valor: object
    tabela_percentuais: list
    valores_soltos: list
    # * [EXPLICAÇÃO] → tabela única agrupada (Item | Como foi obtido |
    #                  R$ | %) pro topo do modal — pedido explícito de
    #                  auditoria (11/09), não substitui tabela_percentuais/
    #                  valores_soltos acima (mantidos como estavam).
    tabela_itens: list
    dimensao: object
    passo_1: object
    passo_2: object
    passo_3: object
    passo_4: object
    passo_5: object
    passo_6: object
    passo_7: object
    passo_8: object
    saida: list
    alertas: list
    # * [EXPLICAÇÃO] → Visão 2 (14/09) — desmontagem do preço final até sobrar o lucro,
    #                  item a item (mesmos dados dos passos 1-8, sem recalcular nada).
    visao_2: list
    # * [EXPLICAÇÃO] → Contraprova da Visão 1 (14/09) — ÚNICA chamada ao vivo desta tela
    #                  (calcular_margem, implementação independente). Só pra exibir a
    #                  prova, nunca substitui nem grava o valor oficial da grade.
    contraprova_1: object
    # * [EXPLICAÇÃO] → Comissão Real (por MLB, seção 8 do checkpoint) e Comissão Média
    #                  do Produto (seção 9) — 25/09. Mesmo padrão do frete_real: só
    #                  comparação/referência no modal, nunca entra no cálculo (Passo 5
    #                  continua usando a Comissão Aproximada/config). None quando a
    #                  comissão real ainda não foi buscada pra esse MLB.
    comissao_real_percentual: object = None
    comissao_real_atualizado_em: object = None
    comissao_media_produto_percentual: object = None
    comissao_media_produto_amostra: object = None

    # Função Objetivo: Lê o detalhamento já persistido e monta a exibição completa.
    # Explicação em detalhe: NUNCA recalcula nada ao vivo — só lê o que já foi persistido.
    @classmethod
    def montar(cls, linha, tipo_label, margem_label):
        det = linha.detalhamento or {}
        e = det.get('entrada', {})
        i = det.get('intermediarios', {})
        s = det.get('saida', {})

        def dec(valor):
            return Decimal(str(valor)) if valor is not None else None

        origem_label = 'Declarada no ML' if e.get('origem_dimensao') == 'variacao_ml' else 'Embalagem ERP'

        passo_1, passo_2, passo_3, passo_4, passo_5, passo_6 = montar_passos_1_a_6(e, i, dec)

        # * [EXPLICAÇÃO] → passo_7/8 ficam FORA do helper compartilhado —
        #                  faixa_min/max aqui é limite de PREÇO (o ML
        #                  busca faixa por peso×preço), e existe rebate,
        #                  os 2 pontos que genuinamente divergem do Magalu.
        # * [EXPLICAÇÃO] → frete_real/dimensoes_ml/peso_billable (22/09) — lidos
        #                  direto da Variação (só existe quando o produto já tem
        #                  MLB publicado; fallback do produto fica sempre None,
        #                  igual origem_dimensao). dimensoes_ml usa as mesmas
        #                  dimensões DECLARADAS no anúncio que alimentam o cálculo
        #                  do frete real (não é a embalagem ERP, essa é a de baixo,
        #                  no bloco Tabela). peso_billable só vem depois que
        #                  buscar_frete_real_ml salvar frete_real_detalhamento —
        #                  fica None pra quem foi buscado antes desse campo existir.
        variacao = linha.variacao
        dimensoes_ml = None
        if variacao and variacao.altura_declarada_cm and variacao.largura_declarada_cm and variacao.comprimento_declarado_cm:
            dimensoes_ml = (
                f'{variacao.altura_declarada_cm:.0f} × {variacao.largura_declarada_cm:.0f} × '
                f'{variacao.comprimento_declarado_cm:.0f} cm'
            )
        frete_real_detalhe = (variacao.frete_real_detalhamento or {}) if variacao else {}

        # * [EXPLICAÇÃO] → billable_weight/1000 (22/09) — a API do ML devolve esse
        #                  campo em GRAMAS (confirmado na doc oficial: "peso em
        #                  gramas inteiros"), mas o Passo 7 exibe em kg (mesma
        #                  unidade do peso calculado, pra comparação fazer
        #                  sentido lado a lado). Achado revisando o print real:
        #                  peso_billable aparecia como "8802,000 kg" (8,8
        #                  toneladas, fisicamente impossível pra a embalagem)
        #                  quando devia ser 8,802 kg. frete_real_detalhamento
        #                  continua guardando o valor cru da API, sem conversão
        #                  — a conversão é só na hora de exibir.
        peso_billable_gramas = frete_real_detalhe.get('billable_weight')
        peso_billable_kg = (
            dec(peso_billable_gramas) / Decimal('1000') if peso_billable_gramas is not None else None
        )

        passo_7 = PassoFaixaFrete(
            peso=dec(e.get('peso')), faixa_min=dec(i.get('faixa_frete_preco_min')),
            faixa_max=dec(i.get('faixa_frete_preco_max')), resultado=dec(s.get('frete_usado')),
            frete_real=dec(variacao.frete_real) if variacao else None,
            dimensoes_ml=dimensoes_ml,
            peso_billable=peso_billable_kg,
        )
        passo_8 = PassoPrecoExato(
            frete=dec(s.get('frete_usado')), fixo=dec(i.get('fixo')), rebate=dec(i.get('rebate_valor')),
            denominador=dec(i.get('denominador')), resultado=dec(i.get('preco_exato_antes_arredondar')),
        )

        # * [EXPLICAÇÃO] → Comissão Real por MLB — mesma fonte que alimenta o
        #                  frete_real acima (Variação). Comissão Média do Produto
        #                  vem de Produto.obter_dados_comissao() (já existia, nunca
        #                  tinha sido chamado em lugar nenhum) — escolhe Clássico ou
        #                  Premium de acordo com o tipo_label desta linha auditada.
        comissao_real_percentual = dec(variacao.comissao_real_percentual) if variacao else None
        comissao_real_atualizado_em = variacao.comissao_real_atualizado_em if variacao else None

        dados_comissao_produto = linha.produto.obter_dados_comissao()
        if tipo_label == 'Clássico':
            comissao_media_produto_percentual = dados_comissao_produto.comissao_media_classico
            comissao_media_produto_amostra = dados_comissao_produto.comissao_media_classico_amostra
        else:
            comissao_media_produto_percentual = dados_comissao_produto.comissao_media_premium
            comissao_media_produto_amostra = dados_comissao_produto.comissao_media_premium_amostra

        custo = dec(e.get('custo'))
        custo_com_boni = dec(e.get('custo_com_boni'))
        margem_alvo = dec(e.get('margem_alvo_percentual'))
        margem_obtida = dec(s.get('margem_percentual_obtida'))
        dimensao = montar_dimensao(e, dec, origem_label)

        preco_final = dec(s.get('preco_final'))
        margem_valor = dec(s.get('margem_valor'))

        visao_2 = montar_visao_2_teardown(
            passo_1, passo_2, passo_3, passo_4, passo_5, passo_8,
            preco_final, margem_valor, margem_obtida, dec,
        )
        contraprova_1 = _montar_contraprova_visao_1(
            linha.produto, preco_final, linha.tipo_anuncio, linha.variacao, margem_valor,
        )

        return cls(
            tipo_label=tipo_label,
            margem_label=margem_label,
            sku=e.get('sku'),
            ean=e.get('ean'),
            custo=custo,
            custo_com_boni=custo_com_boni,
            margem_alvo_percentual=margem_alvo,
            margem_obtida_percentual=margem_obtida,
            preco_final=preco_final,
            margem_valor=margem_valor,
            tabela_percentuais=montar_tabela_percentuais(e, i, dec),
            valores_soltos=montar_valores_soltos(e, dec),
            tabela_itens=montar_tabela_itens_agrupada(e, i, s, dec),
            dimensao=dimensao,
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=montar_saida(i, s, dec),
            alertas=montar_alertas(
                fixo=dec(i.get('fixo')), custo=custo, custo_com_boni=custo_com_boni,
                altura=dimensao.altura, largura=dimensao.largura, comprimento=dimensao.comprimento,
                margem_alvo=margem_alvo, margem_obtida=margem_obtida,
            ),
            visao_2=visao_2,
            contraprova_1=contraprova_1,
            comissao_real_percentual=comissao_real_percentual,
            comissao_real_atualizado_em=comissao_real_atualizado_em,
            comissao_media_produto_percentual=comissao_media_produto_percentual,
            comissao_media_produto_amostra=comissao_media_produto_amostra,
        )


# Função Objetivo: Exibe o modal "como chegamos nesse preço" pra 1 margem específica.
def view_grade_detalhe(request, produto_id, tipo, margem):
    from precificacao.models import GradePrecificacaoML

    variacao_id = request.GET.get('variacao') or None
    tipo_grade = TIPO_ML_PARA_GRADE.get(tipo)

    linha = None
    if tipo_grade and margem in MARGENS_POR_CHAVE:
        linha = GradePrecificacaoML.objects.filter(
            produto_id=produto_id, variacao_id=variacao_id,
            tipo_anuncio=tipo_grade, margem=margem,
        ).select_related('produto', 'variacao__anuncio').first()

    if not linha or not linha.detalhamento:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
            'sem_detalhamento': True,
        })

    tipo_label = 'Clássico' if tipo_grade == 'classico' else 'Premium'
    margem_label = MARGENS_POR_CHAVE[margem].label_base

    if linha.variacao_id:
        mlb = linha.variacao.anuncio.mlb
        titulo_anuncio = linha.variacao.anuncio.titulo_anuncio or linha.produto.titulo
    else:
        mlb = None
        titulo_anuncio = linha.produto.titulo

    det = DetalheFormulaExibida.montar(linha, tipo_label, margem_label)

    return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
        'det': det,
        'mlb': mlb,
        'titulo_anuncio': titulo_anuncio,
        'produto_id': produto_id,
        'tipo': tipo,
        'margem': margem,
        'variacao_id': variacao_id or '',
    })


# Função Objetivo: Página standalone de exportação/impressão da auditoria — mesmos
# dados do modal (mesmo DetalheFormulaExibida.montar), mas com "Todos os itens" e as
# 2 Visões sempre expandidas, sem abas, sem nenhuma interação por JS. Quem usa aperta
# Ctrl+P (ou o botão "Imprimir / Salvar como PDF" da própria página) e usa a tela de
# impressão do navegador — mesmo padrão já validado no relatório de Devolução
# (ver imprimir_relatorio_devolucao, no projeto Sistema de Relatório de Devoluções).
def view_imprimir_grade_detalhe(request, produto_id, tipo, margem):
    from precificacao.models import GradePrecificacaoML

    variacao_id = request.GET.get('variacao') or None
    tipo_grade = TIPO_ML_PARA_GRADE.get(tipo)

    linha = None
    if tipo_grade and margem in MARGENS_POR_CHAVE:
        linha = GradePrecificacaoML.objects.filter(
            produto_id=produto_id, variacao_id=variacao_id,
            tipo_anuncio=tipo_grade, margem=margem,
        ).select_related('produto', 'variacao__anuncio').first()

    if not linha or not linha.detalhamento:
        return render(request, 'precificacao/grade_detalhe_impressao.html', {
            'sem_detalhamento': True,
        })

    tipo_label = 'Clássico' if tipo_grade == 'classico' else 'Premium'
    margem_label = MARGENS_POR_CHAVE[margem].label_base

    if linha.variacao_id:
        mlb = linha.variacao.anuncio.mlb
        titulo_anuncio = linha.variacao.anuncio.titulo_anuncio or linha.produto.titulo
    else:
        mlb = None
        titulo_anuncio = linha.produto.titulo

    det = DetalheFormulaExibida.montar(linha, tipo_label, margem_label)

    return render(request, 'precificacao/grade_detalhe_impressao.html', {
        'det': det,
        'mlb': mlb,
        'titulo_anuncio': titulo_anuncio,
    })


# Função Objetivo: Monta a subquery que busca 1 campo de 1 marketplace/margem, por produto.
def subquery_grade_campo(tipo, campo, margem_geral):
    from django.db.models import Subquery, OuterRef, DecimalField
    from precificacao.models import GradePrecificacaoML

    return Subquery(
        GradePrecificacaoML.objects.filter(
            produto=OuterRef('pk'), variacao__isnull=True,
            tipo_anuncio=tipo, margem=margem_geral,
        ).values(campo)[:1],
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )