# agenda_videos/tests/test_nivel_3__roadmap_produto.py

# Função Objetivo: Nível 3 — cobre _montar_caminho_completo_fases() e
# calcular_roadmap_produto(), de agenda_videos/funcoes_auxiliares/
# roadmap_produto.py — tocam banco de verdade (ConfiguracaoFase e
# CicloVideo). 3ª e última rodada desse arquivo (1ª foi Nível 0, 2ª foi
# Nível 2). Como as peças de baixo (_montar_caminho_completo_fases,
# _localizar_indice_atual, _montar_etapas_rodada_atual) já foram testadas
# nas rodadas anteriores, calcular_roadmap_produto só é testado aqui no que
# é NOVO nesse nível: a query do ciclo mais recente e a inserção do ponto
# extra "Agendar".

from datetime import date, datetime

import pytest
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    _PontoCaminho, _montar_caminho_completo_fases, calcular_roadmap_produto,
)
from agenda_videos.models import CicloVideo, ConfiguracaoFase, Fase, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — roadmap_produto (_montar_caminho_completo_fases / calcular_roadmap_produto)'

PRODUCAO_CONCLUIDA_EM = timezone.make_aware(datetime(2026, 1, 1, 12, 0))  # fixo — etapa_atual só olha is None, não o valor


@pytest.fixture
def regua_de_fases():
    # Setup: monta a régua real (Simples -> Vídeo Mensal -> Vídeo Trimestral)
    # como ConfiguracaoFase de verdade no banco de teste — duplicada de
    # test_nivel_3__criar_proximo.py de propósito (mesmos valores), pra não
    # editar arquivo já existente sem autorização.
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


# ===================================================================
# _montar_caminho_completo_fases — 2 casos: régua real completa (percorre
# fase finita -> fase finita -> fase contínua, cobrindo periodo_continuo
# True/False) e régua quebrada (fase finita sem próxima configurada —
# branch "proxima is None: break" que a régua real nunca visita).
# ===================================================================

def test_montar_caminho_completo_fases_regua_real(regua_de_fases, tabela_resultados):
    # Setup: regua_de_fases (fixture) já criou a régua completa no banco.

    # Exercise: chama o SUT de verdade.
    resultado = _montar_caminho_completo_fases()

    # Assert: registra antes de comparar, depois compara de verdade.
    esperado_pontos = [
        _PontoCaminho(fase=Fase.SIMPLES, numero=1),
        _PontoCaminho(fase=Fase.VIDEO_MENSAL, numero=1),
        _PontoCaminho(fase=Fase.VIDEO_MENSAL, numero=2),
        _PontoCaminho(fase=Fase.VIDEO_MENSAL, numero=3),
        _PontoCaminho(fase=Fase.VIDEO_MENSAL, numero=4),
        _PontoCaminho(fase=Fase.VIDEO_TRIMESTRAL, numero=None),
    ]
    esperado_aviso = (
        'Depois da #4, entra a fase Vídeo Trimestral (a cada 90 dias, pra sempre) — nunca conclui.'
    )
    passou = resultado.pontos == esperado_pontos and resultado.aviso_transicao_continua == esperado_aviso
    registrar_resultado(
        tabela_resultados, 'regua_real_completa',
        'Simples(periodo=1) -> Vídeo Mensal(periodo=4) -> Vídeo Trimestral(contínua)',
        f'{len(esperado_pontos)} pontos, aviso preenchido',
        'Régua real e completa — cada fase finita aponta pra próxima, a última é contínua. Percorre a régua inteira até achar o ponto contínuo.',
        f'{len(resultado.pontos)} pontos, aviso={"preenchido" if resultado.aviso_transicao_continua else "vazio"}',
        passou,
    )
    assert resultado.pontos == esperado_pontos
    assert resultado.aviso_transicao_continua == esperado_aviso

    # TearDown: nada a desmontar — Django reverte a transação de teste sozinho.


