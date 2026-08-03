# agenda_videos/tests/test_nivel_3__criar_proximo.py

# Função Objetivo: Testa CicloVideo.criar_proximo() — Nível 3 (banco de
# verdade). Cobre a régua inteira de transição de fase: Simples -> Vídeo
# Mensal #1 (sem espera) -> Mensal #2 (30d) -> ... -> Mensal #4 -> Vídeo
# Trimestral #1 (espera 90d) -> Trimestral #2 (90d, contínuo pra sempre) +
# 1 caso dedicado de ajuste de dia útil (substitui o antigo
# test_camada3_criar_proximo_dia_util.py, já apagado).
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

from datetime import date, datetime, time

import pytest
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import Fase, ConfiguracaoFase, CicloVideo, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — criar_proximo(): régua completa de transição de fase'


@pytest.fixture
def regua_de_fases():
    # Setup: monta a régua real (Simples -> Vídeo Mensal -> Vídeo Trimestral)
    # como ConfiguracaoFase de verdade no banco de teste — é dado, não
    # hardcode no código, então o teste precisa criar essa régua ele mesmo.
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


def _criar_ciclo_replicado(rotulo, fase, numero_ocorrencia, replicado_em_data):
    # ean curto de propósito — o campo tem limite de tamanho, e o valor em
    # si nunca é verificado por este teste (só precisa existir e ser único).
    produto = Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo='Produto Teste')
    replicado_em = timezone.make_aware(datetime.combine(replicado_em_data, time.min))
    return CicloVideo.objects.create(
        produto=produto, fase=fase, numero_ocorrencia=numero_ocorrencia,
        status=StatusPostagem.REPLICADO, replicado_em=replicado_em,
    )


# ===================================================================
# Régua de transição — terça-feira (04/08) como replicado_em em todos os
# casos, de propósito: nem +0, +30 nem +90 dias cai em fim de semana a
# partir dela, então o resultado só depende da regra de fase, nunca do
# ajuste de dia útil (isso é validado à parte, no caso dedicado abaixo).
# ===================================================================

@pytest.mark.parametrize(
    'rotulo, fase_atual, numero_atual, esperado_fase, esperado_numero, esperado_data_devida, motivo',
    [
        (
            'simples_para_mensal_1_sem_espera', Fase.SIMPLES, 1,
            Fase.VIDEO_MENSAL, 1, date(2026, 8, 4),
            'Vídeo Mensal #1 libera assim que o Simples é replicado — +0 dias, sem espera',
        ),
        (
            'mensal_1_para_2_trinta_dias', Fase.VIDEO_MENSAL, 1,
            Fase.VIDEO_MENSAL, 2, date(2026, 9, 3),
            'dentro do período (2 <= 4) — distância normal de 30 dias corridos',
        ),
        (
            'mensal_4_para_trimestral_1_noventa_dias', Fase.VIDEO_MENSAL, 4,
            Fase.VIDEO_TRIMESTRAL, 1, date(2026, 11, 2),
            'esgotou o período de 4 do Mensal — 1ª ocorrência Trimestral também espera 90 dias',
        ),
        (
            'trimestral_n_para_n_mais_1_noventa_dias', Fase.VIDEO_TRIMESTRAL, 2,
            Fase.VIDEO_TRIMESTRAL, 3, date(2026, 11, 2),
            'fase contínua — nunca esgota período, sempre a mesma distância de 90 dias',
        ),
    ],
    ids=[
        'simples_para_mensal_1_sem_espera', 'mensal_1_para_2_trinta_dias',
        'mensal_4_para_trimestral_1_noventa_dias', 'trimestral_n_para_n_mais_1_noventa_dias',
    ],
)
def test_criar_proximo_regua_de_transicao(
    regua_de_fases, rotulo, fase_atual, numero_atual,
    esperado_fase, esperado_numero, esperado_data_devida, motivo, tabela_resultados,
):
    # Setup: 1 CicloVideo já replicado, na fase/ocorrência de onde a
    # transição parte.
    ciclo_atual = _criar_ciclo_replicado(rotulo, fase_atual, numero_atual, date(2026, 8, 4))

    # Exercise: chama o SUT de verdade.
    proximo = ciclo_atual.criar_proximo()

    # Assert: registra antes de comparar — os 3 campos juntos (fase, número,
    # data), não só 1 escalar solto, porque a régua só está certa se os 3
    # baterem ao mesmo tempo.
    passou = (
        proximo.fase == esperado_fase
        and proximo.numero_ocorrencia == esperado_numero
        and proximo.data_devida == esperado_data_devida
    )
    registrar_resultado(
        tabela_resultados, rotulo,
        f'{fase_atual} #{numero_atual}, replicado 04/08',
        f'{esperado_fase} #{esperado_numero}, {esperado_data_devida:%d/%m}',
        motivo,
        f'{proximo.fase} #{proximo.numero_ocorrencia}, {proximo.data_devida:%d/%m}',
        passou,
    )
    assert passou

    # TearDown: nada a desmontar — banco de teste limpo automaticamente
    # pelo pytest-django a cada teste.


# ===================================================================
# Caso dedicado — ajuste de dia útil de verdade (substitui o teste antigo,
# test_camada3_criar_proximo_dia_util.py). Segunda-feira (03/08) + 90 dias
# cai em fim de semana — aqui a pergunta é só "criar_proximo aplica
# ultimo_dia_util_ou_hoje?", por isso a data exata não importa, só que caiu
# em dia útil (seg-sex).
# ===================================================================

def test_criar_proximo_aplica_ajuste_de_dia_util(regua_de_fases, tabela_resultados):
    # Setup: Trimestral #1, replicado numa segunda — +90 dias corridos dá
    # 01/11 (domingo), então ultimo_dia_util_ou_hoje ajusta pra trás até
    # sexta 30/10.
    ciclo_atual = _criar_ciclo_replicado(
        'ajuste_dia_util', Fase.VIDEO_TRIMESTRAL, 1, date(2026, 8, 3),
    )

    # Exercise: chama o SUT de verdade.
    proximo = ciclo_atual.criar_proximo()

    # Assert: data exata, hardcoded — valor genérico ("é dia útil") só se
    # justificaria se o valor certo não pudesse ser calculado de antemão,
    # não é o caso aqui.
    passou = proximo.data_devida == date(2026, 10, 30)
    registrar_resultado(
        tabela_resultados, 'criar_proximo_aplica_ajuste_de_dia_util',
        'Trimestral #1, replicado segunda 03/08 + 90 dias corridos',
        '30/10 (sexta) — 01/11 seria domingo, ajusta pra trás 2 dias',
        'ultimo_dia_util_ou_hoje ajusta pra trás se a data calculada cair em fim de semana',
        f'{proximo.data_devida:%d/%m} ({proximo.data_devida.strftime("%A")})',
        passou,
    )
    assert passou

    # TearDown: nada a desmontar.