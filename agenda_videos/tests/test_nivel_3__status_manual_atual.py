"""
Nível 3 — ParticipacaoAgenda.status_manual_atual()

DOC usado por calcular_indicadores() (Camada B) — testado aqui na sua
própria camada antes de ser reaproveitado como caixa-preta lá.
"""
import pytest

from agenda_videos.models.participacao_agenda import (
    HistoricoStatusManualAgenda, ParticipacaoAgenda, StatusManualAgenda,
)
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — ParticipacaoAgenda.status_manual_atual()'


def _criar_produto(rotulo):
    return Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo='Produto Teste')


def test_status_manual_atual_sem_historico_e_ativo(tabela_resultados):
    # Setup: participação na agenda, mas nenhum histórico de status manual
    # ainda (nunca foi pausado/descontinuado).
    produto = _criar_produto('sem_historico')
    participacao = ParticipacaoAgenda.objects.create(produto=produto)

    # Exercise: chama o SUT de verdade.
    resultado = participacao.status_manual_atual()

    # Assert: sem histórico, o default é Ativo.
    esperado = StatusManualAgenda.ATIVO
    registrar_resultado(
        tabela_resultados, 'status_manual_atual_sem_historico_e_ativo',
        'ParticipacaoAgenda sem nenhum HistoricoStatusManualAgenda',
        esperado, 'sem histórico registrado, o default é sempre Ativo',
        resultado, resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_status_manual_atual_usa_o_registro_mais_recente(tabela_resultados):
    # Setup: 2 registros de histórico, criados em sequência — o 2º
    # (Pausado) é sempre mais recente que o 1º (Descontinuado), porque
    # alterado_em usa auto_now_add na hora real de cada .create().
    produto = _criar_produto('com_historico')
    participacao = ParticipacaoAgenda.objects.create(produto=produto)
    HistoricoStatusManualAgenda.objects.create(produto=produto, status=StatusManualAgenda.DESCONTINUADO)
    HistoricoStatusManualAgenda.objects.create(produto=produto, status=StatusManualAgenda.PAUSADO)

    # Exercise: chama o SUT de verdade.
    resultado = participacao.status_manual_atual()

    # Assert: pega o ÚLTIMO criado (Pausado), não o primeiro (Descontinuado).
    esperado = StatusManualAgenda.PAUSADO
    registrar_resultado(
        tabela_resultados, 'status_manual_atual_usa_o_registro_mais_recente',
        '2 registros: Descontinuado (1º) -> Pausado (2º, mais recente)',
        esperado, 'ordenado por -alterado_em — sempre o mais recente vale, nunca o primeiro',
        resultado, resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.