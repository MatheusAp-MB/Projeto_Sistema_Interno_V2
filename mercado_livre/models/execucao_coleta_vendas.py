# mercado_livre/models/execucao_coleta_vendas.py
#
# Função Objetivo: Registro de cada CLIQUE nos botões de atualização da tela "Vendas — Histórico de vendas" (1 linha por clique), com o total EXATO de
# chamadas ao Mercado Livre que o clique custou. Serve para responder depois, com uma consulta, "quanto a coleta custa?" (por dia, por tipo de botão, por
# SKU, por pessoa) sem depender de arquivo de log. Decisão do Matheus (12/10/2026): esse número é importante e precisa ficar guardado no banco.
#
# * [EXPLICAÇÃO] → Diferença para ColetaVendasMercadoLivre (coleta_vendas.py): aquela tem 1 linha por TRECHO lido e é ela que diz a cobertura ("tenho dados
#                  de X a Y"). Um "Atualizar produto" gera dezenas de linhas lá, e as chamadas que não viraram trecho (a 1ª página de uma janela que voltou
#                  partida, trechos que falharam) não aparecem em nenhuma delas. Esta tabela tem 1 linha por CLIQUE e soma tudo que o clique gastou.
#                  Para custo de API, SOMAR SÓ ESTA TABELA: os mesmos pedidos aparecem nas duas e somar as duas conta em dobro.
# * [EXPLICAÇÃO] → Quem preenche: "Atualizar dia" e "Coletar período da conta" são gravados pelo servidor (coletar_vendas_ml.py), que conta cada
#                  requisição no cliente da API. "Atualizar" de um MLB e "Atualizar produto" (com ou sem "Reler tudo") a tela monta em vários trechos;
#                  quando o último termina, a tela soma e manda o total para o servidor gravar (view_vendas_execucao_registrar). Se a pessoa fechar a
#                  aba no meio, esse clique não é registrado aqui (os trechos que já terminaram continuam em ColetaVendasMercadoLivre).
# * [EXPLICAÇÃO] → Não há tela de administração para esta tabela (decisão do Matheus): consulta-se pelo shell do Django ou direto no MySQL.

from django.db import models
from django.utils import timezone


class ExecucaoColetaVendasMercadoLivre(models.Model):
    class Tipo(models.TextChoices):
        PRODUTO = 'produto', 'Atualizar produto (todos os MLBs do SKU; com ou sem "Reler tudo")'
        MLB     = 'mlb',     'Atualizar um MLB'
        DIA     = 'dia',     'Atualizar um dia da conta toda'
        PERIODO = 'periodo', 'Coletar um período da conta toda'

    class Status(models.TextChoices):
        CONCLUIDA = 'concluida', 'Concluída'
        PARCIAL   = 'parcial',   'Parcial (parou, foi interrompida ou algum trecho falhou)'
        FALHA     = 'falha',     'Falhou (nenhum trecho foi lido)'

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    sku  = models.CharField(max_length=40, blank=True)   # quem pediu (só em 'produto' e 'mlb')
    mlb  = models.CharField(max_length=20, blank=True)   # só em 'mlb'
    reler_tudo = models.BooleanField(default=False)      # o clique foi "Reler tudo" (ignora o que já estava coletado)

    # * [EXPLICAÇÃO] → O período PEDIDO no clique (datas inclusivas, dia de Brasília). Em 'dia' as duas datas são o mesmo dia.
    data_de  = models.DateField()
    data_ate = models.DateField()

    status = models.CharField(max_length=10, choices=Status.choices)

    # * [EXPLICAÇÃO] → O tamanho do trabalho: `mlbs` = quantos MLBs (0 nos botões da conta toda); `dias_total` = dias × MLBs do período pedido;
    #                  `dias_a_coletar` = o que o plano decidiu ler (o resto já estava coletado e foi pulado). `trechos` = leituras que terminaram
    #                  (no 'dia' é 1; no 'periodo' são os dias lidos); `trechos_com_falha` = leituras que falharam.
    mlbs           = models.PositiveIntegerField(default=0)
    dias_total     = models.PositiveIntegerField(default=0)
    dias_a_coletar = models.PositiveIntegerField(default=0)
    trechos        = models.PositiveIntegerField(default=0)
    trechos_com_falha = models.PositiveIntegerField(default=0)

    # * [EXPLICAÇÃO] → `chamadas` é o número que importa: as requisições REAIS ao Mercado Livre deste clique (cada tentativa conta, inclusive as que
    #                  voltaram partidas ou falharam). Se `trechos_sem_contagem` > 0, algum trecho não informou o seu número (erro inesperado ou rede
    #                  caída) e `chamadas` é um MÍNIMO, não o total exato.
    chamadas             = models.PositiveIntegerField(default=0)
    trechos_sem_contagem = models.PositiveIntegerField(default=0)
    erros_429            = models.PositiveIntegerField(default=0)
    pedidos_lidos        = models.PositiveIntegerField(default=0)
    segundos             = models.PositiveIntegerField(default=0)

    # O texto que a pessoa viu ao final do clique. Nos botões que o servidor executa inteiro (dia e período) vem com a lista COMPLETA dos avisos da coleta
    # (título "Avisos desta coleta", um por linha); a tela mostra só o 1º.
    mensagem = models.TextField(blank=True)
    usuario  = models.CharField(max_length=150, blank=True)

    iniciado_em  = models.DateTimeField()
    concluido_em = models.DateTimeField()

    class Meta:
        verbose_name        = 'Execução de coleta de vendas do Mercado Livre'
        verbose_name_plural = 'Execuções de coleta de vendas do Mercado Livre'
        ordering = ['-iniciado_em']
        indexes = [
            models.Index(fields=['iniciado_em'], name='execcol_inicio_idx'),
            models.Index(fields=['tipo', 'iniciado_em'], name='execcol_tipo_inicio_idx'),
            models.Index(fields=['sku', 'iniciado_em'], name='execcol_sku_inicio_idx'),
        ]

    def __str__(self):
        alvo = self.mlb or self.sku or 'conta'
        return f'{self.get_tipo_display()} · {alvo} · {self.chamadas} chamadas ({timezone.localtime(self.iniciado_em):%d/%m/%Y %H:%M})'
