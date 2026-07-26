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

    # * [EXPLICAÇÃO] → Movido de AndamentoAgenda (25/07) — qualquer produto pode
    #                  ser marcado como urgente, mesmo "Não Agendado" (a urgência
    #                  é justamente pra que ele COMECE a ser feito/postado, não só
    #                  pra quem já está no ciclo). RoadmapAgenda é a única tabela
    #                  que existe pra todo produto, sempre — por isso é o dono certo.
    #                  Prioridade 1 em qualquer listagem: Urgente > Atrasado >
    #                  Sem vídeo (critério UP_HAS_SHORTS reprovado, API do ML) > resto.
    urgente = models.BooleanField(default=False)

    # * [EXPLICAÇÃO] → Persistido (25/07), corrigindo erro de arquitetura: esse
    #                  indicador vinha de uma Exists() ao vivo (Produto → Variação
    #                  → Qualidade → Critério), recalculada pra TODO produto a cada
    #                  carregamento de tela, pra poder ordenar por prioridade — isso
    #                  deixou a tela extremamente lenta (até 1955 produtos, 4 tabelas
    #                  juntas, toda vez). Agora só recalcula nos mesmos pontos que já
    #                  recalculam o resto (sincronizar_roadmap_agenda_produto + o
    #                  comando em lote) — fica tão atualizado quanto a última
    #                  sincronização, não em tempo real (defasagem aceitável, mesma
    #                  lógica já usada pro resto do sistema).
    tem_video_reprovado = models.BooleanField(default=False)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Roadmap da Agenda'
        verbose_name_plural = 'Roadmaps da Agenda'

    def __str__(self):
        return f'{self.produto.sku or self.produto.ean} — {self.get_estagio_atual_display()}'