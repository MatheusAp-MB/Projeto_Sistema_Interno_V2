"""
Nível 4 — ContextoTelaAgendaVideos (contexto_tela_agenda_videos.py)

Fecha o módulo em 100% de cobertura, complementando o que já foi coberto
indiretamente em test_nivel_4__view_agenda_videos.py (aquele testa via
client HTTP + template; este testa a classe isolada, via RequestFactory —
nunca usado antes neste projeto, introduzido aqui porque nenhuma das partes
que faltam cobrir precisa de HTTP nem de template pra ser exercitada).
Depois das 4 correções de test_nivel_4__view_agenda_videos.py, a cobertura
deste arquivo estava em 83% (155 Stmts, 19 Miss, 32 Branch, 7 BrPart) —
faltava:

C0 — ParametrosBuscaAgendaVideos.a_partir_da_requisicao(): os 4 fallbacks
     de valor inválido na querystring (por_pagina, ordenar, periodo, aba) e
     o bloco data_simulada (só ativo com settings.DEBUG=True) nos seus 2
     ramos (data válida, data inválida) — sem DEBUG, o bloco inteiro nunca
     roda, então também documento com 1 teste que confirma que fica None.
C1 — ConstrutorChipsAtivosAgendaVideos._montar_chips_faixa(): os 3 rótulos
     possíveis (mínimo e máximo, só mínimo, só máximo) — o "nenhum dos 2"
     (linha do continue) já é coberto de sobra por qualquer chip sem faixa.
C2 — os 5 métodos privados que montam querystring de link (base, sem
     página, sem tela nem página, sem período nem página, sem aba nem
     página) — nenhum precisa de banco, só de um request fake.
C3 — _montar_contadores_chips(): o "{}" pras 3 telas sem chip (Aguardando
     Aprovação/Prontos pra Agendar/Pausados) e os 3 ramos com chip (Geral,
     A Fazer Hoje, Aguardando Postar/Replicar), incluindo a prova de que o
     chip clicado não zera a própria contagem.

_enriquecer_pagina() chama calcular_diagnostico_preparo_drive(), que hoje é
stub (retorna None sempre, "TEMPORARIAMENTE DESATIVADO 30/07") — por isso
nenhum cenário aqui precisa semear ConfiguracaoFase/régua de fases, ao
contrário dos testes de view_agenda_videos.py (que renderizam template e
passam pela templatetag de roadmap).
"""
from datetime import date

import pytest
from django.http import QueryDict
from django.test import RequestFactory

from agenda_videos.funcoes_auxiliares.contexto_tela_agenda_videos import (
    ContextoTelaAgendaVideos, ParametrosBuscaAgendaVideos, ConstrutorChipsAtivosAgendaVideos,
)
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import (
    Tela, Periodo, OPCOES_ETAPA, ETAPAS_FABRICA, OPCOES_ABA,
)
from agenda_videos.models.ciclo_video import CicloVideo, StatusPostagem
from agenda_videos.models.configuracao_fase import Fase
from agenda_videos.models.indicadores_agenda_produto import IndicadoresAgendaProduto
from agenda_videos.models.participacao_agenda import StatusManualAgenda
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 4 — ContextoTelaAgendaVideos (contexto_tela_agenda_videos.py)'


def _criar_produto(rotulo, titulo=None, marca=None):
    return Produto.objects.create(
        ean=f'EAN{abs(hash(rotulo)) % 1000000}',
        titulo=titulo or f'Produto {rotulo}',
        marca=marca,
    )


def _criar_produto_com_ciclo(
    rotulo, fase=Fase.VIDEO_MENSAL, etapa_atual='base', data_devida=None,
    status_ciclo=None, aguardando_aprovacao_em=None, titulo=None, marca=None,
    **indicadores_overrides,
):
    produto = _criar_produto(rotulo, titulo=titulo, marca=marca)
    CicloVideo.objects.create(
        produto=produto, fase=fase, numero_ocorrencia=1,
        data_devida=data_devida, status=status_ciclo, aguardando_aprovacao_em=aguardando_aprovacao_em,
    )
    campos_indicadores = {
        'fase_atual': fase, 'etapa_atual': etapa_atual,
        'ciclo_atual_atrasado': False, 'tem_video_reprovado': False,
        'status_manual': StatusManualAgenda.ATIVO,
    }
    campos_indicadores.update(indicadores_overrides)
    IndicadoresAgendaProduto.objects.create(produto=produto, **campos_indicadores)
    return produto


