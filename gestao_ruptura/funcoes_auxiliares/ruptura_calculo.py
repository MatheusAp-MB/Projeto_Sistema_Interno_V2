# gestao_ruptura/funcoes_auxiliares/ruptura_calculo.py
#
# Função Objetivo: As CONTAS da tela "Previsão de Ruptura de estoque" (prova de conceito, 12/10/2026): ritmo de vendas, quantos dias o estoque dura, a data da ruptura, a data
# limite do envio (ou do pedido), o ponto de pedido, o nível do estoque e a comparação entre o ritmo recente e o do período. Só matemática: aqui NÃO há banco, API nem tela
# (quem junta tudo é ruptura_pagina.py), por isso cada regra mora num lugar só e dá para entender e mudar sem mexer em mais nada.
#
# AS CONTAS SÃO AS MESMAS NOS DOIS "MUNDOS" da tela (decisão do Matheus, 12/10/2026): ENVIOS FULL (estoque do Full, vendas do Full) e FORA DO FULL (estoque e vendas de fora do Full). O que muda de um
# mundo para o outro é só o que entra nas contas (estoque, ritmo, prazo) e as palavras (enviar x pedir): a matemática daqui não sabe em qual mundo está.
#
# REGRAS DO MATHEUS que moram aqui:
#   - O ritmo é o MESMO da tela de Vendas: unidades dos dias COMPLETOS ÷ número de dias completos. Hoje (dia parcial) e dia que nunca foi coletado ficam de fora
#     ("ausente não é zero"); venda cancelada não conta (isso já vem resolvido de vendas_ml.unidades_por_dia).
#   - Dias de estoque = estoque ÷ ritmo. A ruptura cai no dia (hoje + dias de estoque, arredondado para baixo).
#   - PRAZO ATÉ VENDER (o lead time) = o tempo todo, desde o ZERO, até o produto estar à venda. No Full: abrir o Mercado Livre, planejar o envio, escolher a data, a coleta acontecer e a mercadoria chegar
#     ao Full. Fora do Full: do pedido ao fornecedor até a transportadora entregar para a gente.
#   - O envio TEM QUE CHEGAR até `ante` dias ANTES da ruptura total (decisão do Matheus, 12/10/2026: "para nunca ficarmos sem venda, mas também para não mandar envios muito antes e sobrecarregar o
#     estoque"; padrão 3 dias, editável). Enviar (ou pedir) até = ruptura − prazo − ante. O ÚLTIMO dia possível (ruptura − prazo) é o limite sem margem nenhuma: depois dele vai faltar produto.
#   - FOLGA (a MESMA ideia nos dois mundos, correção do Matheus, 12/10/2026): "estou mandando este envio e quero ter X dias de estoque de folga". É quantos dias de estoque o envio ACRESCENTA: com a ruptura
#     em 15/10 e folga de 15 dias, a sugestão leva a NOVA ruptura para 30/10. Quantidade sugerida = ritmo × folga; nova ruptura = max(ruptura atual, chegada) + folga. Não existe mais "cada envio dura".
#   - Ponto de pedido = ritmo × (prazo + ante) (em unidades): com menos estoque que isso, já não dá tempo de enviar chegando `ante` dias antes da ruptura.
#   - URGÊNCIA DE ENVIO (decisão do Matheus, 12/10/2026: "referência de urgência: Mercado Livre ou Sistema"): o Sistema fala a MESMA língua do Mercado Livre (Urgente, Esta semana, Próxima semana, Em 2
#     semanas, Sem urgência) para as duas poderem ser comparadas e para o filtro "Divergem" existir. A urgência do Sistema sai da DATA de enviar até: já passou ou é hoje = Urgente; em até 7 dias = Esta semana;
#     até 14 = Próxima semana; até 21 = Em 2 semanas; depois disso (ou sem ruptura prevista) = Sem urgência. As faixas são provisórias (mudam em FAIXAS_DA_URGENCIA_EM_DIAS).
#
# * [EXPLICAÇÃO] → Os 4 NÍVEIS do estoque são PROVISÓRIOS (decisão do Matheus, 12/10/2026: "ok pode seguir" para uma regra de teste; os limites são dele e podem
#                  mudar): ruptura = estoque zerado; crítico = o estoque dura MENOS que o prazo (não dá mais tempo de repor); baixo = dura até prazo + folga
#                  (com a folga padrão, igual ao prazo, 2× o prazo); alto = dura mais que isso. Sem vendas nos dias completos o estoque não acaba: nível alto.
# * [EXPLICAÇÃO] → A FOLGA em dias AINDA NÃO FOI DEFINIDA pelo Matheus (precisa do retorno do responsável pelo Full): enquanto ninguém digita, vale o prazo como padrão PROVISÓRIO e a tela avisa
#                  "provisório" ao lado do campo (igual ao prazo de 7 dias). Os 3 dias de chegada antes da ruptura (`ante`) já são regra dele, mas continuam editáveis.
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
# * [EXPLICAÇÃO] → `ANTECEDENCIA_PADRAO` = quantos dias ANTES da ruptura o envio deve chegar (3, regra do Matheus de 12/10/2026; editável na tela, de 0 a ANTECEDENCIA_MAXIMA). A FOLGA (dias de estoque que o
#                  envio acrescenta) sem digitar vale o próprio prazo (provisório); o máximo que a tela aceita é FOLGA_MAXIMA_DIAS.
ANTECEDENCIA_PADRAO = 3
ANTECEDENCIA_MAXIMA = 60
FOLGA_MAXIMA_DIAS = 365
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


