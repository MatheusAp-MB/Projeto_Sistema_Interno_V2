# gestao_ruptura/funcoes_auxiliares/ruptura_calculo.py
#
# Função Objetivo: As CONTAS da tela "Ruptura de estoque" (prova de conceito, 12/10/2026): ritmo de vendas, quantos dias o estoque dura, a data da ruptura, a data
# limite do envio, o ponto de pedido, o nível do estoque e a comparação entre o ritmo recente e o do período. Só matemática: aqui NÃO há banco, API nem tela
# (quem junta tudo é ruptura_pagina.py), por isso cada regra mora num lugar só e dá para entender e mudar sem mexer em mais nada.
#
# REGRAS DO MATHEUS que moram aqui:
#   - O ritmo é o MESMO da tela de Vendas: unidades dos dias COMPLETOS ÷ número de dias completos. Hoje (dia parcial) e dia que nunca foi coletado ficam de fora
#     ("ausente não é zero"); venda cancelada não conta (isso já vem resolvido de vendas_ml.unidades_por_dia).
#   - Dias de estoque = estoque ÷ ritmo. A ruptura cai no dia (hoje + dias de estoque, arredondado para baixo).
#   - Data limite do envio = data da ruptura − lead time (o lead time é o tempo até o produto ficar disponível para venda).
#   - Ponto de pedido = ritmo × lead time (em unidades): com menos estoque que isso, já não dá tempo de repor antes da ruptura.
#
# * [EXPLICAÇÃO] → Os 4 NÍVEIS do estoque são PROVISÓRIOS (decisão do Matheus, 12/10/2026: "ok pode seguir" para uma regra de teste; os limites são dele e podem
#                  mudar): ruptura = estoque zerado; crítico = o estoque dura MENOS que o lead time (não dá mais tempo de repor); baixo = dura até
#                  FATOR_DO_NIVEL_BAIXO vezes o lead time; alto = dura mais que isso. Sem vendas nos dias completos o estoque não acaba: nível alto.
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
FATOR_DO_NIVEL_BAIXO = 2
LIMITE_DE_ACELERACAO_PCT = 15
DIAS_MAXIMOS_DA_PROJECAO = 3650   # acima disso (10 anos) a data nem faz sentido: a tela diz "sem previsão"

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


# Função Objetivo: O nível do estoque ('ruptura', 'critico', 'baixo' ou 'alto'); None enquanto faltar a projeção ou o lead time (o nível depende dele).
def nivel_do_estoque(projecao, lead):
    if projecao is None or lead is None:
        return None
    if projecao['situacao'] == 'zerado':
        return 'ruptura'
    if projecao['situacao'] in ('sem_vendas', 'longe'):
        return 'alto'
    dias = projecao['dias_exatos']
    if dias < lead:
        return 'critico'
    if dias <= FATOR_DO_NIVEL_BAIXO * lead:
        return 'baixo'
    return 'alto'


# Função Objetivo: A data limite para preparar o envio (ruptura − lead time). Atrasado = a data já passou: mesmo enviando hoje o produto só fica disponível
# em `chegada` (hoje + lead time) e vão faltar `faltam_dias` dias de estoque. None se não há ruptura prevista ou falta o lead time.
def envio(projecao, lead, hoje):
    if projecao is None or projecao['situacao'] != 'normal' or lead is None:
        return None
    enviar_ate = projecao['data'] - timedelta(days=lead)
    if enviar_ate >= hoje:
        return {'enviar_ate': enviar_ate, 'atrasado': False, 'em_dias': (enviar_ate - hoje).days, 'chegada': None, 'faltam_dias': 0}
    return {'enviar_ate': enviar_ate, 'atrasado': True, 'em_dias': 0, 'chegada': hoje + timedelta(days=lead), 'faltam_dias': lead - projecao['dias']}


# Função Objetivo: O ponto de pedido em unidades (ritmo × lead time, arredondado para cima). None se faltar o ritmo ou o lead time.
def ponto_de_pedido(media, lead):
    if media is None or lead is None:
        return None
    return ceil(media * lead)


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