def _criar_requisicao(**parametros_get):
    # RequestFactory nunca foi usado neste projeto antes — introduz o padrão
    # aqui porque nada do que falta cobrir precisa de client HTTP nem de
    # template, só de um objeto request de verdade (request.GET) pra montar
    # ParametrosBuscaAgendaVideos/ContextoTelaAgendaVideos direto.
    return RequestFactory().get('/', parametros_get)


# ============================================================
# C0 — ParametrosBuscaAgendaVideos.a_partir_da_requisicao(): fallbacks de
# valor inválido na querystring, e o bloco data_simulada (só com DEBUG).
# ============================================================

def test_por_pagina_invalido_cai_no_padrao_25(tabela_resultados):
    # Setup: querystring com por_pagina não numérico.
    request = _criar_requisicao(por_pagina='abc')

    # Exercise
    parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, 'por_pagina_invalido_cai_no_padrao_25',
        "por_pagina='abc'", '25',
        'por_pagina não numérico não pode quebrar a paginação — cai no padrão de 25 itens',
        f'{parametros.por_pagina}', parametros.por_pagina == 25,
    )
    assert parametros.por_pagina == 25

    # TearDown: nada a desmontar — leitura de querystring não abre recurso.


def test_ordenar_invalido_cai_no_padrao_titulo(tabela_resultados):
    # Setup: campo de ordenação forjado, fora de CAMPOS_ORDENACAO.
    request = _criar_requisicao(ordenar='campo-que-nao-existe')

    # Exercise
    parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    # Assert
    registrar_resultado(
        tabela_resultados, 'ordenar_invalido_cai_no_padrao_titulo',
        "ordenar='campo-que-nao-existe'", 'titulo',
        'ordenar fora de CAMPOS_ORDENACAO não pode gerar erro de SQL — cai no padrão titulo',
        f'{parametros.ordenar}', parametros.ordenar == 'titulo',
    )
    assert parametros.ordenar == 'titulo'

    # TearDown: nada a desmontar.


def test_periodo_invalido_cai_no_padrao_todos(tabela_resultados):
    # Setup: período forjado, fora de Periodo.values.
    request = _criar_requisicao(periodo='periodo-forjado')

    # Exercise
    parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    # Assert
    registrar_resultado(
        tabela_resultados, 'periodo_invalido_cai_no_padrao_todos',
        "periodo='periodo-forjado'", Periodo.TODOS,
        'periodo fora de Periodo.values não pode quebrar o filtro — cai no padrão Todos',
        f'{parametros.filtros["periodo"]}', parametros.filtros['periodo'] == Periodo.TODOS,
    )
    assert parametros.filtros['periodo'] == Periodo.TODOS

    # TearDown: nada a desmontar.


def test_aba_invalida_cai_no_padrao_postar(tabela_resultados):
    # Setup: aba forjada, fora de ('postar', 'replicar').
    request = _criar_requisicao(aba='aba-forjada')

    # Exercise
    parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    # Assert
    registrar_resultado(
        tabela_resultados, 'aba_invalida_cai_no_padrao_postar',
        "aba='aba-forjada'", 'postar',
        "aba fora de ('postar', 'replicar') não pode quebrar a tela — cai no padrão postar",
        f'{parametros.filtros["aba"]}', parametros.filtros['aba'] == 'postar',
    )
    assert parametros.filtros['aba'] == 'postar'

    # TearDown: nada a desmontar.


def test_data_simulada_valida_com_debug_ativo(settings, tabela_resultados):
    # Setup: simular_data só é lido quando settings.DEBUG=True (recurso de
    # depuração, nunca em produção) — liga DEBUG só pra este teste.
    settings.DEBUG = True
    request = _criar_requisicao(simular_data='2026-08-01')

    # Exercise
    parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    # Assert
    registrar_resultado(
        tabela_resultados, 'data_simulada_valida_com_debug_ativo',
        "DEBUG=True, simular_data='2026-08-01'", 'date(2026, 8, 1)',
        'Com DEBUG ativo e data em formato válido, data_simulada é usada pra testar A Fazer Hoje/atrasado/risco com outra data',
        f'{parametros.data_simulada}', parametros.data_simulada == date(2026, 8, 1),
    )
    assert parametros.data_simulada == date(2026, 8, 1)

    # TearDown: settings é revertido automaticamente pela fixture do pytest-django.


