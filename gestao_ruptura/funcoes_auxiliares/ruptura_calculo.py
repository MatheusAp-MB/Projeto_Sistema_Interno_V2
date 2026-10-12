# gestao_ruptura/funcoes_auxiliares/ruptura_calculo.py
#
# Função Objetivo: As CONTAS da tela "Previsão de Ruptura de estoque" (prova de conceito, 12/10/2026): ritmo de vendas, quantos dias o estoque dura, a data da ruptura, a data
# limite do envio, o ponto de pedido, o nível do estoque e a comparação entre o ritmo recente e o do período. Só matemática: aqui NÃO há banco, API nem tela
# (quem junta tudo é ruptura_pagina.py), por isso cada regra mora num lugar só e dá para entender e mudar sem mexer em mais nada.
#
# REGRAS DO MATHEUS que moram aqui:
#   - O ritmo é o MESMO da tela de Vendas: unidades dos dias COMPLETOS ÷ número de dias completos. Hoje (dia parcial) e dia que nunca foi coletado ficam de fora
#     ("ausente não é zero"); venda cancelada não conta (isso já vem resolvido de vendas_ml.unidades_por_dia).
#   - Dias de estoque = estoque ÷ ritmo. A ruptura cai no dia (hoje + dias de estoque, arredondado para baixo).
#   - ÚLTIMO dia possível do envio = data da ruptura − lead time (o lead time é o tempo até o produto ficar disponível para venda). Mas a data RECOMENDADA ("Enviar até") tem uma MARGEM DE
#     SEGURANÇA (decisão do Matheus, 12/10/2026): a remessa deve CHEGAR com pelo menos `folga` dias de estoque sobrando. A margem é uma % do lead time (padrão 100%: lead de 15 dias →
#     a ruptura precisa estar a 30 dias do envio) e é editável na tela. Enviar até = ruptura − lead time − folga.
#   - Ponto de pedido = ritmo × (lead time + folga) (em unidades): com menos estoque que isso, já não dá tempo de enviar COM a margem de segurança.
#   - Sugestão do SISTEMA de quanto enviar: a quantidade que, na chegada da remessa, deixa `folga` dias de margem + `cobre` dias de cobertura da própria remessa.
#   - URGÊNCIA DE ENVIO (decisão do Matheus, 12/10/2026: "referência de urgência: Mercado Livre ou Sistema"): o Sistema fala a MESMA língua do Mercado Livre (Urgente, Esta semana, Próxima semana, Em 2
#     semanas, Sem urgência) para as duas poderem ser comparadas e para o filtro "Divergem" existir. A urgência do Sistema sai da DATA de enviar até: já passou ou é hoje = Urgente; em até 7 dias = Esta semana;
#     até 14 = Próxima semana; até 21 = Em 2 semanas; depois disso (ou sem ruptura prevista) = Sem urgência. As faixas são provisórias (mudam em FAIXAS_DA_URGENCIA_EM_DIAS).
#
# * [EXPLICAÇÃO] → Os 4 NÍVEIS do estoque são PROVISÓRIOS (decisão do Matheus, 12/10/2026: "ok pode seguir" para uma regra de teste; os limites são dele e podem
#                  mudar): ruptura = estoque zerado; crítico = o estoque dura MENOS que o lead time (não dá mais tempo de repor); baixo = dura até lead time + margem
#                  (com a margem padrão de 100%, 2× o lead time); alto = dura mais que isso. Sem vendas nos dias completos o estoque não acaba: nível alto.
# * [EXPLICAÇÃO] → "Quantos dias cada remessa cobre" (`cobre`) AINDA NÃO FOI DEFINIDO pelo Matheus (precisa do retorno do responsável pelo Full): enquanto ninguém digita, vale o lead time como
#                  padrão PROVISÓRIO e a tela avisa "padrão provisório" ao lado do campo (igual ao lead time de 7 dias).
# * [EXPLICAÇÃO] → LIMITE_DE_ACELERACAO_PCT (15) é o mesmo limite da lista de Vendas ("vs. anterior") e também é PROVISÓRIO. DIAS_DO_RITMO_RECENTE (7) é o "ritmo
#                  recente" que a tela compara com o ritmo do período escolhido, para avisar "o ritmo acelerou".

from datetime import timedelta
from math import ceil, floor

