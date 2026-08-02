# agenda_videos/tests/test_criar_proximo_dia_util.py

# Função Objetivo: [mesmo comentário de antes]

import pytest
from datetime import date, datetime, time
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import Fase, ConfiguracaoFase, CicloVideo, StatusPostagem
from agenda_videos.tests.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Camada 3 — criar_proximo() e dias úteis'


def _criar_produto():
    return Produto.objects.create(ean='EAN-TESTE-001', titulo='Produto Teste')


def _criar_configuracao_trimestral():
    return ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_TRIMESTRAL, periodo_continuo=True,
        distancia_dias_corridos=90, distancia_dias_ao_entrar_na_fase=0,
    )


def test_criar_proximo_cai_em_dia_util_mesmo_cruzando_fim_de_semana(tabela_resultados):
    produto = _criar_produto()
    _criar_configuracao_trimestral()

    segunda = date(2026, 8, 3)
    replicado_em = timezone.make_aware(datetime.combine(segunda, time.min))

    ciclo_atual = CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_TRIMESTRAL, numero_ocorrencia=1,
        data_devida=segunda, status=StatusPostagem.REPLICADO,
        replicado_em=replicado_em,
    )

    proximo = ciclo_atual.criar_proximo()
    passou = proximo.data_devida.weekday() < 5

    registrar_resultado(
        tabela_resultados, 'criar_proximo_cai_em_dia_util',
        f'replicado_em = {segunda:%d/%m} (segunda) + 90 dias corridos',
        'cair em dia útil (seg-sex)',
        f'{proximo.data_devida:%d/%m} ({proximo.data_devida.strftime("%A")})',
        passou,
    )

    assert passou, f'{proximo.data_devida} caiu num fim de semana'