def test_montar_caminho_completo_fases_regua_quebrada(tabela_resultados):
    # Setup: régua quebrada de propósito — só Simples, sem próxima fase
    # configurada e sem ser contínua (config incompleta/inválida). Não usa a
    # fixture regua_de_fases — precisa de um banco só com esse 1 registro.
    ConfiguracaoFase.objects.create(fase=Fase.SIMPLES, periodo_continuo=False, periodo=1)

    # Exercise: chama o SUT de verdade.
    resultado = _montar_caminho_completo_fases()

    # Assert: registra antes de comparar, depois compara de verdade.
    esperado_pontos = [_PontoCaminho(fase=Fase.SIMPLES, numero=1)]
    passou = resultado.pontos == esperado_pontos and resultado.aviso_transicao_continua == ''
    registrar_resultado(
        tabela_resultados, 'regua_quebrada_sem_proxima_fase',
        'Simples(periodo=1), proxima_fase=None, não contínua',
        '1 ponto, aviso vazio',
        'Régua incompleta (fase finita sem próxima configurada) — a função para no lugar, sem travar nem lançar erro, e sem aviso (nunca chegou numa fase contínua).',
        f'{len(resultado.pontos)} ponto(s), aviso={"preenchido" if resultado.aviso_transicao_continua else "vazio"}',
        passou,
    )
    assert resultado.pontos == esperado_pontos
    assert resultado.aviso_transicao_continua == ''

    # TearDown: nada a desmontar.


# ===================================================================
# calcular_roadmap_produto — só o que é NOVO neste nível (as peças de baixo
# já foram testadas nas rodadas anteriores): query do ciclo mais recente, e
# a inserção condicional do ponto extra "Agendar".
# ===================================================================

def test_calcular_roadmap_produto_sem_ciclo_nenhum(regua_de_fases, tabela_resultados):
    # Setup: produto novo, sem nenhum CicloVideo salvo no banco.
    produto = Produto.objects.create(ean='EAN000001', titulo='Produto Sem Ciclo')

    # Exercise: chama o SUT de verdade.
    resultado = calcular_roadmap_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade — confere
    # também que NADA foi escrito no banco só de montar a tela, e que a
    # legenda vem vazia (Simples nunca tem data_devida, cai no else).
    contagem_ciclos_no_banco = CicloVideo.objects.filter(produto=produto).count()
    passou = (
        resultado.rodada_atual_id == 'simples_1'
        and resultado.rodada_atual_legenda == ''
        and contagem_ciclos_no_banco == 0
    )
    registrar_resultado(
        tabela_resultados, 'produto_sem_nenhum_ciclo_video',
        'Produto novo, 0 CicloVideo no banco',
        "rodada_atual_id='simples_1', legenda='', 0 CicloVideo no banco",
        'Sem nenhum ciclo salvo, a função monta um Simples#1 EM MEMÓRIA só pra exibir — nunca cria nada no banco só de olhar a tela. Simples nunca vence, então a legenda cai no else (vazia).',
        f'rodada_atual_id={resultado.rodada_atual_id!r}, legenda={resultado.rodada_atual_legenda!r}, {contagem_ciclos_no_banco} CicloVideo no banco',
        passou,
    )
    assert resultado.rodada_atual_id == 'simples_1'
    assert resultado.rodada_atual_legenda == ''
    assert contagem_ciclos_no_banco == 0

    # TearDown: nada a desmontar.


