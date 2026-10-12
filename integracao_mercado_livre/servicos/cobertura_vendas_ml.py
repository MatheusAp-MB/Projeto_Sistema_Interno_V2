# integracao_mercado_livre/servicos/cobertura_vendas_ml.py
#
# Função Objetivo: Responde "o que já foi coletado do histórico de vendas?" a partir do registro de coletas (ColetaVendasMercadoLivre). É a
# ÚNICA fonte dessa regra: a tela (gestao_vendas) usa para mostrar "sem dado" / dia parcial, e o coletor usa para só buscar o que FALTA.
# Não chama a API do Mercado Livre e não grava nada: só lê o registro de coletas.
#
# REGRAS (as mesmas que a tela mostra):
#   - Coleta da CONTA TODA (escopo dia ou período) cobre todos os SKUs. Coleta de MLB cobre só aquele MLB (e um produto só fica coberto quando
#     TODOS os MLBs dele têm o dia).
#   - Dia "completo" = a coleta terminou DEPOIS que o dia acabou. Hoje nunca é completo.
#   - Coleta com falha não cobre nada; coleta parcial cobre o trecho que chegou a ser lido.
#
# PERÍODOS DA TELA DE VENDAS (decisão do Matheus, 11/10/2026): por CALENDÁRIO, não por contagem de dias. O fim é sempre HOJE (dia parcial) e o
# início é "a mesma data uma unidade atrás": Última semana = hoje − 7 dias; Último mês = mesma data 1 mês atrás; 3 meses; 6 meses; Último ano.
# Em 11/10/2026: semana 04/10→11/10 · mês 11/09→11/10 · 3 meses 11/07→11/10 · 6 meses 11/04→11/10 · ano 11/10/2025→11/10/2026.
# A regra mora AQUI (e só aqui) porque a tela e o coletor precisam concordar no primeiro dia: se divergissem em 1 dia, esse dia ficaria "sem dado".
#
# * [EXPLICAÇÃO] → "Só o que falta" (dias_pendentes): um dia já coletado COMPLETO não precisa voltar do Mercado Livre, EXCETO os últimos
#                  DIAS_DE_REVISAO dias: ali um pedido ainda pode ser cancelado/alterado, e o cancelamento só chega ao banco relendo o dia.
#                  O valor 30 é PROVISÓRIO (decisão do Matheus, 11/10/2026: pode subir ou descer aqui). "Reler tudo" ignora esta regra.

import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mercado_livre.models import ColetaVendasMercadoLivre

FUSO = ZoneInfo('America/Sao_Paulo')
RANGE_MIN = datetime(2000, 1, 1, tzinfo=FUSO)
DIAS_DE_REVISAO = 30

# O Mercado Livre guarda ~12 meses de pedidos. `FOLGA_DO_LIMITE_ML_DIAS` = quantos dias a MAIS (depois do dia exato de 12 meses atrás) o primeiro
# dia disponível fica. 0 = tenta o dia exato; 1 = começa 1 dia depois (12/10/2025 em 12/10/2026). Com folga, a tela mostra sozinha o aviso "limite do ML"
# (período recortado) e o coletor não pede mais o dia da borda.
# * [EXPLICAÇÃO] → POR QUE 1 (pedido do Matheus, 12/10/2026): MEDIDO em 12/10/2026 01:14 (scripts_exploracao_ML/conferir_borda_de_12_meses_do_orders_search.py):
#                  o ML não recusa o dia mais antigo (11/10/2025), mas o devolve PARCIAL: ML 196 × banco 197 (o pedido das 03:45:38 é cortado e o 1º que vem
#                  é o das 06:05:04). O dia seguinte (12/10/2025) veio inteiro (203 = 203), e o de controle (13/10/2025) também (332 = 332). Em 11/10/2026 isso
#                  passou despercebido: o dia "funcionou" (39 un num produto) sem ninguém ver que faltava o começo dele. Com 1 dia de folga o primeiro dia
#                  da tela vem inteiro. AINDA NÃO SE SABE a hora exata do corte nem se ele anda ao longo do dia: se o primeiro dia voltar a vir parcial, suba a folga.
MESES_DO_HISTORICO_ML = 12
FOLGA_DO_LIMITE_ML_DIAS = 1


def carregar_coletas(de, ate):
    return list(ColetaVendasMercadoLivre.objects.filter(
        status__in=[ColetaVendasMercadoLivre.Status.CONCLUIDA, ColetaVendasMercadoLivre.Status.PARCIAL],
        data_ate__gte=de, data_de__lte=ate, concluido_em__isnull=False))


