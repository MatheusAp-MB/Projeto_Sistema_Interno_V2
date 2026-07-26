import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from agenda_videos.models import AndamentoAgenda, PreparacaoVideoFase, ConfiguracaoFase, Fase
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto

ORDEM_FASES = [Fase.DIARIA, Fase.SEMANAL, Fase.MENSAL]
periodos = {c.fase: c.periodo for c in ConfiguracaoFase.objects.all()}

qtd = 0
for andamento in AndamentoAgenda.objects.select_related('produto', 'fase_atual').all():
    indice_atual = ORDEM_FASES.index(andamento.fase_atual.fase)
    for fase in ORDEM_FASES[:indice_atual + 1]:
        PreparacaoVideoFase.objects.update_or_create(
            produto=andamento.produto, fase=fase,
            defaults={
                'roteiros_gerados': True, 'completos_produzidos': True,
                'quantidade_roteiros': periodos.get(fase, 0),
            },
        )
    sincronizar_roadmap_agenda_produto(andamento.produto)
    qtd += 1

print(f"{qtd} produto(s) com PreparacaoVideoFase reaplicada (Decisão A) pra todas as fases até a atual.")