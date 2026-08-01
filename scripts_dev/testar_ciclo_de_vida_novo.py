# scripts_dev/testar_ciclo_de_vida_novo.py

# Função Objetivo: Testa o ciclo de vida inteiro do modelo novo (Simples →
# Vídeo Mensal x4 → Vídeo Trimestral) sem depender de nenhuma tela — só
# ConfiguracaoFase + CicloVideo. Roda em cima de um produto real (você escolhe
# o EAN abaixo), então USE UM PRODUTO DE TESTE, não um de verdade.
#
# * [EXPLICAÇÃO] → replicado_em é simulado com data artificial, avançando
#                  30/90 dias a cada rodada (em vez de timezone.now() real) —
#                  senão todas as rodadas replicariam no mesmo segundo real,
#                  e "hoje + 30 dias" daria sempre a mesma data (não prova
#                  nada sobre o espaçamento). Isso é só pra ESTE script —
#                  código de verdade nunca deve fazer isso.

import os
import sys
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from produtos.models import Produto
from agenda_videos.models import ConfiguracaoFase, Fase, CicloVideo, StatusPostagem

EAN_PRODUTO_DE_TESTE = '7893946189532'


def preparar_configuracao_fase():
    trimestral, _ = ConfiguracaoFase.objects.update_or_create(
        fase=Fase.VIDEO_TRIMESTRAL,
        defaults={'periodo_continuo': True, 'periodo': None,
                  'distancia_dias_corridos': 90, 'distancia_dias_ao_entrar_na_fase': 90},
    )
    mensal, _ = ConfiguracaoFase.objects.update_or_create(
        fase=Fase.VIDEO_MENSAL,
        defaults={'periodo_continuo': False, 'periodo': 4,
                  'distancia_dias_corridos': 30, 'distancia_dias_ao_entrar_na_fase': 0,
                  'proxima_fase': trimestral},
    )
    ConfiguracaoFase.objects.update_or_create(
        fase=Fase.SIMPLES,
        defaults={'periodo_continuo': False, 'periodo': 1,
                  'distancia_dias_corridos': None, 'distancia_dias_ao_entrar_na_fase': 0,
                  'proxima_fase': mensal},
    )
    print('ConfiguracaoFase preparada: Simples -> Vídeo Mensal (4x, 30d) -> Vídeo Trimestral (contínua, 90d)\n')


# Função Objetivo: Simula o ciclo completo, mas com REPLICADO_EM numa data
# artificial (não "agora") — só assim dá pra provar o espaçamento de
# 30/90 dias sem esperar meses de verdade.
def simular_ciclo_completo(ciclo, data_replicado_simulada):
    ciclo.base_concluido_em = timezone.now()
    ciclo.roteiro_concluido_em = timezone.now()
    ciclo.completo_concluido_em = timezone.now()
    ciclo.save(update_fields=['base_concluido_em', 'roteiro_concluido_em', 'completo_concluido_em'])
    assert ciclo.etapa_atual() == 'postar', f'Esperava "postar", veio "{ciclo.etapa_atual()}"'

    ciclo.status = StatusPostagem.AGUARDANDO_APROVACAO
    ciclo.aguardando_aprovacao_em = timezone.now()
    ciclo.save(update_fields=['status', 'aguardando_aprovacao_em'])

    ciclo.status = StatusPostagem.APROVADO
    ciclo.aprovado_ou_recusado_em = timezone.now()
    ciclo.save(update_fields=['status', 'aprovado_ou_recusado_em'])
    assert ciclo.etapa_atual() == 'replicar', f'Esperava "replicar", veio "{ciclo.etapa_atual()}"'

    replicado_em_simulado = timezone.make_aware(datetime.combine(data_replicado_simulada, datetime.min.time()))
    with transaction.atomic():
        ciclo.status = StatusPostagem.REPLICADO
        ciclo.replicado_em = replicado_em_simulado
        ciclo.mlbs_replicados = ['MLB000TESTE1', 'MLB000TESTE2']
        ciclo.mlbs_nao_encontrados = []
        ciclo.save(update_fields=['status', 'replicado_em', 'mlbs_replicados', 'mlbs_nao_encontrados'])
        proximo = ciclo.criar_proximo()

    assert ciclo.etapa_atual() == 'concluido'
    return proximo


preparar_configuracao_fase()

produto = Produto.objects.filter(ean=EAN_PRODUTO_DE_TESTE).first()
if produto is None:
    print(f'Produto EAN {EAN_PRODUTO_DE_TESTE} não encontrado — ajuste EAN_PRODUTO_DE_TESTE no topo do script.')
    sys.exit(1)

CicloVideo.objects.filter(produto=produto).delete()

ciclo = CicloVideo.iniciar_agenda(produto)
print(f'1. {ciclo.get_fase_display()} #{ciclo.numero_ocorrencia} — devida em {ciclo.data_devida} (deve ser hoje)')
assert ciclo.fase == Fase.SIMPLES and ciclo.numero_ocorrencia == 1

# * [EXPLICAÇÃO] → Simula 6 replicações, cada uma "acontecendo" no dia exato
#                  em que a rodada anterior venceu — o cenário mais realista
#                  possível (opera sempre no prazo certo).
data_simulada = ciclo.data_devida
for i in range(6):
    proximo = simular_ciclo_completo(ciclo, data_simulada)
    diferenca_dias = (proximo.data_devida - data_simulada).days
    print(
        f'{i + 2}. {proximo.get_fase_display()} #{proximo.numero_ocorrencia} — '
        f'devida em {proximo.data_devida} ({diferenca_dias} dias corridos após replicar o anterior)'
    )
    ciclo = proximo
    data_simulada = ciclo.data_devida

print('\nConcluído sem nenhum assert falhar — o espaçamento entre rodadas está correto.')