@pytest.mark.parametrize(
    'rotulo, criado_em_antigo, criado_em_recente, motivo',
    [
        (
            'timestamps_claramente_diferentes',
            datetime(2026, 1, 1), datetime(2026, 6, 1),
            'Timestamps bem distintos — nenhuma ambiguidade, o mais recente por data já é suficiente.',
        ),
        (
            'timestamps_empatados_desempate_por_id',
            datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 12, 0),
            'Timestamps IDÊNTICOS de propósito (simula o empate real, comum no Windows) — só o desempate por id (ciclo_recente criado depois, id maior) garante escolher o certo. Prova a correção em order_by("criado_em", "id").',
        ),
    ],
    ids=['timestamps_claramente_diferentes', 'timestamps_empatados_desempate_por_id'],
)
def test_calcular_roadmap_produto_pega_ciclo_mais_recente(
    regua_de_fases, rotulo, criado_em_antigo, criado_em_recente, motivo, tabela_resultados,
):
    # Setup: produto com 2 CicloVideo salvos — criado_em forçado
    # explicitamente (nunca a hora real de criação), tanto no caso normal
    # quanto no caso de empate proposital, pra provar que
    # order_by('criado_em', 'id') desempata certo (ciclo_recente tem id
    # maior, criado depois de ciclo_antigo).
    produto = Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo='Produto Dois Ciclos')
    ciclo_antigo = CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=PRODUCAO_CONCLUIDA_EM, roteiro_concluido_em=PRODUCAO_CONCLUIDA_EM,
        completo_concluido_em=PRODUCAO_CONCLUIDA_EM, status=StatusPostagem.REPLICADO,
    )
    ciclo_recente = CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
    )
    CicloVideo.objects.filter(pk=ciclo_antigo.pk).update(criado_em=timezone.make_aware(criado_em_antigo))
    CicloVideo.objects.filter(pk=ciclo_recente.pk).update(criado_em=timezone.make_aware(criado_em_recente))

    # Exercise: chama o SUT de verdade.
    resultado = calcular_roadmap_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, rotulo,
        f'ciclo_antigo(Simples, criado_em={criado_em_antigo}, id menor), ciclo_recente(Vídeo Mensal#1, criado_em={criado_em_recente}, id maior)',
        "rodada_atual_id='video_mensal_1'",
        motivo,
        f'rodada_atual_id={resultado.rodada_atual_id!r}',
        resultado.rodada_atual_id == 'video_mensal_1',
    )
    assert resultado.rodada_atual_id == 'video_mensal_1'

    # TearDown: nada a desmontar.


def test_calcular_roadmap_produto_ponto_agendar_aparece(regua_de_fases, tabela_resultados):
    # Setup: Simples já replicado, Vídeo Mensal#1 ainda não criado.
    produto = Produto.objects.create(ean='EAN000003', titulo='Produto Aguardando Agendar')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=PRODUCAO_CONCLUIDA_EM, roteiro_concluido_em=PRODUCAO_CONCLUIDA_EM,
        completo_concluido_em=PRODUCAO_CONCLUIDA_EM, status=StatusPostagem.REPLICADO,
    )

    # Exercise: chama o SUT de verdade.
    resultado = calcular_roadmap_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    ids_das_rodadas = [rodada.id for rodada in resultado.rodadas]
    passou = 'agendar' in ids_das_rodadas and ids_das_rodadas[1] == 'agendar'
    registrar_resultado(
        tabela_resultados, 'ponto_agendar_aparece_apos_simples_replicado',
        'Simples#1 replicado, sem Vídeo Mensal#1 ainda',
        "'agendar' presente, na posição 1",
        'Janela específica: Simples concluído mas próxima fase ainda não criada — ponto extra clicável "Agendar" aparece logo depois do Simples.',
        f'ids={ids_das_rodadas}',
        passou,
    )
    assert 'agendar' in ids_das_rodadas
    assert ids_das_rodadas[1] == 'agendar'

    # TearDown: nada a desmontar.


