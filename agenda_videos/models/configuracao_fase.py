# agenda_videos/models/configuracao_fase.py

# Função Objetivo: Define a "régua" de cada fase de postagem de vídeo (Diária/Semanal/Mensal).
# Explicação em detalhe: existe 1 registro por fase, nunca por produto — é a configuração
# global que todo produto na Agenda segue. Números (quantidade/período) não são fixos no
# código de propósito: podem mudar sem exigir migration, e o próprio usuário confirmou não
# ter certeza dos valores reais de Semanal/Mensal hoje — por isso não há seed/valor padrão
# assumido aqui, os 3 registros devem ser criados manualmente (admin) com os números reais.

from django.db import models


class Fase(models.TextChoices):
    DIARIA = 'diaria', 'Diária'
    SEMANAL = 'semanal', 'Semanal'
    MENSAL = 'mensal', 'Mensal'


class ConfiguracaoFase(models.Model):
    fase = models.CharField(max_length=10, choices=Fase.choices, unique=True)

    # Função Objetivo: Nº de vídeos obrigatórios dentro do período (ex: 1).
    quantidade_postagens = models.PositiveIntegerField()

    # * [EXPLICAÇÃO] → Unidade de tempo depende da fase (confirmado com o usuário):
    #                  Diária = nº de dias úteis (pula sáb/dom; feriado não é detectado
    #                  de propósito — simplificação deliberada, vira "Atrasado" normal).
    #                  Semanal = nº de semanas (cada semana sempre segunda a sexta).
    #                  Mensal = nº de meses (do dia 1 ao último dia do mês, dias corridos
    #                  — dia útil não se aplica aqui).
    periodo = models.PositiveIntegerField()

    class Meta:
        verbose_name = 'Configuração de Fase'
        verbose_name_plural = 'Configurações de Fase'

    def __str__(self):
        return f'{self.get_fase_display()} — {self.quantidade_postagens}x a cada {self.periodo}'