def test_data_simulada_invalida_com_debug_ativo_cai_em_none(settings, tabela_resultados):
    # Setup: DEBUG ativo, mas o valor não é uma data válida no formato esperado.
    settings.DEBUG = True
    request = _criar_requisicao(simular_data='isso-nao-eh-uma-data')

    # Exercise
    parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    # Assert
    registrar_resultado(
        tabela_resultados, 'data_simulada_invalida_com_debug_ativo_cai_em_none',
        "DEBUG=True, simular_data='isso-nao-eh-uma-data'", 'None',
        'Formato de data inválido não pode quebrar a tela — cai em None (usa a data real)',
        f'{parametros.data_simulada}', parametros.data_simulada is None,
    )
    assert parametros.data_simulada is None

    # TearDown: nada a desmontar.

def test_data_simulada_ausente_com_debug_ativo_nao_tenta_converter(tabela_resultados, settings):
    # Setup: DEBUG ativo, mas sem simular_data na querystring — valor_bruto
    # fica '' (falsy), então nem entra no try/except de conversão.
    settings.DEBUG = True
    request = _criar_requisicao()

    # Exercise
    parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    # Assert
    registrar_resultado(
        tabela_resultados, 'data_simulada_ausente_com_debug_ativo_nao_tenta_converter',
        'DEBUG=True, sem simular_data na querystring', 'None',
        "sem o parâmetro, valor_bruto é vazio — o 'if valor_bruto' pula direto pro resto, sem tentar converter nada",
        f'{parametros.data_simulada}', parametros.data_simulada is None,
    )
    assert parametros.data_simulada is None

    # TearDown: nada a desmontar.
    
def test_data_simulada_ignorada_sem_debug_ativo(settings, tabela_resultados):
    # Setup: DEBUG desligado (explícito, mesmo sendo o padrão em teste) —
    # documenta que simular_data é recurso só de depuração.
    settings.DEBUG = False
    request = _criar_requisicao(simular_data='2026-08-01')

    # Exercise
    parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    # Assert
    registrar_resultado(
        tabela_resultados, 'data_simulada_ignorada_sem_debug_ativo',
        "DEBUG=False, simular_data='2026-08-01'", 'None',
        'simular_data só existe pra depuração — sem DEBUG ativo, é sempre ignorada, mesmo com data em formato válido',
        f'{parametros.data_simulada}', parametros.data_simulada is None,
    )
    assert parametros.data_simulada is None

    # TearDown: nada a desmontar.


# ============================================================
# C1 — ConstrutorChipsAtivosAgendaVideos._montar_chips_faixa(): os 3
# rótulos possíveis do chip de faixa.
# ============================================================

