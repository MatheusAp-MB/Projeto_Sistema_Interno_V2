# agenda_videos/tests/test_nivel_4__integracao_config_afeta_roadmap.py

# Função Objetivo: Prova a cadeia INTEIRA — POST real na tela de Configurações
# muda uma ConfiguracaoFase, e o próximo CicloVideo criado por criar_proximo()
# já reflete o valor novo. Motivo de existir: view_configuracoes_agenda_videos
# (Nível 4) e CicloVideo.criar_proximo() (Nível 3) já são testados cada um
# isoladamente, mas nenhum teste até agora provava os dois juntos, ponta a
# ponta. Confirmado por leitura de código que ConfiguracaoFase não é cache
# de nada (diferente de IndicadoresAgendaProduto) — é lida direto do banco
# toda vez — mas este teste dá a garantia executável, não só a leitura do
# código.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

from datetime import date, datetime, time

import pytest
from django.urls import reverse
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import Fase, ConfiguracaoFase, CicloVideo, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — Integração: config mudada pela tela afeta o próximo ciclo real'


@pytest.fixture
def regua_de_fases():
    # Mesma régua real usada em test_nivel_3__criar_proximo.py — Simples
    # (1x) -> Vídeo Mensal (4x, 30d) -> Vídeo Trimestral (contínuo, 90d).
    trimestral = ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_TRIMESTRAL, periodo_continuo=True,
        distancia_dias_corridos=90, distancia_dias_ao_entrar_na_fase=90,
    )
    ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_MENSAL, periodo_continuo=False, periodo=4,
        distancia_dias_corridos=30, distancia_dias_ao_entrar_na_fase=0,
        proxima_fase=trimestral,
    )
    ConfiguracaoFase.objects.create(
        fase=Fase.SIMPLES, periodo_continuo=False, periodo=1,
        proxima_fase=ConfiguracaoFase.objects.get(fase=Fase.VIDEO_MENSAL),
    )


def _url_configuracoes():
    return reverse('agenda_videos_configuracoes')


def _payload_da_regua(**overrides):
    # Reenvia a régua inteira como está, com só o campo sob teste mudando —
    # espelha uma submissão real do form único (as 3 fases sempre juntas).
    dados = {
        'simples_periodo': '1',
        'simples_distancia_dias_corridos': '',
        'simples_distancia_dias_ao_entrar_na_fase': '0',
        'video_mensal_periodo': '4',
        'video_mensal_distancia_dias_corridos': '30',
        'video_mensal_distancia_dias_ao_entrar_na_fase': '0',
        'video_trimestral_periodo_continuo': 'on',
        'video_trimestral_distancia_dias_corridos': '90',
        'video_trimestral_distancia_dias_ao_entrar_na_fase': '90',
    }
    dados.update(overrides)
    return dados


def _criar_ciclo_mensal_replicado(numero_ocorrencia):
    produto = Produto.objects.create(ean=f'EAN-INTEG-{numero_ocorrencia}', titulo='Produto Teste')
    replicado_em = timezone.make_aware(datetime.combine(date(2026, 8, 4), time.min))  # terça-feira
    return CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=numero_ocorrencia,
        status=StatusPostagem.REPLICADO, replicado_em=replicado_em,
    )


def test_post_muda_distancia_e_criar_proximo_ja_usa_o_valor_novo(client, tabela_resultados, regua_de_fases):
    # Setup: ciclo Mensal #1 replicado com a régua ORIGINAL (distância 30d).
    ciclo = _criar_ciclo_mensal_replicado(numero_ocorrencia=1)

    # Exercise: muda a distância do Vídeo Mensal pra 45d pela tela real...
    client.post(_url_configuracoes(), _payload_da_regua(video_mensal_distancia_dias_corridos='45'))
    # ...e só DEPOIS chama criar_proximo() no ciclo que já existia.
    proximo = ciclo.criar_proximo()

    # Assert:
    esperado = date(2026, 9, 18)  # 04/08 + 45 dias corridos, sexta-feira (sem ajuste de dia útil)
    passou = proximo.fase == Fase.VIDEO_MENSAL and proximo.numero_ocorrencia == 2 and proximo.data_devida == esperado
    registrar_resultado(
        tabela_resultados, teste='POST muda distância (30→45d) e criar_proximo() usa o valor novo',
        entrada='ciclo criado com a régua antiga (30d), config mudada DEPOIS pra 45d', esperado=f'data_devida == {esperado} (usa 45d, não 30d)',
        motivo='ConfiguracaoFase é lida ao vivo por criar_proximo() — não existe cache pra ficar desatualizado',
        obtido=f'fase={proximo.fase}, numero_ocorrencia={proximo.numero_ocorrencia}, data_devida={proximo.data_devida}',
        passou=passou,
    )
    assert passou


def test_post_muda_periodo_e_criar_proximo_ja_transiciona_de_fase_mais_cedo(client, tabela_resultados, regua_de_fases):
    # Setup: ciclo Mensal #2 replicado — com o período ORIGINAL (4), a
    # ocorrência #3 ainda estaria dentro do período (não transicionaria).
    ciclo = _criar_ciclo_mensal_replicado(numero_ocorrencia=2)

    # Exercise: muda o período do Vídeo Mensal de 4 pra 2 pela tela real...
    client.post(_url_configuracoes(), _payload_da_regua(video_mensal_periodo='2'))
    # ...e só DEPOIS chama criar_proximo() — a próxima ocorrência seria #3.
    proximo = ciclo.criar_proximo()

    # Assert:
    esperado = date(2026, 11, 2)  # 04/08 + 90 dias corridos (distância de entrada do Trimestral), segunda-feira
    passou = proximo.fase == Fase.VIDEO_TRIMESTRAL and proximo.numero_ocorrencia == 1 and proximo.data_devida == esperado
    registrar_resultado(
        tabela_resultados, teste='POST muda período (4→2) e criar_proximo() já transiciona de fase mais cedo',
        entrada='ciclo #2 replicado com período antigo (4), config mudada DEPOIS pra período 2', esperado='ocorrência #3 não fica mais dentro do período → cria Vídeo Trimestral #1',
        motivo='dentro_do_periodo() é avaliado contra a ConfiguracaoFase atual, lida na hora — não contra o valor que existia quando o ciclo foi criado',
        obtido=f'fase={proximo.fase}, numero_ocorrencia={proximo.numero_ocorrencia}, data_devida={proximo.data_devida}',
        passou=passou,
    )
    assert passou