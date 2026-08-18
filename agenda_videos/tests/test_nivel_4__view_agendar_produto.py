# agenda_videos/tests/test_nivel_4__view_agendar_produto.py

# Função Objetivo: Testa view_agendar_produto() — Nível 4 (view HTTP real).
# Transição formal Simples -> Vídeo Mensal #1. Cobre a trava dupla (fase E
# etapa), o caso sem ciclo nenhum, e a idempotência de agendado_em (marca
# a transição de verdade, nunca sobrescreve se já foi marcada antes).
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import CicloVideo, ConfiguracaoFase, Fase, ParticipacaoAgenda, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_agendar_produto(): Simples → Vídeo Mensal via HTTP'


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


def _url(produto_id):
    return reverse('agenda_videos_agendar_produto', args=[produto_id])


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


def _ciclo_simples_concluido(produto):
    agora = timezone.now()
    return CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
        status=StatusPostagem.REPLICADO, aguardando_aprovacao_em=agora,
        aprovado_ou_recusado_em=agora, replicado_em=agora,
    )


def test_simples_concluido_agenda_com_sucesso(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-001')
    _ciclo_simples_concluido(produto)

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    mensal_1 = CicloVideo.objects.filter(produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1).first()
    participacao = ParticipacaoAgenda.objects.filter(produto=produto).first()
    passou = (
        resposta.status_code == 200 and mensal_1 is not None
        and participacao is not None and participacao.agendado_em is not None
    )
    registrar_resultado(
        tabela_resultados, teste='Simples concluído → agenda com sucesso',
        entrada='CicloVideo Simples com status=Replicado', esperado='cria Vídeo Mensal #1, ParticipacaoAgenda.agendado_em preenchido',
        motivo='Transição formal Simples → Vídeo Mensal, marcando o momento real',
        obtido=f'status={resposta.status_code}, mensal_1_existe={mensal_1 is not None}, agendado_em={participacao.agendado_em if participacao else None}',
        passou=passou,
    )
    assert passou


def test_simples_nao_concluido_e_400_sem_criar_nada(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-002')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    nada_novo = CicloVideo.objects.filter(produto=produto).count() == 1
    sem_participacao = not ParticipacaoAgenda.objects.filter(produto=produto).exists()
    passou = resposta.status_code == 400 and nada_novo and sem_participacao
    registrar_resultado(
        tabela_resultados, teste='Simples não concluído (ainda em Base) → 400',
        entrada='CicloVideo Simples etapa_atual()=base', esperado='400, nenhum ciclo novo, nenhuma ParticipacaoAgenda',
        motivo='Só é possível agendar depois do Simples replicado',
        obtido=f'status={resposta.status_code}, ainda_1_ciclo={nada_novo}, sem_participacao={sem_participacao}',
        passou=passou,
    )
    assert passou


def test_sem_ciclo_nenhum_e_400(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-003')

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='produto nunca tocado (sem ciclo) → 400',
        entrada='produto sem nenhum CicloVideo', esperado='status_code == 400',
        motivo='ciclo is None entra na mesma trava de "não pode agendar ainda"',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_ciclo_concluido_mas_fase_nao_e_simples_e_400(client, tabela_resultados, regua_de_fases):
    # Função Objetivo: prova que a trava confere FASE explicitamente, não
    # só a etapa — um ciclo "concluido" fora da fase Simples (estado que
    # não deveria existir de verdade, mas a view precisa recusar mesmo
    # assim, nunca confiar só na etapa) não pode disparar um agendamento.
    # Setup:
    produto = _criar_produto('SKU-004')
    agora = timezone.now()
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
        status=StatusPostagem.REPLICADO, aguardando_aprovacao_em=agora,
        aprovado_ou_recusado_em=agora, replicado_em=agora,
    )

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='ciclo concluído mas fase=Vídeo Mensal → 400',
        entrada='etapa_atual()=concluido, fase=Vídeo Mensal (não Simples)', esperado='status_code == 400',
        motivo='A trava exige fase==Simples E etapa==concluido — as 2 juntas, nunca só uma',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_agendado_em_ja_preenchido_nao_e_sobrescrito(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-005')
    _ciclo_simples_concluido(produto)
    marco_original = timezone.now() - timezone.timedelta(days=10)
    ParticipacaoAgenda.objects.create(produto=produto, agendado_em=marco_original)

    # Exercise:
    resposta = client.get(_url(produto.id))

    # Assert:
    participacao = ParticipacaoAgenda.objects.get(produto=produto)
    passou = resposta.status_code == 200 and participacao.agendado_em == marco_original
    registrar_resultado(
        tabela_resultados, teste='agendado_em já preenchido → não é sobrescrito',
        entrada='ParticipacaoAgenda já existe com agendado_em de 10 dias atrás', esperado='agendado_em continua o valor original',
        motivo='Idempotente: uma vez agendado, sempre agendado — nunca reseta o marco real',
        obtido=f'status={resposta.status_code}, agendado_em={participacao.agendado_em}',
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