# Função Objetivo: O nível do estoque ('ruptura', 'critico', 'baixo' ou 'alto'); None enquanto faltar a projeção ou o prazo (o nível depende dele). `folga` = os dias de estoque que o envio acrescenta:
# baixo = dura até prazo + folga (regra provisória).
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


# Função Objetivo: A data do envio (ou do pedido), chegando `ante` dias antes da ruptura. Devolve:
#   enviar_ate = ruptura − prazo − ante (a data RECOMENDADA); ultimo_dia = ruptura − prazo (o último dia em que ainda dá tempo, mas já chegando em cima da ruptura);
#   estado = 'ok' (a data recomendada ainda não chegou) | 'hoje' (hoje é o último dia para chegar `ante` dias antes) | 'ja' (a recomendada passou, mas ainda dá tempo: enviar já; chega com
#   `sobra_na_chegada` dias de estoque, menos que os `ante` desejados) | 'vencido' (o último dia passou: mesmo enviando hoje o produto só fica disponível em `chegada` e vão faltar `faltam_dias` dias).
#   `atrasado` = (estado == 'vencido'), `em_dias` = dias até a data recomendada (0 quando já passou). None se não há ruptura prevista ou falta o prazo.
def envio(projecao, lead, hoje, ante):
    if projecao is None or projecao['situacao'] != 'normal' or lead is None or ante is None:
        return None
    ultimo_dia = projecao['data'] - timedelta(days=lead)
    enviar_ate = ultimo_dia - timedelta(days=ante)
    base = {'enviar_ate': enviar_ate, 'ultimo_dia': ultimo_dia, 'chegada': hoje + timedelta(days=lead), 'ante': ante, 'faltam_dias': 0, 'sobra_na_chegada': projecao['dias'] - lead}
    if ultimo_dia < hoje:
        return {**base, 'estado': 'vencido', 'atrasado': True, 'em_dias': 0, 'faltam_dias': lead - projecao['dias'], 'sobra_na_chegada': 0}
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


# Função Objetivo: A diferença entre a quantidade que o Mercado Livre sugere enviar e a do Sistema (ML − Sistema, em unidades): positivo = o ML sugere MAIS; negativo = o Sistema sugere mais; 0 = iguais.
# None quando falta um dos lados (sem número não é zero: não há o que comparar). Numa faixa do ML vale o começo dela (a mesma regra do gráfico e da urgência).
def diferenca_de_quantidades(qtd_sistema, qtd_ml):
    if qtd_sistema is None or qtd_ml is None:
        return None
    return qtd_ml - qtd_sistema