def test_chip_faixa_com_minimo_e_maximo(tabela_resultados):
    # Setup: só o campo numero_ocorrencia_ciclo_atual com os 2 limites.
    filtros = {
        'numero_ocorrencia_ciclo_atual_min': '2', 'numero_ocorrencia_ciclo_atual_max': '5',
        'data_devida_ciclo_atual_min': '', 'data_devida_ciclo_atual_max': '',
    }

    # Exercise
    chips = ConstrutorChipsAtivosAgendaVideos(filtros)._montar_chips_faixa()

    # Assert
    esperado = 'Ocorrência: 2 até 5'
    obtido = chips[0].label if chips else None
    registrar_resultado(
        tabela_resultados, 'chip_faixa_com_minimo_e_maximo',
        'ocorrencia_min=2, ocorrencia_max=5', esperado,
        'com os 2 limites preenchidos, o rótulo mostra a faixa inteira: "de X até Y"',
        f'{obtido}', obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar — função pura sobre um dict.


def test_chip_faixa_so_com_minimo(tabela_resultados):
    # Setup: só o campo data_devida_ciclo_atual, só o mínimo preenchido.
    filtros = {
        'numero_ocorrencia_ciclo_atual_min': '', 'numero_ocorrencia_ciclo_atual_max': '',
        'data_devida_ciclo_atual_min': '2026-08-01', 'data_devida_ciclo_atual_max': '',
    }

    # Exercise
    chips = ConstrutorChipsAtivosAgendaVideos(filtros)._montar_chips_faixa()

    # Assert
    esperado = 'Vencimento: a partir de 2026-08-01'
    obtido = chips[0].label if chips else None
    registrar_resultado(
        tabela_resultados, 'chip_faixa_so_com_minimo',
        'data_devida_min=2026-08-01, sem máximo', esperado,
        'só com mínimo, o rótulo é aberto pra frente: "a partir de X"',
        f'{obtido}', obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_chip_faixa_so_com_maximo(tabela_resultados):
    # Setup: só o campo data_devida_ciclo_atual, só o máximo preenchido.
    filtros = {
        'numero_ocorrencia_ciclo_atual_min': '', 'numero_ocorrencia_ciclo_atual_max': '',
        'data_devida_ciclo_atual_min': '', 'data_devida_ciclo_atual_max': '2026-08-31',
    }

    # Exercise
    chips = ConstrutorChipsAtivosAgendaVideos(filtros)._montar_chips_faixa()

    # Assert
    esperado = 'Vencimento: até 2026-08-31'
    obtido = chips[0].label if chips else None
    registrar_resultado(
        tabela_resultados, 'chip_faixa_so_com_maximo',
        'data_devida_max=2026-08-31, sem mínimo', esperado,
        'só com máximo, o rótulo é aberto pra trás: "até Y"',
        f'{obtido}', obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C2 — os 5 métodos privados que montam querystring de link. Nenhum precisa
# de banco — só do request.GET de verdade, via RequestFactory.
# ============================================================

_PARAMETROS_QUERYSTRING = {
    'busca': 'boneca', 'ordenar': '-titulo', 'pagina': '3',
    'tela': Tela.GERAL, 'periodo': Periodo.SIMPLES, 'etapa': ['base', 'roteiro'],
    'aba': 'replicar', 'marca': 'Marca X',
}


def test_querystring_base_remove_ordenar_e_pagina(tabela_resultados):
    # Setup: querystring completa, com todos os parâmetros possíveis.
    request = _criar_requisicao(**_PARAMETROS_QUERYSTRING)
    contexto = ContextoTelaAgendaVideos(request)

    # Exercise
    resultado = contexto._montar_querystring_base()

    # Assert: o que importa é QUAIS chaves sobraram, não a ordem exata do
    # texto — urlencode() não é a regra de negócio, o STRIP certo é.
    esperado = {'busca', 'tela', 'periodo', 'etapa', 'aba', 'marca'}
    obtido = set(QueryDict(resultado).keys())
    registrar_resultado(
        tabela_resultados, 'querystring_base_remove_ordenar_e_pagina',
        str(sorted(_PARAMETROS_QUERYSTRING.keys())), str(sorted(esperado)),
        'link de cabeçalho de ordenação: troca só ordenar/pagina, preserva todo o resto',
        str(sorted(obtido)), obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_querystring_sem_pagina_remove_so_pagina(tabela_resultados):
    request = _criar_requisicao(**_PARAMETROS_QUERYSTRING)
    contexto = ContextoTelaAgendaVideos(request)

    resultado = contexto._montar_querystring_sem_pagina()

    esperado = {'busca', 'ordenar', 'tela', 'periodo', 'etapa', 'aba', 'marca'}
    obtido = set(QueryDict(resultado).keys())
    registrar_resultado(
        tabela_resultados, 'querystring_sem_pagina_remove_so_pagina',
        str(sorted(_PARAMETROS_QUERYSTRING.keys())), str(sorted(esperado)),
        'link de troca de página: preserva ordenar e todo filtro ativo, remove só a página atual',
        str(sorted(obtido)), obtido == esperado,
    )
    assert obtido == esperado


def test_querystring_sem_tela_nem_pagina_remove_periodo_etapa_aba_tambem(tabela_resultados):
    request = _criar_requisicao(**_PARAMETROS_QUERYSTRING)
    contexto = ContextoTelaAgendaVideos(request)

    resultado = contexto._montar_querystring_sem_tela_nem_pagina()

    esperado = {'busca', 'ordenar', 'marca'}
    obtido = set(QueryDict(resultado).keys())
    registrar_resultado(
        tabela_resultados, 'querystring_sem_tela_nem_pagina_remove_periodo_etapa_aba_tambem',
        str(sorted(_PARAMETROS_QUERYSTRING.keys())), str(sorted(esperado)),
        'link de troca de TELA: período/etapa/aba são específicos de cada tela e nunca podem vazar pra outra',
        str(sorted(obtido)), obtido == esperado,
    )
    assert obtido == esperado


def test_querystring_sem_periodo_nem_pagina_preserva_tela_e_etapa(tabela_resultados):
    request = _criar_requisicao(**_PARAMETROS_QUERYSTRING)
    contexto = ContextoTelaAgendaVideos(request)

    resultado = contexto._montar_querystring_sem_periodo_nem_pagina()

    esperado = {'busca', 'ordenar', 'tela', 'etapa', 'aba', 'marca'}
    obtido = set(QueryDict(resultado).keys())
    registrar_resultado(
        tabela_resultados, 'querystring_sem_periodo_nem_pagina_preserva_tela_e_etapa',
        str(sorted(_PARAMETROS_QUERYSTRING.keys())), str(sorted(esperado)),
        'link de troca de PERÍODO (Geral/A Fazer Hoje): troca só o período, preserva tela/etapa/busca',
        str(sorted(obtido)), obtido == esperado,
    )
    assert obtido == esperado


def test_querystring_sem_aba_nem_pagina_preserva_tela_e_periodo(tabela_resultados):
    request = _criar_requisicao(**_PARAMETROS_QUERYSTRING)
    contexto = ContextoTelaAgendaVideos(request)

    resultado = contexto._montar_querystring_sem_aba_nem_pagina()

    esperado = {'busca', 'ordenar', 'tela', 'periodo', 'etapa', 'marca'}
    obtido = set(QueryDict(resultado).keys())
    registrar_resultado(
        tabela_resultados, 'querystring_sem_aba_nem_pagina_preserva_tela_e_periodo',
        str(sorted(_PARAMETROS_QUERYSTRING.keys())), str(sorted(esperado)),
        'link de troca de ABA (Aguardando Postar/Replicar): troca só a aba, preserva tela/busca',
        str(sorted(obtido)), obtido == esperado,
    )
    assert obtido == esperado


# ============================================================
# C3 — _montar_contadores_chips(): o "{}" das 3 telas sem chip e os 3 ramos
# com chip, incluindo a prova de que o chip clicado não zera a própria
# contagem.
# ============================================================

@pytest.mark.parametrize('tela', [
    Tela.AGUARDANDO_APROVACAO, Tela.PRONTOS_AGENDAR, Tela.PAUSADOS,
], ids=['aguardando_aprovacao', 'prontos_agendar', 'pausados'])
def test_contadores_chips_fora_das_3_telas_com_chip_retorna_vazio(tabela_resultados, tela):
    # Setup: request pra uma das 3 telas sem chip nenhum.
    request = _criar_requisicao(tela=tela)
    contexto = ContextoTelaAgendaVideos(request)

    # Exercise
    resultado = contexto._montar_contadores_chips()

    # Assert
    registrar_resultado(
        tabela_resultados, 'contadores_chips_fora_das_3_telas_com_chip_retorna_vazio',
        f'tela={tela}', '{}',
        'Aguardando Aprovação/Prontos pra Agendar/Pausados não têm chip nenhum na tela — contagem vazia',
        f'{resultado}', resultado == {},
    )
    assert resultado == {}

    # TearDown: nada a desmontar.


def test_contadores_chips_geral_conta_as_8_opcoes_de_etapa(tabela_resultados):
    # Setup: 1 produto por etapa relevante — base (via cache 'nao_agendado'),
    # completo e concluido — as outras 5 chaves de OPCOES_ETAPA ficam em 0.
    _criar_produto_com_ciclo('geral_base', etapa_atual='base')
    _criar_produto_com_ciclo('geral_completo', etapa_atual='completo')
    _criar_produto_com_ciclo(
        'geral_concluido', fase=Fase.SIMPLES, etapa_atual='concluido',
    )
    request = _criar_requisicao(tela=Tela.GERAL)
    contexto = ContextoTelaAgendaVideos(request)

    # Exercise
    resultado = contexto._montar_contadores_chips()

    # Assert
    esperado = {chave: (1 if chave in ('base', 'completo', 'concluido') else 0) for chave, _ in OPCOES_ETAPA}
    registrar_resultado(
        tabela_resultados, 'contadores_chips_geral_conta_as_8_opcoes_de_etapa',
        '1 produto em base, 1 em completo, 1 em concluido', str(esperado),
        'Geral usa as 8 chaves de OPCOES_ETAPA — fonte única dos chips de Etapa',
        str(resultado), resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_contadores_chips_geral_nao_zera_ao_clicar_no_proprio_chip(tabela_resultados):
    # Setup: mesmos 2 produtos (base e completo), mas agora a querystring
    # JÁ TRAZ etapa=completo (simulando o clique no próprio chip) — se o
    # filtro não fosse retirado antes de contar, 'base' apareceria zerado.
    _criar_produto_com_ciclo('geral_nz_base', etapa_atual='base')
    _criar_produto_com_ciclo('geral_nz_completo', etapa_atual='completo')
    request = _criar_requisicao(tela=Tela.GERAL, etapa='completo')
    contexto = ContextoTelaAgendaVideos(request)

    # Exercise
    resultado = contexto._montar_contadores_chips()

    # Assert
    registrar_resultado(
        tabela_resultados, 'contadores_chips_geral_nao_zera_ao_clicar_no_proprio_chip',
        "1 em base, 1 em completo, querystring já com etapa=completo",
        'base=1 e completo=1 (nenhum zerado)',
        'filtros_sem_chip existe exatamente pra isso: contar sobre o queryset SEM o filtro de etapa aplicado',
        f"base={resultado['base']}, completo={resultado['completo']}",
        resultado['base'] == 1 and resultado['completo'] == 1,
    )
    assert resultado['base'] == 1
    assert resultado['completo'] == 1

    # TearDown: nada a desmontar.


def test_contadores_chips_a_fazer_hoje_conta_as_4_etapas_fabrica(tabela_resultados):
    # Setup: 1 produto por etapa de ETAPAS_FABRICA — recusado é por status
    # do ciclo (StatusPostagem.RECUSADO), não por etapa_atual; completo com
    # status None prova que não é contado em dobro como recusado.
    _criar_produto_com_ciclo('fabrica_base', etapa_atual='base')
    _criar_produto_com_ciclo('fabrica_roteiro', etapa_atual='roteiro')
    _criar_produto_com_ciclo('fabrica_completo', etapa_atual='completo')
    _criar_produto_com_ciclo(
        'fabrica_recusado', etapa_atual='completo', status_ciclo=StatusPostagem.RECUSADO,
    )
    request = _criar_requisicao(tela=Tela.A_FAZER_HOJE)
    contexto = ContextoTelaAgendaVideos(request)

    # Exercise
    resultado = contexto._montar_contadores_chips()

    # Assert
    esperado = {chave: 1 for chave in ETAPAS_FABRICA}
    registrar_resultado(
        tabela_resultados, 'contadores_chips_a_fazer_hoje_conta_as_4_etapas_fabrica',
        '1 produto em cada uma das 4 ETAPAS_FABRICA', str(esperado),
        'A Fazer Hoje usa só as 4 chaves de produção real — recusado por status, não por etapa_atual',
        str(resultado), resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_contadores_chips_aguardando_postar_replicar_conta_as_2_abas(tabela_resultados):
    # Setup: 1 produto em postar, 1 em replicar.
    _criar_produto_com_ciclo('apr_postar', etapa_atual='postar')
    _criar_produto_com_ciclo('apr_replicar', etapa_atual='replicar')
    request = _criar_requisicao(tela=Tela.AGUARDANDO_POSTAR_REPLICAR)
    contexto = ContextoTelaAgendaVideos(request)

    # Exercise
    resultado = contexto._montar_contadores_chips()

    # Assert
    esperado = {chave: 1 for chave, _ in OPCOES_ABA}
    registrar_resultado(
        tabela_resultados, 'contadores_chips_aguardando_postar_replicar_conta_as_2_abas',
        '1 produto em postar, 1 em replicar', str(esperado),
        'Aguardando Postar/Replicar usa as 2 chaves de OPCOES_ABA — contagem sem a aba já aplicada',
        str(resultado), resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.