# precificacao/funcoes_auxiliares/gravar_grade_precificacao.py

# Função Objetivo: Gravar o resultado de uma calculadora de Grade de Precificação (TikTok, Magalu, Amazon) no banco da empresa ativa,
# deixando a tabela IGUAL ao que o cálculo acabou de dar — inclusive APAGANDO a linha antiga de toda combinação que, agora, não tem preço.
#
# * [DECISÃO, 15/10/2026] → Antes, a calculadora pulava (`continue`) a combinação que não fechava (meta inatingível, sem faixa de frete,
#   erro de validação) e a linha ANTIGA ficava na tabela com o preço de antes. Isso é um buraco de dessincronização: com a atualização das
#   tabelas de frete espelhando o arquivo (some faixa, muda valor), uma combinação que deixou de ter cálculo continuaria mostrando um
#   preço calculado com uma tabela que já não existe. Agora, "sem cálculo hoje" = "sem linha": as telas e a promoção do TikTok já tratam
#   a falta de linha como "sem preço" (nada aponta para estas linhas por chave estrangeira, então apagar é seguro).
# * [EXPLICAÇÃO] → Tudo acontece numa única transação do banco da empresa: quem está olhando a grade enxerga a grade antiga inteira ou a
#   nova inteira, nunca uma grade pela metade (linhas apagadas e ainda não recriadas). Se qualquer passo falhar, nada muda.
# * [EXPLICAÇÃO] → "Linha mantida" = a que a calculadora acabou de atualizar (`para_atualizar`). Toda outra linha que já existia é removida:
#   combinação sem cálculo, erro de validação, ou uma margem/tipo que já nem existe mais na calculadora. Linhas novas (`para_criar`) ainda
#   não têm chave primária e por isso nunca entram na conta de remoção.
# * [IMPORTANTE] → A lista de remoção é tirada ANTES de criar as linhas novas, e a gravação só acontece depois de a calculadora terminar o
#   laço inteiro: se o cálculo quebrar no meio (erro que não seja de validação), nada foi apagado nem gravado.

import logging

from django.db import transaction

from core.empresa import obter_alias_banco_ativo

logger = logging.getLogger(__name__)

TAMANHO_DO_LOTE_DE_REMOCAO = 500   # chaves por DELETE (lotes pequenos são mais seguros que uma lista enorme)


# Função Objetivo: Apaga as linhas de `chaves` (pk) em lotes. Devolve quantas foram apagadas.
def _remover_em_lotes(modelo, alias, chaves):
    apagadas = 0
    for inicio in range(0, len(chaves), TAMANHO_DO_LOTE_DE_REMOCAO):
        lote = chaves[inicio:inicio + TAMANHO_DO_LOTE_DE_REMOCAO]
        apagadas += modelo.objects.using(alias).filter(pk__in=lote).delete()[0]
    return apagadas


# Função Objetivo: Deixa a tabela do `modelo` igual ao cálculo. Devolve quantas linhas antigas foram removidas por não terem mais cálculo.
#   existentes         → dict {chave: linha} que a calculadora carregou ANTES do laço (e onde ela também pôs as linhas novas).
#   para_criar         → linhas novas (ainda sem pk).
#   para_atualizar     → linhas que já existiam e foram recalculadas (as únicas antigas que ficam).
#   campos_atualizaveis → colunas regravadas no bulk_update.
def gravar_grade_espelhando_o_calculo(modelo, existentes, para_criar, para_atualizar, campos_atualizaveis, batch_size):
    alias = obter_alias_banco_ativo()
    mantidas = {linha.pk for linha in para_atualizar}
    a_remover = [linha.pk for linha in existentes.values() if linha.pk is not None and linha.pk not in mantidas]

    with transaction.atomic(using=alias):
        removidas = _remover_em_lotes(modelo, alias, a_remover)
        if para_criar:
            modelo.objects.using(alias).bulk_create(para_criar, batch_size=batch_size)
        if para_atualizar:
            modelo.objects.using(alias).bulk_update(para_atualizar, campos_atualizaveis, batch_size=batch_size)

    if removidas:
        logger.info('Grade %s: %s linha(s) antiga(s) removida(s) por não terem mais cálculo.', modelo.__name__, removidas)
    return removidas
