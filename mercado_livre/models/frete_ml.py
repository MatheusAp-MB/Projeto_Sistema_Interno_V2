from django.db import models


# ================================================
# FRETE ML
# ================================================

# * [EXPLICAÇÃO] → Cada linha dessa tabela representa UMA célula da matriz
#                  de frete do Mercado Livre. A matriz tem faixas de peso
#                  nas linhas e faixas de preço nas colunas — e, desde
#                  23/09/2026, também o REGIME (Sem/Com Frete Grátis
#                  Rápido) como uma 3ª dimensão: são 2 tabelas reais de
#                  frete diferentes, publicadas juntas na mesma planilha
#                  (1 tabela única, 2 linhas por faixa de peso — 1 por
#                  regime, ver Tabela_Frete_Mercado_Livre.xlsx).
#                  Exemplo: peso_min=0.000, peso_max=0.300,
#                  preco_min=0.00, preco_max=79.99,
#                  regime=sem_frete_gratis_rapido, valor=12.50
#                  → produto até 300g vendido até R$79,99, sem frete
#                  grátis rápido → frete R$12,50
#
# * [DECISÃO EM ABERTO] → Quem consulta frete pra calcular margem
#                  (calculo_margem.buscar_frete, montar_linhas_candidatas,
#                  FormulaPrecificacao.filtrar_faixas_frete) recebeu um
#                  parâmetro `regime`, com padrão SEM_FRETE_GRATIS_RAPIDO
#                  — nenhum lugar do sistema ainda sabe, por anúncio, se
#                  ele tem frete grátis rápido ativo (isso ainda está
#                  sendo investigado via API, ver
#                  scripts_exploracao_ML/testar_matriz_frete_gratis_via_api.py).
#                  Quando essa informação existir por anúncio, é só
#                  passar o regime certo pra esses 3 lugares.

class FreteML(models.Model):

    class Regime(models.TextChoices):
        SEM_FRETE_GRATIS_RAPIDO = 'sem_frete_gratis_rapido', 'Sem Frete Grátis Rápido'
        COM_FRETE_GRATIS_RAPIDO = 'com_frete_gratis_rapido', 'Com Frete Grátis Rápido'

    # Faixa de peso (em kg)
    # * [EXPLICAÇÃO] → peso_max é null na última faixa — significa "acima de X kg"
    peso_min = models.DecimalField(max_digits=8, decimal_places=3)
    peso_max = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)

    # Faixa de preço (em R$)
    # * [EXPLICAÇÃO] → preco_max é null na última faixa — significa "acima de R$ X"
    preco_min = models.DecimalField(max_digits=10, decimal_places=2)
    preco_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # * [EXPLICAÇÃO] → Qual das 2 tabelas reais de frete essa linha
    #                  pertence — ver explicação da classe, no topo do
    #                  arquivo.
    regime = models.CharField(
        max_length=30, choices=Regime.choices, default=Regime.SEM_FRETE_GRATIS_RAPIDO,
    )

    # Valor do frete para essa combinação de peso + preço + regime
    valor = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'Frete ML'
        verbose_name_plural = 'Fretes ML'
        # * [EXPLICAÇÃO] → Ordena por peso, depois preço, depois regime —
        #                  "-regime" (decrescente) é intencional: como
        #                  'sem_frete_gratis_rapido' vem depois de
        #                  'com_frete_gratis_rapido' em ordem alfabética,
        #                  decrescente é o único jeito de fazer "Sem"
        #                  aparecer antes de "Com" (mesma ordem da
        #                  planilha).
        ordering = ['peso_min', 'preco_min', '-regime']
        # * [EXPLICAÇÃO] → Nunca mais permite a MESMA célula (peso × preço
        #                  × regime) duplicada — é a proteção que faltava
        #                  e que permitiu o bug de bulk_update sem pk
        #                  (ver vault: "Importação de Frete ML Quebra...").
        constraints = [
            models.UniqueConstraint(
                fields=['peso_min', 'preco_min', 'regime'], name='frete_ml_peso_preco_regime_unico',
            ),
        ]

    def __str__(self):
        return (
            f'Peso {self.peso_min}-{self.peso_max}kg | Preço {self.preco_min}-{self.preco_max} '
            f'| {self.get_regime_display()} → R${self.valor}'
        )