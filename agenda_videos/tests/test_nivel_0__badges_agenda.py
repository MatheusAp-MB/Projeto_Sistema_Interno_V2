# agenda_videos/tests/test_nivel_0__badges_agenda.py

# Função Objetivo: Nível 0 — cobre buscar_badge_de() e montar_opcoes_com_badge(),
# funções puras de agenda_videos/funcoes_auxiliares/badges_agenda.py. Cobre TODO
# o domínio conhecido dos 3 dicionários de badge (status manual, status de
# postagem, etapa do ciclo) mais os 2 casos de fallback (valor desconhecido e
# None) — nunca amostra, sempre o conjunto completo de chaves reais.
# Valor esperado sempre hardcoded (nunca derivado do próprio dicionário sendo
# testado) — senão o teste só provaria que o dict bate com ele mesmo.

import pytest

from agenda_videos.funcoes_auxiliares.badges_agenda import (
    Badge, OpcaoComBadge, BADGE_PADRAO,
    BADGES_STATUS_MANUAL, BADGES_STATUS_POSTAGEM, BADGES_ETAPA,
    buscar_badge_de, montar_opcoes_com_badge,
)
from agenda_videos.models import StatusManualAgenda, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — badges_agenda (buscar_badge_de / montar_opcoes_com_badge)'

# ===================================================================
# buscar_badge_de — 1 caso por chave real dos 3 dicionários (14) + 2
# fallbacks (valor desconhecido, None). Sem match/case: o código-fonte só
# tem .get() com default, nenhum cenário mutuamente exclusivo pra enumerar.
# ===================================================================

@pytest.mark.parametrize(
    'mapa, valor_bruto, esperado, motivo',
    [
        (BADGES_STATUS_MANUAL, StatusManualAgenda.ATIVO,
         Badge(label='Ativo', classe='status-ativo', icone='fa-circle-check'),
         "'Ativo' é chave real de BADGES_STATUS_MANUAL — badge exato, não cai no fallback."),
        (BADGES_STATUS_MANUAL, StatusManualAgenda.PAUSADO,
         Badge(label='Pausado', classe='status-pausado', icone='fa-pause'),
         "'Pausado' é chave real de BADGES_STATUS_MANUAL."),
        (BADGES_STATUS_MANUAL, StatusManualAgenda.DESCONTINUADO,
         Badge(label='Descontinuado', classe='status-descontinuado', icone='fa-circle-xmark'),
         "'Descontinuado' é chave real de BADGES_STATUS_MANUAL."),
        (BADGES_STATUS_POSTAGEM, StatusPostagem.AGUARDANDO_APROVACAO,
         Badge(label='Aguardando aprovação', classe='postagem-aguardando', icone='fa-hourglass-half'),
         "'Aguardando aprovação' é chave real de BADGES_STATUS_POSTAGEM."),
        (BADGES_STATUS_POSTAGEM, StatusPostagem.APROVADO,
         Badge(label='Aprovado', classe='postagem-aprovado', icone='fa-circle-check'),
         "'Aprovado' é chave real de BADGES_STATUS_POSTAGEM."),
        (BADGES_STATUS_POSTAGEM, StatusPostagem.RECUSADO,
         Badge(label='Recusado', classe='postagem-recusado', icone='fa-circle-xmark'),
         "'Recusado' é chave real de BADGES_STATUS_POSTAGEM."),
        (BADGES_STATUS_POSTAGEM, StatusPostagem.REPLICADO,
         Badge(label='Replicado', classe='postagem-replicado', icone='fa-copy'),
         "'Replicado' é chave real de BADGES_STATUS_POSTAGEM."),
        (BADGES_ETAPA, 'base',
         Badge(label='Base', classe='etapa-base', icone='fa-video'),
         "'base' é 1 dos 7 valores que CicloVideo.etapa_atual() pode devolver."),
        (BADGES_ETAPA, 'roteiro',
         Badge(label='Roteiro', classe='etapa-roteiro', icone='fa-pen'),
         "'roteiro' é 1 dos 7 valores de etapa_atual()."),
        (BADGES_ETAPA, 'completo',
         Badge(label='Completo', classe='etapa-completo', icone='fa-film'),
         "'completo' é 1 dos 7 valores de etapa_atual()."),
        (BADGES_ETAPA, 'postar',
         Badge(label='Aguardando Postar', classe='etapa-postar', icone='fa-upload'),
         "'postar' é 1 dos 7 valores de etapa_atual()."),
        (BADGES_ETAPA, 'aguardando_aprovacao',
         Badge(label='Aguardando aprovação', classe='postagem-aguardando', icone='fa-hourglass-half'),
         "'aguardando_aprovacao' é 1 dos 7 valores de etapa_atual() — mesmo badge visual do status de postagem homônimo."),
        (BADGES_ETAPA, 'replicar',
         Badge(label='Aprovado, aguardando replicar', classe='postagem-aprovado', icone='fa-copy'),
         "'replicar' é 1 dos 7 valores de etapa_atual()."),
        (BADGES_ETAPA, 'concluido',
         Badge(label='Concluído', classe='etapa-concluido', icone='fa-circle-check'),
         "'concluido' é 1 dos 7 valores de etapa_atual()."),
        (BADGES_ETAPA, 'xyz_invalido', BADGE_PADRAO,
         'Valor bruto não existe em nenhum dicionário — cai no BADGE_PADRAO em vez de lançar KeyError.'),
        (BADGES_ETAPA, None, BADGE_PADRAO,
         'None não é chave de nenhum dicionário — mesmo fallback do valor desconhecido, prova que .get() nunca quebra com entrada nula.'),
    ],
    ids=[
        'status_manual_ativo', 'status_manual_pausado', 'status_manual_descontinuado',
        'status_postagem_aguardando_aprovacao', 'status_postagem_aprovado',
        'status_postagem_recusado', 'status_postagem_replicado',
        'etapa_base', 'etapa_roteiro', 'etapa_completo', 'etapa_postar',
        'etapa_aguardando_aprovacao', 'etapa_replicar', 'etapa_concluido',
        'fallback_valor_desconhecido', 'fallback_valor_none',
    ],
)
def test_buscar_badge_de(mapa, valor_bruto, esperado, motivo, tabela_resultados):
    # Setup: nada pra montar — mapa/valor_bruto/esperado/motivo já vêm prontos
    # do parametrize.

    # Exercise: chama o SUT de verdade.
    resultado = buscar_badge_de(mapa, valor_bruto)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, f'buscar_badge_de_{valor_bruto}',
        f'{valor_bruto}', f'{esperado.label}', motivo,
        f'{resultado.label}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — função pura, sem estado, sem recurso aberto.


