"""
Nível 2 — calcular_indicadores_ciclo()

Calcula os indicadores usados no dashboard "A Fazer Hoje" (atrasado, risco,
vencimento, fase) a partir de um produto+ciclo já prontos. Não toca banco —
só lê e escreve atributos Python soltos, por isso fica no Nível 2.

DOC (ultimo_dia_util_ou_hoje, adicionar_dias_uteis, etapa_atual(),
esta_atrasado()) já testados em Nível 0/2 — aqui só confirmamos o
passthrough e a lógica NOVA (o indicador de risco).
"""
from datetime import date, datetime

import pytest
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.a_fazer_hoje import calcular_indicadores_ciclo
from agenda_videos.models.ciclo_video import CicloVideo
from agenda_videos.models.configuracao_fase import Fase
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 2 — calcular_indicadores_ciclo()'

# data_referencia fixa em todo o arquivo: segunda 03/08/2026.
# hoje = ultimo_dia_util_ou_hoje(03/08) = 03/08 (já é dia útil).
# limite_risco = adicionar_dias_uteis(03/08, 1) = 04/08 (terça, sem fim de
# semana no meio) — confirmado pelos testes de Nível 0.
DATA_REFERENCIA = date(2026, 8, 3)


def _producao_completa():
    momento = timezone.make_aware(datetime(2026, 8, 1, 12, 0))
    return {
        'base_concluido_em': momento,
        'roteiro_concluido_em': momento,
        'completo_concluido_em': momento,
    }


def _formatar_data(valor):
    return valor.strftime('%d/%m/%Y') if valor else 'None'


@pytest.mark.parametrize(
    'rotulo, data_devida, campos_producao, esperado, motivo',
    [
        (
            'risco_true_quando_tudo_bate', date(2026, 8, 3), {}, True,
            'etapa base (produção) + não atrasado + prazo dentro do limite (hoje)',
        ),
        (
            'risco_true_no_limite_exato', date(2026, 8, 4), {}, True,
            'prazo exatamente igual ao limite de risco (hoje + 1 dia útil) — regra usa <=',
        ),
        (
            'risco_false_quando_atrasado', date(2026, 7, 31), {}, False,
            'prazo já passou — "não atrasado" falha, mesmo com etapa em produção e dentro do limite',
        ),
        (
            'risco_false_quando_etapa_fora_de_producao', date(2026, 8, 3), _producao_completa(), False,
            'produção inteira concluída (etapa vira "postar") — "postar" não é etapa de produção',
        ),
        (
            'risco_false_quando_sem_data_devida', None, {}, False,
            'Simples nunca tem vencimento — sem data_devida, risco nunca é True mesmo em produção',
        ),
        (
            'risco_false_quando_prazo_ainda_longe', date(2026, 8, 10), {}, False,
            'prazo muito depois do limite de risco — ainda não é hora de alertar',
        ),
    ],
    ids=[
        'risco_true_quando_tudo_bate', 'risco_true_no_limite_exato',
        'risco_false_quando_atrasado', 'risco_false_quando_etapa_fora_de_producao',
        'risco_false_quando_sem_data_devida', 'risco_false_quando_prazo_ainda_longe',
    ],
)
def test_calcular_indicadores_ciclo_risco(rotulo, data_devida, campos_producao, esperado, motivo, tabela_resultados):
    # Setup: produto + ciclo em memória, sem .save().
    produto = Produto(sku='ABC123', titulo='Produto Teste')
    ciclo = CicloVideo(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        data_devida=data_devida, **campos_producao,
    )

    # Exercise: chama o SUT de verdade.
    calcular_indicadores_ciclo(produto, ciclo, DATA_REFERENCIA)

    # Assert: só o indicador de risco importa aqui — atrasado/vencimento/fase
    # são passthrough direto, sem lógica nova pra testar isoladamente.
    resultado = produto.a_fazer_hoje_risco
    etapa_legivel = 'postar' if campos_producao else 'base'
    registrar_resultado(
        tabela_resultados, rotulo,
        f'data_devida={_formatar_data(data_devida)}, etapa={etapa_legivel}',
        esperado, motivo, resultado, resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar (nada foi salvo no banco).


def test_calcular_indicadores_ciclo_atrasado_usa_data_referencia(tabela_resultados):
    # Setup: prazo em 31/12/2029, mas a data_referencia simulada é 01/01/2030
    # — de propósito bem longe da data real do sistema. Se a função ignorasse
    # data_referencia e usasse date.today() por fora, o resultado sairia
    # False (a data real de hoje é muito anterior a 2029).
    produto = Produto(sku='ABC123', titulo='Produto Teste')
    ciclo = CicloVideo(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        data_devida=date(2029, 12, 31),
    )
    data_referencia_simulada = date(2030, 1, 1)

    # Exercise: chama o SUT de verdade.
    calcular_indicadores_ciclo(produto, ciclo, data_referencia_simulada)

    # Assert: só bate True se a propagação pro DOC (esta_atrasado) realmente
    # aconteceu com a data simulada, não com a data real do sistema.
    resultado = produto.a_fazer_hoje_atrasado
    esperado = True
    registrar_resultado(
        tabela_resultados, 'atrasado_usa_data_referencia_informada',
        'data_devida=31/12/2029, data_referencia simulada=01/01/2030',
        esperado,
        'só bate se a função propagar data_referencia de verdade pro DOC, não a data real do sistema',
        resultado, resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.