# Função Objetivo: O ponto de pedido em unidades (ritmo × (prazo + ante), arredondado para cima). None se faltar o ritmo, o prazo ou os dias de antecedência.
def ponto_de_pedido(media, lead, ante):
    if media is None or lead is None or ante is None:
        return None
    return ceil(round(media * (lead + ante), 6))


# Função Objetivo: A quantidade que o SISTEMA sugere enviar (ou pedir), SÓ pelo ritmo e pela folga: ritmo × folga, arredondada para cima (nenhuma venda no ritmo ou sem folga: None). Não olha o estoque: serve à lista do
# Fora do Full, que ainda não tem estoque, e é a mesma quantidade de `sugestao_do_sistema`.
def quantidade_do_sistema(media, folga):
    if media is None or media <= 0 or folga is None:
        return None
    return ceil(round(media * folga, 6))


# Função Objetivo: A sugestão do SISTEMA de quanto enviar (ou pedir): a quantidade que dá `folga` dias de estoque de folga, ou seja, ritmo × folga (arredondada para cima). É a regra do Matheus
# ("estou mandando este envio e quero ter X dias de folga"): a NOVA ruptura passa a vir `folga` dias depois do que viria sem o envio. Se o estoque ainda dura até a chegada, a nova ruptura é a atual + folga;
# se acaba antes de a remessa chegar, é a chegada + folga (`t_alvo` = max(dias de estoque, prazo) + folga, em dias a partir de hoje). `sobra_na_chegada` = o que ainda sobra do estoque atual no dia em que a
# remessa chega. Devolve {qtd, folga, sobra_na_chegada, t_alvo}; None se faltar o estoque, o ritmo (ritmo zero: sem venda não há ruptura a empurrar), o prazo ou a folga.
def sugestao_do_sistema(estoque, media, lead, folga):
    if estoque is None or media is None or media <= 0 or lead is None or folga is None:
        return None
    t_alvo = max(max(estoque, 0) / media, lead) + folga
    return {'qtd': quantidade_do_sistema(media, folga), 'folga': folga, 'sobra_na_chegada': max(0.0, estoque - media * lead), 't_alvo': t_alvo}


# Função Objetivo: O que acontece com o estoque SE a remessa de `qtd` unidades for enviada HOJE (qualquer quantidade: a do Sistema, a do ML ou a digitada). A remessa chega em `lead` dias; nesse dia o
# estoque é o que sobrou (`antes` = max(0, estoque − ritmo × lead)) mais a remessa (`apos`) e passa a cair no mesmo ritmo até zerar em `t_zero` = lead + apos ÷ ritmo (dias a partir de hoje; a nova
# ruptura cai no dia floor(t_zero), como em projetar). `faltam` = dias sem estoque ANTES de a remessa chegar (a mesma conta do "prazo vencido": lead − dias de estoque; 0 se o estoque aguenta até a
# chegada). `dias_apos` = quantos dias de vendas o estoque cobre logo depois da chegada. `folga_dada` = quantos dias de estoque a remessa ACRESCENTA (quantidade ÷ ritmo): é o que se compara com a folga
# desejada (a nova ruptura = max(ruptura atual, chegada) + folga_dada). None se faltar o estoque, o ritmo (ou ritmo zero), o prazo ou a quantidade (zero = nada enviado).
def com_envio(estoque, media, lead, qtd):
    if estoque is None or media is None or media <= 0 or lead is None or not qtd or qtd <= 0:
        return None
    antes = max(0.0, estoque - media * lead)
    apos = antes + qtd
    t_zero = lead + apos / media
    faltam = lead if estoque <= 0 else max(0, lead - floor(estoque / media))
    return {'qtd': qtd, 'antes': antes, 'apos': apos, 't_zero': t_zero, 'dia_nova_ruptura': floor(t_zero), 'faltam': faltam, 'dias_apos': apos / media, 'dias_antes': antes / media, 'folga_dada': qtd / media}


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
