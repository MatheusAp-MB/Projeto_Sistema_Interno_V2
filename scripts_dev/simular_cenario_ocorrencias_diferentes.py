import os
import sys


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

from datetime import timedelta
from django.utils import timezone
from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONFIGURACOES = [
    {'ean': '7891117102687', 'ocorrencia': 2},  # Tramontina
    {'ean': '7891988003199', 'ocorrencia': 3},  # Guarany
]
# ========================================

hoje = timezone.now().date()


# Função Objetivo: Acha o inicio_fase certo TESTANDO com a função real do
# sistema — em vez de tentar reproduzir a matemática de dia útil na mão,
# testa candidatos voltando dia a dia até achar o que realmente faz essa
# ocorrência vencer hoje. Garantia de bater com a lógica de produção.
def _achar_inicio_fase_para_vencer_hoje(fase, ocorrencia, hoje):
    for dias_atras in range(90):
        candidato = hoje - timedelta(days=dias_atras)
        janela = calcular_janela_ocorrencia(fase, candidato, ocorrencia)
        if janela.fim == hoje:
            return candidato
    raise RuntimeError(f'Não encontrei inicio_fase que faça a ocorrência {ocorrencia} vencer hoje.')


for config in CONFIGURACOES:
    produto = Produto.objects.filter(ean=config['ean']).first()
    if produto is None:
        print(f'{config["ean"]}: não encontrado.')
        continue

    andamento = produto.andamento_agenda
    fase = andamento.fase_atual.fase
    inicio_fase_certo = _achar_inicio_fase_para_vencer_hoje(fase, config['ocorrencia'], hoje)

    andamento.inicio_fase = inicio_fase_certo
    andamento.ocorrencia_atual = config['ocorrencia']
    andamento.fim_ocorrencia_atual = hoje
    andamento.save(update_fields=['inicio_fase', 'ocorrencia_atual', 'fim_ocorrencia_atual'])
    print(
        f'{config["ean"]}: ocorrência {config["ocorrencia"]}, '
        f'inicio_fase ajustado pra {inicio_fase_certo}, vencendo hoje ({hoje}).'
    )