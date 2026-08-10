# integracao_sysemp/tests/test_nivel_3__sincronizacao_xml_manifesto.py

# Função Objetivo: Nível 3 (toca banco de verdade) do model
# SincronizacaoXmlManifestoNotaEntrada — nunca chama a API do Sysemp, só
# testa a lógica de watermark/cobertura em cima do banco real de teste.
# Regra de negócio coberta: cobertura nunca regride, data_inicial_cobertura
# escreve só 1 vez, e falha nunca move nenhuma das datas de cobertura.
# Ver decisão completa no vault: "Sincronizacao Incremental com Watermark
# para Manifesto de Notas de Entrada".

from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone
from django.utils.timezone import make_aware

from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — SincronizacaoXmlManifestoNotaEntrada'

pytestmark = pytest.mark.django_db


def test_obter_cria_linha_vazia_quando_nao_existe(tabela_resultados):
    # Setup: nada a montar — o ponto do teste é justamente a tabela vazia,
    # garantida pelo banco de teste limpo do pytest-django.

    # Exercise: chama o SUT de verdade.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()

    # Assert: registra antes de comparar, depois compara de verdade.
    campos_vazios = (
        registro.data_inicial_cobertura is None
        and registro.data_final_cobertura is None
        and registro.status == ''
    )
    registrar_resultado(
        tabela_resultados, 'obter_cria_linha_vazia',
        'tabela vazia', 'todos os campos em branco/nulos',
        'Antes da 1ª sincronização não pode haver erro, só estado zerado',
        f'inicial={registro.data_inicial_cobertura}, final={registro.data_final_cobertura}, status={registro.status!r}',
        campos_vazios,
    )
    assert campos_vazios

    # TearDown: nada a desmontar — pytest-django desfaz a transação sozinho
    # no fim do teste.


def test_esta_desatualizada_retorna_verdadeiro_quando_nunca_sincronizado(tabela_resultados):
    # Setup: linha recém-criada, nunca sincronizada.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()

    # Exercise
    resultado = registro.esta_desatualizada(data_referencia=date(2026, 8, 9))

    # Assert
    registrar_resultado(
        tabela_resultados, 'esta_desatualizada_nunca_sincronizado',
        'data_final_cobertura=None', 'True',
        'Sem cobertura nenhuma, é sempre considerado desatualizado',
        f'{resultado}', resultado is True,
    )
    assert resultado is True

    # TearDown: nada a desmontar.


