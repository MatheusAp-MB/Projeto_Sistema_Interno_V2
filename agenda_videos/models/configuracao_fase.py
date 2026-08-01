# agenda_videos/models/configuracao_fase.py

# Função Objetivo: Define a "régua" de cada fase de produção/postagem de vídeo —
# existe 1 registro por fase, nunca por produto. Reestruturação completa (30/07,
# reunião com equipe + superior) — modelo anterior (Diária/Semanal/Mensal, "pool"
# reaproveitado, ciclo com fim) foi descartado por inteiro. Modelo novo: toda
# ocorrência, em qualquer fase, produz vídeo do zero (Base → Roteiro → Completo →
# Postar → Replicar); Vídeo Trimestral nunca termina.

from django.db import models


class Fase(models.TextChoices):
    SIMPLES = 'simples', 'Simples'
    VIDEO_MENSAL = 'video_mensal', 'Vídeo Mensal'
    VIDEO_TRIMESTRAL = 'video_trimestral', 'Vídeo Trimestral'


class ConfiguracaoFase(models.Model):
    fase = models.CharField(max_length=20, choices=Fase.choices, unique=True)

    # * [EXPLICAÇÃO] → Vídeo Trimestral não tem fim — periodo_continuo=True marca
    #                  isso sem ambiguidade (nunca periodo=None pra dizer a mesma
    #                  coisa — decisão explícita do usuário). Quando True, `periodo`
    #                  nunca é lido.
    periodo_continuo = models.BooleanField(default=False)
    periodo = models.PositiveIntegerField(null=True, blank=True)

    # Distância em dias CORRIDOS (nunca úteis) entre 1 ocorrência e a próxima,
    # dentro da mesma fase. Simples não usa (só tem 1 ocorrência).
    distancia_dias_corridos = models.PositiveIntegerField(null=True, blank=True)

    # Distância em dias corridos só na 1ª ocorrência de uma fase, vinda da fase
    # anterior — regra DIFERENTE da distância normal (confirmado com o usuário):
    # Vídeo Mensal #1 libera imediatamente (0) ao Simples terminar; Vídeo
    # Trimestral #1 espera os mesmos 90 dias da distância normal dele.
    distancia_dias_ao_entrar_na_fase = models.PositiveIntegerField(default=0)

    # * [EXPLICAÇÃO] → A sequência Simples→Vídeo Mensal→Vídeo Trimestral é DADO,
    #                  editável no admin — nunca um dict fixo escondido em código
    #                  (decisão explícita do usuário, 30/07). None = não tem
    #                  próxima fase (só faz sentido pra quem já é periodo_continuo).
    proxima_fase = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='fases_anteriores')

    class Meta:
        verbose_name = 'Configuração de Fase'
        verbose_name_plural = 'Configurações de Fase'

    def dentro_do_periodo(self, numero_ocorrencia):
        return self.periodo_continuo or numero_ocorrencia <= self.periodo

    def __str__(self):
        if self.periodo_continuo:
            return f'{self.get_fase_display()} — contínua, a cada {self.distancia_dias_corridos}d'
        return f'{self.get_fase_display()} — {self.periodo}x, a cada {self.distancia_dias_corridos}d'