# * [EXPLICAÇÃO] → Valores INICIAIS da tela (quando a pessoa não digita nada): o ritmo dos últimos 30 dias e o lead time de 7 dias. O lead time de 7 é um PADRÃO PROVISÓRIO só para a lista já abrir
#                  com níveis calculados (a tela avisa "padrão provisório" ao lado do campo); o lead time real é do Matheus, e depois vai vir de um cadastro por produto.
DIAS_PADRAO = 30
LEAD_TIME_PADRAO = 7
DIAS_DO_RITMO_RECENTE = 7
# * [EXPLICAÇÃO] → Os ritmos que o gráfico do detalhe desenha SEMPRE, lado a lado (cada um com a sua cor fixa): 3, 7, 15 e 30 dias. Se a pessoa escolher outro período (ex.: 10 dias), ele entra como mais uma
#                  curva, já em destaque. O ritmo em destaque é o período escolhido na tela: é ele que manda nas zonas, nos marcadores e no diagnóstico.
DIAS_DOS_RITMOS_DO_GRAFICO = (3, 7, 15, 30)
# * [EXPLICAÇÃO] → A MARGEM DE SEGURANÇA padrão é 100% do lead time (decisão do Matheus, 12/10/2026) e a pessoa pode mudar na tela (de 0% a 500%). "Cada remessa cobre" vale, sem digitar, o lead time.
MARGEM_PADRAO_PCT = 100
MARGEM_MAXIMA_PCT = 500
COBRE_MAXIMO_DIAS = 365
LIMITE_DE_ACELERACAO_PCT = 15
DIAS_MAXIMOS_DA_PROJECAO = 3650   # acima disso (10 anos) a data nem faz sentido: a tela diz "sem previsão"

# * [EXPLICAÇÃO] → A URGÊNCIA na língua do Mercado Livre. Os valores são os exatos que a API manda (REPOS stock.shipping_urgency). O Sistema só usa as 5 primeiras faixas: "Excedente" (sobra de estoque)
#                  só existe no ML e, para comparar, conta como "Sem urgência" (a mesma faixa). `FAIXAS_DA_URGENCIA_EM_DIAS` = até quantos dias faltam para a data de enviar até, por faixa.
URGENCIAS_DO_ML = ('URGENT', 'THIS_WEEK', 'NEXT_WEEK', 'IN_TWO_WEEKS', 'NO_URGENCY', 'EXCEDENT')   # da mais urgente para a mais folgada (a ordem da lista É a ordem de urgência)
FAIXAS_DA_URGENCIA_EM_DIAS = (('THIS_WEEK', 7), ('NEXT_WEEK', 14), ('IN_TWO_WEEKS', 21))
FAIXA_DA_URGENCIA = {'URGENT': 0, 'THIS_WEEK': 1, 'NEXT_WEEK': 2, 'IN_TWO_WEEKS': 3, 'NO_URGENCY': 4, 'EXCEDENT': 4}
FAIXAS_PARA_DIVERGIR = 1   # as duas referências "divergem" quando estão em faixas diferentes (diferença de pelo menos 1 faixa); suba para 2 para ver só as discordâncias grandes

NIVEIS = {
    'ruptura': 'Ruptura',
    'critico': 'Estoque crítico',
    'baixo': 'Estoque baixo',
    'alto': 'Estoque alto',
}
# versão curta, para o selo pequeno dos cartões (o selo grande do diagnóstico usa NIVEIS)
NIVEIS_CURTOS = {'ruptura': 'Ruptura', 'critico': 'Crítico', 'baixo': 'Baixo', 'alto': 'Alto'}


# Função Objetivo: O ritmo de vendas de uma janela de dias: média por dia (só dias completos), unidades vendidas nesses dias e quantos dias completos entraram.
# `por_dia` = {dia: unidades}; `estados` = {dia: 'ok' (completo) | 'parcial' | 'sem_dado'} (vendas_ml.unidades_por_dia). Média None = nenhum dia completo.
def ritmo_da_janela(dias, por_dia, estados):
    completos = [d for d in dias if estados.get(d) == 'ok']
    unidades = sum(por_dia.get(d, 0) for d in completos)
    return {'media': unidades / len(completos) if completos else None, 'unidades': unidades, 'n_completos': len(completos)}


# Função Objetivo: Quanto tempo o estoque dura nesse ritmo. `situacao`: 'zerado' (estoque 0), 'sem_vendas' (ritmo 0: não acaba), 'longe' (passa de DIAS_MAXIMOS_DA_PROJECAO)
# ou 'normal' (com `dias_exatos`, `dias` inteiro para baixo e `data` da ruptura). None se o estoque não foi informado.
def projetar(estoque, media, hoje):
    if estoque is None:
        return None
    if estoque <= 0:
        return {'situacao': 'zerado', 'dias_exatos': 0.0, 'dias': 0, 'data': hoje}
    if media is None or media <= 0:
        return {'situacao': 'sem_vendas', 'dias_exatos': None, 'dias': None, 'data': None}
    dias_exatos = estoque / media
    if dias_exatos > DIAS_MAXIMOS_DA_PROJECAO:
        return {'situacao': 'longe', 'dias_exatos': dias_exatos, 'dias': None, 'data': None}
    dias = floor(dias_exatos)
    return {'situacao': 'normal', 'dias_exatos': dias_exatos, 'dias': dias, 'data': hoje + timedelta(days=dias)}