def test_registrar_sincronizacao_bem_sucedida_primeira_vez_preenche_inicial_e_final(tabela_resultados):
    # Setup: linha vazia + datas fixas da 1ª chamada (carga histórica).
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    data_inicial_chamada = date(2020, 5, 1)
    data_final_chamada = date(2021, 5, 1)
    agora_fixo = make_aware(datetime(2021, 5, 2, 10, 0))

    # Exercise
    registro.registrar_sincronizacao_bem_sucedida(
        data_inicial_chamada, data_final_chamada, agora=agora_fixo,
    )

    # Assert: relê do banco antes de comparar — nunca confia só no objeto
    # em memória depois do save().
    atualizado = SincronizacaoXmlManifestoNotaEntrada.objects.get(pk=registro.pk)
    bateu = (
        atualizado.data_inicial_cobertura == data_inicial_chamada
        and atualizado.data_final_cobertura == data_final_chamada
        and atualizado.status == SincronizacaoXmlManifestoNotaEntrada.Status.SINCRONIZADO
    )
    registrar_resultado(
        tabela_resultados, 'primeira_sincronizacao_preenche_inicial_e_final',
        f'{data_inicial_chamada} → {data_final_chamada}',
        f'inicial={data_inicial_chamada}, final={data_final_chamada}, status=Sincronizado',
        'Primeira sincronização de todas — os 2 campos de cobertura nascem juntos',
        f'inicial={atualizado.data_inicial_cobertura}, final={atualizado.data_final_cobertura}, status={atualizado.status!r}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_registrar_sincronizacao_bem_sucedida_segunda_vez_nao_sobrescreve_inicial(tabela_resultados):
    # Setup: simula a 1ª sincronização (histórica) já registrada antes.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(
        date(2020, 5, 1), date(2021, 5, 1), agora=make_aware(datetime(2021, 5, 2, 10, 0)),
    )

    # Exercise: 2ª chamada, 1 ano depois — janela de parâmetro diferente
    # da cobertura já salva (2021-04-20, não 2020-05-01).
    registro.registrar_sincronizacao_bem_sucedida(
        date(2021, 4, 20), date(2022, 5, 1), agora=make_aware(datetime(2022, 5, 2, 10, 0)),
    )

    # Assert
    atualizado = SincronizacaoXmlManifestoNotaEntrada.objects.get(pk=registro.pk)
    bateu = (
        atualizado.data_inicial_cobertura == date(2020, 5, 1)
        and atualizado.data_final_cobertura == date(2022, 5, 1)
    )
    registrar_resultado(
        tabela_resultados, 'segunda_sincronizacao_nao_regride_inicial',
        'parâmetro da 2ª chamada = 2021-04-20 → 2022-05-01',
        'inicial continua 2020-05-01, final avança para 2022-05-01',
        'data_inicial_cobertura só escreve na 1ª vez — nunca regride depois',
        f'inicial={atualizado.data_inicial_cobertura}, final={atualizado.data_final_cobertura}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.parametrize(
    'data_referencia, esperado',
    [
        (date(2026, 8, 5), False),
        (date(2026, 8, 20), True),
    ],
    ids=[
        'dentro_da_margem_nao_esta_desatualizada',
        'alem_da_margem_esta_desatualizada',
    ],
)
def test_esta_desatualizada_respeita_a_margem_de_seguranca(data_referencia, esperado, tabela_resultados):
    # Setup: cobertura até 2026-08-01, margem de 7 dias (padrão do model).
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(
        date(2026, 1, 1), date(2026, 8, 1), agora=make_aware(datetime(2026, 8, 1, 12, 0)),
    )

    # Exercise
    resultado = registro.esta_desatualizada(data_referencia=data_referencia)

    # Assert
    registrar_resultado(
        tabela_resultados, f'esta_desatualizada_ref_{data_referencia}',
        f'cobertura até 2026-08-01, referência {data_referencia}', f'{esperado}',
        'Margem de 7 dias: só considera desatualizado depois de cobertura + margem',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_registrar_falha_nao_altera_cobertura(tabela_resultados):
    # Setup: sincronização bem-sucedida já registrada antes.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(
        date(2020, 5, 1), date(2021, 5, 1), agora=make_aware(datetime(2021, 5, 2, 10, 0)),
    )
    agora_da_falha = make_aware(datetime(2021, 5, 3, 9, 0))

    # Exercise
    registro.registrar_falha('Erro de rede simulado', agora=agora_da_falha)

    # Assert
    atualizado = SincronizacaoXmlManifestoNotaEntrada.objects.get(pk=registro.pk)
    bateu = (
        atualizado.data_inicial_cobertura == date(2020, 5, 1)
        and atualizado.data_final_cobertura == date(2021, 5, 1)
        and atualizado.status == SincronizacaoXmlManifestoNotaEntrada.Status.FALHA
        and atualizado.motivo_da_falha == 'Erro de rede simulado'
        and atualizado.data_ultima_chamada == agora_da_falha
    )
    registrar_resultado(
        tabela_resultados, 'registrar_falha_nao_altera_cobertura',
        'falha depois de cobertura já existente',
        'cobertura intocada, status=Falha, motivo preenchido',
        'Falha nunca move data de cobertura — só marca quando e por quê',
        f'inicial={atualizado.data_inicial_cobertura}, final={atualizado.data_final_cobertura}, status={atualizado.status!r}, motivo={atualizado.motivo_da_falha!r}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_esta_desatualizada_usa_hoje_quando_nao_informada(tabela_resultados):
    # Setup: ancora tudo em "hoje" capturado 1x — cobertura fica 10 dias
    # atrás dele, bem além da margem de 7 dias. Determinístico em
    # qualquer dia real, sem usar data_referencia cru na comparação.
    hoje = date.today()
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(
        hoje - timedelta(days=400), hoje - timedelta(days=10),
        agora=make_aware(datetime.combine(hoje, datetime.min.time())),
    )

    # Exercise: chama SEM data_referencia — força o método a cair no
    # date.today() interno (branch antes não coberto).
    resultado = registro.esta_desatualizada()

    # Assert
    registrar_resultado(
        tabela_resultados, 'esta_desatualizada_usa_hoje_quando_nao_informada',
        'data_referencia não informada, cobertura até hoje-10d', 'True',
        'Sem data_referencia, o método cai pra date.today() — cobertura de 10 dias atrás já passou da margem de 7 dias',
        f'{resultado}', resultado is True,
    )
    assert resultado is True

    # TearDown: nada a desmontar.


def test_registrar_sincronizacao_bem_sucedida_usa_agora_atual_quando_nao_informado(tabela_resultados):
    # Setup: linha vazia — só precisa existir pra receber a chamada.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()

    # Exercise: chama SEM agora — marca o intervalo real antes/depois,
    # porque o valor exato do instante não pode ser conhecido de antemão.
    antes = timezone.now()
    registro.registrar_sincronizacao_bem_sucedida(date(2020, 5, 1), date(2021, 5, 1))
    depois = timezone.now()

    # Assert: relê do banco antes de comparar.
    atualizado = SincronizacaoXmlManifestoNotaEntrada.objects.get(pk=registro.pk)
    bateu = antes <= atualizado.data_ultima_chamada <= depois
    registrar_resultado(
        tabela_resultados, 'registrar_sincronizacao_usa_agora_atual_quando_nao_informado',
        'agora não informado', f'entre {antes} e {depois}',
        'Sem agora explícito, o método usa timezone.now() real — só dá pra provar por intervalo, nunca valor exato',
        f'{atualizado.data_ultima_chamada}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_registrar_falha_usa_agora_atual_quando_nao_informado(tabela_resultados):
    # Setup: linha vazia — só precisa existir pra receber a chamada.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()

    # Exercise: chama SEM agora — mesmo esquema de intervalo do teste
    # anterior, agora pro caminho de falha.
    antes = timezone.now()
    registro.registrar_falha('Erro simulado sem agora')
    depois = timezone.now()

    # Assert: relê do banco antes de comparar.
    atualizado = SincronizacaoXmlManifestoNotaEntrada.objects.get(pk=registro.pk)
    bateu = antes <= atualizado.data_ultima_chamada <= depois
    registrar_resultado(
        tabela_resultados, 'registrar_falha_usa_agora_atual_quando_nao_informado',
        'agora não informado', f'entre {antes} e {depois}',
        'Sem agora explícito, registrar_falha também usa timezone.now() real — mesma prova por intervalo',
        f'{atualizado.data_ultima_chamada}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_calcular_janela_da_proxima_busca_primeira_vez_usa_data_inicial_da_carga(tabela_resultados):
    # Setup: linha vazia, nunca sincronizada.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()

    # Exercise
    data_inicial, data_final = registro.calcular_janela_da_proxima_busca(
        data_referencia=date(2026, 8, 10),
    )

    # Assert
    bateu = (
        data_inicial == SincronizacaoXmlManifestoNotaEntrada.DATA_INICIAL_PRIMEIRA_CARGA
        and data_final == date(2026, 8, 10)
    )
    registrar_resultado(
        tabela_resultados, 'calcular_janela_primeira_vez',
        'data_final_cobertura=None, referência 2026-08-10',
        f'({SincronizacaoXmlManifestoNotaEntrada.DATA_INICIAL_PRIMEIRA_CARGA}, 2026-08-10)',
        'Sem cobertura nenhuma, a janela começa na data mínima real de dados úteis do sistema',
        f'({data_inicial}, {data_final})', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_calcular_janela_da_proxima_busca_com_cobertura_aplica_margem(tabela_resultados):
    # Setup: cobertura já registrada até 2026-08-01.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(
        date(2026, 1, 1), date(2026, 8, 1), agora=make_aware(datetime(2026, 8, 1, 12, 0)),
    )

    # Exercise
    data_inicial, data_final = registro.calcular_janela_da_proxima_busca(
        data_referencia=date(2026, 8, 10),
    )

    # Assert
    bateu = data_inicial == date(2026, 7, 25) and data_final == date(2026, 8, 10)
    registrar_resultado(
        tabela_resultados, 'calcular_janela_com_cobertura',
        'cobertura até 2026-08-01, referência 2026-08-10',
        '(2026-07-25, 2026-08-10)',
        'Com cobertura registrada, a janela reaplica a mesma margem de 7 dias de esta_desatualizada()',
        f'({data_inicial}, {data_final})', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_calcular_janela_da_proxima_busca_usa_hoje_quando_nao_informada(tabela_resultados):
    # Setup: ancora "hoje" 1x — nunca sincronizado (data_final_cobertura
    # vazio), determinístico em qualquer dia real.
    hoje = date.today()
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()

    # Exercise: chama SEM data_referencia — força o método a cair no
    # date.today() interno (branch antes não coberto).
    data_inicial, data_final = registro.calcular_janela_da_proxima_busca()

    # Assert
    bateu = (
        data_inicial == SincronizacaoXmlManifestoNotaEntrada.DATA_INICIAL_PRIMEIRA_CARGA
        and data_final == hoje
    )
    registrar_resultado(
        tabela_resultados, 'calcular_janela_usa_hoje_quando_nao_informada',
        'data_referencia não informada, nunca sincronizado',
        f'({SincronizacaoXmlManifestoNotaEntrada.DATA_INICIAL_PRIMEIRA_CARGA}, {hoje})',
        'Sem data_referencia, o método cai pra date.today() real',
        f'({data_inicial}, {data_final})', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


# ===================================================================
# Caso de falha proposital — existe só pra provar que a tabela mostra
# FALHOU corretamente. NUNCA remover, mesmo motivo do modelo padrão de
# teste do projeto.
# ===================================================================

@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_registrar_sincronizacao_bem_sucedida_caso_de_falha_proposital(tabela_resultados):
    # Setup: valor esperado ERRADO de propósito.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    data_final_chamada = date(2021, 5, 1)
    data_final_errada_de_proposito = date(2099, 1, 1)

    # Exercise
    registro.registrar_sincronizacao_bem_sucedida(
        date(2020, 5, 1), data_final_chamada, agora=make_aware(datetime(2021, 5, 2, 10, 0)),
    )

    # Assert: compara contra o valor errado de propósito — tem que falhar.
    atualizado = SincronizacaoXmlManifestoNotaEntrada.objects.get(pk=registro.pk)
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{data_final_chamada}', f'{data_final_errada_de_proposito}',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{atualizado.data_final_cobertura}',
        atualizado.data_final_cobertura == data_final_errada_de_proposito,
    )
    assert atualizado.data_final_cobertura == data_final_errada_de_proposito

    # TearDown: nada a desmontar.