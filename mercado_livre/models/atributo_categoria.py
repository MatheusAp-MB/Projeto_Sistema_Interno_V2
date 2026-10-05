# mercado_livre/models/atributo_categoria.py
from django.db import models


class AtributoCategoriaMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → "O que cada categoria do ML pede": 1 linha para cada
    #                  combinação de categoria + característica (ex.: a
    #                  categoria X pede o campo "Modelo"). Guarda SÓ as
    #                  características do card "Características principais"
    #                  do ML: grupo MAIN de GET /categories/{id}/
    #                  technical_specs/input, menos as que a API marca com
    #                  a etiqueta allow_variations (essas pertencem à
    #                  variação, não ao anúncio). Alimentada SOMENTE pelos
    #                  botões da tela de Características dos anúncios
    #                  ("Fazer varredura completa" e "Atualizar" do produto)
    #                  — nunca por chamada automática à API. Dado de
    #                  consumo: sobrescrito a cada nova leitura, nunca
    #                  escrito por interação do usuário.

    categoria = models.ForeignKey(
        'mercado_livre.CategoriaMercadoLivre',
        on_delete=models.CASCADE,
        related_name='atributos'
    )

    # * [EXPLICAÇÃO] → É o "ID na API" que aparece no card (ex.: "MODEL").
    atributo_id = models.CharField(max_length=60)

    nome = models.CharField(max_length=255)

    # * [EXPLICAÇÃO] → Tipo do valor exatamente como a API manda (string,
    #                  list, number, number_unit, boolean...). Sem choices
    #                  de propósito: dado cru da API não é normalizado nem
    #                  restringido por nós.
    tipo_valor = models.CharField(max_length=30, blank=True)

    # * [EXPLICAÇÃO] → Etiquetas ativas da API, juntando as duas fontes (a
    #                  do card, technical_specs, e a da definição do
    #                  atributo, /attributes), numa lista só. É daqui que
    #                  vem a informação de "obrigatório", "somente leitura"
    #                  etc. "Obrigatório" NÃO é gravado como campo próprio —
    #                  é derivado destas etiquetas na hora de exibir, para
    #                  não existir duas verdades sobre o mesmo dado.
    tags = models.JSONField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Limite de caracteres do campo (alimenta a linha
    #                  "Regra" do card). O "limite mais restrito entre as
    #                  categorias do produto" é calculado na hora, nunca
    #                  gravado.
    tamanho_maximo = models.PositiveIntegerField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Unidades aceitas, crua como a API manda: lista de
    #                  {"id", "name"}. A API NÃO informa unidade padrão.
    unidades_permitidas = models.JSONField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Opções da lista (crua: lista de {"id", "name"}). Quando
    #                  o campo é texto com sugestões, aqui ficam as sugestões.
    opcoes = models.JSONField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Vem do componente de tela do ML (ui_config.
    #                  allow_custom_value): False = lista fechada (só vale o
    #                  que está em "opcoes"), True = o ML aceita valor
    #                  próprio (as opções viram só sugestões), None = a API
    #                  não informou.
    permite_valor_proprio = models.BooleanField(blank=True, null=True)

    # * [EXPLICAÇÃO] → Tipo de componente de tela do ML (TEXT_INPUT, COMBO,
    #                  NUMBER_INPUT, NUMBER_UNIT_INPUT, COLOR_INPUT,
    #                  BOOLEAN_INPUT...), cru. Ajuda a decidir como desenhar
    #                  o campo no card.
    componente = models.CharField(max_length=40, blank=True)

    # * [EXPLICAÇÃO] → Posição do campo no card do ML (0, 1, 2...) — para o
    #                  nosso card mostrar na mesma ordem.
    ordem = models.PositiveSmallIntegerField(default=0)

    # * [EXPLICAÇÃO] → auto_now: atualiza sozinho a cada save(). Quem
    #                  gravar em lote (bulk_create com update_conflicts ou
    #                  bulk_update) precisa incluir este campo na lista de
    #                  campos, senão a data não muda.
    lido_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together     = ['categoria', 'atributo_id']
        verbose_name        = 'Atributo de Categoria Mercado Livre'
        verbose_name_plural = 'Atributos de Categoria Mercado Livre'
        ordering            = ['ordem', 'nome']

    def __str__(self):
        return f'{self.categoria_id} — {self.atributo_id} ({self.nome})'