@pytest.mark.parametrize(
    'rotulo, criado_em_simples, criado_em_mensal, motivo',
    [
        (
            'timestamps_claramente_diferentes',
            datetime(2026, 1, 1), datetime(2026, 6, 1),
            'Timestamps bem distintos — o Vídeo Mensal#1 é claramente o mais recente.',
        ),
        (
            'timestamps_empatados_desempate_por_id',
            datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 12, 0),
            'Timestamps IDÊNTICOS de propósito — só o desempate por id garante que o Mensal#1 (criado depois, id maior) vença, escondendo o ponto "Agendar" corretamente mesmo no empate.',
        ),
    ],
    ids=['timestamps_claramente_diferentes', 'timestamps_empatados_desempate_por_id'],
)
def test_calcular_roadmap_produto_ponto_agendar_nao_aparece(
    regua_de_fases, rotulo, criado_em_simples, criado_em_mensal, motivo, tabela_resultados,
):
    # Setup: Simples replicado E Vídeo Mensal#1 já criado (produto já foi
    # agendado) — criado_em forçado, tanto no caso normal quanto no empate
    # proposital.
    produto = Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo='Produto Ja Agendado')
    ciclo_simples = CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=PRODUCAO_CONCLUIDA_EM, roteiro_concluido_em=PRODUCAO_CONCLUIDA_EM,
        completo_concluido_em=PRODUCAO_CONCLUIDA_EM, status=StatusPostagem.REPLICADO,
    )
    ciclo_mensal = CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
    )
    CicloVideo.objects.filter(pk=ciclo_simples.pk).update(criado_em=timezone.make_aware(criado_em_simples))
    CicloVideo.objects.filter(pk=ciclo_mensal.pk).update(criado_em=timezone.make_aware(criado_em_mensal))

    # Exercise: chama o SUT de verdade.
    resultado = calcular_roadmap_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    ids_das_rodadas = [rodada.id for rodada in resultado.rodadas]
    registrar_resultado(
        tabela_resultados, rotulo,
        f'ciclo_simples(criado_em={criado_em_simples}, id menor), ciclo_mensal(criado_em={criado_em_mensal}, id maior)',
        "'agendar' ausente",
        motivo,
        f'ids={ids_das_rodadas}',
        'agendar' not in ids_das_rodadas,
    )
    assert 'agendar' not in ids_das_rodadas

    # TearDown: nada a desmontar.


# ===================================================================
# rodada_atual_legenda — 2 casos que faltavam pra fechar 100%: legenda vinda
# do mapa fixo (estado com aviso próprio) e legenda vinda da data_devida
# (nenhum dos 4 testes acima verificava esse campo — só executavam a linha,
# nunca conferiam o valor).
# ===================================================================

def test_calcular_roadmap_produto_legenda_usa_mapa_fixo(regua_de_fases, tabela_resultados):
    # Setup: Vídeo Mensal#1, produção completa, aguardando aprovação do marketplace.
    produto = Produto.objects.create(ean='EAN000005', titulo='Produto Aguardando Aprovacao')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em=PRODUCAO_CONCLUIDA_EM, roteiro_concluido_em=PRODUCAO_CONCLUIDA_EM,
        completo_concluido_em=PRODUCAO_CONCLUIDA_EM, status=StatusPostagem.AGUARDANDO_APROVACAO,
    )

    # Exercise: chama o SUT de verdade.
    resultado = calcular_roadmap_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, 'legenda_usa_mapa_quando_estado_tem_legenda_fixa',
        'Vídeo Mensal#1, produção completa, status=Aguardando Aprovação',
        "legenda='aguardando aprovação' (vem do mapa fixo, não da data)",
        'Estado visual Aguardando está em LEGENDAS_POR_ESTADO_VISUAL — a legenda usa o texto fixo do mapa, nunca chega a olhar data_devida.',
        f'legenda={resultado.rodada_atual_legenda!r}',
        resultado.rodada_atual_legenda == 'aguardando aprovação',
    )
    assert resultado.rodada_atual_legenda == 'aguardando aprovação'

    # TearDown: nada a desmontar.


def test_calcular_roadmap_produto_legenda_mostra_data_devida(regua_de_fases, tabela_resultados):
    # Setup: Vídeo Mensal#1, produção completa, ainda sem status (esperando o dia de Postar).
    produto = Produto.objects.create(ean='EAN000006', titulo='Produto Aguardando Postar')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em=PRODUCAO_CONCLUIDA_EM, roteiro_concluido_em=PRODUCAO_CONCLUIDA_EM,
        completo_concluido_em=PRODUCAO_CONCLUIDA_EM, data_devida=date(2026, 8, 10),
    )

    # Exercise: chama o SUT de verdade.
    resultado = calcular_roadmap_produto(produto)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, 'legenda_mostra_data_devida_quando_nao_ha_legenda_fixa',
        'Vídeo Mensal#1, produção completa, sem status, data_devida=10/08/2026',
        "legenda='vence 10/08'",
        'Estado Atual não está no mapa fixo de legendas — cai no fallback de data, mostrando "vence DD/MM".',
        f'legenda={resultado.rodada_atual_legenda!r}',
        resultado.rodada_atual_legenda == 'vence 10/08',
    )
    assert resultado.rodada_atual_legenda == 'vence 10/08'

    # TearDown: nada a desmontar.