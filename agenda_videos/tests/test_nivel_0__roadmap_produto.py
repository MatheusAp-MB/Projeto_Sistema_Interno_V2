# agenda_videos/tests/test_nivel_0__roadmap_produto.py

# Função Objetivo: Nível 0 — cobre montar_rotulo_rodada() e
# _traduzir_status_em_estado_visual(), funções puras de
# agenda_videos/funcoes_auxiliares/roadmap_produto.py. Primeira rodada desse
# arquivo — o restante (_localizar_indice_atual, _montar_etapas_rodada_atual)
# é Nível 2, e _montar_caminho_completo_fases/calcular_roadmap_produto são
# Nível 3 (tocam banco via ConfiguracaoFase), tratados em arquivos separados.

import pytest

from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    EstadoVisualRoadmap, montar_rotulo_rodada, _traduzir_status_em_estado_visual,
)
from agenda_videos.models import Fase, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — roadmap_produto (montar_rotulo_rodada / _traduzir_status_em_estado_visual)'

# ===================================================================
# montar_rotulo_rodada — Simples nunca numera; qualquer outra fase mostra
# "Label #N". Sem match/case: o SUT usa if/else simples (1 único ramo de
# exceção — Simples — o resto cai no mesmo caminho).
# ===================================================================

@pytest.mark.parametrize(
    'fase, numero_ocorrencia, esperado, motivo',
    [
        (Fase.SIMPLES, 1, 'Simples',
         'Simples só existe 1 vez — nunca numera, mesmo recebendo numero_ocorrencia=1.'),
        (Fase.VIDEO_MENSAL, 1, 'Vídeo Mensal #1',
         'Vídeo Mensal numera normalmente — 1ª ocorrência.'),
        (Fase.VIDEO_MENSAL, 4, 'Vídeo Mensal #4',
         'Vídeo Mensal numera normalmente — última ocorrência da régua (período de 4).'),
        (Fase.VIDEO_TRIMESTRAL, 1, 'Vídeo Trimestral #1',
         'Vídeo Trimestral numera normalmente — a função não sabe que essa fase é contínua, só formata o que recebe.'),
        (Fase.VIDEO_TRIMESTRAL, 7, 'Vídeo Trimestral #7',
         'Número alto, sem teto — prova que a função não limita a numeração.'),
    ],
    ids=[
        'simples_nunca_numera',
        'video_mensal_ocorrencia_1',
        'video_mensal_ocorrencia_4',
        'video_trimestral_ocorrencia_1',
        'video_trimestral_ocorrencia_alta',
    ],
)
def test_montar_rotulo_rodada(fase, numero_ocorrencia, esperado, motivo, tabela_resultados):
    # Setup: nada pra montar — fase/numero_ocorrencia/esperado/motivo já vêm
    # prontos do parametrize.

    # Exercise: chama o SUT de verdade.
    resultado = montar_rotulo_rodada(fase, numero_ocorrencia)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, f'montar_rotulo_rodada_{fase}_{numero_ocorrencia}',
        f'fase={fase}, numero_ocorrencia={numero_ocorrencia}', esperado, motivo,
        resultado, resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — função pura, sem estado, sem recurso aberto.


# ===================================================================
# _traduzir_status_em_estado_visual — todo o domínio de StatusPostagem (4) +
# None + valor desconhecido (2 fallbacks). Sem match/case: o SUT só tem
# .get() com default.
# ===================================================================

@pytest.mark.parametrize(
    'status, esperado, motivo',
    [
        (None, EstadoVisualRoadmap.ATUAL,
         'Sem status (nenhuma postagem ainda) — estado visual é Atual.'),
        (StatusPostagem.AGUARDANDO_APROVACAO, EstadoVisualRoadmap.AGUARDANDO,
         'Aguardando aprovação do marketplace — bolinha fica Aguardando.'),
        (StatusPostagem.RECUSADO, EstadoVisualRoadmap.RECUSADO,
         'Postagem recusada pelo marketplace — bolinha fica Recusado.'),
        (StatusPostagem.APROVADO, EstadoVisualRoadmap.APROVADO_CLARO,
         'Aprovado, falta só o clique de Replicar — bolinha fica Aprovado, aguardando replicar.'),
        (StatusPostagem.REPLICADO, EstadoVisualRoadmap.CONCLUIDO,
         'Replicado — rodada encerrada, bolinha fica Concluído.'),
        ('xyz_invalido', EstadoVisualRoadmap.ATUAL,
         'Valor desconhecido (defensivo — StatusPostagem é fechado, mas nunca deve quebrar) — cai no mesmo fallback do None, Atual.'),
    ],
    ids=[
        'sem_status_e_atual',
        'aguardando_aprovacao',
        'recusado',
        'aprovado_claro',
        'replicado_e_concluido',
        'fallback_valor_desconhecido',
    ],
)
def test_traduzir_status_em_estado_visual(status, esperado, motivo, tabela_resultados):
    # Setup: nada pra montar — status/esperado/motivo já vêm prontos do parametrize.

    # Exercise: chama o SUT de verdade.
    resultado = _traduzir_status_em_estado_visual(status)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, f'traduzir_status_{status}',
        f'{status}', f'{esperado.label}', motivo,
        f'{resultado.label}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — função pura, sem estado, sem recurso aberto.