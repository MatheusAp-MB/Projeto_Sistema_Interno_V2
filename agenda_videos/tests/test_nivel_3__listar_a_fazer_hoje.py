"""
Nível 3 — listar_a_fazer_hoje()

O dashboard "A Fazer Hoje" em si. Divide em 7 blocos: C1 esqueleto de
inclusão/exclusão, C2 busca, C3 filtros simples, C4 atrasado/risco,
C5 pendente_agora, C6 faixas, C7 ordenação final. DOC (cache de
IndicadoresAgendaProduto/ParticipacaoAgenda) já validado nas Camadas A/B —
aqui só se preenche o cache manualmente por cenário, não se reexaure a
lógica de cálculo dos indicadores.
"""
from datetime import date, datetime

import pytest
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.a_fazer_hoje import listar_a_fazer_hoje
from agenda_videos.models.ciclo_video import CicloVideo, StatusPostagem
from agenda_videos.models.configuracao_fase import Fase
from agenda_videos.models.indicadores_agenda_produto import IndicadoresAgendaProduto
from agenda_videos.models.participacao_agenda import ParticipacaoAgenda, StatusManualAgenda
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — listar_a_fazer_hoje()'

# data_referencia fixa: segunda 03/08/2026 (mesma da Camada A).
# hoje=03/08, limite_risco=04/08.
DATA_REFERENCIA = date(2026, 8, 3)


def _criar_produto(rotulo, titulo=None, marca=None, cod_fabricante=None):
    return Produto.objects.create(
        ean=f'EAN{abs(hash(rotulo)) % 1000000}',
        titulo=titulo or f'Produto {rotulo}',
        marca=marca, cod_fabricante=cod_fabricante,
    )


def _criar_produto_visivel(rotulo, data_devida=None, status_ciclo=None, aguardando_aprovacao_em=None,
                            titulo=None, marca=None, cod_fabricante=None, **indicadores_overrides):
    # Monta um produto que passa por TODAS as regras básicas de inclusão do
    # C1 (tem ciclo, status ativo, etapa não concluída/postar-futuro) —
    # ponto de partida pros testes de busca/filtro/ordenação, que variam
    # só o que interessa em cada cenário.
    produto = _criar_produto(rotulo, titulo=titulo, marca=marca, cod_fabricante=cod_fabricante)
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        data_devida=data_devida, status=status_ciclo, aguardando_aprovacao_em=aguardando_aprovacao_em,
    )
    campos_indicadores = {'etapa_atual': 'base', 'status_manual': StatusManualAgenda.ATIVO}
    campos_indicadores.update(indicadores_overrides)
    IndicadoresAgendaProduto.objects.create(produto=produto, **campos_indicadores)
    return produto


def _aparece(produto, resultado):
    return resultado.filter(pk=produto.pk).exists()


# ============================================================
# C1 — esqueleto de inclusão/exclusão (sem filtro nenhum do dict)
# ============================================================

