# gestao_apis/funcoes_auxiliares/eventos.py

# Função Objetivo: Único lugar que lê e grava o histórico (EventoIntegracao).
# Toda função aqui é à prova de "tabela ainda não existe": se a migração não
# foi rodada, a tela abre normalmente e avisa — nunca dá erro 500.

import traceback
from datetime import timedelta
from types import SimpleNamespace

from django.db import DatabaseError
from django.utils import timezone

from ..models import EventoIntegracao

LIMITE_DE_EVENTOS_GUARDADOS = 500

# Um pouco acima do corte feito em protecao_de_segredos.LIMITE_DA_RESPOSTA_EXIBIDA (que ainda acrescenta 1 linha de aviso).
LIMITE_DA_RESPOSTA_GUARDADA = 4300

# * [EXPLICAÇÃO] → Proteção contra clique repetido: a mesma conexão não é
#                  testada de novo antes disso (vale pra qualquer pessoa/aba).
SEGUNDOS_ENTRE_TESTES_DA_MESMA_CONEXAO = 8


def identificar_quem(request):
    usuario = getattr(request, 'user', None)
    if usuario is not None and usuario.is_authenticated:
        return usuario.get_username()[:80]
    return 'Sem login (acesso aberto)'


def registrar_evento(conexao_id, acao, resultado, quem):
    """Grava 1 evento. Devolve True se gravou, False se o banco recusou."""
    try:
        EventoIntegracao.objects.create(
            conexao=conexao_id,
            acao=acao,
            estado=resultado.estado,
            motivo=(resultado.motivo or '')[:300],
            impacto=(resultado.impacto or '')[:300],
            como_resolver=(resultado.como_resolver or '')[:300],
            evidencia=(resultado.evidencia or '')[:300],
            # * [EXPLICAÇÃO] → Já vem pronta (sem segredos e cortada) dos verificadores; o corte aqui é só rede de segurança.
            resposta=(resultado.resposta or '')[:LIMITE_DA_RESPOSTA_GUARDADA],
            quem=quem[:80],
        )
        _aparar_historico()
        return True
    except DatabaseError:
        traceback.print_exc()
        return False


def evento_em_memoria(acao, resultado):
    """
    Evento de mentirinha, só na memória, com os mesmos campos do EventoIntegracao. Usado quando o
    banco recusou gravar o histórico (ex.: migração ainda não rodada): o cartão ainda mostra o
    resultado do teste que acabou de ser feito, em vez de parecer que nada aconteceu.
    """
    return SimpleNamespace(
        criado_em=timezone.now(), acao=acao, estado=resultado.estado, motivo=resultado.motivo or '',
        impacto=resultado.impacto or '', como_resolver=resultado.como_resolver or '',
        evidencia=resultado.evidencia or '', resposta=resultado.resposta or '',
    )


def _aparar_historico():
    # * [EXPLICAÇÃO] → Guarda só os últimos LIMITE_DE_EVENTOS_GUARDADOS. Roda a
    #                  cada gravação, então só sobra um punhado pra apagar.
    # * [IMPORTANTE] → Os eventos "autorizacao" (renovação do login do Google Drive) nunca são apagados aqui: é
    #                  deles que a tela tira a data de vencimento da autorização, e uma sequência grande de testes não
    #                  pode empurrá-los para fora do histórico. São poucos (1 por renovação).
    ids_antigos = list(
        EventoIntegracao.objects.exclude(acao='autorizacao').order_by('-criado_em', '-id')
        .values_list('id', flat=True)[LIMITE_DE_EVENTOS_GUARDADOS:]
    )
    if ids_antigos:
        EventoIntegracao.objects.filter(id__in=ids_antigos).delete()


def ultimo_evento_da_conexao(conexao_id):
    """Evento mais recente da conexão, ou None. Levanta DatabaseError se a tabela não existe."""
    return EventoIntegracao.objects.filter(conexao=conexao_id).first()


def ultimo_evento_da_acao(conexao_id, acao):
    """Evento mais recente da conexão para uma ação específica (ex.: 'autorizacao'), ou None. Levanta DatabaseError se a tabela não existe."""
    return EventoIntegracao.objects.filter(conexao=conexao_id, acao=acao).first()


def listar_eventos(limite=60, conexoes=None):
    """
    Eventos mais recentes (lista). `conexoes` = ids das conexões que interessam (None = todas).
    Levanta DatabaseError se a tabela não existe.
    """
    consulta = EventoIntegracao.objects.all()
    if conexoes is not None:
        consulta = consulta.filter(conexao__in=list(conexoes))
    return list(consulta[:limite])


def testado_ha_pouco(conexao_id):
    limite = timezone.now() - timedelta(seconds=SEGUNDOS_ENTRE_TESTES_DA_MESMA_CONEXAO)
    try:
        return EventoIntegracao.objects.filter(
            conexao=conexao_id, acao__in=('teste', 'erro_interno'), criado_em__gte=limite,
        ).exists()
    except DatabaseError:
        return False
