# agenda_videos/tests/test_nivel_4__view_alternar_pausado_agenda.py

# Função Objetivo: Testa view_alternar_pausado_agenda() — Nível 4 (view
# HTTP real). Regressão direta do bug real corrigido em 04/08 (ver
# "Status Manual Atual Ignora Historico Quando Participacao Nao Existe"
# no vault): antes do fix, o botão "Pausar" ficava travado pra qualquer
# produto sem ParticipacaoAgenda — o teste do 2º clique abaixo é
# exatamente o cenário que provava o bug.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import (
    HistoricoStatusManualAgenda, IndicadoresAgendaProduto, ParticipacaoAgenda, StatusManualAgenda,
)
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_alternar_pausado_agenda(): toggle de status manual via HTTP'


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


def _url(produto_id):
    return reverse('agenda_videos_alternar_pausado', args=[produto_id])


def test_sem_participacao_primeiro_toggle_pausa(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-001')

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    historico = resposta.context['historico']
    passou = resposta.status_code == 200 and historico.status_manual_atual.label == 'Pausado'
    registrar_resultado(
        tabela_resultados, teste='sem ParticipacaoAgenda → 1º toggle pausa',
        entrada='produto sem ParticipacaoAgenda, nunca pausado', esperado='200, status_manual_atual.label == "Pausado"',
        motivo='status_manual_atual_do_produto() lê o histórico direto — nunca depende de ParticipacaoAgenda existir',
        obtido=f'status={resposta.status_code}, badge={historico.status_manual_atual}',
        passou=passou,
    )
    assert passou


def test_sem_participacao_segundo_toggle_volta_pra_ativo(client, tabela_resultados):
    # Função Objetivo: ESTE é o cenário exato do bug real corrigido — antes
    # do fix, o 2º clique achava (errado) que o status atual ainda era
    # Ativo, e criava OUTRO registro de Pausado em vez de voltar — o botão
    # ficava travado pra sempre nesse estado.
    # Setup:
    produto = _criar_produto('SKU-002')
    client.get(_url(produto.id))  # 1º clique: pausa

    # Exercise:
    resposta = client.get(_url(produto.id))  # 2º clique: deveria despausar

    # Assert:
    historico = resposta.context['historico']
    total_registros = HistoricoStatusManualAgenda.objects.filter(produto=produto).count()
    passou = (
        resposta.status_code == 200 and historico.status_manual_atual.label == 'Ativo'
        and total_registros == 2
    )
    registrar_resultado(
        tabela_resultados, teste='sem ParticipacaoAgenda → 2º toggle volta pra Ativo (regressão do bug)',
        entrada='produto sem ParticipacaoAgenda, já pausado por 1 clique anterior', esperado='status_manual_atual.label == "Ativo", 2 registros no histórico',
        motivo='Antes do fix, ficava travado sempre criando Pausado — nunca voltava',
        obtido=f'status={resposta.status_code}, badge={historico.status_manual_atual}, total_registros={total_registros}',
        passou=passou,
    )
    assert passou


def test_com_participacao_ativo_toggle_pausa(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-003')
    ParticipacaoAgenda.objects.create(produto=produto)

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    historico = resposta.context['historico']
    passou = resposta.status_code == 200 and historico.status_manual_atual.label == 'Pausado'
    registrar_resultado(
        tabela_resultados, teste='com ParticipacaoAgenda, Ativo → toggle pausa',
        entrada='ParticipacaoAgenda existe, sem histórico ainda', esperado='200, status_manual_atual.label == "Pausado"',
        motivo='Mesmo caminho, agora com ParticipacaoAgenda existindo de verdade',
        obtido=f'status={resposta.status_code}, badge={historico.status_manual_atual}',
        passou=passou,
    )
    assert passou


def test_produto_pausado_toggle_volta_pra_ativo(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-004')
    HistoricoStatusManualAgenda.objects.create(produto=produto, status=StatusManualAgenda.PAUSADO)

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    historico = resposta.context['historico']
    passou = resposta.status_code == 200 and historico.status_manual_atual.label == 'Ativo'
    registrar_resultado(
        tabela_resultados, teste='produto pausado → toggle volta pra Ativo',
        entrada='HistoricoStatusManualAgenda(status=PAUSADO) já existe', esperado='200, status_manual_atual.label == "Ativo"',
        motivo='Toggle simétrico — Pausado vira Ativo',
        obtido=f'status={resposta.status_code}, badge={historico.status_manual_atual}',
        passou=passou,
    )
    assert passou


def test_toggle_sincroniza_o_cache_de_indicadores(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-005')

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    indicadores = IndicadoresAgendaProduto.objects.filter(produto=produto).first()
    passou = resposta.status_code == 200 and indicadores is not None and indicadores.status_manual == StatusManualAgenda.PAUSADO
    registrar_resultado(
        tabela_resultados, teste='toggle sincroniza o cache pra Pausado',
        entrada='produto sem cache prévio, pausa', esperado='IndicadoresAgendaProduto.status_manual == PAUSADO',
        motivo='sincronizar_indicadores_agenda_produto() roda depois de criar o histórico — cache precisa refletir na hora',
        obtido=f'status={resposta.status_code}, status_manual_no_cache={indicadores.status_manual if indicadores else None}',
        passou=passou,
    )
    assert passou


def test_produto_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url(999999))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='produto_id inexistente → 404',
        entrada='produto_id=999999 (não existe)', esperado='status_code == 404',
        motivo='get_object_or_404 precisa disparar 404 de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou