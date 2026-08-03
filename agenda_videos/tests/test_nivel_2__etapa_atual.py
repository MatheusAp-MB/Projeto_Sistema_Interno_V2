# agenda_videos/tests/test_nivel2_etapa_atual.py

# Função Objetivo: Testa CicloVideo.etapa_atual() — Nível 2, em memória, sem
# banco. O SUT é uma cascata de 7 "if" com retorno antecipado + 1 else — não
# usa match/case (nem no teste). Cobre os 8 caminhos de retorno possíveis.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

from datetime import datetime

import pytest
from django.utils import timezone

from agenda_videos.models import CicloVideo, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 2 — CicloVideo.etapa_atual()'

AGORA = timezone.make_aware(datetime(2026, 8, 1, 12, 0))  # fixo — etapa_atual só olha is None, não o valor


@pytest.mark.parametrize(
    'rotulo, campos, entrada_legivel, esperado, motivo',
    [
        (
            'nada_feito_comeca_em_base', {}, 'nenhuma etapa feita ainda', 'base',
            'nenhum campo preenchido — toda ocorrência nova começa em Base',
        ),
        (
            'base_feito_falta_roteiro', {'base_concluido_em': AGORA},
            'Base: feito | Roteiro: pendente', 'roteiro',
            'Base concluído, Roteiro ainda não — avança pra próxima etapa da sequência travada',
        ),
        (
            'base_e_roteiro_feitos_falta_completo',
            {'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA},
            'Base: feito | Roteiro: feito | Completo: pendente', 'completo',
            'Base e Roteiro concluídos, Completo ainda não',
        ),
        (
            'producao_pronta_falta_postar',
            {'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA},
            'Base/Roteiro/Completo: feitos | status: nenhum', 'postar',
            'produção inteira concluída, sem status de postagem ainda — pronto pra Postar',
        ),
        (
            'aguardando_aprovacao_do_marketplace',
            {
                'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA,
                'status': StatusPostagem.AGUARDANDO_APROVACAO,
            },
            'produção feita | status: Aguardando Aprovação', 'aguardando_aprovacao',
            'postado, esperando o marketplace aprovar ou recusar',
        ),
        (
            'recusado_volta_pra_completo',
            {
                'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA,
                'status': StatusPostagem.RECUSADO,
            },
            'produção feita | status: Recusado', 'completo',
            'recusado NUNCA fica travado em Postar — precisa refazer o Completo e postar de novo',
        ),
        (
            'aprovado_pronto_pra_replicar',
            {
                'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA,
                'status': StatusPostagem.APROVADO,
            },
            'produção feita | status: Aprovado', 'replicar',
            'aprovado pelo marketplace — só falta o clique manual de Replicar',
        ),
        (
            'replicado_conclui_a_ocorrencia',
            {
                'base_concluido_em': AGORA, 'roteiro_concluido_em': AGORA, 'completo_concluido_em': AGORA,
                'status': StatusPostagem.REPLICADO,
            },
            'produção feita | status: Replicado', 'concluido',
            'replicado — esta ocorrência específica está encerrada (o ciclo como um todo pode continuar)',
        ),
    ],
    ids=[
        'nada_feito_comeca_em_base', 'base_feito_falta_roteiro', 'base_e_roteiro_feitos_falta_completo',
        'producao_pronta_falta_postar', 'aguardando_aprovacao_do_marketplace',
        'recusado_volta_pra_completo', 'aprovado_pronto_pra_replicar', 'replicado_conclui_a_ocorrencia',
    ],
)
def test_etapa_atual(rotulo, campos, entrada_legivel, esperado, motivo, tabela_resultados):
    # Setup: monta 1 CicloVideo em memória, sem salvar.
    ciclo = CicloVideo(**campos)

    # Exercise: chama o SUT de verdade.
    resultado = ciclo.etapa_atual()

    # Assert: registra antes de comparar — entrada_legivel é escrito à mão,
    # nunca o dict cru (isso é o que causava o texto ilegível/cortado).
    registrar_resultado(
        tabela_resultados, rotulo, entrada_legivel, esperado, motivo, resultado,
        resultado == esperado, dado_bruto=campos,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — instância nunca foi salva no banco.