def mapa_de_dias(coletas, de, ate):
    mapa = {}
    for c in coletas:
        dia, fim = max(c.data_de, de), min(c.data_ate, ate)
        while dia <= fim:
            if c.concluido_em > mapa.get(dia, RANGE_MIN):
                mapa[dia] = c.concluido_em
            dia += timedelta(days=1)
    return mapa


# Função Objetivo: Quais dias de [de, ate] têm dado coletado para estes MLBs e quando foi a coleta: {dia: instante}. Conta toda (dia, período)
# cobre tudo; coleta de MLB só cobre o conjunto quando TODOS os MLBs têm o dia. Sem MLBs: só a conta toda.
def cobertura(coletas, mlbs, de, ate):
    mapa = mapa_de_dias([c for c in coletas if c.escopo in (ColetaVendasMercadoLivre.Escopo.DIA, ColetaVendasMercadoLivre.Escopo.PERIODO)], de, ate)
    if mlbs:
        por_mlb = [mapa_de_dias([c for c in coletas if c.escopo == ColetaVendasMercadoLivre.Escopo.MLB and c.mlb == mlb], de, ate) for mlb in mlbs]
        for dia in set.intersection(*[set(m) for m in por_mlb]):
            quando = min(m[dia] for m in por_mlb)
            if quando > mapa.get(dia, RANGE_MIN):
                mapa[dia] = quando
    return mapa


def dia_completo(dia, coletado_em):
    return coletado_em >= datetime(dia.year, dia.month, dia.day, tzinfo=FUSO) + timedelta(days=1)


# Função Objetivo: Os dias de [de, ate] que precisam voltar do Mercado Livre, do mais antigo para o mais novo. `mlb` = o MLB (None = conta toda).
# Pendente = nunca coletado, só coletado parcial (antes do dia acabar) OU dentro dos últimos DIAS_DE_REVISAO dias. `reler_tudo` = todos.
def dias_pendentes(coletas, mlb, de, ate, hoje, reler_tudo=False):
    todos = [de + timedelta(days=i) for i in range((ate - de).days + 1)]
    if reler_tudo:
        return todos
    mapa = cobertura(coletas, [mlb] if mlb else [], de, ate)
    primeiro_da_revisao = hoje - timedelta(days=DIAS_DE_REVISAO - 1)
    return [d for d in todos if d >= primeiro_da_revisao or d not in mapa or not dia_completo(d, mapa[d])]


# Função Objetivo: Junta dias em sequência em faixas [(inicio, fim), ...]. Entrada em ordem crescente.
def faixas_de_dias(dias_ordenados):
    faixas = []
    for dia in dias_ordenados:
        if faixas and dia == faixas[-1][1] + timedelta(days=1):
            faixas[-1] = (faixas[-1][0], dia)
        else:
            faixas.append((dia, dia))
    return faixas


# Função Objetivo: Parte [de, ate] em `partes` pedaços de tamanho quase igual (em dias), em ordem crescente. Nunca devolve mais pedaços que dias.
def dividir_janela(de, ate, partes):
    n_dias = (ate - de).days + 1
    partes = max(1, min(partes, n_dias))
    base, resto = divmod(n_dias, partes)
    saida, inicio = [], de
    for i in range(partes):
        tamanho = base + (1 if i < resto else 0)
        fim = inicio + timedelta(days=tamanho - 1)
        saida.append((inicio, fim))
        inicio = fim + timedelta(days=1)
    return saida


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# PERÍODOS POR CALENDÁRIO (usados pela tela de Vendas e pelo coletor)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════

# chave → (meses, dias, rótulo, frase "frente ao anterior", frase "no anterior"). `meses` > 0 = volta por calendário; senão volta `dias`.
PERIODOS_DA_TELA = {
    'semana': (0, 7, 'Última semana', 'frente à semana anterior', 'na semana anterior'),
    'mes': (1, 0, 'Último mês', 'frente ao mês anterior', 'no mês anterior'),
    '3meses': (3, 0, 'Últimos 3 meses', 'frente aos 3 meses anteriores', 'nos 3 meses anteriores'),
    '6meses': (6, 0, 'Últimos 6 meses', 'frente aos 6 meses anteriores', 'nos 6 meses anteriores'),
    'ano': (12, 0, 'Último ano', 'frente ao ano anterior', 'no ano anterior'),
}
ORDEM_DOS_PERIODOS = ['semana', 'mes', '3meses', '6meses', 'ano']
PERIODO_PADRAO = '3meses'
# Links antigos da tela (?dias=7/30/90/180/365) continuam funcionando.
PERIODO_DOS_DIAS_ANTIGOS = {7: 'semana', 30: 'mes', 90: '3meses', 180: '6meses', 365: 'ano'}


