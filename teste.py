import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from agenda_videos.models import AndamentoAgenda
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia

qtd = 0
for andamento in AndamentoAgenda.objects.filter(fim_ocorrencia_atual__isnull=True, concluido=False).select_related('fase_atual'):
    janela = calcular_janela_ocorrencia(andamento.fase_atual.fase, andamento.inicio_fase, andamento.ocorrencia_atual)
    andamento.fim_ocorrencia_atual = janela.fim
    andamento.save(update_fields=['fim_ocorrencia_atual'])
    qtd += 1

print(f"{qtd} produto(s) com fim_ocorrencia_atual preenchido retroativamente.")