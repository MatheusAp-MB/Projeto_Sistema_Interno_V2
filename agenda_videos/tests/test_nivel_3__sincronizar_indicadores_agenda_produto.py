"""
Nível 3 — sincronizar_indicadores_agenda_produto()

Grava o resultado de calcular_indicadores() (DOC já testado nas camadas
B0-B2) em IndicadoresAgendaProduto via update_or_create. Aqui só confirma
persistência (relê do banco) e o comportamento de criar x atualizar — não
reexaure a lógica dos indicadores.
"""
from datetime import datetime

import pytest
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_indicadores_agenda_produto
from agenda_videos.models.ciclo_video import CicloVideo
from agenda_videos.models.configuracao_fase import Fase
from agenda_videos.models.indicadores_agenda_produto import IndicadoresAgendaProduto
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 3 — sincronizar_indicadores_agenda_produto()'


def _criar_produto(rotulo):
    return Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo='Produto Teste')


def test_sincronizar_cria_registro_novo(tabela_resultados):
    # Setup: produto com 1 ciclo, sem NENHUM IndicadoresAgendaProduto ainda.
    produto = _criar_produto('cria_registro_novo')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise: chama o SUT de verdade.
    sincronizar_indicadores_agenda_produto(produto)

    # Assert: relê do banco antes de comparar — prova que a escrita
    # persistiu, não confia só no retorno em memória.
    indicadores = IndicadoresAgendaProduto.objects.get(produto=produto)
    esperado = 'base'
    registrar_resultado(
        tabela_resultados, 'sincronizar_cria_registro_novo',
        'produto novo, 1 ciclo Simples, sem indicador ainda',
        esperado, 'nenhum registro existia — update_or_create cria o 1º',
        indicadores.etapa_atual, indicadores.etapa_atual == esperado,
    )
    assert indicadores.etapa_atual == esperado

    # TearDown: nada a desmontar.


def test_sincronizar_atualiza_registro_existente(tabela_resultados):
    # Setup: produto já tem um IndicadoresAgendaProduto desatualizado
    # (etapa='base', de uma sincronização anterior) — o ciclo real já
    # avançou pra 'postar' (produção inteira concluída).
    produto = _criar_produto('atualiza_registro_existente')
    momento = timezone.make_aware(datetime(2026, 8, 1, 12, 0))
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=momento, roteiro_concluido_em=momento, completo_concluido_em=momento,
    )
    IndicadoresAgendaProduto.objects.create(produto=produto, etapa_atual='base')

    # Exercise: chama o SUT de verdade.
    sincronizar_indicadores_agenda_produto(produto)

    # Assert: continua sendo 1 registro só (atualizou, não duplicou), e o
    # valor bate com o estado REAL e atual do ciclo, não com o antigo.
    total_registros = IndicadoresAgendaProduto.objects.filter(produto=produto).count()
    indicadores = IndicadoresAgendaProduto.objects.get(produto=produto)
    esperado = (1, 'postar')
    obtido = (total_registros, indicadores.etapa_atual)
    registrar_resultado(
        tabela_resultados, 'sincronizar_atualiza_registro_existente',
        'indicador antigo dizia "base", ciclo real já está em "postar"',
        esperado, 'update_or_create ATUALIZA o mesmo registro — nunca duplica, e reflete o estado atual',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.