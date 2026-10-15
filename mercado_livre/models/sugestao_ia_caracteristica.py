# mercado_livre/models/sugestao_ia_caracteristica.py
from django.db import models
from django.utils import timezone


class ConsultaIACaracteristicaMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → A ÚLTIMA vez que a IA foi consultada para 1 produto (1 linha por produto —
    #                  pedir de novo SUBSTITUI esta linha). Guarda o que a tela mostra no painel da
    #                  IA (custo, tokens, modo, duração) e na gaveta "Entrada e saída" (o texto exato
    #                  enviado e devolvido, e as sugestões descartadas na conferência).
    #                  As sugestões em si ficam em SugestaoIACaracteristicaMercadoLivre.
    #
    # * [DECISÃO, 15/10/2026] → Só a última consulta de cada produto é guardada, não o histórico:
    #                  a pessoa quer "pensar com calma" com a última sugestão sempre disponível, e
    #                  pedir outra substitui. O gasto mensal (que somará todas as consultas) é uma
    #                  etapa futura e terá a sua própria tabela.

    produto = models.OneToOneField(
        'produtos.Produto',
        on_delete=models.CASCADE,
        related_name='consulta_ia_caracteristicas_ml',
    )
    consultada_em = models.DateTimeField(default=timezone.now)

    # * [EXPLICAÇÃO] → Quem apertou o botão (nome de usuário do Django).
    usuario = models.CharField(max_length=150, blank=True)

    modelo = models.CharField(max_length=60)
    modelo_rotulo = models.CharField(max_length=40, blank=True)
    esforco = models.CharField(max_length=20, blank=True)

    # * [EXPLICAÇÃO] → "estruturada" (JSON garantido pela API) ou "prompt" (plano B).
    modo = models.CharField(max_length=12, blank=True)

    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_saida = models.PositiveIntegerField(default=0)
    custo_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    duracao_segundos = models.DecimalField(max_digits=7, decimal_places=1, default=0)

    n_sugestoes = models.PositiveIntegerField(default=0)
    n_campos_enviados = models.PositiveIntegerField(default=0)

    # * [EXPLICAÇÃO] → IDs dos campos que a IA viu (a tela só escreve "Sem sugestão" nestes). Quando um
    #                  campo é enviado ao ML, ele sai desta lista junto com a sugestão dele.
    campos_enviados = models.JSONField(default=list, blank=True)

    # * [EXPLICAÇÃO] → Lista de {"campo", "nome", "motivo"} do que a IA devolveu e a conferência recusou.
    ignoradas = models.JSONField(default=list, blank=True)

    entrada = models.TextField(blank=True)
    saida = models.TextField(blank=True)

    class Meta:
        verbose_name        = 'Consulta de IA — Características Mercado Livre'
        verbose_name_plural = 'Consultas de IA — Características Mercado Livre'

    def __str__(self):
        return f'{self.produto.sku} — IA em {self.consultada_em:%d/%m/%Y %H:%M}'


class SugestaoIACaracteristicaMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → A última sugestão da IA para 1 campo de 1 produto: 1 linha por produto + campo
    #                  (nunca se misturam entre produtos nem entre campos). Pedir sugestões de novo
    #                  substitui o conjunto inteiro do produto. É só SUGESTÃO: não vai ao Mercado Livre
    #                  nem vira "Valor a enviar" sem a pessoa aceitar e usar o "Revisar e enviar".

    produto = models.ForeignKey(
        'produtos.Produto',
        on_delete=models.CASCADE,
        related_name='sugestoes_ia_caracteristicas_ml',
    )

    # * [EXPLICAÇÃO] → Mesmo "ID na API" de AtributoCategoriaMercadoLivre (ex.: "MODEL"), como em
    #                  CaracteristicaProdutoMercadoLivre: o campo é do produto, não de uma categoria.
    atributo_id = models.CharField(max_length=60)

    # * [EXPLICAÇÃO] → O valor no formato que o card sabe preencher: {"valor_id": "..."} (lista),
    #                  {"numero": "...", "unidade": "..."}, {"numero": "..."} ou {"texto": "..."}.
    valor = models.JSONField()

    # * [EXPLICAÇÃO] → O valor como aparece no card ("Bivolt", "8,5 h") e o trecho do cadastro que a IA
    #                  citou como prova.
    texto = models.CharField(max_length=300)
    evidencia = models.CharField(max_length=255, blank=True)

    atualizada_em = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together     = ['produto', 'atributo_id']
        verbose_name        = 'Sugestão de IA — Característica Mercado Livre'
        verbose_name_plural = 'Sugestões de IA — Características Mercado Livre'
        ordering            = ['atributo_id']

    def __str__(self):
        return f'{self.produto.sku} — {self.atributo_id}: {self.texto}'
