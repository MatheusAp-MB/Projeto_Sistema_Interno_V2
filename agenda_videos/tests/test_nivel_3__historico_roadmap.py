# agenda_videos/tests/test_nivel_3__historico_roadmap.py

# Função Objetivo: Nível 3 — cobre montar_linha_do_tempo_produto() e
# montar_historico_produto(), de agenda_videos/funcoes_auxiliares/
# historico_roadmap.py. As duas tocam banco de verdade
# (produto.ciclos_video), por isso não têm fatia Nível 0/2 — diferente de
# roadmap_produto.py, aqui não existe função pura isolável.
# listar_produtos_com_historico() fica pra uma rodada separada (7 filtros
# diferentes, merece arquivo próprio).

from datetime import datetime

import pytest
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.historico_roadmap import (
    EventoHistorico, ResumoEtapa, TipoEventoHistorico,
    montar_historico_produto, montar_linha_do_tempo_produto,
)
from agenda_videos.funcoes_auxiliares.badges_agenda import buscar_badge_de, BADGES_ETAPA, BADGES_STATUS_POSTAGEM
from agenda_videos.models import CicloVideo, Fase, ParticipacaoAgenda, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 3 — historico_roadmap (montar_linha_do_tempo_produto / montar_historico_produto)'


def _criar_produto(rotulo, titulo='Produto Teste'):
    # Função Objetivo: EAN curto único por rótulo — o valor em si nunca é
    # verificado por estes testes, só precisa existir e não colidir.
    return Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo=titulo)


# ===================================================================
# montar_linha_do_tempo_produto — 9 casos: os 6 tipos de marco possíveis,
# o evento de "entrada na agenda", ordenação cronológica entre ciclos
# diferentes, e desempate determinístico quando 2 eventos empatam no
# timestamp exato.
# ===================================================================

def test_linha_do_tempo_sem_participacao_e_sem_ciclos(tabela_resultados):
    # Setup: produto sem ParticipacaoAgenda e sem nenhum CicloVideo.
    produto = _criar_produto('sem_participacao_e_sem_ciclos')

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, 'sem_participacao_e_sem_ciclos',
        'Produto sem ParticipacaoAgenda, sem CicloVideo',
        '0 eventos', 'Nada pra mostrar — nem entrada na agenda nem marco de produção.',
        f'{len(resultado.eventos)} evento(s)', resultado.eventos == [],
    )
    assert resultado.eventos == []

    # TearDown: nada a desmontar.


def test_linha_do_tempo_com_participacao_e_agendado_em(tabela_resultados):
    # Setup: produto com ParticipacaoAgenda.agendado_em preenchido.
    produto = _criar_produto('com_participacao_e_agendado_em')
    momento = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
    ParticipacaoAgenda.objects.create(produto=produto, agendado_em=momento)

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    esperado = [EventoHistorico(
        timestamp=momento, label='Agendado — Vídeo Mensal Iniciado',
        tipo=TipoEventoHistorico.MARCO, icone='fa-calendar-check',
    )]
    registrar_resultado(
        tabela_resultados, 'com_participacao_e_agendado_em',
        'ParticipacaoAgenda.agendado_em preenchido',
        "1 evento 'Agendado — Vídeo Mensal Iniciado'",
        'Participação existe E agendado_em preenchido — as 2 condições precisam ser verdadeiras.',
        f'{len(resultado.eventos)} evento(s)', resultado.eventos == esperado,
    )
    assert resultado.eventos == esperado

    # TearDown: nada a desmontar.


def test_linha_do_tempo_com_participacao_sem_agendado_em(tabela_resultados):
    # Setup: produto com ParticipacaoAgenda, mas agendado_em vazio.
    produto = _criar_produto('com_participacao_sem_agendado_em')
    ParticipacaoAgenda.objects.create(produto=produto, agendado_em=None)

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, 'com_participacao_sem_agendado_em',
        'ParticipacaoAgenda existe, agendado_em=None',
        '0 eventos',
        'Participação existe mas agendado_em vazio — a condição "participacao and participacao.agendado_em" falha na 2ª parte.',
        f'{len(resultado.eventos)} evento(s)', resultado.eventos == [],
    )
    assert resultado.eventos == []

    # TearDown: nada a desmontar.


