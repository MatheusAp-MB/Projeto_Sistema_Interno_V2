import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')

import django
django.setup()

from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada

w = SincronizacaoXmlManifestoNotaEntrada.obter()
print('cobertura:', w.data_inicial_cobertura, '→', w.data_final_cobertura)
print('última chamada:', w.data_ultima_chamada)
print('status:', w.status, '| falha:', w.motivo_da_falha)
print('está desatualizada agora?', w.esta_desatualizada())
print('próxima janela seria:', w.calcular_janela_da_proxima_busca())