"""
Nível 3 — listar_produtos_com_historico()

Relatório geral do Histórico, agrupado por produto. Divide em 11 blocos:
C1 fase, C2 status, C3 fase+status (conjunção no MESMO ciclo — ponto sutil),
C4 data_de/data_ate (janela de criado_em do ciclo), C5 urgente (com o fix de
NULL já aplicado), C6 marcas, C7 status_manual (inclui a dependência de
cache descoberta na Fase de redesenho das 5 telas), C8 busca multi-termo,
C9 estrutural (produto sem ciclo nenhum / sem filtro nenhum), C10 ordenação,
C11 composição de múltiplos filtros de produto ao mesmo tempo. DOC (cache de
IndicadoresAgendaProduto/ParticipacaoAgenda) já validado nas Camadas A/B —
aqui só se preenche o cache manualmente por cenário quando necessário.
"""
from datetime import date, datetime

import pytest
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.historico_roadmap import listar_produtos_com_historico
from agenda_videos.models.ciclo_video import CicloVideo, StatusPostagem
from agenda_videos.models.configuracao_fase import Fase
from agenda_videos.models.indicadores_agenda_produto import IndicadoresAgendaProduto
from agenda_videos.models.participacao_agenda import ParticipacaoAgenda, StatusManualAgenda
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — listar_produtos_com_historico()'


def _criar_produto(rotulo, titulo=None, marca=None, sku=None, cod_fabricante=None):
    return Produto.objects.create(
        ean=f'EAN{abs(hash(rotulo)) % 1000000}',
        titulo=titulo or f'Produto {rotulo}',
        marca=marca, sku=sku, cod_fabricante=cod_fabricante,
    )


def _criar_ciclo(produto, fase=Fase.SIMPLES, numero_ocorrencia=1, status=None, criado_em=None):
    # Função Objetivo: cria 1 CicloVideo com fase/status controlados.
    # criado_em é auto_now_add — só dá pra ajustar via update() depois de
    # criado, nunca no create() direto.
    ciclo = CicloVideo.objects.create(produto=produto, fase=fase, numero_ocorrencia=numero_ocorrencia, status=status)
    if criado_em is not None:
        CicloVideo.objects.filter(pk=ciclo.pk).update(criado_em=criado_em)
        ciclo.refresh_from_db()
    return ciclo


def _aparece(produto, resultado):
    return resultado.filter(pk=produto.pk).exists()


# ============================================================
# C1 — filtro por fase (ciclo-level, IN)
# ============================================================

