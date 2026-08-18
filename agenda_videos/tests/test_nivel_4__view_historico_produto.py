# agenda_videos/tests/test_nivel_4__view_historico_produto.py

# Função Objetivo: Testa view_historico_produto() — Nível 4 (view HTTP real,
# via client do Django). Primeira view testada assim: requisição de verdade
# (client.get + reverse), em vez de chamar a função Python direto — cobre
# roteamento real (urls.py/reverse) e a mensagem/parcial certos sendo
# devolvidos, coisas que uma chamada direta da função nunca prova.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import CicloVideo, Fase, StatusManualAgenda, HistoricoStatusManualAgenda
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_historico_produto(): modal individual via HTTP'


def _criar_produto(sku='SKU-001'):
    # ean derivado do sku só pra garantir unicidade entre os testes deste
    # arquivo — nenhum teste aqui verifica o valor de ean em si.
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


def test_produto_sem_nenhum_ciclo_renderiza_historico_vazio(client, tabela_resultados):
    # Função Objetivo: produto nunca tocado (0 CicloVideo) é o caso mais
    # comum do catálogo real — a view precisa lidar com ele sem quebrar.
    # Setup:
    produto = _criar_produto()

    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico_produto', args=[produto.id]))

    # Assert:
    historico = resposta.context['historico']
    passou = resposta.status_code == 200 and historico.total == 0 and historico.eventos == []
    registrar_resultado(
        tabela_resultados, teste='produto sem ciclo → histórico vazio, sem erro',
        entrada='produto recém-criado, 0 CicloVideo', esperado='200, total=0, eventos=[]',
        motivo='View não pode quebrar pro caso mais comum (produto nunca tocado)',
        obtido=f'status={resposta.status_code}, total={historico.total}, eventos={historico.eventos}',
        passou=passou,
    )
    assert passou


def test_produto_com_ciclo_em_base_aparece_no_resumo(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-002')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, data_devida=None)

    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico_produto', args=[produto.id]))

    # Assert:
    historico = resposta.context['historico']
    resumo_base = next((r for r in historico.resumo if r.valor == 'base'), None)
    passou = (
        resposta.status_code == 200 and historico.total == 1
        and resumo_base is not None and resumo_base.quantidade == 1
    )
    registrar_resultado(
        tabela_resultados, teste='produto com 1 ciclo em Base → aparece no resumo',
        entrada='1 CicloVideo, etapa_atual=base', esperado='total=1, resumo tem "base" com quantidade=1',
        motivo='Confirma que a view passa o produto certo pra montar_historico_produto',
        obtido=f'total={historico.total}, resumo={historico.resumo}',
        passou=passou,
    )
    assert passou


def test_produto_pausado_reflete_status_manual_atual_no_contexto(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-003')
    HistoricoStatusManualAgenda.objects.create(produto=produto, status=StatusManualAgenda.PAUSADO)

    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico_produto', args=[produto.id]))

    # Assert:
    historico = resposta.context['historico']
    passou = resposta.status_code == 200 and historico.status_manual_atual.label == 'Pausado'
    registrar_resultado(
        tabela_resultados, teste='produto pausado → badge "Pausado" no contexto',
        entrada='1 HistoricoStatusManualAgenda(status=PAUSADO)', esperado='status_manual_atual.label == "Pausado"',
        motivo='Garante que a view não usa um valor cacheado/desatualizado do status manual',
        obtido=f'status_manual_atual={historico.status_manual_atual}',
        passou=passou,
    )
    assert passou


def test_produto_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico_produto', args=[999999]))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='produto_id inexistente → 404',
        entrada='produto_id=999999 (não existe)', esperado='status_code == 404',
        motivo='get_object_or_404 precisa disparar 404 de verdade, não deixar exceção vazar',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou