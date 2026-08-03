# agenda_videos/tests/test_nivel_2__roadmap_produto.py

# Função Objetivo: Nível 2 — cobre _localizar_indice_atual() e
# _montar_etapas_rodada_atual(), de agenda_videos/funcoes_auxiliares/
# roadmap_produto.py — precisam de 1 CicloVideo em memória (nunca salvo),
# mas não tocam banco. 2ª rodada desse arquivo (1ª foi Nível 0 — rótulo e
# estado visual puros); a 3ª (_montar_caminho_completo_fases,
# calcular_roadmap_produto) é Nível 3, tocam ConfiguracaoFase de verdade.

from datetime import datetime

import pytest
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    EstadoVisualRoadmap, EtapaRodadaAtual, _PontoCaminho,
    _localizar_indice_atual, _montar_etapas_rodada_atual,
)
from agenda_videos.models import CicloVideo, Fase, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 2 — roadmap_produto (_localizar_indice_atual / _montar_etapas_rodada_atual)'

AGORA = timezone.make_aware(datetime(2026, 8, 1, 12, 0))  # fixo — etapa_atual só olha is None, não o valor

# Esteira fixa padrão — mesma régua real do projeto (Simples#1, Mensal#1-4,
# Trimestral contínuo), reaproveitada em todos os casos de
# _localizar_indice_atual.
PONTOS_CAMINHO_PADRAO = [
    _PontoCaminho(fase=Fase.SIMPLES, numero=1),
    _PontoCaminho(fase=Fase.VIDEO_MENSAL, numero=1),
    _PontoCaminho(fase=Fase.VIDEO_MENSAL, numero=2),
    _PontoCaminho(fase=Fase.VIDEO_MENSAL, numero=3),
    _PontoCaminho(fase=Fase.VIDEO_MENSAL, numero=4),
    _PontoCaminho(fase=Fase.VIDEO_TRIMESTRAL, numero=None),
]


# ===================================================================
# _localizar_indice_atual — 5 casos cobrem 100% de branch: ponto contínuo
# que casa e que não casa, ponto numerado que casa e que não casa (dentro
# dos próprios casos, ao pular pontos errados), e o fallback final.
# ===================================================================

@pytest.mark.parametrize(
    'rotulo, fase_ciclo, numero_ciclo, esperado, motivo',
    [
        (
            'simples_e_o_primeiro_ponto', Fase.SIMPLES, 1, 0,
            'Simples#1 é o 1º ponto do caminho fixo — índice 0.',
        ),
        (
            'video_mensal_no_meio', Fase.VIDEO_MENSAL, 2, 2,
            'Vídeo Mensal#2 é o 3º ponto do caminho (índice 2) — pula Simples e Mensal#1 antes de achar.',
        ),
        (
            'video_mensal_ultimo_antes_do_continuo', Fase.VIDEO_MENSAL, 4, 4,
            'Vídeo Mensal#4 é o último ponto finito antes do contínuo — índice 4.',
        ),
        (
            'video_trimestral_casa_so_pela_fase', Fase.VIDEO_TRIMESTRAL, 9, 5,
            'Ponto contínuo (numero=None) casa só pela fase — número 9 do ciclo é ignorado, sempre índice 5.',
        ),
        (
            'fase_nao_existe_no_caminho_cai_no_ultimo', 'fase_inexistente_xyz', 1, 5,
            'Fase que não existe em nenhum ponto do caminho — fallback de segurança cai no último índice (len(pontos)-1 = 5).',
        ),
    ],
    ids=[
        'simples_e_o_primeiro_ponto',
        'video_mensal_no_meio',
        'video_mensal_ultimo_antes_do_continuo',
        'video_trimestral_casa_so_pela_fase',
        'fase_nao_existe_no_caminho_cai_no_ultimo',
    ],
)
def test_localizar_indice_atual(rotulo, fase_ciclo, numero_ciclo, esperado, motivo, tabela_resultados):
    # Setup: monta 1 CicloVideo em memória, sem salvar — a função só lê
    # .fase e .numero_ocorrencia da instância.
    ciclo = CicloVideo(fase=fase_ciclo, numero_ocorrencia=numero_ciclo)

    # Exercise: chama o SUT de verdade, com a esteira fixa padrão.
    resultado = _localizar_indice_atual(PONTOS_CAMINHO_PADRAO, ciclo)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, rotulo,
        f'fase={fase_ciclo}, numero_ocorrencia={numero_ciclo}',
        f'{esperado}', motivo, f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — instância nunca foi salva no banco.


# ===================================================================
# _montar_etapas_rodada_atual — 8 casos cobrem as 5 posições da esteira +
# as 2 sobreposições de índice (postar/aguardando_aprovacao no índice 3,
# completo/recusado no índice 2) + o caso "concluido" (índice 5, fora do
# range 0-4 — nenhum passo fica marcado como atual, todos viram Concluído).
# ===================================================================

def _resumo(etapas):
    # Função Objetivo: representação compacta de 1 lista de EtapaRodadaAtual
    # pra caber na tabela do terminal — o assert real usa a lista completa,
    # isso é só pra exibição legível.
    return [(e.chave_badge, e.estado.value, e.chave_acao) for e in etapas]


@pytest.mark.parametrize(
    'rotulo, campos, entrada_legivel, esperado, motivo',
    [
        (
            'etapa_base', {}, 'nenhuma etapa feita ainda',
            [
                EtapaRodadaAtual(nome='Base', chave_badge='base', estado=EstadoVisualRoadmap.ATUAL, chave_acao='base'),
                EtapaRodadaAtual(nome='Roteiro', chave_badge='roteiro', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
                EtapaRodadaAtual(nome='Completo', chave_badge='completo', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
                EtapaRodadaAtual(nome='Postar', chave_badge='postar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
                EtapaRodadaAtual(nome='Replicar', chave_badge='replicar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
            ],
            'Nada feito ainda — Base é a posição 0, fica Atual; resto Futuro.',
        ),
        (
            'etapa_roteiro', {'base_concluido_em': AGORA}, 'Base: feito | Roteiro: pendente',
            [
                EtapaRodadaAtual(nome='Base', chave_badge='base', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Roteiro', chave_badge='roteiro', estado=EstadoVisualRoadmap.ATUAL, chave_acao='roteiro'),
                EtapaRodadaAtual(nome='Completo', chave_badge='completo', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
                EtapaRodadaAtual(nome='Postar', chave_badge='postar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
                EtapaRodadaAtual(nome='Replicar', chave_badge='replicar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
            ],
            'Base concluído (posição 0), Roteiro é a posição 1 — fica Atual; resto Futuro.',
        ),
        (
            'etapa_completo', {'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA},
            'Base: feito | Roteiro: feito | Completo: pendente | status: nenhum',
            [
                EtapaRodadaAtual(nome='Base', chave_badge='base', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Roteiro', chave_badge='roteiro', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Completo', chave_badge='completo', estado=EstadoVisualRoadmap.ATUAL, chave_acao='completo'),
                EtapaRodadaAtual(nome='Postar', chave_badge='postar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
                EtapaRodadaAtual(nome='Replicar', chave_badge='replicar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
            ],
            'Base/Roteiro concluídos, Completo é a posição 2 — sem status, fica Atual (não Recusado).',
        ),
        (
            'etapa_completo_recusado',
            {
                'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA,
                'status': StatusPostagem.RECUSADO,
            },
            'produção feita | status: Recusado (volta pra Completo)',
            [
                EtapaRodadaAtual(nome='Base', chave_badge='base', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Roteiro', chave_badge='roteiro', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Completo', chave_badge='completo', estado=EstadoVisualRoadmap.RECUSADO, chave_acao='completo'),
                EtapaRodadaAtual(nome='Postar', chave_badge='postar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
                EtapaRodadaAtual(nome='Replicar', chave_badge='replicar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
            ],
            'Mesma posição 2 do caso anterior (etapa_atual() também devolve "completo"), mas status=Recusado muda a aparência pra Recusado.',
        ),
        (
            'etapa_postar',
            {'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA},
            'produção feita | status: nenhum',
            [
                EtapaRodadaAtual(nome='Base', chave_badge='base', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Roteiro', chave_badge='roteiro', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Completo', chave_badge='completo', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Postar', chave_badge='postar', estado=EstadoVisualRoadmap.ATUAL, chave_acao='postar'),
                EtapaRodadaAtual(nome='Replicar', chave_badge='replicar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
            ],
            'Produção pronta, sem status ainda — Postar é a posição 3, fica Atual.',
        ),
        (
            'etapa_aguardando_aprovacao',
            {
                'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA,
                'status': StatusPostagem.AGUARDANDO_APROVACAO,
            },
            'produção feita | status: Aguardando Aprovação',
            [
                EtapaRodadaAtual(nome='Base', chave_badge='base', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Roteiro', chave_badge='roteiro', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Completo', chave_badge='completo', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Postar', chave_badge='postar', estado=EstadoVisualRoadmap.AGUARDANDO, chave_acao='aguardando_aprovacao'),
                EtapaRodadaAtual(nome='Replicar', chave_badge='replicar', estado=EstadoVisualRoadmap.FUTURO, chave_acao=None),
            ],
            'Mesma posição 3 do caso anterior, mas status=Aguardando aprovação muda a aparência e a chave_acao (nunca "postar" de novo).',
        ),
        (
            'etapa_replicar',
            {
                'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA,
                'status': StatusPostagem.APROVADO,
            },
            'produção feita | status: Aprovado',
            [
                EtapaRodadaAtual(nome='Base', chave_badge='base', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Roteiro', chave_badge='roteiro', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Completo', chave_badge='completo', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Postar', chave_badge='postar', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Replicar', chave_badge='replicar', estado=EstadoVisualRoadmap.APROVADO_CLARO, chave_acao='replicar'),
            ],
            'Aprovado — Replicar é a última posição (4), fica Aprovado/aguardando replicar.',
        ),
        (
            'etapa_concluido',
            {
                'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA,
                'status': StatusPostagem.REPLICADO,
            },
            'produção feita | status: Replicado',
            [
                EtapaRodadaAtual(nome='Base', chave_badge='base', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Roteiro', chave_badge='roteiro', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Completo', chave_badge='completo', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Postar', chave_badge='postar', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
                EtapaRodadaAtual(nome='Replicar', chave_badge='replicar', estado=EstadoVisualRoadmap.CONCLUIDO, chave_acao=None),
            ],
            'Replicado — índice interno vira 5, fora do range de 0-4 — os 5 passos viram Concluído, NENHUM fica marcado como atual.',
        ),
    ],
    ids=[
        'etapa_base', 'etapa_roteiro', 'etapa_completo', 'etapa_completo_recusado',
        'etapa_postar', 'etapa_aguardando_aprovacao', 'etapa_replicar', 'etapa_concluido',
    ],
)
def test_montar_etapas_rodada_atual(rotulo, campos, entrada_legivel, esperado, motivo, tabela_resultados):
    # Setup: monta 1 CicloVideo em memória, sem salvar.
    ciclo = CicloVideo(**campos)

    # Exercise: chama o SUT de verdade.
    resultado = _montar_etapas_rodada_atual(ciclo)

    # Assert: registra antes de comparar (resumo compacto pra tabela caber),
    # depois compara a lista completa de verdade.
    registrar_resultado(
        tabela_resultados, rotulo, entrada_legivel, f'{_resumo(esperado)}', motivo,
        f'{_resumo(resultado)}', resultado == esperado, dado_bruto=campos,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — instância nunca foi salva no banco.