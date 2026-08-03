# agenda_videos/tests/test_nivel_3__iniciar_agenda_e_agendar_apos_simples.py

# Função Objetivo: Testa CicloVideo.iniciar_agenda() e agendar_apos_simples()
# — Nível 3 (banco de verdade). agendar_apos_simples() ganhou data_referencia
# opcional (mesmo padrão de esta_atrasado()) — teste nunca usa a data real
# de hoje. Os 2 jeitos de dar erro (fase errada / etapa não concluída) são
# cobertos separado, mesmo levando ao mesmo ValueError — cada guarda de
# validação precisa do próprio caso, não só 1 representante genérico.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

from datetime import date, datetime, time

import pytest
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import Fase, ConfiguracaoFase, CicloVideo, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — iniciar_agenda() e agendar_apos_simples()'


@pytest.fixture
def regua_simples_para_mensal():
    # Setup: só o trecho da régua que agendar_apos_simples() de fato lê —
    # Simples -> proxima_fase = Vídeo Mensal.
    mensal = ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_MENSAL, periodo_continuo=False, periodo=4,
        distancia_dias_corridos=30, distancia_dias_ao_entrar_na_fase=0,
    )
    ConfiguracaoFase.objects.create(
        fase=Fase.SIMPLES, periodo_continuo=False, periodo=1, proxima_fase=mensal,
    )


def _criar_produto(rotulo):
    return Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo='Produto Teste')


def _criar_ciclo(rotulo, fase, etapa_concluida):
    produto = _criar_produto(rotulo)
    agora = timezone.make_aware(datetime(2026, 8, 1, 12, 0))
    campos = {'produto': produto, 'fase': fase, 'numero_ocorrencia': 1}
    if etapa_concluida:
        # status=REPLICADO é o único valor que faz etapa_atual() cair no
        # 'concluido' final (já validado em test_nivel_2__etapa_atual.py).
        campos.update(
            base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
            status=StatusPostagem.REPLICADO,
        )
    return CicloVideo.objects.create(**campos)


# ===================================================================
# iniciar_agenda — único ponto de entrada do produto na Agenda. 1 caso só:
# não há cenário exclusivo pra enumerar, é sempre a mesma criação.
# ===================================================================

def test_iniciar_agenda(tabela_resultados):
    # Setup: 1 produto, ainda sem nenhum CicloVideo.
    produto = _criar_produto('iniciar_agenda')

    # Exercise: chama o SUT de verdade.
    ciclo = CicloVideo.iniciar_agenda(produto)

    # Assert: relê do banco — prova que persistiu, não só que o objeto
    # devolvido em memória está certo.
    ciclo_no_banco = CicloVideo.objects.get(pk=ciclo.pk)
    passou = (
        ciclo_no_banco.produto_id == produto.pk
        and ciclo_no_banco.fase == Fase.SIMPLES
        and ciclo_no_banco.numero_ocorrencia == 1
        and ciclo_no_banco.data_devida is None
    )
    registrar_resultado(
        tabela_resultados, 'iniciar_agenda',
        'produto novo, sem CicloVideo nenhum', 'Simples #1, sem data_devida',
        'único ponto de entrada do produto na Agenda — Simples nunca tem vencimento',
        f'{ciclo_no_banco.fase} #{ciclo_no_banco.numero_ocorrencia}, data_devida={ciclo_no_banco.data_devida}',
        passou,
    )
    assert passou

    # TearDown: nada a desmontar.


# ===================================================================
# agendar_apos_simples — único ponto de transição MANUAL do sistema.
# ===================================================================

def test_agendar_apos_simples_sucesso(regua_simples_para_mensal, tabela_resultados):
    # Setup: ciclo Simples já replicado (etapa_atual() == 'concluido').
    ciclo = _criar_ciclo('agendar_sucesso', Fase.SIMPLES, etapa_concluida=True)

    # Exercise: chama o SUT de verdade, com data_referencia fixa — segunda
    # 03/08 (já validado em Nível 0 que proximo_dia_util avança pra terça).
    proximo = ciclo.agendar_apos_simples(date(2026, 8, 3))

    # Assert: relê do banco.
    proximo_no_banco = CicloVideo.objects.get(pk=proximo.pk)
    passou = (
        proximo_no_banco.fase == Fase.VIDEO_MENSAL
        and proximo_no_banco.numero_ocorrencia == 1
        and proximo_no_banco.data_devida == date(2026, 8, 4)
    )
    registrar_resultado(
        tabela_resultados, 'agendar_apos_simples_sucesso',
        'Simples replicado, agendado numa segunda (03/08)', 'Vídeo Mensal #1, vence terça (04/08)',
        'proximo_dia_util nunca fica no mesmo dia — reaproveita a regra já testada no Nível 0',
        f'{proximo_no_banco.fase} #{proximo_no_banco.numero_ocorrencia}, data_devida={proximo_no_banco.data_devida}',
        passou,
    )
    assert passou

    # TearDown: nada a desmontar.


@pytest.mark.parametrize(
    'rotulo, fase, etapa_concluida, motivo',
    [
        (
            'fase_errada_levanta_erro', Fase.VIDEO_MENSAL, True,
            'só é possível agendar a partir do Simples — qualquer outra fase é erro de uso',
        ),
        (
            'etapa_nao_concluida_levanta_erro', Fase.SIMPLES, False,
            'Simples ainda não foi replicado — não dá pra agendar o que vem depois antes de terminar',
        ),
    ],
    ids=['fase_errada_levanta_erro', 'etapa_nao_concluida_levanta_erro'],
)
def test_agendar_apos_simples_fora_de_hora_levanta_erro(
    regua_simples_para_mensal, rotulo, fase, etapa_concluida, motivo, tabela_resultados,
):
    # Setup: ciclo fora da condição exigida (fase errada OU ainda não concluído).
    ciclo = _criar_ciclo(rotulo, fase, etapa_concluida)

    # Exercise + Assert: captura a exceção contratual ANTES de registrar,
    # pra linha aparecer na tabela mesmo se o comportamento mudar no futuro
    # e a exceção parar de ser levantada.
    levantou = False
    try:
        ciclo.agendar_apos_simples(date(2026, 8, 3))
    except ValueError:
        levantou = True

    registrar_resultado(
        tabela_resultados, rotulo,
        f'fase={fase}, etapa_concluida={etapa_concluida}', 'levanta ValueError', motivo,
        'levantou ValueError' if levantou else 'não levantou nada',
        levantou,
    )
    assert levantou

    # TearDown: nada a desmontar.