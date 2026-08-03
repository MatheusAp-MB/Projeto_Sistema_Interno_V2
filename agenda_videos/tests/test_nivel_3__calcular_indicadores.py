"""
Nível 3 — calcular_indicadores()

Monta os 4 indicadores que alimentam o cache IndicadoresAgendaProduto, a
partir das fontes reais (CicloVideo, ParticipacaoAgenda, avaliação de
qualidade do Mercado Livre). DOC etapa_atual()/esta_atrasado() (Nível 2) e
status_manual_atual() (Nível 3, testado à parte) já confiáveis — aqui só
confirmamos passthrough + os casos NOVOS (sem ciclo, sem participação,
com/sem vídeo reprovado).
"""
import pytest

from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import calcular_indicadores
from agenda_videos.models.ciclo_video import CicloVideo
from agenda_videos.models.configuracao_fase import Fase
from agenda_videos.models.participacao_agenda import (
    HistoricoStatusManualAgenda, ParticipacaoAgenda, StatusManualAgenda,
)
from mercado_livre.models.anuncio import AnuncioMercadoLivre
from mercado_livre.models.criterio_qualidade import CriterioQualidade
from mercado_livre.models.qualidade_anuncio import QualidadeAnuncio
from mercado_livre.models.qualidade_anuncio_criterio import QualidadeAnuncioCriterio
from mercado_livre.models.variacao import VariacaoAnuncioMercadoLivre
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — calcular_indicadores()'


def _criar_produto(rotulo, sku=None):
    return Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo='Produto Teste', sku=sku)