# ===================================================================
# montar_opcoes_com_badge — 1 caso por dicionário real (3) + 1 vazio.
# Esperado hardcoded (valor + label + classe + ícone de cada opção, na ordem
# real de declaração do dict) — não derivado do próprio dict testado.
# ===================================================================

@pytest.mark.parametrize(
    'mapa, esperado, motivo',
    [
        (
            BADGES_STATUS_MANUAL,
            [
                OpcaoComBadge(valor=StatusManualAgenda.ATIVO, label='Ativo', classe='status-ativo', icone='fa-circle-check'),
                OpcaoComBadge(valor=StatusManualAgenda.PAUSADO, label='Pausado', classe='status-pausado', icone='fa-pause'),
                OpcaoComBadge(valor=StatusManualAgenda.DESCONTINUADO, label='Descontinuado', classe='status-descontinuado', icone='fa-circle-xmark'),
            ],
            '3 chaves reais de BADGES_STATUS_MANUAL — cada uma vira 1 OpcaoComBadge, na mesma ordem de declaração do dict.',
        ),
        (
            BADGES_STATUS_POSTAGEM,
            [
                OpcaoComBadge(valor=StatusPostagem.AGUARDANDO_APROVACAO, label='Aguardando aprovação', classe='postagem-aguardando', icone='fa-hourglass-half'),
                OpcaoComBadge(valor=StatusPostagem.APROVADO, label='Aprovado', classe='postagem-aprovado', icone='fa-circle-check'),
                OpcaoComBadge(valor=StatusPostagem.RECUSADO, label='Recusado', classe='postagem-recusado', icone='fa-circle-xmark'),
                OpcaoComBadge(valor=StatusPostagem.REPLICADO, label='Replicado', classe='postagem-replicado', icone='fa-copy'),
            ],
            '4 chaves reais de BADGES_STATUS_POSTAGEM, mesma ordem de declaração do dict.',
        ),
        (
            BADGES_ETAPA,
            [
                OpcaoComBadge(valor='base', label='Base', classe='etapa-base', icone='fa-video'),
                OpcaoComBadge(valor='roteiro', label='Roteiro', classe='etapa-roteiro', icone='fa-pen'),
                OpcaoComBadge(valor='completo', label='Completo', classe='etapa-completo', icone='fa-film'),
                OpcaoComBadge(valor='postar', label='Aguardando Postar', classe='etapa-postar', icone='fa-upload'),
                OpcaoComBadge(valor='aguardando_aprovacao', label='Aguardando aprovação', classe='postagem-aguardando', icone='fa-hourglass-half'),
                OpcaoComBadge(valor='replicar', label='Aprovado, aguardando replicar', classe='postagem-aprovado', icone='fa-copy'),
                OpcaoComBadge(valor='concluido', label='Concluído', classe='etapa-concluido', icone='fa-circle-check'),
            ],
            '7 chaves reais de BADGES_ETAPA, mesma ordem de declaração do dict.',
        ),
        (
            {},
            [],
            'Dicionário vazio — nenhum BADGES_* real é vazio hoje, mas é o limite estrutural da função — lista de opções também vem vazia, sem erro.',
        ),
    ],
    ids=[
        'dicionario_status_manual_3_itens',
        'dicionario_status_postagem_4_itens',
        'dicionario_etapa_7_itens',
        'dicionario_vazio',
    ],
)
def test_montar_opcoes_com_badge(mapa, esperado, motivo, tabela_resultados):
    # Setup: nada pra montar — mapa/esperado/motivo já vêm prontos do parametrize.

    # Exercise: chama o SUT de verdade.
    resultado = montar_opcoes_com_badge(mapa)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, f'montar_opcoes_com_badge_{len(esperado)}_itens',
        f'{len(mapa)} chave(s) de entrada',
        f'{len(esperado)} opção(ões), ordem: {[o.label for o in esperado]}',
        motivo,
        f'{len(resultado)} opção(ões), ordem: {[o.label for o in resultado]}',
        resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — função pura, sem estado, sem recurso aberto.