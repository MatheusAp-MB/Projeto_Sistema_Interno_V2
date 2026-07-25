# agenda_videos/models/roadmap_agenda.py

# Função Objetivo: Estágio AGRUPADO do produto na Agenda (6 valores) — versão
# filtrável/paginável do roadmap de 9 pontos, que só existe calculado em Python.
# Explicação em detalhe: os 4 primeiros pontos do roadmap visual (Simples/Base/
# Roteiros/Completos) colapsam num só valor aqui ("nao_agendado") — o filtro não
# precisa saber em qual dos 4 exatamente, só que a preparação ainda não terminou.

from django.db import models
from produtos.models import Produto


class EstagioAgenda(models.TextChoices):
    NAO_AGENDADO = 'nao_agendado', 'Não Agendado'
    PRONTO_AGENDAMENTO = 'pronto_agendamento', 'Pronto para Agendar'
    DIARIA = 'diaria', 'Diário'
    SEMANAL = 'semanal', 'Semanal'
    MENSAL = 'mensal', 'Mensal'
    OTIMIZADO = 'otimizado', 'Otimizado'


class RoadmapAgenda(models.Model):
    produto = models.OneToOneField(
        Produto, on_delete=models.CASCADE, related_name='roadmap_agenda')
    estagio_atual = models.CharField(
        max_length=20, choices=EstagioAgenda.choices, default=EstagioAgenda.NAO_AGENDADO)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Roadmap da Agenda'
        verbose_name_plural = 'Roadmaps da Agenda'

    def __str__(self):
        return f'{self.produto.sku or self.produto.ean} — {self.get_estagio_atual_display()}'