def test_listar_sem_ciclo_nenhum_nao_aparece(tabela_resultados):
    # Setup: produto sem NENHUM CicloVideo.
    produto = _criar_produto('sem_ciclo')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: sem ciclo, nunca entra na Agenda.
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_sem_ciclo_nenhum_nao_aparece',
        'produto sem nenhum CicloVideo',
        esperado, 'ciclos_video__isnull=False é a regra básica de entrada — sem ciclo, nunca aparece',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_status_pausado_nao_aparece(tabela_resultados):
    # Setup: ciclo válido, mas status manual Pausado.
    produto = _criar_produto_visivel('status_pausado', status_manual=StatusManualAgenda.PAUSADO)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: pausado é excluído sempre, incondicionalmente.
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_status_pausado_nao_aparece',
        'status_manual=Pausado',
        esperado, 'produto pausado nunca aparece no dashboard, mesmo com ciclo válido',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_status_descontinuado_nao_aparece(tabela_resultados):
    # Setup: ciclo válido, mas status manual Descontinuado.
    produto = _criar_produto_visivel('status_descontinuado', status_manual=StatusManualAgenda.DESCONTINUADO)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: descontinuado é excluído sempre, incondicionalmente.
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_status_descontinuado_nao_aparece',
        'status_manual=Descontinuado',
        esperado, 'produto descontinuado nunca aparece no dashboard, mesmo com ciclo válido',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_etapa_concluido_nao_aparece(tabela_resultados):
    # Setup: etapa da ocorrência atual já concluída.
    produto = _criar_produto_visivel('etapa_concluido', etapa_atual='concluido')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: ocorrência concluída não tem mais nada "a fazer hoje".
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_etapa_concluido_nao_aparece',
        'etapa_atual=concluido',
        esperado, 'nada a fazer numa ocorrência já concluída',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_etapa_postar_prazo_futuro_nao_aparece(tabela_resultados):
    # Setup: etapa "postar", mas o prazo ainda não chegou.
    produto = _criar_produto_visivel(
        'postar_prazo_futuro', etapa_atual='postar', data_devida=date(2026, 8, 10),
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: prazo no futuro — ainda não aparece.
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_etapa_postar_prazo_futuro_nao_aparece',
        'etapa=postar, data_devida=10/08 (depois de hoje 03/08)',
        esperado, 'só aparece pra postar quando o prazo realmente chegou',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_etapa_postar_ja_postou_hoje_nao_aparece(tabela_resultados):
    # Setup: etapa "postar", prazo já chegou, mas JÁ foi postado hoje.
    momento_hoje = timezone.make_aware(datetime(2026, 8, 3, 15, 0))
    produto = _criar_produto_visivel(
        'postar_ja_postou', etapa_atual='postar', data_devida=DATA_REFERENCIA,
        aguardando_aprovacao_em=momento_hoje,
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: já postou hoje — não precisa aparecer de novo.
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_etapa_postar_ja_postou_hoje_nao_aparece',
        'etapa=postar, prazo=hoje, já postado hoje às 15h',
        esperado, 'já foi postado hoje — não precisa reaparecer no "a fazer hoje"',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_produto_normal_aparece(tabela_resultados):
    # Setup: produto "de livro" — ciclo válido, etapa em produção, status
    # ativo. O caso feliz, contraste com todas as exclusões acima.
    produto = _criar_produto_visivel('produto_normal')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: nenhum motivo de exclusão bate — aparece.
    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'listar_produto_normal_aparece',
        'ciclo válido, etapa=base, status=Ativo',
        esperado, 'caso feliz — nenhuma regra de exclusão bate',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_etapa_postar_prazo_chegou_nao_postou_aparece(tabela_resultados):
    # Setup: etapa "postar", prazo já chegou (hoje), e ainda NÃO postou —
    # contraste direto com o caso anterior.
    produto = _criar_produto_visivel(
        'postar_prazo_chegou', etapa_atual='postar', data_devida=DATA_REFERENCIA,
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: prazo chegou, ainda não postou — precisa aparecer.
    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'listar_etapa_postar_prazo_chegou_nao_postou_aparece',
        'etapa=postar, data_devida=hoje (03/08), ainda não postou',
        esperado, 'prazo chegou e ainda não postou — precisa aparecer pra postar hoje',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C2 — busca por termo (título/ean/sku/cod_fabricante)
# ============================================================

def test_listar_busca_acha_por_titulo(tabela_resultados):
    # Setup: produto com termo alvo no título.
    produto = _criar_produto_visivel('busca_titulo', titulo='Fone Bluetooth XPTO')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(busca='XPTO', data_referencia=DATA_REFERENCIA)

    # Assert: termo aparece no título — acha.
    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'listar_busca_acha_por_titulo',
        'título="Fone Bluetooth XPTO", busca="XPTO"',
        esperado, 'termo aparece no título — acha',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_busca_nao_acha_termo_ausente(tabela_resultados):
    # Setup: mesmo produto, termo que não aparece em nenhum campo.
    produto = _criar_produto_visivel('busca_ausente', titulo='Fone Bluetooth XPTO')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(busca='ZZZINEXISTENTE', data_referencia=DATA_REFERENCIA)

    # Assert: termo não bate em nenhum dos 4 campos — não acha.
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_busca_nao_acha_termo_ausente',
        'título="Fone Bluetooth XPTO", busca="ZZZINEXISTENTE"',
        esperado, 'termo não aparece em nenhum dos 4 campos — não acha',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_busca_dois_termos_ambos_batem_acha(tabela_resultados):
    # Setup: 2 termos, cada um bate num campo DIFERENTE.
    produto = _criar_produto_visivel(
        'busca_dois_termos_ok', titulo='Fone Bluetooth XPTO', cod_fabricante='ABC999',
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(busca='XPTO ABC999', data_referencia=DATA_REFERENCIA)

    # Assert: múltiplos termos = E — os 2 batem, acha.
    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'listar_busca_dois_termos_ambos_batem_acha',
        'título tem "XPTO", cod_fabricante tem "ABC999", busca="XPTO ABC999"',
        esperado, 'múltiplos termos = E — os 2 batem (em campos diferentes), acha',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_busca_dois_termos_um_nao_bate_nao_acha(tabela_resultados):
    # Setup: 1 termo bate, o outro não bate em NENHUM campo.
    produto = _criar_produto_visivel('busca_dois_termos_falha', titulo='Fone Bluetooth XPTO')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(busca='XPTO ZZZINEXISTENTE', data_referencia=DATA_REFERENCIA)

    # Assert: múltiplos termos = E — 1 falha, não acha.
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_busca_dois_termos_um_nao_bate_nao_acha',
        'título tem "XPTO", busca="XPTO ZZZINEXISTENTE"',
        esperado, 'múltiplos termos = E — 1 dos 2 não bate em nenhum campo, não acha',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C3 — filtros simples (marcas, status_manual, urgente, sem_video)
# ============================================================

def test_listar_filtro_marcas(tabela_resultados):
    # Setup: 2 produtos, marcas diferentes.
    produto_a = _criar_produto_visivel('filtro_marca_a', marca='Samsung')
    produto_b = _criar_produto_visivel('filtro_marca_b', marca='LG')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'marcas': ['Samsung']}, data_referencia=DATA_REFERENCIA)

    # Assert: filtro direto — só a marca escolhida aparece.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_marcas',
        'produto A marca=Samsung, produto B marca=LG, filtro marcas=[Samsung]',
        esperado, 'filtro direto — só a marca escolhida aparece',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_filtro_status_manual_so_deixa_passar_ativo(tabela_resultados):
    # Setup: como Pausado/Descontinuado já são excluídos SEMPRE, antes até
    # do filtro do dict rodar (regra do C1), o filtro "status_manual"
    # nunca consegue trazer de volta um produto pausado/descontinuado —
    # na prática, só "ativo" tem efeito real. Documentando o comportamento
    # ATUAL (possível código herdado da listagem paginada — vale checar
    # se é intencional; não estou corrigindo aqui, só registrando).
    produto = _criar_produto_visivel('filtro_status_manual', status_manual=StatusManualAgenda.ATIVO)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(
        filtros={'status_manual': [StatusManualAgenda.PAUSADO]}, data_referencia=DATA_REFERENCIA,
    )

    # Assert: pedir "pausado" nunca traz nada, porque pausado já foi
    # excluído antes do filtro rodar.
    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'listar_filtro_status_manual_so_deixa_passar_ativo',
        'produto Ativo, filtro status_manual=[Pausado]',
        esperado, 'exclusão incondicional de pausado/descontinuado roda ANTES do filtro — pedir esses 2 valores sempre dá vazio',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_listar_filtro_urgente(tabela_resultados):
    # Setup: 2 produtos, urgência diferente.
    produto_a = _criar_produto_visivel('filtro_urgente_a')
    ParticipacaoAgenda.objects.create(produto=produto_a, urgente=True)
    produto_b = _criar_produto_visivel('filtro_urgente_b')
    ParticipacaoAgenda.objects.create(produto=produto_b, urgente=False)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'urgente': ['sim']}, data_referencia=DATA_REFERENCIA)

    # Assert: filtro direto — só o urgente aparece.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_urgente',
        'produto A urgente=True, produto B urgente=False, filtro urgente=[sim]',
        esperado, 'filtro direto — só o urgente aparece',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_filtro_sem_video(tabela_resultados):
    # Setup: 2 produtos, indicador de vídeo reprovado diferente.
    produto_a = _criar_produto_visivel('filtro_sem_video_a', tem_video_reprovado=True)
    produto_b = _criar_produto_visivel('filtro_sem_video_b', tem_video_reprovado=False)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'sem_video': ['sim']}, data_referencia=DATA_REFERENCIA)

    # Assert: filtro direto — só quem tem vídeo reprovado aparece.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_sem_video',
        'produto A tem_video_reprovado=True, produto B=False, filtro sem_video=[sim]',
        esperado, 'filtro direto — só quem tem vídeo reprovado aparece',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C4 — atrasado / risco (sim/não/ambíguo)
