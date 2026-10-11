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
# * [EXPLICAÇÃO] → "Só o que falta" (dias_pendentes): um dia já coletado COMPLETO não precisa voltar do Mercado Livre, EXCETO os últimos
#                  DIAS_DE_REVISAO dias: ali um pedido ainda pode ser cancelado/alterado, e o cancelamento só chega ao banco relendo o dia.
#                  O valor 30 é PROVISÓRIO (decisão do Matheus, 11/10/2026: pode subir ou descer aqui). "Reler tudo" ignora esta regra.

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mercado_livre.models import ColetaVendasMercadoLivre

FUSO = ZoneInfo('America/Sao_Paulo')
RANGE_MIN = datetime(2000, 1, 1, tzinfo=FUSO)
DIAS_DE_REVISAO = 30


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
