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

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EAN_ATRASADO = '7891117102687'  # Tramontina
DIAS_UTEIS_DE_ATRASO = 3
# ========================================


# Função Objetivo: Recua em DIAS ÚTEIS (segunda a sexta), nunca em dias
# corridos — Diária só existe em dia útil; subtrair dia corrido pode cair
# num sábado/domingo, um cenário que nunca aconteceria na vida real.
def _subtrair_dias_uteis(data, quantidade):
    candidato = data
    dias_subtraidos = 0
    while dias_subtraidos < quantidade:
        candidato -= timedelta(days=1)
        if candidato.weekday() < 5:  # 0=segunda ... 4=sexta
            dias_subtraidos += 1
    return candidato


hoje = timezone.now().date()
data_atrasada = _subtrair_dias_uteis(hoje, DIAS_UTEIS_DE_ATRASO)

produto = Produto.objects.filter(ean=EAN_ATRASADO).first()
if produto is None:
    print(f'{EAN_ATRASADO}: não encontrado.')
else:
    andamento = produto.andamento_agenda
    # * [EXPLICAÇÃO] → Ocorrência 1 é o caso mais simples de forçar vencido:
    #                  a janela dela é só o próprio inicio_fase (sem avançar
    #                  dia útil nenhum), então setar os 2 iguais já garante
    #                  que a TELA (recalculada) e o CAMPO salvo (usado pro
    #                  filtro de verdade) concordam — mesmo cuidado que
    #                  aprendemos no cenário anterior.
    andamento.ocorrencia_atual = 1
    andamento.inicio_fase = data_atrasada
    andamento.fim_ocorrencia_atual = data_atrasada
    andamento.save(update_fields=['ocorrencia_atual', 'inicio_fase', 'fim_ocorrencia_atual'])
    print(
        f'{EAN_ATRASADO}: ocorrência 1, vencendo {data_atrasada} '
        f'({DIAS_UTEIS_DE_ATRASO} dia(s) útil(eis) atrás, {data_atrasada.strftime("%A")}) — deve aparecer como Atrasado.'
    )