# ============================================================

def test_listar_filtro_atrasado_sim(tabela_resultados):
    # Setup: 2 produtos, atraso diferente.
    produto_a = _criar_produto_visivel('atrasado_sim_a', ciclo_atual_atrasado=True)
    produto_b = _criar_produto_visivel('atrasado_sim_b', ciclo_atual_atrasado=False)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'atrasado': ['sim']}, data_referencia=DATA_REFERENCIA)

    # Assert: 'sim' sem 'nao' junto — filtra só os atrasados.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_atrasado_sim',
        'produto A atrasado=True, produto B=False, filtro atrasado=[sim]',
        esperado, "'sim' sem 'nao' junto — filtra só os atrasados",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_filtro_atrasado_nao(tabela_resultados):
    # Setup: 2 produtos, atraso diferente.
    produto_a = _criar_produto_visivel('atrasado_nao_a', ciclo_atual_atrasado=True)
    produto_b = _criar_produto_visivel('atrasado_nao_b', ciclo_atual_atrasado=False)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'atrasado': ['nao']}, data_referencia=DATA_REFERENCIA)

    # Assert: 'nao' sem 'sim' junto — exclui os atrasados.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (False, True)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_atrasado_nao',
        'produto A atrasado=True, produto B=False, filtro atrasado=[nao]',
        esperado, "'nao' sem 'sim' junto — exclui os atrasados, deixa só o resto",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_filtro_atrasado_ambiguo_nao_filtra(tabela_resultados):
    # Setup: 2 produtos, atraso diferente.
    produto_a = _criar_produto_visivel('atrasado_ambiguo_a', ciclo_atual_atrasado=True)
    produto_b = _criar_produto_visivel('atrasado_ambiguo_b', ciclo_atual_atrasado=False)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'atrasado': ['sim', 'nao']}, data_referencia=DATA_REFERENCIA)

    # Assert: os 2 valores marcados ao mesmo tempo — não filtra nada.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_atrasado_ambiguo_nao_filtra',
        "produto A atrasado=True, produto B=False, filtro atrasado=['sim','nao']",
        esperado, 'os 2 valores marcados ao mesmo tempo — comportamento é NÃO filtrar nada',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_filtro_risco_sim_reusa_regra_da_camada_a(tabela_resultados):
    # Setup: A bate as 3 condições (etapa em produção + não atrasado +
    # prazo dentro do limite) — mesma regra já validada em Python na
    # Camada A, aqui em SQL. B tem etapa fora de produção (mas ainda
    # visível pelo C1 — prazo=hoje, não postou), não deveria bater.
    produto_a = _criar_produto_visivel(
        'risco_sim_a', etapa_atual='base', ciclo_atual_atrasado=False, data_devida=date(2026, 8, 4),
    )
    produto_b = _criar_produto_visivel(
        'risco_sim_b', etapa_atual='postar', ciclo_atual_atrasado=False, data_devida=DATA_REFERENCIA,
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'risco': ['sim']}, data_referencia=DATA_REFERENCIA)

    # Assert: mesma condição de 3 partes da Camada A, agora em SQL.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_risco_sim_reusa_regra_da_camada_a',
        'A: etapa=base+não atrasado+prazo=04/08 (limite) | B: etapa=postar (fora de produção)',
        esperado, 'mesma condição de 3 partes da Camada A, agora em SQL — precisam bater',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.

