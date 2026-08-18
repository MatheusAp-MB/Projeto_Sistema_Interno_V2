# agenda_videos/tests/test_nivel_4__view_alternar_urgente.py

# Função Objetivo: Testa view_alternar_urgente() — Nível 4 (view HTTP real).
# Toggle simples, sem confirmação — cobre criação implícita de
# ParticipacaoAgenda (get_or_create) e o round-trip completo (2 cliques
# voltam ao estado original).
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import ConfiguracaoFase, Fase, ParticipacaoAgenda
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_alternar_urgente(): toggle de urgência via HTTP'


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


def _url(produto_id):
    return reverse('agenda_videos_alternar_urgente', args=[produto_id])


@pytest.fixture
def regua_de_fases():
    trimestral = ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_TRIMESTRAL, periodo_continuo=True,
        distancia_dias_corridos=90, distancia_dias_ao_entrar_na_fase=90,
    )
    mensal = ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_MENSAL, periodo_continuo=False, periodo=4,
        distancia_dias_corridos=30, distancia_dias_ao_entrar_na_fase=0,
        proxima_fase=trimestral,
    )
    ConfiguracaoFase.objects.create(
        fase=Fase.SIMPLES, periodo_continuo=False, periodo=1,
        proxima_fase=mensal,
    )


def test_sem_participacao_toggle_cria_e_marca_urgente(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-001')

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    participacao = ParticipacaoAgenda.objects.filter(produto=produto).first()
    passou = resposta.status_code == 200 and participacao is not None and participacao.urgente is True
    registrar_resultado(
        tabela_resultados, teste='sem ParticipacaoAgenda → toggle cria e marca urgente',
        entrada='produto sem ParticipacaoAgenda', esperado='200, ParticipacaoAgenda criada com urgente=True',
        motivo='get_or_create cria o registro na hora, default urgente=False, primeiro toggle vira True',
        obtido=f'status={resposta.status_code}, participacao_existe={participacao is not None}, urgente={participacao.urgente if participacao else None}',
        passou=passou,
    )
    assert passou


def test_com_participacao_urgente_true_toggle_vira_false(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-002')
    ParticipacaoAgenda.objects.create(produto=produto, urgente=True)

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    participacao = ParticipacaoAgenda.objects.get(produto=produto)
    passou = resposta.status_code == 200 and participacao.urgente is False
    registrar_resultado(
        tabela_resultados, teste='urgente=True → toggle vira False',
        entrada='ParticipacaoAgenda existente, urgente=True', esperado='200, urgente=False',
        motivo='Toggle simples — inverte o valor atual',
        obtido=f'status={resposta.status_code}, urgente={participacao.urgente}',
        passou=passou,
    )
    assert passou


def test_dois_toggles_seguidos_voltam_ao_original(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-003')

    # Exercise:
    client.get(_url(produto.id))
    resposta_2 = client.get(_url(produto.id))

    # Assert:
    participacao = ParticipacaoAgenda.objects.get(produto=produto)
    passou = resposta_2.status_code == 200 and participacao.urgente is False
    registrar_resultado(
        tabela_resultados, teste='2 toggles seguidos → volta ao estado original',
        entrada='produto sem ParticipacaoAgenda, 2 cliques em sequência', esperado='urgente=False (voltou ao default)',
        motivo='Round-trip: False -> True -> False',
        obtido=f'status={resposta_2.status_code}, urgente={participacao.urgente}',
        passou=passou,
    )
    assert passou


def test_produto_inexistente_devolve_404(client, tabela_resultados, regua_de_fases):
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