# Função Objetivo: A mesma data `meses` meses atrás. Mês mais curto encurta o dia (31/03 − 1 mês = 28/02; 29/02/2028 − 1 ano = 28/02/2027).
def voltar_meses(dia, meses):
    total = dia.year * 12 + (dia.month - 1) - meses
    ano, mes = divmod(total, 12)
    mes += 1
    return dia.replace(year=ano, month=mes, day=min(dia.day, calendar.monthrange(ano, mes)[1]))


# Função Objetivo: O dia "uma unidade atrás" do período (7 dias, ou N meses de calendário).
def voltar_unidade(dia, chave):
    meses, dias = PERIODOS_DA_TELA[chave][0], PERIODOS_DA_TELA[chave][1]
    return voltar_meses(dia, meses) if meses else dia - timedelta(days=dias)


def rotulo_do_periodo(chave):
    return PERIODOS_DA_TELA[chave][2]


def frase_frente_ao_anterior(chave):
    return PERIODOS_DA_TELA[chave][3]


def frase_no_anterior(chave):
    return PERIODOS_DA_TELA[chave][4]


# Função Objetivo: Aceita a chave nova ou o número antigo de dias (7/30/90/180/365) e devolve a chave; qualquer outra coisa vira o padrão.
def normalizar_periodo(valor):
    valor = str(valor or '').strip().lower()
    if valor in PERIODOS_DA_TELA:
        return valor
    return PERIODO_DOS_DIAS_ANTIGOS.get(int(valor)) if valor.isdigit() and int(valor) in PERIODO_DOS_DIAS_ANTIGOS else PERIODO_PADRAO


# Função Objetivo: Primeiro dia que o Mercado Livre ainda devolve: o dia de 12 meses atrás (+ folga, ver FOLGA_DO_LIMITE_ML_DIAS).
def primeiro_dia_do_ml(hoje):
    return voltar_meses(hoje, MESES_DO_HISTORICO_ML) + timedelta(days=FOLGA_DO_LIMITE_ML_DIAS)


# Função Objetivo: Início do período pedido (fim = hoje). Já recortado no limite do ML; `recortado` diz se o limite cortou o período.
def inicio_do_periodo(chave, hoje):
    inicio = voltar_unidade(hoje, chave)
    limite = primeiro_dia_do_ml(hoje)
    return (limite, True) if inicio < limite else (inicio, False)


# Função Objetivo: O período imediatamente ANTES, da mesma unidade, colado no atual (sem buraco nem sobreposição):
# anterior = [início − 1 unidade, início − 1 dia]. Usa o início SEM recorte (o do calendário), para o tamanho ser o certo.
def periodo_anterior(chave, hoje):
    inicio = voltar_unidade(hoje, chave)
    return voltar_unidade(inicio, chave), inicio - timedelta(days=1)


# Função Objetivo: "Quantos dias para trás" do início de um período, que é o N do coletor (`de = hoje − N`, `ate = hoje`; N+1 dias no total).
def dias_para_tras(chave, hoje):
    return (hoje - inicio_do_periodo(chave, hoje)[0]).days


def texto_do_intervalo(de, ate):
    com_ano = de.year != ate.year
    formato = '%d/%m/%Y' if com_ano else '%d/%m'
    return f'{de.strftime(formato)} a {ate.strftime(formato)}'


# Função Objetivo: Os 5 períodos de hoje, na ordem dos botões, com as datas reais: chave, rótulo, de, ate, dias_para_tras, total_dias, recortado, texto.
def periodos_de_hoje(hoje):
    saida = []
    for chave in ORDEM_DOS_PERIODOS:
        de, recortado = inicio_do_periodo(chave, hoje)
        saida.append({'chave': chave, 'rotulo': rotulo_do_periodo(chave), 'de': de, 'ate': hoje, 'dias_para_tras': (hoje - de).days,
                      'total_dias': (hoje - de).days + 1, 'recortado': recortado, 'texto': texto_do_intervalo(de, hoje)})
    return saida


# Função Objetivo: Texto de ajuda para quando o Mercado Livre recusa um dia que está na borda dos 12 meses (vazio se o dia não é da borda).
def dica_de_borda(dia, hoje):
    if (dia - voltar_meses(hoje, MESES_DO_HISTORICO_ML)).days <= FOLGA_DO_LIMITE_ML_DIAS + 1:
        return ' (limite do ML: este dia está na borda dos 12 meses que o Mercado Livre guarda)'
    return ''