def test_listar_filtro_risco_nao(tabela_resultados):
    # Setup: mesmo par do teste anterior — A em risco, B não.
    produto_a = _criar_produto_visivel(
        'risco_nao_a', etapa_atual='base', ciclo_atual_atrasado=False, data_devida=date(2026, 8, 4),
    )
    produto_b = _criar_produto_visivel(
        'risco_nao_b', etapa_atual='postar', ciclo_atual_atrasado=False, data_devida=DATA_REFERENCIA,
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'risco': ['nao']}, data_referencia=DATA_REFERENCIA)

    # Assert: 'nao' sem 'sim' junto — exclui quem está em risco, deixa só o resto.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (False, True)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_risco_nao',
        'A: em risco (bate as 3 condições) | B: fora de risco (etapa=postar). Filtro risco=[nao]',
        esperado, "'nao' sem 'sim' junto — exclui quem está em risco",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_filtro_risco_ambiguo_nao_filtra(tabela_resultados):
    # Setup: mesmo par de novo.
    produto_a = _criar_produto_visivel(
        'risco_ambiguo_a', etapa_atual='base', ciclo_atual_atrasado=False, data_devida=date(2026, 8, 4),
    )
    produto_b = _criar_produto_visivel(
        'risco_ambiguo_b', etapa_atual='postar', ciclo_atual_atrasado=False, data_devida=DATA_REFERENCIA,
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'risco': ['sim', 'nao']}, data_referencia=DATA_REFERENCIA)

    # Assert: os 2 valores marcados ao mesmo tempo — não filtra nada.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'listar_filtro_risco_ambiguo_nao_filtra',
        "A: em risco | B: fora de risco. Filtro risco=['sim','nao']",
        esperado, 'os 2 valores marcados ao mesmo tempo — comportamento é NÃO filtrar nada',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C5 — pendente_agora (7 categorias, focando nos 2 casos especiais)