def test_calcular_indicadores_sem_ciclo_nenhum(tabela_resultados):
    # Setup: produto novo, nunca entrou na Agenda de Vídeos — 0 CicloVideo.
    produto = _criar_produto('sem_ciclo_nenhum')

    # Exercise: chama o SUT de verdade, passando None explicitamente — é
    # exatamente isso que sincronizar_indicadores_agenda_produto() faz
    # quando produto.ciclos_video.first() não acha nada.
    resultado = calcular_indicadores(produto, None)

    # Assert: caso especial que etapa_atual() isolado nunca produz.
    esperado = ('nao_agendado', '')
    obtido = (resultado.etapa_atual, resultado.fase_atual)
    registrar_resultado(
        tabela_resultados, 'calcular_indicadores_sem_ciclo_nenhum',
        'ciclo_mais_recente=None',
        esperado, 'produto sem nenhum ciclo — etapa e fase ganham valor especial, não vêm de etapa_atual()',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_calcular_indicadores_com_ciclo_passthrough(tabela_resultados):
    # Setup: ciclo real, salvo, sem nenhum campo de produção — etapa='base',
    # sem data_devida — não atrasado.
    produto = _criar_produto('com_ciclo_passthrough')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1)

    # Exercise: chama o SUT de verdade.
    resultado = calcular_indicadores(produto, ciclo)

    # Assert: passthrough direto de DOC já testados (etapa_atual, fase,
    # esta_atrasado) — Nível 2.
    esperado = ('base', 'video_mensal', False)
    obtido = (resultado.etapa_atual, resultado.fase_atual, resultado.ciclo_atual_atrasado)
    registrar_resultado(
        tabela_resultados, 'calcular_indicadores_com_ciclo_passthrough',
        'CicloVideo real, fase=Vídeo Mensal, sem produção nem data_devida',
        esperado, 'passthrough direto de etapa_atual()/fase/esta_atrasado() — DOC já testados no Nível 2',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_calcular_indicadores_sem_participacao_agenda(tabela_resultados):
    # Setup: produto sem NENHUM registro de ParticipacaoAgenda.
    produto = _criar_produto('sem_participacao')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise: chama o SUT de verdade.
    resultado = calcular_indicadores(produto, ciclo)

    # Assert: sem participação, o default Ativo vem direto — nem chega a
    # chamar status_manual_atual().
    esperado = StatusManualAgenda.ATIVO
    registrar_resultado(
        tabela_resultados, 'calcular_indicadores_sem_participacao_agenda',
        'produto sem ParticipacaoAgenda',
        esperado, 'getattr(produto, "participacao_agenda", None) é None — default Ativo direto',
        resultado.status_manual, resultado.status_manual == esperado,
    )
    assert resultado.status_manual == esperado

    # TearDown: nada a desmontar.


def test_calcular_indicadores_com_participacao_usa_historico(tabela_resultados):
    # Setup: produto COM ParticipacaoAgenda e 1 histórico (Pausado) — a
    # regra de "qual status vale" já foi testada isoladamente em
    # status_manual_atual() (Nível 3); aqui só confirma a delegação.
    produto = _criar_produto('com_participacao')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    ParticipacaoAgenda.objects.create(produto=produto)
    HistoricoStatusManualAgenda.objects.create(produto=produto, status=StatusManualAgenda.PAUSADO)

    # Exercise: chama o SUT de verdade.
    resultado = calcular_indicadores(produto, ciclo)

    # Assert: delega pra status_manual_atual(), que já sabemos que funciona.
    esperado = StatusManualAgenda.PAUSADO
    registrar_resultado(
        tabela_resultados, 'calcular_indicadores_com_participacao_usa_historico',
        'produto com ParticipacaoAgenda + histórico Pausado',
        esperado, 'delega pra status_manual_atual() (DOC já testado) — não reimplementa a regra aqui',
        resultado.status_manual, resultado.status_manual == esperado,
    )
    assert resultado.status_manual == esperado

    # TearDown: nada a desmontar.


def test_calcular_indicadores_video_reprovado_false_sem_dados_relacionados(tabela_resultados):
    # Setup: produto sem NENHUMA variação/anúncio/qualidade vinculada — o
    # caso mais comum, não precisa de setup extra.
    produto = _criar_produto('video_reprovado_false')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise: chama o SUT de verdade.
    resultado = calcular_indicadores(produto, ciclo)

    # Assert: sem nenhuma linha de qualidade, a consulta não acha nada —
    # False é o caminho "de graça".
    esperado = False
    registrar_resultado(
        tabela_resultados, 'calcular_indicadores_video_reprovado_false_sem_dados_relacionados',
        'produto sem nenhuma VariacaoAnuncioMercadoLivre/QualidadeAnuncio',
        esperado, 'sem linha relacionada, o .exists() da consulta é sempre False',
        resultado.tem_video_reprovado, resultado.tem_video_reprovado == esperado,
    )
    assert resultado.tem_video_reprovado == esperado

    # TearDown: nada a desmontar.


def test_calcular_indicadores_video_reprovado_true_criterio_reprovado(tabela_resultados):
    # Setup: cadeia real completa — Produto -> AnuncioMercadoLivre ->
    # VariacaoAnuncioMercadoLivre -> QualidadeAnuncio -> QualidadeAnuncioCriterio
    # (critério UP_HAS_SHORTS, status Não aprovado). DOC real, sem dublê —
    # é o próprio critério que _verificar_video_reprovado() procura.
    # produto precisa de sku (não só ean) — a FK de Variacao usa to_field='sku'.
    produto = _criar_produto('video_reprovado_true', sku='SKU900001')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    anuncio = AnuncioMercadoLivre.objects.create(mlb='MLB900000001')
    variacao = VariacaoAnuncioMercadoLivre.objects.create(anuncio=anuncio, variacao_id='1', produto=produto)
    qualidade = QualidadeAnuncio.objects.create(variacao=variacao)
    criterio = CriterioQualidade.objects.create(
        rule_key='UP_HAS_SHORTS', grupo=CriterioQualidade.Grupo.SHORTS,
        nome='Clipes', pergunta='Tem clipe aprovado?',
    )
    QualidadeAnuncioCriterio.objects.create(
        qualidade=qualidade, criterio=criterio, status=QualidadeAnuncioCriterio.Status.NAO_APROVADO,
    )

    # Exercise: chama o SUT de verdade.
    resultado = calcular_indicadores(produto, ciclo)

    # Assert: agora existe 1 linha reprovada pra esse critério — True.
    esperado = True
    registrar_resultado(
        tabela_resultados, 'calcular_indicadores_video_reprovado_true_criterio_reprovado',
        'critério UP_HAS_SHORTS avaliado como Não aprovado',
        esperado, 'existe avaliação reprovada pra esse critério nesse produto — .exists() vira True',
        resultado.tem_video_reprovado, resultado.tem_video_reprovado == esperado,
    )
    assert resultado.tem_video_reprovado == esperado

    # TearDown: nada a desmontar.