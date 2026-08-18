# agenda_videos/tests/test_nivel_3__marcar_aguardando_aprovacao_e_replicado.py

# Função Objetivo: Testa CicloVideo.marcar_aguardando_aprovacao() e
# marcar_replicado() — Nível 3 (banco de verdade). Os 2 fazem .save(), então
# todo Assert relê do banco antes de comparar (ver "Nível 3 sempre relê do
# banco antes de comparar" na Disciplina de Testes). marcar_replicado() já
# teve criar_proximo() exaustivamente testado embaixo — aqui só confirma que
# a CHAMADA acontece (ou não) certo, sem repetir a régua de datas.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

from datetime import date, datetime, time

import pytest
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import Fase, ConfiguracaoFase, CicloVideo, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 3 — marcar_aguardando_aprovacao() e marcar_replicado()'


@pytest.fixture
def regua_de_fases():
    # Setup: régua Simples -> Vídeo Mensal -> Vídeo Trimestral, só necessária
    # pro caso em que marcar_replicado() dispara criar_proximo() de verdade.
    trimestral = ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_TRIMESTRAL, periodo_continuo=True,
        distancia_dias_corridos=90, distancia_dias_ao_entrar_na_fase=90,
    )
    ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_MENSAL, periodo_continuo=False, periodo=4,
        distancia_dias_corridos=30, distancia_dias_ao_entrar_na_fase=0,
        proxima_fase=trimestral,
    )


def _criar_produto_e_ciclo(rotulo, fase, numero_ocorrencia, replicado_em_data=None):
    produto = Produto.objects.create(ean=f'EAN{abs(hash(rotulo)) % 1000000}', titulo='Produto Teste')
    replicado_em = None
    if replicado_em_data is not None:
        replicado_em = timezone.make_aware(datetime.combine(replicado_em_data, time.min))
    return CicloVideo.objects.create(
        produto=produto, fase=fase, numero_ocorrencia=numero_ocorrencia, replicado_em=replicado_em,
    )


# ===================================================================
# marcar_aguardando_aprovacao — marca status + timestamp, sem decidir
# nada além disso. Testa relendo do banco, não o objeto em memória.
# ===================================================================

def test_marcar_aguardando_aprovacao(tabela_resultados):
    # Setup: 1 CicloVideo qualquer, ainda sem status de postagem.
    ciclo = _criar_produto_e_ciclo('aguardando_aprovacao', Fase.SIMPLES, 1)

    # Exercise: chama o SUT de verdade.
    ciclo.marcar_aguardando_aprovacao()

    # Assert: relê do banco — prova que o .save() persistiu de verdade,
    # não só que o atributo em memória mudou.
    ciclo_no_banco = CicloVideo.objects.get(pk=ciclo.pk)
    passou = (
        ciclo_no_banco.status == StatusPostagem.AGUARDANDO_APROVACAO
        and ciclo_no_banco.aguardando_aprovacao_em is not None
    )
    registrar_resultado(
        tabela_resultados, 'marcar_aguardando_aprovacao',
        'CicloVideo sem status', 'status=AGUARDANDO_APROVACAO, timestamp preenchido',
        'marcar_aguardando_aprovacao() só registra o status e o momento — não decide mais nada',
        f'status={ciclo_no_banco.status}, timestamp={"preenchido" if ciclo_no_banco.aguardando_aprovacao_em else "vazio"}',
        passou,
    )
    assert passou

    # TearDown: nada a desmontar — banco de teste limpo automaticamente
    # pelo pytest-django a cada teste.


# ===================================================================
# marcar_replicado — Simples NUNCA dispara o próximo ciclo sozinho (regra
# de negócio: espera o clique manual de "Agendar"), qualquer outra fase
# dispara criar_proximo() automaticamente.
# ===================================================================

def test_marcar_replicado_simples_nao_dispara_proximo(tabela_resultados):
    # Setup: CicloVideo na fase Simples.
    ciclo = _criar_produto_e_ciclo('replicado_simples', Fase.SIMPLES, 1)

    # Exercise: chama o SUT de verdade.
    resultado = ciclo.marcar_replicado(['MLB111'], ['MLB222'])

    # Assert: relê o ciclo original do banco (os campos dele mudaram mesmo
    # sem disparar nada) e confirma que NADA novo foi criado.
    ciclo_no_banco = CicloVideo.objects.get(pk=ciclo.pk)
    passou = (
        resultado is None
        and ciclo_no_banco.status == StatusPostagem.REPLICADO
        and ciclo_no_banco.mlbs_replicados == ['MLB111']
        and ciclo_no_banco.mlbs_nao_encontrados == ['MLB222']
    )
    registrar_resultado(
        tabela_resultados, 'marcar_replicado_simples_nao_dispara_proximo',
        'CicloVideo fase=Simples', 'retorna None, mas o próprio ciclo fica marcado REPLICADO',
        'Simples nunca dispara o próximo ciclo sozinho — espera o clique manual de "Agendar"',
        f'retornou={resultado}, status={ciclo_no_banco.status}',
        passou,
    )
    assert passou

    # TearDown: nada a desmontar.


def test_marcar_replicado_fase_normal_dispara_proximo(regua_de_fases, tabela_resultados):
    # Setup: CicloVideo na fase Vídeo Mensal #1, já com replicado_em prévio
    # não é necessário aqui — quem importa é o replicado_em que o PRÓPRIO
    # marcar_replicado() acabou de setar (usa timezone.now(), por isso o
    # teste não prevê a data exata da próxima ocorrência — isso já foi
    # exaustivamente validado em test_nivel_3__criar_proximo.py).
    ciclo = _criar_produto_e_ciclo('replicado_mensal', Fase.VIDEO_MENSAL, 1)

    # Exercise: chama o SUT de verdade.
    resultado = ciclo.marcar_replicado(['MLB333'], [])

    # Assert: confirma que criar_proximo() foi CHAMADO e devolveu a próxima
    # ocorrência certa (fase/número) — não repete a régua de datas, que já
    # tem sua própria bateria de testes.
    passou = (
        resultado is not None
        and resultado.fase == Fase.VIDEO_MENSAL
        and resultado.numero_ocorrencia == 2
    )
    registrar_resultado(
        tabela_resultados, 'marcar_replicado_fase_normal_dispara_proximo',
        'CicloVideo fase=Vídeo Mensal #1', 'retorna a nova ocorrência (Vídeo Mensal #2)',
        'qualquer fase que não seja Simples dispara criar_proximo() automaticamente',
        f'retornou={resultado.fase if resultado else None} #{resultado.numero_ocorrencia if resultado else None}',
        passou,
    )
    assert passou

    # TearDown: nada a desmontar.