def test_linha_do_tempo_ciclo_so_com_base(tabela_resultados):
    # Setup: 1 CicloVideo só com Base concluída.
    produto = _criar_produto('ciclo_so_com_base')
    momento = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, base_concluido_em=momento,
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    esperado = [EventoHistorico(
        timestamp=momento, label='Base concluída (Simples)',
        tipo=TipoEventoHistorico.MARCO, icone='fa-video',
    )]
    registrar_resultado(
        tabela_resultados, 'ciclo_so_com_base',
        'CicloVideo Simples#1, só base_concluido_em preenchido',
        "1 evento 'Base concluída (Simples)'",
        'Só o campo preenchido vira evento — os outros 5 ifs não batem.',
        f'{len(resultado.eventos)} evento(s)', resultado.eventos == esperado,
    )
    assert resultado.eventos == esperado

    # TearDown: nada a desmontar.


def test_linha_do_tempo_ciclo_com_todas_as_6_marcas_aprovado(tabela_resultados):
    # Setup: 1 CicloVideo com as 6 marcas preenchidas, status=Aprovado.
    produto = _criar_produto('ciclo_com_todas_as_6_marcas_aprovado')
    t1 = timezone.make_aware(datetime(2026, 1, 1, 8, 0))
    t2 = timezone.make_aware(datetime(2026, 1, 2, 8, 0))
    t3 = timezone.make_aware(datetime(2026, 1, 3, 8, 0))
    t4 = timezone.make_aware(datetime(2026, 1, 4, 8, 0))
    t5 = timezone.make_aware(datetime(2026, 1, 5, 8, 0))
    t6 = timezone.make_aware(datetime(2026, 1, 6, 8, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=t1, roteiro_concluido_em=t2, completo_concluido_em=t3,
        aguardando_aprovacao_em=t4, aprovado_ou_recusado_em=t5, status=StatusPostagem.APROVADO,
        replicado_em=t6, mlbs_replicados=[], mlbs_nao_encontrados=[],
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    esperado = [
        EventoHistorico(timestamp=t1, label='Base concluída (Simples)', tipo=TipoEventoHistorico.MARCO, icone='fa-video'),
        EventoHistorico(timestamp=t2, label='Roteiro concluído (Simples)', tipo=TipoEventoHistorico.MARCO, icone='fa-pen'),
        EventoHistorico(timestamp=t3, label='Completo concluído (Simples)', tipo=TipoEventoHistorico.MARCO, icone='fa-film'),
        EventoHistorico(timestamp=t4, label='Simples — Postado', tipo=TipoEventoHistorico.AGUARDANDO_APROVACAO, icone='fa-upload'),
        EventoHistorico(timestamp=t5, label='Simples — Aprovado', tipo=TipoEventoHistorico.APROVADO, icone='fa-gavel'),
        EventoHistorico(
            timestamp=t6, label='Simples — Replicado', tipo=TipoEventoHistorico.REPLICADO, icone='fa-copy',
            mlbs_replicados=[], mlbs_nao_encontrados=[],
        ),
    ]
    registrar_resultado(
        tabela_resultados, 'ciclo_com_todas_as_6_marcas_aprovado',
        'CicloVideo com as 6 marcas + status=Aprovado',
        '6 eventos, nessa ordem cronológica',
        'Cada campo preenchido vira 1 evento — status=Aprovado usa o branch "else" (tipo=APROVADO, ação=Aprovado).',
        f'{len(resultado.eventos)} evento(s)', resultado.eventos == esperado,
    )
    assert resultado.eventos == esperado

    # TearDown: nada a desmontar.


def test_linha_do_tempo_ciclo_recusado_gera_evento_recusado(tabela_resultados):
    # Setup: 1 CicloVideo recusado — produção completa + aguardando +
    # recusado, sem replicado_em (recusado nunca chega no Replicar).
    produto = _criar_produto('ciclo_recusado_gera_evento_recusado')
    t1 = timezone.make_aware(datetime(2026, 1, 1, 8, 0))
    t2 = timezone.make_aware(datetime(2026, 1, 2, 8, 0))
    t3 = timezone.make_aware(datetime(2026, 1, 3, 8, 0))
    t4 = timezone.make_aware(datetime(2026, 1, 4, 8, 0))
    t5 = timezone.make_aware(datetime(2026, 1, 5, 8, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=t1, roteiro_concluido_em=t2, completo_concluido_em=t3,
        aguardando_aprovacao_em=t4, aprovado_ou_recusado_em=t5, status=StatusPostagem.RECUSADO,
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    ultimo_evento = resultado.eventos[-1]
    esperado_ultimo = EventoHistorico(
        timestamp=t5, label='Simples — Recusado', tipo=TipoEventoHistorico.RECUSADO, icone='fa-gavel',
    )
    registrar_resultado(
        tabela_resultados, 'ciclo_recusado_gera_evento_recusado',
        'CicloVideo com status=Recusado (branch "if" do RECUSADO)',
        "último evento = 'Simples — Recusado', tipo=RECUSADO",
        'status=Recusado usa o branch "if" (tipo=RECUSADO, ação=Recusado) — diferente do caso Aprovado (branch "else").',
        f'{len(resultado.eventos)} evento(s), último={ultimo_evento}',
        len(resultado.eventos) == 5 and ultimo_evento == esperado_ultimo,
    )
    assert len(resultado.eventos) == 5
    assert ultimo_evento == esperado_ultimo

    # TearDown: nada a desmontar.


def test_linha_do_tempo_ciclo_replicado_carrega_mlbs(tabela_resultados):
    # Setup: 1 CicloVideo replicado, com MLBs replicados e não encontrados.
    produto = _criar_produto('ciclo_replicado_carrega_mlbs')
    momento = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, replicado_em=momento,
        mlbs_replicados=['MLB111', 'MLB222'], mlbs_nao_encontrados=['MLB333'],
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    esperado = [EventoHistorico(
        timestamp=momento, label='Simples — Replicado', tipo=TipoEventoHistorico.REPLICADO, icone='fa-copy',
        mlbs_replicados=['MLB111', 'MLB222'], mlbs_nao_encontrados=['MLB333'],
    )]
    registrar_resultado(
        tabela_resultados, 'ciclo_replicado_carrega_mlbs',
        "replicado_em preenchido, mlbs_replicados=['MLB111','MLB222'], mlbs_nao_encontrados=['MLB333']",
        'evento carrega as 2 listas junto',
        'O evento de Replicado é o único que carrega mlbs_replicados/mlbs_nao_encontrados — os outros 5 tipos não têm esses campos.',
        f'{resultado.eventos}', resultado.eventos == esperado,
    )
    assert resultado.eventos == esperado

    # TearDown: nada a desmontar.


def test_linha_do_tempo_dois_ciclos_ordenados_cronologicamente(tabela_resultados):
    # Setup: 2 ciclos (Simples e Vídeo Mensal#1) com eventos entremeados —
    # Simples termina Roteiro DEPOIS do Mensal#1 ter concluído Base.
    produto = _criar_produto('dois_ciclos_ordenados_cronologicamente')
    simples_base = timezone.make_aware(datetime(2026, 1, 1, 8, 0))
    mensal_base = timezone.make_aware(datetime(2026, 1, 2, 8, 0))
    mensal_roteiro = timezone.make_aware(datetime(2026, 1, 3, 8, 0))
    simples_roteiro = timezone.make_aware(datetime(2026, 1, 4, 8, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=simples_base, roteiro_concluido_em=simples_roteiro,
    )
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em=mensal_base, roteiro_concluido_em=mensal_roteiro,
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    esperado = [
        EventoHistorico(timestamp=simples_base, label='Base concluída (Simples)', tipo=TipoEventoHistorico.MARCO, icone='fa-video'),
        EventoHistorico(timestamp=mensal_base, label='Base concluída (Vídeo Mensal #1)', tipo=TipoEventoHistorico.MARCO, icone='fa-video'),
        EventoHistorico(timestamp=mensal_roteiro, label='Roteiro concluído (Vídeo Mensal #1)', tipo=TipoEventoHistorico.MARCO, icone='fa-pen'),
        EventoHistorico(timestamp=simples_roteiro, label='Roteiro concluído (Simples)', tipo=TipoEventoHistorico.MARCO, icone='fa-pen'),
    ]
    rotulos_na_ordem = [evento.label for evento in resultado.eventos]
    registrar_resultado(
        tabela_resultados, 'dois_ciclos_ordenados_cronologicamente',
        '2 ciclos com eventos entremeados no tempo',
        f'{[e.label for e in esperado]}',
        'A ordenação final é por timestamp GLOBAL — mistura eventos de ciclos diferentes, nunca agrupa por ciclo primeiro.',
        f'{rotulos_na_ordem}', resultado.eventos == esperado,
    )
    assert resultado.eventos == esperado

    # TearDown: nada a desmontar.


def test_linha_do_tempo_dois_ciclos_timestamps_empatados_ordem_deterministica(tabela_resultados):
    # Setup: 2 ciclos, 1 evento cada, com o MESMO timestamp exato de
    # propósito — prova que a ordem de saída é sempre a mesma (ciclo criado
    # primeiro aparece primeiro), graças ao order_by('criado_em', 'id') +
    # sort() estável do Python.
    produto = _criar_produto('dois_ciclos_timestamps_empatados')
    momento = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
    ciclo_simples = CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, base_concluido_em=momento,
    )
    ciclo_mensal = CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, base_concluido_em=momento,
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_linha_do_tempo_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    esperado = [
        EventoHistorico(timestamp=momento, label='Base concluída (Simples)', tipo=TipoEventoHistorico.MARCO, icone='fa-video'),
        EventoHistorico(timestamp=momento, label='Base concluída (Vídeo Mensal #1)', tipo=TipoEventoHistorico.MARCO, icone='fa-video'),
    ]
    rotulos_na_ordem = [evento.label for evento in resultado.eventos]
    registrar_resultado(
        tabela_resultados, 'dois_ciclos_timestamps_empatados_ordem_deterministica',
        f'2 ciclos, mesmo timestamp={momento}, ciclo_simples criado antes (id menor)',
        f'{[e.label for e in esperado]} — sempre nessa ordem',
        'Timestamps IDÊNTICOS de propósito — sem o order_by(criado_em, id) no laço de ciclos, a ordem relativa seria indefinida.',
        f'{rotulos_na_ordem}', resultado.eventos == esperado,
    )
    assert resultado.eventos == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# montar_historico_produto — 6 casos: vazio, badge por status vs por
# etapa, agrupamento do resumo por etapa (mesmo com status diferente), e
# ordenação (clara + empate) do mais recente primeiro.
# ===================================================================

def test_historico_produto_sem_nenhum_ciclo(tabela_resultados):
    # Setup: produto sem nenhum CicloVideo.
    produto = _criar_produto('historico_sem_nenhum_ciclo')

    # Exercise: chama o SUT de verdade.
    resultado = montar_historico_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    passou = resultado.total == 0 and resultado.ciclos == [] and resultado.resumo == []
    registrar_resultado(
        tabela_resultados, 'historico_sem_nenhum_ciclo',
        'Produto sem nenhum CicloVideo',
        'total=0, ciclos=[], resumo=[]',
        'Sem ciclo nenhum, tudo fica vazio — nenhuma etapa pra contar no resumo.',
        f'total={resultado.total}, ciclos={resultado.ciclos}, resumo={resultado.resumo}',
        passou,
    )
    assert resultado.total == 0
    assert resultado.ciclos == []
    assert resultado.resumo == []

    # TearDown: nada a desmontar.


def test_historico_produto_ciclo_com_status_usa_badge_de_status(tabela_resultados):
    # Setup: 1 CicloVideo com status preenchido (Aprovado).
    produto = _criar_produto('ciclo_com_status_usa_badge_de_status')
    momento = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=momento, roteiro_concluido_em=momento, completo_concluido_em=momento,
        status=StatusPostagem.APROVADO,
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_historico_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    badge_esperado = buscar_badge_de(BADGES_STATUS_POSTAGEM, StatusPostagem.APROVADO)
    badge_obtido = resultado.ciclos[0].badge
    registrar_resultado(
        tabela_resultados, 'ciclo_com_status_usa_badge_de_status',
        'CicloVideo com status=Aprovado',
        f"badge='{badge_esperado.label}' (vem de BADGES_STATUS_POSTAGEM)",
        'ciclo.status é truthy — usa BADGES_STATUS_POSTAGEM, nunca BADGES_ETAPA, mesmo a etapa sendo "replicar".',
        f"badge='{badge_obtido.label}'", badge_obtido == badge_esperado,
    )
    assert badge_obtido == badge_esperado

    # TearDown: nada a desmontar.


def test_historico_produto_ciclo_sem_status_usa_badge_de_etapa(tabela_resultados):
    # Setup: 1 CicloVideo sem status — só Base concluída (etapa='roteiro').
    produto = _criar_produto('ciclo_sem_status_usa_badge_de_etapa')
    momento = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, base_concluido_em=momento,
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_historico_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    badge_esperado = buscar_badge_de(BADGES_ETAPA, 'roteiro')
    badge_obtido = resultado.ciclos[0].badge
    registrar_resultado(
        tabela_resultados, 'ciclo_sem_status_usa_badge_de_etapa',
        'CicloVideo sem status, etapa_atual()="roteiro"',
        f"badge='{badge_esperado.label}' (vem de BADGES_ETAPA)",
        'ciclo.status é None (falsy) — usa BADGES_ETAPA com a etapa atual.',
        f"badge='{badge_obtido.label}'", badge_obtido == badge_esperado,
    )
    assert badge_obtido == badge_esperado

    # TearDown: nada a desmontar.


def test_historico_produto_resumo_agrupa_por_etapa_mesmo_com_status_diferente(tabela_resultados):
    # Setup: 2 CicloVideo que caem na MESMA etapa_atual()='completo' por
    # caminhos diferentes — 1 sem status (completo ainda pendente), 1
    # recusado (completo concluído, mas volta pra "completo").
    produto = _criar_produto('resumo_agrupa_por_etapa')
    momento = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=momento, roteiro_concluido_em=momento,
    )
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em=momento, roteiro_concluido_em=momento, completo_concluido_em=momento,
        status=StatusPostagem.RECUSADO,
    )

    # Exercise: chama o SUT de verdade.
    resultado = montar_historico_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    badge_etapa = buscar_badge_de(BADGES_ETAPA, 'completo')
    esperado_resumo = [ResumoEtapa(valor='completo', label=badge_etapa.label, classe=badge_etapa.classe, quantidade=2)]
    registrar_resultado(
        tabela_resultados, 'resumo_agrupa_por_etapa_mesmo_com_status_diferente',
        '2 ciclos, ambos etapa_atual()="completo" (1 sem status, 1 recusado)',
        f"resumo=[ResumoEtapa(valor='completo', label='{badge_etapa.label}', quantidade=2)]",
        'O resumo agrupa por ETAPA sempre via BADGES_ETAPA — nunca mistura com o rótulo de status individual de cada ciclo.',
        f'{resultado.resumo}', resultado.resumo == esperado_resumo,
    )
    assert resultado.resumo == esperado_resumo

    # TearDown: nada a desmontar.


def test_historico_produto_ordenacao_timestamps_claramente_diferentes(tabela_resultados):
    # Setup: 2 ciclos, criado_em forçado bem diferente.
    produto = _criar_produto('ordenacao_timestamps_claramente_diferentes')
    ciclo_antigo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    ciclo_recente = CicloVideo.objects.create(produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1)
    CicloVideo.objects.filter(pk=ciclo_antigo.pk).update(criado_em=timezone.make_aware(datetime(2026, 1, 1)))
    CicloVideo.objects.filter(pk=ciclo_recente.pk).update(criado_em=timezone.make_aware(datetime(2026, 6, 1)))

    # Exercise: chama o SUT de verdade.
    resultado = montar_historico_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, 'ordenacao_timestamps_claramente_diferentes',
        'ciclo_antigo (01/2026) e ciclo_recente (06/2026)',
        'ciclos[0] = ciclo_recente (Vídeo Mensal#1)',
        'order_by("-criado_em", "-id") — mais recente primeiro, sem ambiguidade nesse caso.',
        f'ciclos[0].fase={resultado.ciclos[0].fase!r}', resultado.ciclos[0].pk == ciclo_recente.pk,
    )
    assert resultado.ciclos[0].pk == ciclo_recente.pk

    # TearDown: nada a desmontar.


def test_historico_produto_ordenacao_timestamps_empatados_desempate_por_id(tabela_resultados):
    # Setup: 2 ciclos, criado_em IDÊNTICO de propósito — só o desempate por
    # -id garante o mais recente (criado por último, id maior) primeiro.
    produto = _criar_produto('ordenacao_timestamps_empatados')
    ciclo_antigo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    ciclo_recente = CicloVideo.objects.create(produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1)
    momento_empatado = timezone.make_aware(datetime(2026, 1, 1, 12, 0))
    CicloVideo.objects.filter(pk=ciclo_antigo.pk).update(criado_em=momento_empatado)
    CicloVideo.objects.filter(pk=ciclo_recente.pk).update(criado_em=momento_empatado)

    # Exercise: chama o SUT de verdade.
    resultado = montar_historico_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, 'ordenacao_timestamps_empatados_desempate_por_id',
        f'ciclo_antigo e ciclo_recente com criado_em IDÊNTICO ({momento_empatado})',
        'ciclos[0] = ciclo_recente (id maior, criado por último)',
        'Timestamps empatados de propósito (simula o empate real, comum no Windows) — só "-id" desempata certo.',
        f'ciclos[0].pk={resultado.ciclos[0].pk}, ciclo_recente.pk={ciclo_recente.pk}',
        resultado.ciclos[0].pk == ciclo_recente.pk,
    )
    assert resultado.ciclos[0].pk == ciclo_recente.pk

    # TearDown: nada a desmontar.