# Função Objetivo: A margem de segurança em DIAS: a % do lead time arredondada para cima (100% de 15 dias = 15; 30% de 7 dias = 3). None se faltar o lead time.
def folga_em_dias(lead, margem_pct):
    if lead is None or margem_pct is None:
        return None
    return -(-(lead * margem_pct) // 100)   # divisão inteira para cima (sem erro de ponto flutuante)


# Função Objetivo: O nível do estoque ('ruptura', 'critico', 'baixo' ou 'alto'); None enquanto faltar a projeção ou o lead time (o nível depende dele). `folga` = a margem de segurança em dias:
# baixo = dura até lead time + folga.
def nivel_do_estoque(projecao, lead, folga):
    if projecao is None or lead is None or folga is None:
        return None
    if projecao['situacao'] == 'zerado':
        return 'ruptura'
    if projecao['situacao'] in ('sem_vendas', 'longe'):
        return 'alto'
    dias = projecao['dias_exatos']
    if dias < lead:
        return 'critico'
    if dias <= lead + folga:
        return 'baixo'
    return 'alto'


# Função Objetivo: A data do envio, com a margem de segurança. Devolve:
#   enviar_ate = ruptura − lead time − folga (a data RECOMENDADA); ultimo_dia = ruptura − lead time (o último dia em que ainda dá tempo, mas já sem a margem inteira);
#   estado = 'ok' (a data recomendada ainda não chegou) | 'hoje' (hoje é o último dia COM margem) | 'ja' (a recomendada passou, mas ainda dá tempo: enviar já; a remessa chega com `folga_na_chegada`
#   dias de estoque, menos que a margem) | 'vencido' (o último dia passou: mesmo enviando hoje o produto só fica disponível em `chegada` e vão faltar `faltam_dias` dias).
#   `atrasado` = (estado == 'vencido'), `em_dias` = dias até a data recomendada (0 quando já passou). None se não há ruptura prevista ou falta o lead time.
def envio(projecao, lead, hoje, folga):
    if projecao is None or projecao['situacao'] != 'normal' or lead is None or folga is None:
        return None
    ultimo_dia = projecao['data'] - timedelta(days=lead)
    enviar_ate = ultimo_dia - timedelta(days=folga)
    base = {'enviar_ate': enviar_ate, 'ultimo_dia': ultimo_dia, 'chegada': hoje + timedelta(days=lead), 'folga': folga, 'faltam_dias': 0, 'folga_na_chegada': projecao['dias'] - lead}
    if ultimo_dia < hoje:
        return {**base, 'estado': 'vencido', 'atrasado': True, 'em_dias': 0, 'faltam_dias': lead - projecao['dias'], 'folga_na_chegada': 0}
    if enviar_ate > hoje:
        return {**base, 'estado': 'ok', 'atrasado': False, 'em_dias': (enviar_ate - hoje).days}
    return {**base, 'estado': 'hoje' if enviar_ate == hoje else 'ja', 'atrasado': False, 'em_dias': 0}


# Função Objetivo: A urgência de envio do SISTEMA, na língua do Mercado Livre (URGENCIAS_DO_ML): 'URGENT' (estoque zerado, ou a data de enviar até já passou ou é hoje), 'THIS_WEEK', 'NEXT_WEEK' ou
# 'IN_TWO_WEEKS' (a data de enviar até cai em até 7, 14 ou 21 dias) e 'NO_URGENCY' (depois disso, ou sem ruptura prevista: sem venda no ritmo). None quando não dá para saber (sem estoque lido: "ausente
# não é zero"). `cat` é a categoria da linha (ruptura_lista) e `envio_do_item` o resultado de envio() (None se não há data).
def urgencia_do_sistema(cat, envio_do_item):
    if cat == 'sem_estoque':
        return None
    if cat == 'ruptura':
        return 'URGENT'
    if envio_do_item is None:
        return 'NO_URGENCY'   # sem venda no ritmo (ou longe demais): não há ruptura para enviar contra
    if envio_do_item['estado'] != 'ok':
        return 'URGENT'   # a data de enviar até é hoje ou já passou (inclui o prazo vencido)
    for chave, ate in FAIXAS_DA_URGENCIA_EM_DIAS:
        if envio_do_item['em_dias'] <= ate:
            return chave
    return 'NO_URGENCY'


# Função Objetivo: As duas urgências (Sistema e Mercado Livre) estão em faixas diferentes? Só compara quando as duas existem (sem a leitura de um dos lados não há o que comparar).
def urgencias_divergem(urgencia_a, urgencia_b):
    if urgencia_a is None or urgencia_b is None:
        return False
    return abs(FAIXA_DA_URGENCIA.get(urgencia_a, 4) - FAIXA_DA_URGENCIA.get(urgencia_b, 4)) >= FAIXAS_PARA_DIVERGIR


# Função Objetivo: O ponto de pedido em unidades (ritmo × (lead time + folga), arredondado para cima). None se faltar o ritmo, o lead time ou a margem.
def ponto_de_pedido(media, lead, folga):
    if media is None or lead is None or folga is None:
        return None
    return ceil(round(media * (lead + folga), 6))


# Função Objetivo: A sugestão do SISTEMA de quanto enviar. Na chegada da remessa (daqui a `lead` dias) o estoque que sobra é max(0, estoque − ritmo × lead); a meta é ter, nesse dia, `folga` dias de margem
# + `cobre` dias de cobertura da própria remessa (ritmo × (folga + cobre)). A sugestão é a diferença, arredondada para cima (nunca negativa). Devolve a quantidade, o que sobra na chegada e a meta; None
# se faltar o estoque, o ritmo (ou ritmo zero: sem venda não há o que cobrir), o lead time, a margem ou os dias que a remessa cobre.
def sugestao_do_sistema(estoque, media, lead, folga, cobre):
    if estoque is None or media is None or media <= 0 or lead is None or folga is None or cobre is None:
        return None
    sobra = max(0.0, estoque - media * lead)
    meta = media * (folga + cobre)
    return {'qtd': max(0, ceil(round(meta - sobra, 6))), 'sobra_na_chegada': sobra, 'meta': meta, 'folga': folga, 'cobre': cobre}


# Função Objetivo: O que acontece com o estoque SE a remessa de `qtd` unidades for enviada HOJE (qualquer quantidade: a do Sistema, a do ML ou a digitada). A remessa chega em `lead` dias; nesse dia o
# estoque é o que sobrou (`antes` = max(0, estoque − ritmo × lead)) mais a remessa (`apos`) e passa a cair no mesmo ritmo até zerar em `t_zero` = lead + apos ÷ ritmo (dias a partir de hoje; a nova
# ruptura cai no dia floor(t_zero), como em projetar). `faltam` = dias sem estoque ANTES de a remessa chegar (a mesma conta do "prazo vencido": lead − dias de estoque; 0 se o estoque aguenta até a
# chegada). `dias_apos` = quantos dias de vendas o estoque cobre logo depois da chegada. None se faltar o estoque, o ritmo (ou ritmo zero), o lead time ou a quantidade (zero = nada enviado).
def com_envio(estoque, media, lead, qtd):
    if estoque is None or media is None or media <= 0 or lead is None or not qtd or qtd <= 0:
        return None
    antes = max(0.0, estoque - media * lead)
    apos = antes + qtd
    t_zero = lead + apos / media
    faltam = lead if estoque <= 0 else max(0, lead - floor(estoque / media))
    return {'qtd': qtd, 'antes': antes, 'apos': apos, 't_zero': t_zero, 'dia_nova_ruptura': floor(t_zero), 'faltam': faltam, 'dias_apos': apos / media, 'dias_antes': antes / media}


# Função Objetivo: Compara o ritmo recente com o do período escolhido: 'acelerou' (mais de LIMITE_DE_ACELERACAO_PCT acima), 'caiu' (mais de LIMITE abaixo) ou 'estavel',
# com a variação em % (None quando o período não teve vendas). None se algum dos dois ritmos não existe.
def comparar_ritmos(media_recente, media_periodo):
    if media_recente is None or media_periodo is None:
        return None
    if media_periodo <= 0:
        return {'sentido': 'acelerou' if media_recente > 0 else 'estavel', 'pct': None}
    pct = (media_recente - media_periodo) / media_periodo * 100
    if pct > LIMITE_DE_ACELERACAO_PCT:
        sentido = 'acelerou'
    elif pct < -LIMITE_DE_ACELERACAO_PCT:
        sentido = 'caiu'
    else:
        sentido = 'estavel'
    return {'sentido': sentido, 'pct': pct}