def test_filtro_fase_inclui_quando_bate(tabela_resultados):
    produto = _criar_produto('fase_inclui')
    _criar_ciclo(produto, fase=Fase.VIDEO_MENSAL)

    resultado = listar_produtos_com_historico(filtros={'fase': [Fase.VIDEO_MENSAL]})

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_filtro_fase_inclui_quando_bate',
        'ciclo fase=Vídeo Mensal, filtro fase=[Vídeo Mensal]',
        esperado, 'ciclo bate a fase pedida — produto entra',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_filtro_fase_exclui_quando_nao_bate(tabela_resultados):
    produto = _criar_produto('fase_exclui')
    _criar_ciclo(produto, fase=Fase.SIMPLES)

    resultado = listar_produtos_com_historico(filtros={'fase': [Fase.VIDEO_MENSAL]})

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_filtro_fase_exclui_quando_nao_bate',
        'ciclo fase=Simples, filtro fase=[Vídeo Mensal]',
        esperado, 'único ciclo do produto não bate a fase pedida — fica de fora',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_filtro_fase_multiplas_fases_e_uniao(tabela_resultados):
    produto_simples = _criar_produto('fase_multi_simples')
    _criar_ciclo(produto_simples, fase=Fase.SIMPLES)
    produto_trimestral = _criar_produto('fase_multi_trimestral')
    _criar_ciclo(produto_trimestral, fase=Fase.VIDEO_TRIMESTRAL)
    produto_mensal = _criar_produto('fase_multi_mensal')
    _criar_ciclo(produto_mensal, fase=Fase.VIDEO_MENSAL)

    resultado = listar_produtos_com_historico(filtros={'fase': [Fase.SIMPLES, Fase.VIDEO_TRIMESTRAL]})

    obtido = (_aparece(produto_simples, resultado), _aparece(produto_trimestral, resultado), _aparece(produto_mensal, resultado))
    esperado = (True, True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_fase_multiplas_fases_e_uniao',
        'A: Simples | B: Trimestral | C: Mensal, filtro fase=[Simples, Trimestral]',
        esperado, 'fase__in é união — qualquer uma das fases pedidas entra',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C2 — filtro por status (ciclo-level, IN)
# ============================================================

def test_filtro_status_inclui_quando_bate(tabela_resultados):
    produto = _criar_produto('status_inclui')
    _criar_ciclo(produto, status=StatusPostagem.APROVADO)

    resultado = listar_produtos_com_historico(filtros={'status': [StatusPostagem.APROVADO]})

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_filtro_status_inclui_quando_bate',
        'ciclo status=Aprovado, filtro status=[Aprovado]',
        esperado, 'ciclo bate o status pedido — produto entra',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_filtro_status_exclui_quando_nao_bate(tabela_resultados):
    produto = _criar_produto('status_exclui')
    _criar_ciclo(produto, status=StatusPostagem.RECUSADO)

    resultado = listar_produtos_com_historico(filtros={'status': [StatusPostagem.APROVADO]})

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_filtro_status_exclui_quando_nao_bate',
        'ciclo status=Recusado, filtro status=[Aprovado]',
        esperado, 'único ciclo do produto não bate o status pedido — fica de fora',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C3 — fase + status juntos: conjunção no MESMO ciclo (ponto sutil)
# ============================================================

def test_fase_e_status_juntos_precisam_bater_no_mesmo_ciclo(tabela_resultados):
    # Setup: produto com 2 ciclos — 1 Simples sem status, 1 Mensal Aprovado.
    # Nenhum ciclo ÚNICO tem fase=Simples E status=Aprovado ao mesmo tempo,
    # mesmo cada condição batendo isoladamente em ciclos diferentes do
    # mesmo produto — fase e status são filtrados na MESMA queryset de
    # ciclos, sequencialmente, então é AND por linha, não por produto.
    produto = _criar_produto('conjuncao_sem_combo')
    _criar_ciclo(produto, fase=Fase.SIMPLES, numero_ocorrencia=1, status=None)
    _criar_ciclo(produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, status=StatusPostagem.APROVADO)

    resultado = listar_produtos_com_historico(filtros={'fase': [Fase.SIMPLES], 'status': [StatusPostagem.APROVADO]})

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_fase_e_status_juntos_precisam_bater_no_mesmo_ciclo',
        'ciclo 1: Simples/sem status | ciclo 2: Mensal/Aprovado. Filtro fase=[Simples]+status=[Aprovado]',
        esperado, 'fase e status aplicados na MESMA queryset de ciclos — precisam bater no mesmo ciclo, não em ciclos diferentes do produto',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_fase_e_status_juntos_quando_combinacao_existe_no_mesmo_ciclo(tabela_resultados):
    # Setup: mesmo par de ciclos do teste anterior — agora o filtro pede a
    # combinação que REALMENTE existe (Mensal + Aprovado, no ciclo 2).
    produto = _criar_produto('conjuncao_com_combo')
    _criar_ciclo(produto, fase=Fase.SIMPLES, numero_ocorrencia=1, status=None)
    _criar_ciclo(produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, status=StatusPostagem.APROVADO)

    resultado = listar_produtos_com_historico(filtros={'fase': [Fase.VIDEO_MENSAL], 'status': [StatusPostagem.APROVADO]})

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_fase_e_status_juntos_quando_combinacao_existe_no_mesmo_ciclo',
        'mesmo par de ciclos. Filtro fase=[Vídeo Mensal]+status=[Aprovado]',
        esperado, 'agora a combinação pedida bate de verdade no ciclo 2 — aparece',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C4 — data_de / data_ate (janela de criado_em do ciclo)
# ============================================================

def test_filtro_data_de_sozinho(tabela_resultados):
    produto_dentro = _criar_produto('data_de_dentro')
    _criar_ciclo(produto_dentro, criado_em=timezone.make_aware(datetime(2026, 8, 10)))
    produto_fora = _criar_produto('data_de_fora')
    _criar_ciclo(produto_fora, criado_em=timezone.make_aware(datetime(2026, 7, 1)))

    resultado = listar_produtos_com_historico(filtros={'data_de': date(2026, 8, 1)})

    obtido = (_aparece(produto_dentro, resultado), _aparece(produto_fora, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_data_de_sozinho',
        'A: ciclo criado 10/08 | B: ciclo criado 01/07, filtro data_de=01/08',
        esperado, 'data_de é __gte — só quem foi criado a partir dali entra',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_data_ate_sozinho(tabela_resultados):
    produto_dentro = _criar_produto('data_ate_dentro')
    _criar_ciclo(produto_dentro, criado_em=timezone.make_aware(datetime(2026, 8, 1)))
    produto_fora = _criar_produto('data_ate_fora')
    _criar_ciclo(produto_fora, criado_em=timezone.make_aware(datetime(2026, 8, 20)))

    resultado = listar_produtos_com_historico(filtros={'data_ate': date(2026, 8, 10)})

    obtido = (_aparece(produto_dentro, resultado), _aparece(produto_fora, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_data_ate_sozinho',
        'A: ciclo criado 01/08 | B: ciclo criado 20/08, filtro data_ate=10/08',
        esperado, 'data_ate é __lte — só quem foi criado até ali entra',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_data_de_e_data_ate_juntos_formam_janela(tabela_resultados):
    produto_dentro = _criar_produto('data_janela_dentro')
    _criar_ciclo(produto_dentro, criado_em=timezone.make_aware(datetime(2026, 8, 5)))
    produto_antes = _criar_produto('data_janela_antes')
    _criar_ciclo(produto_antes, criado_em=timezone.make_aware(datetime(2026, 7, 1)))
    produto_depois = _criar_produto('data_janela_depois')
    _criar_ciclo(produto_depois, criado_em=timezone.make_aware(datetime(2026, 9, 1)))

    resultado = listar_produtos_com_historico(filtros={'data_de': date(2026, 8, 1), 'data_ate': date(2026, 8, 10)})

    obtido = (_aparece(produto_dentro, resultado), _aparece(produto_antes, resultado), _aparece(produto_depois, resultado))
    esperado = (True, False, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_data_de_e_data_ate_juntos_formam_janela',
        'A: 05/08 (dentro) | B: 01/07 (antes) | C: 01/09 (depois), janela 01/08-10/08',
        esperado, 'os 2 filtros juntos formam uma janela fechada — só quem cai dentro entra',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C5 — urgente (com o fix de NULL já aplicado)
# ============================================================

def test_filtro_urgente_sim_pega_so_true(tabela_resultados):
    produto_urgente = _criar_produto('urgente_sim_a')
    _criar_ciclo(produto_urgente)
    ParticipacaoAgenda.objects.create(produto=produto_urgente, urgente=True)
    produto_nao_urgente = _criar_produto('urgente_sim_b')
    _criar_ciclo(produto_nao_urgente)
    ParticipacaoAgenda.objects.create(produto=produto_nao_urgente, urgente=False)

    resultado = listar_produtos_com_historico(filtros={'urgente': ['sim']})

    obtido = (_aparece(produto_urgente, resultado), _aparece(produto_nao_urgente, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_urgente_sim_pega_so_true',
        'A urgente=True | B urgente=False, filtro urgente=[sim]',
        esperado, 'filtro direto — só quem tem urgente=True aparece',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_urgente_nao_pega_false_explicito(tabela_resultados):
    produto = _criar_produto('urgente_nao_explicito')
    _criar_ciclo(produto)
    ParticipacaoAgenda.objects.create(produto=produto, urgente=False)

    resultado = listar_produtos_com_historico(filtros={'urgente': ['nao']})

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_filtro_urgente_nao_pega_false_explicito',
        'urgente=False (registro existe), filtro urgente=[nao]',
        esperado, 'caso direto — False bate "não urgente"',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_filtro_urgente_nao_pega_quem_nunca_teve_participacao(tabela_resultados):
    # Setup: produto sem NENHUM ParticipacaoAgenda — o fix aplicado antes
    # da pausa garante que isso conta como "não urgente" também.
    produto = _criar_produto('urgente_nao_sem_participacao')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico(filtros={'urgente': ['nao']})

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_filtro_urgente_nao_pega_quem_nunca_teve_participacao',
        'sem nenhum ParticipacaoAgenda, filtro urgente=[nao]',
        esperado, 'fix de NULL: quem nunca clicou "Urgente" conta como não urgente, não fica de fora do filtro',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_filtro_urgente_ambiguo_nao_filtra(tabela_resultados):
    produto_a = _criar_produto('urgente_ambiguo_a')
    _criar_ciclo(produto_a)
    ParticipacaoAgenda.objects.create(produto=produto_a, urgente=True)
    produto_b = _criar_produto('urgente_ambiguo_b')
    _criar_ciclo(produto_b)

    resultado = listar_produtos_com_historico(filtros={'urgente': ['sim', 'nao']})

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_filtro_urgente_ambiguo_nao_filtra',
        'A urgente=True | B sem participação, filtro urgente=[sim, nao]',
        esperado, 'os 2 valores marcados ao mesmo tempo — comportamento é não filtrar nada',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C6 — marcas
# ============================================================

def test_filtro_marcas(tabela_resultados):
    produto_a = _criar_produto('marca_a', marca='Samsung')
    _criar_ciclo(produto_a)
    produto_b = _criar_produto('marca_b', marca='LG')
    _criar_ciclo(produto_b)

    resultado = listar_produtos_com_historico(filtros={'marcas': ['Samsung']})

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_marcas',
        'A marca=Samsung | B marca=LG, filtro marcas=[Samsung]',
        esperado, 'filtro direto por marca',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C7 — status_manual (inclui a dependência de cache descoberta no
# redesenho das 5 telas — indicadores_agenda__X é join INNER)
# ============================================================

def test_filtro_status_manual_inclui_quando_bate(tabela_resultados):
    produto = _criar_produto('status_manual_bate')
    _criar_ciclo(produto)
    IndicadoresAgendaProduto.objects.create(produto=produto, status_manual=StatusManualAgenda.ATIVO)

    resultado = listar_produtos_com_historico(filtros={'status_manual': [StatusManualAgenda.ATIVO]})

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_filtro_status_manual_inclui_quando_bate',
        'cache status_manual=Ativo, filtro status_manual=[Ativo]',
        esperado, 'filtro direto por status manual',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_filtro_status_manual_exclui_produto_sem_cache(tabela_resultados):
    # Setup: produto com ciclo (entra no relatório via ids_produtos), mas
    # SEM IndicadoresAgendaProduto nenhum — o filtro status_manual faz
    # join INNER com o cache, então exclui quem não tem essa linha (mesma
    # classe de achado documentada em [[Cache de Indicadores Nao e
    # Populado Automaticamente]]).
    produto = _criar_produto('status_manual_sem_cache')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico(filtros={'status_manual': [StatusManualAgenda.ATIVO]})

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_filtro_status_manual_exclui_produto_sem_cache',
        'produto com ciclo mas sem IndicadoresAgendaProduto, filtro status_manual=[Ativo]',
        esperado, 'join INNER via indicadores_agenda — sem cache, o filtro nunca traz esse produto de volta',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_sem_filtro_status_manual_nao_exige_cache(tabela_resultados):
    # Setup: mesmo tipo de produto (ciclo sem cache), mas SEM aplicar o
    # filtro status_manual — contraste direto com o teste anterior.
    produto = _criar_produto('sem_filtro_status_manual_sem_cache')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico()

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_sem_filtro_status_manual_nao_exige_cache',
        'produto com ciclo, sem IndicadoresAgendaProduto, SEM filtro de status_manual',
        esperado, 'sem o filtro aplicado, a ausência de cache não exclui ninguém — só acontece quando o filtro é usado de propósito',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C8 — busca multi-termo (título/ean/sku/cod_fabricante)
# ============================================================

def test_busca_por_titulo(tabela_resultados):
    produto = _criar_produto('busca_titulo', titulo='Fone Bluetooth XPTO')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico(busca='XPTO')

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_busca_por_titulo',
        'título="Fone Bluetooth XPTO", busca="XPTO"',
        esperado, 'termo bate no título',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_busca_por_ean(tabela_resultados):
    produto = Produto.objects.create(ean='7891234500019', titulo='Produto EAN')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico(busca='7891234500019')

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_busca_por_ean',
        'ean="7891234500019", busca="7891234500019"',
        esperado, 'termo bate no EAN',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_busca_por_sku(tabela_resultados):
    produto = _criar_produto('busca_sku', sku='SKU-XPTO-001')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico(busca='SKU-XPTO')

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_busca_por_sku',
        'sku="SKU-XPTO-001", busca="SKU-XPTO"',
        esperado, 'termo bate no SKU',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_busca_por_cod_fabricante(tabela_resultados):
    produto = _criar_produto('busca_cod_fabricante', cod_fabricante='FAB-XPTO-9')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico(busca='FAB-XPTO')

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_busca_por_cod_fabricante',
        'cod_fabricante="FAB-XPTO-9", busca="FAB-XPTO"',
        esperado, 'termo bate no código do fabricante',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_busca_multi_termo_precisa_bater_todos(tabela_resultados):
    produto = _criar_produto('busca_multi', titulo='Fone Bluetooth XPTO ABC999')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico(busca='XPTO ABC999')

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_busca_multi_termo_precisa_bater_todos',
        'título="Fone Bluetooth XPTO ABC999", busca="XPTO ABC999"',
        esperado, 'os 2 termos batem (cada um em qualquer campo) — produto entra',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_busca_multi_termo_um_nao_bate_exclui(tabela_resultados):
    produto = _criar_produto('busca_multi_falha', titulo='Fone Bluetooth XPTO')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico(busca='XPTO ZZZINEXISTENTE')

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_busca_multi_termo_um_nao_bate_exclui',
        'título="Fone Bluetooth XPTO", busca="XPTO ZZZINEXISTENTE"',
        esperado, '1 dos 2 termos não bate em campo nenhum — produto some, mesmo o outro termo batendo',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C9 — estrutural: produto sem ciclo nenhum / sem filtro nenhum
# ============================================================

def test_produto_sem_ciclo_nenhum_nunca_aparece(tabela_resultados):
    # Setup: produto sem NENHUM CicloVideo — a entrada no relatório vem de
    # ids_produtos derivado dos ciclos, então nunca aparece, não importa
    # qual outro filtro de produto seja aplicado.
    produto = _criar_produto('sem_ciclo_nenhum')

    resultado = listar_produtos_com_historico()

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_produto_sem_ciclo_nenhum_nunca_aparece',
        'produto sem nenhum CicloVideo, sem filtro nenhum',
        esperado, 'entrada no relatório é via ids_produtos vindo dos ciclos — zero ciclo nunca aparece',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_sem_filtro_nenhum_retorna_quem_tem_ciclo(tabela_resultados):
    # Setup: produto com 1 ciclo qualquer, sem busca nem filtro nenhum —
    # contraste direto com o teste anterior.
    produto = _criar_produto('com_ciclo_sem_filtro')
    _criar_ciclo(produto)

    resultado = listar_produtos_com_historico()

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_sem_filtro_nenhum_retorna_quem_tem_ciclo',
        'produto com 1 ciclo, sem busca nem filtro nenhum',
        esperado, 'sem filtro nenhum, todo produto com pelo menos 1 ciclo aparece',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C10 — ordenação por título
# ============================================================

def test_ordenacao_por_titulo(tabela_resultados):
    produto_z = _criar_produto('ordem_z', titulo='ZZZ Produto')
    _criar_ciclo(produto_z)
    produto_a = _criar_produto('ordem_a', titulo='AAA Produto')
    _criar_ciclo(produto_a)

    resultado = listar_produtos_com_historico()

    ids_na_ordem = list(resultado.filter(pk__in=[produto_z.pk, produto_a.pk]).values_list('pk', flat=True))
    esperado = [produto_a.pk, produto_z.pk]
    registrar_resultado(
        tabela_resultados, 'test_ordenacao_por_titulo',
        'A="AAA Produto" | Z="ZZZ Produto"',
        'A antes de Z (ordem alfabética)',
        'order_by(titulo) — sempre alfabética, sem opção de escolha nesta função',
        ids_na_ordem, ids_na_ordem == esperado,
    )
    assert ids_na_ordem == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C11 — composição de múltiplos filtros de produto ao mesmo tempo (smoke)
# ============================================================

def test_combinacao_marca_e_urgente_e_status_manual_juntos(tabela_resultados):
    # Setup: produto que bate os 3 filtros ao mesmo tempo; produto que
    # falha só na marca.
    produto_bate_tudo = _criar_produto('combo_bate_tudo', marca='Samsung')
    _criar_ciclo(produto_bate_tudo)
    ParticipacaoAgenda.objects.create(produto=produto_bate_tudo, urgente=True)
    IndicadoresAgendaProduto.objects.create(produto=produto_bate_tudo, status_manual=StatusManualAgenda.ATIVO)

    produto_marca_errada = _criar_produto('combo_marca_errada', marca='LG')
    _criar_ciclo(produto_marca_errada)
    ParticipacaoAgenda.objects.create(produto=produto_marca_errada, urgente=True)
    IndicadoresAgendaProduto.objects.create(produto=produto_marca_errada, status_manual=StatusManualAgenda.ATIVO)

    resultado = listar_produtos_com_historico(
        filtros={'marcas': ['Samsung'], 'urgente': ['sim'], 'status_manual': [StatusManualAgenda.ATIVO]},
    )

    obtido = (_aparece(produto_bate_tudo, resultado), _aparece(produto_marca_errada, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_combinacao_marca_e_urgente_e_status_manual_juntos',
        'A bate marca+urgente+status_manual | B só bate urgente+status_manual (marca errada)',
        esperado, 'os 3 filtros de produto são aplicados em sequência (AND) — precisa bater todos',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.