# ============================================================

def test_listar_pendente_agora_categoria_simples(tabela_resultados):
    # Setup: categoria "direta" — só compara etapa_atual==chave.
    produto_a = _criar_produto_visivel('pendente_roteiro_a', etapa_atual='roteiro')
    produto_b = _criar_produto_visivel('pendente_roteiro_b', etapa_atual='base')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'pendente_agora': ['roteiro']}, data_referencia=DATA_REFERENCIA)

    # Assert: categoria direta.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_pendente_agora_categoria_simples',
        'A: etapa=roteiro | B: etapa=base, filtro pendente_agora=[roteiro]',
        esperado, "categoria direta — Q(indicadores_agenda__etapa_atual='roteiro')",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_pendente_agora_recusado(tabela_resultados):
    # Setup: categoria especial "recusado" — usa status_ciclo_atual, não
    # etapa_atual (que também seria 'completo' nesse caso).
    produto_a = _criar_produto_visivel(
        'pendente_recusado_a', etapa_atual='completo', status_ciclo=StatusPostagem.RECUSADO,
    )
    produto_b = _criar_produto_visivel('pendente_recusado_b', etapa_atual='completo')

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'pendente_agora': ['recusado']}, data_referencia=DATA_REFERENCIA)

    # Assert: categoria especial — usa status_ciclo_atual.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_pendente_agora_recusado',
        'A: etapa=completo + status=Recusado | B: etapa=completo, sem recusa. Filtro pendente_agora=[recusado]',
        esperado, 'categoria especial — usa status_ciclo_atual, não etapa_atual',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_pendente_agora_completo_exclui_recusado(tabela_resultados):
    # Setup: categoria especial "completo" — mesma etapa='completo' que
    # "recusado" também produz, mas aqui tem que EXCLUIR quem foi
    # recusado, pra não misturar as 2 categorias.
    produto_a = _criar_produto_visivel('pendente_completo_a', etapa_atual='completo')
    produto_b = _criar_produto_visivel(
        'pendente_completo_b', etapa_atual='completo', status_ciclo=StatusPostagem.RECUSADO,
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(filtros={'pendente_agora': ['completo']}, data_referencia=DATA_REFERENCIA)

    # Assert: 'completo' exclui quem foi recusado.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_pendente_agora_completo_exclui_recusado',
        'A: etapa=completo, nunca recusado | B: etapa=completo, mas recusado. Filtro pendente_agora=[completo]',
        esperado, "'completo' exclui quem foi recusado — senão as 2 categorias se misturam",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C6 — faixas numéricas/data (aplicar_filtro_faixa é DOC de outro app —
# não reexaure a lógica dele, só confirma que o parâmetro certo chega
# no campo certo)
# ============================================================

def test_listar_faixa_numero_ocorrencia(tabela_resultados):
    # Setup: 2 produtos, número de ocorrência diferente.
    produto_a = _criar_produto_visivel('faixa_numero_a')
    CicloVideo.objects.filter(produto=produto_a).update(numero_ocorrencia=5)
    produto_b = _criar_produto_visivel('faixa_numero_b')
    CicloVideo.objects.filter(produto=produto_b).update(numero_ocorrencia=1)

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(
        filtros={'numero_ocorrencia_ciclo_atual_min': 3}, data_referencia=DATA_REFERENCIA,
    )

    # Assert: DOC de outro app — só confirma o parâmetro certo.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_faixa_numero_ocorrencia',
        'A: ocorrência #5 | B: ocorrência #1, filtro numero_ocorrencia_ciclo_atual_min=3',
        esperado, 'aplicar_filtro_faixa (DOC de outro app) — só confirma que o parâmetro chega certo',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_listar_faixa_data_devida(tabela_resultados):
    # Setup: 2 produtos, vencimento diferente.
    produto_a = _criar_produto_visivel('faixa_data_a', data_devida=date(2026, 8, 20))
    produto_b = _criar_produto_visivel('faixa_data_b', data_devida=date(2026, 8, 1))

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(
        filtros={'data_devida_ciclo_atual_min': date(2026, 8, 10)}, data_referencia=DATA_REFERENCIA,
    )

    # Assert: mesmo DOC de faixa, agora num campo de data.
    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'listar_faixa_data_devida',
        'A: vencimento 20/08 | B: vencimento 01/08, filtro data_devida_ciclo_atual_min=10/08',
        esperado, 'mesmo DOC de faixa, aplicado em campo de data — __gte funciona igual pra data e número',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C7 — ordenação final: prioridade (6 níveis) -> fase (3 níveis) -> data
# ============================================================

def test_listar_ordenacao_prioridade_fase_data(tabela_resultados):
    # Setup: 3 produtos que só se distinguem pela ordenação — nenhum
    # motivo de exclusão em jogo.
    produto_prioridade_alta = _criar_produto_visivel(
        'ordenacao_prioridade_alta', fase_atual=Fase.VIDEO_TRIMESTRAL, tem_video_reprovado=True,
    )
    ParticipacaoAgenda.objects.create(produto=produto_prioridade_alta, urgente=True)

    produto_resto_trimestral = _criar_produto_visivel(
        'ordenacao_resto_trimestral', fase_atual=Fase.VIDEO_TRIMESTRAL,
    )
    produto_resto_simples = _criar_produto_visivel(
        'ordenacao_resto_simples', fase_atual=Fase.SIMPLES,
    )

    # Exercise: chama o SUT de verdade.
    resultado = listar_a_fazer_hoje(data_referencia=DATA_REFERENCIA)

    # Assert: prioridade decide primeiro (alta vence todo o resto,
    # independente da fase); entre os 2 do "resto" (mesma prioridade),
    # fase decide — Simples antes de Trimestral.
    ids_na_ordem = list(resultado.filter(
        pk__in=[produto_prioridade_alta.pk, produto_resto_trimestral.pk, produto_resto_simples.pk],
    ).values_list('pk', flat=True))
    esperado = [produto_prioridade_alta.pk, produto_resto_simples.pk, produto_resto_trimestral.pk]
    registrar_resultado(
        tabela_resultados, 'listar_ordenacao_prioridade_fase_data',
        'A: urgente+sem vídeo (prioridade 1) | B: resto+Trimestral | C: resto+Simples',
        'A, C, B (nessa ordem)',
        'prioridade decide 1º (A vence) — entre B e C (mesma prioridade), fase decide (Simples antes de Trimestral)',
        ids_na_ordem, ids_na_ordem == esperado,
    )
    assert ids_na_ordem == esperado

    # TearDown: nada a desmontar.