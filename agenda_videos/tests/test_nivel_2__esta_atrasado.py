# agenda_videos/tests/test_nivel2_esta_atrasado.py

# Função Objetivo: Testa CicloVideo.esta_atrasado() — Nível 2: precisa de 1
# instância de CicloVideo em memória, mas NÃO toca banco (nunca salva, sem
# @pytest.mark.django_db) — o método só lê os próprios campos da instância.
# data_referencia é sempre passado explícito (nunca a data real de hoje),
# pra dar o mesmo resultado hoje, amanhã e daqui a 1 ano.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.
#
# Referência de calendário: 2026-08-06 = quinta | 07 = sexta | 08 = sábado | 10 = segunda

from datetime import date

import pytest
from django.utils import timezone

from agenda_videos.models import CicloVideo
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 2 — CicloVideo.esta_atrasado()'

DATA_DEVIDA = date(2026, 8, 7)  # sexta-feira, fixa de propósito


@pytest.mark.parametrize(
    'rotulo, data_devida, aguardando_aprovacao_em, data_referencia, esperado, motivo',
    [
        (
            'sem_data_devida_nunca_atrasa', None, None, date(2026, 8, 10), False,
            'Simples nunca tem vencimento — sem data_devida, nunca atrasa',
        ),
        (
            'aguardando_aprovacao_nunca_atrasa', DATA_DEVIDA, timezone.now(), date(2026, 8, 10), False,
            'aguardando aprovação: prazo já foi cumprido, não conta atraso mesmo depois da data',
        ),
        (
            'antes_do_prazo_nao_atrasado', DATA_DEVIDA, None, date(2026, 8, 6), False,
            'quinta, 1 dia antes do prazo (sexta) — ainda não venceu',
        ),
        (
            'no_dia_do_prazo_nao_atrasado', DATA_DEVIDA, None, date(2026, 8, 7), False,
            'no próprio dia do prazo — ainda dentro do prazo, não atrasado',
        ),
        (
            'depois_do_prazo_atrasado', DATA_DEVIDA, None, date(2026, 8, 8), True,
            'sábado, 1 dia depois do prazo — atrasado',
        ),
    ],
    ids=[
        'sem_data_devida_nunca_atrasa', 'aguardando_aprovacao_nunca_atrasa',
        'antes_do_prazo_nao_atrasado', 'no_dia_do_prazo_nao_atrasado', 'depois_do_prazo_atrasado',
    ],
)
def test_esta_atrasado(rotulo, data_devida, aguardando_aprovacao_em, data_referencia, esperado, motivo, tabela_resultados):
    # Setup: monta 1 CicloVideo em memória, sem salvar — esta_atrasado() só
    # lê os próprios campos da instância, não precisa de banco.
    ciclo = CicloVideo(data_devida=data_devida, aguardando_aprovacao_em=aguardando_aprovacao_em)

    # Exercise: chama o SUT de verdade, com data_referencia fixa.
    resultado = ciclo.esta_atrasado(data_referencia)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, rotulo,
        f'data_devida={data_devida or "None"}, aguardando_aprovacao={"sim" if aguardando_aprovacao_em else "não"}, hoje={data_referencia:%d/%m}',
        f'{esperado}', motivo, f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — instância nunca foi salva no banco.