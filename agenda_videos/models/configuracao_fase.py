# agenda_videos/models/configuracao_fase.py

# Função Objetivo: Define a "régua" de cada fase de postagem de vídeo (Diária/Semanal/Mensal).
# Explicação em detalhe: existe 1 registro por fase, nunca por produto — é a configuração
# global que todo produto na Agenda segue. Números (quantidade/período) não são fixos no
# código de propósito: podem mudar sem exigir migration, e são editados pela tela
# "Configurações" (Agenda de Vídeos → Configurações), que substitui o Admin como forma
# de manutenção — o Admin continua funcionando, mas não é mais o caminho principal.

from django.db import models


class Fase(models.TextChoices):
    DIARIA = 'diaria', 'Diária'
    SEMANAL = 'semanal', 'Semanal'
    MENSAL = 'mensal', 'Mensal'


class ConfiguracaoFase(models.Model):
    fase = models.CharField(max_length=10, choices=Fase.choices, unique=True)

    # Função Objetivo: Nº de vídeos obrigatórios dentro do período (ex: 1).
    # * [EXPLICAÇÃO] → Editável na tela de Configurações, mas NENHUM cálculo do
    #                  sistema lê esse valor hoje — todo cálculo de data/ocorrência
    #                  assume implicitamente "1 vídeo por período" (calculo_datas_fase.py,
    #                  avancar_ocorrencia_ou_fase). Decisão consciente (26/07, pente
    #                  fino): manter assim por enquanto — não há caso de uso real
    #                  hoje pra mais de 1 postagem por período, e o custo de
    #                  implementar isso de verdade (multiplicar em toda a cadeia de
    #                  cálculo) não se justifica sem necessidade concreta. Se um dia
    #                  isso mudar, revisar esse campo primeiro.
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