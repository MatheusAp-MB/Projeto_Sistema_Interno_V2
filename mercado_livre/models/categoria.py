# mercado_livre/models/categoria.py
from django.db import models


class EstadoDumpCategoriasMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Controla a "idade" do dump de categorias usado pra
    #                  popular CategoriaMercadoLivre. O ML expõe 2 headers
    #                  no endpoint do dump (X-Content-Created e
    #                  X-Content-MD5) que permitem checar se ele mudou sem
    #                  precisar baixar o arquivo inteiro de novo — essa
    #                  tabela guarda o último valor conhecido desses 2
    #                  headers. Só deve existir 1 linha (singleton).

    gerado_em_ml = models.DateTimeField(
        help_text="Valor do header X-Content-Created retornado pelo ML na última baixa."
    )
    md5 = models.CharField(
        max_length=64,
        help_text="Valor do header X-Content-MD5 retornado pelo ML na última baixa."
    )
    total_categorias = models.PositiveIntegerField()
    baixado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Dump de {self.gerado_em_ml} — {self.total_categorias} categorias"


class CategoriaMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Tabela de referência local com as categorias do ML,
    #                  alimentada pelo dump oficial (GET /sites/MLB/
    #                  categories/all). Existe pra nunca mais precisar
    #                  perguntar pro ML "qual o nome/hierarquia dessa
    #                  categoria" — é só cruzar (JOIN) com o category_id
    #                  que já vem em cada anúncio/variação.

    category_id = models.CharField(max_length=20, primary_key=True)  # ex: "MLB33390"
    nome = models.CharField(max_length=255)

    categoria_pai = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='filhos'
    )

    # * [EXPLICAÇÃO] → path_from_root já vem pronto da API — guardamos
    #                  achatado pra exibir o "breadcrumb" sem precisar
    #                  subir a árvore com N queries toda vez.
    categoria_raiz_id = models.CharField(max_length=20, db_index=True)
    nivel = models.PositiveSmallIntegerField(help_text="Profundidade na árvore (tamanho do path_from_root).")
    caminho_completo = models.CharField(max_length=500, help_text="Ex: 'Casa, Móveis e Decoração > Camas, Colchões e Acessórios > Conjuntos de Box e Colchão'.")
    e_folha = models.BooleanField(default=True, help_text="True quando children_categories vem vazio — só categoria folha aceita anúncio.")

    aceita_novo_anuncio = models.BooleanField(default=True)  # settings.listing_allowed
    status_categoria = models.CharField(max_length=30, blank=True)  # settings.status (ex: enabled)

    # * [EXPLICAÇÃO] → attribute_types, campo confirmado na doc oficial
    #                  (exemplo de /categories/{id}), mas sem explicação
    #                  de significado por parte do ML. Só 3 valores
    #                  confirmados no dump inteiro: 'attributes' (53,4%),
    #                  'variations' (46,4%) e 'none' (0,2%, aparentando
    #                  correlação com categorias-pai não publicáveis).
    tipo_atributos = models.CharField(max_length=20, blank=True)

    condicoes_aceitas = models.JSONField(default=list, blank=True)  # settings.item_conditions
    preco_minimo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    preco_maximo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    vertical = models.CharField(max_length=50, blank=True, null=True)

    # * [EXPLICAÇÃO] → limites de criação de anúncio por categoria —
    #                  candidatos a validação futura antes de publicar
    #                  (ex: avisar que o título passou do limite).
    limite_titulo = models.PositiveSmallIntegerField(null=True, blank=True)
    limite_subtitulo = models.PositiveSmallIntegerField(null=True, blank=True)
    limite_descricao = models.PositiveIntegerField(null=True, blank=True)
    limite_fotos = models.PositiveSmallIntegerField(null=True, blank=True)
    limite_fotos_variacao = models.PositiveSmallIntegerField(null=True, blank=True)
    limite_variacoes = models.PositiveSmallIntegerField(null=True, blank=True)

    # * [EXPLICAÇÃO] → catalog_domain — Grupo 2 da investigação: pista
    #                  ainda não confirmada de que pode explicar a
    #                  variação de comissão real entre categorias (ver
    #                  Checkpoint de Investigação da Comissão, seção 7).
    #                  Guardado desde já porque é de graça (já vem no
    #                  dump) — não significa que já decidimos usar.
    catalog_domain = models.CharField(max_length=100, blank=True, null=True)

    # * [EXPLICAÇÃO] → Comissão Média da categoria (Clássico/Premium) — SEMPRE
    #                  snapshot (recalculada do zero, nunca incremental), a
    #                  partir de comissao_real_percentual de TODAS as variações
    #                  vinculadas a esta categoria (cross-produto). Só
    #                  informativo — nunca entra no cálculo de precificação
    #                  (que usa a comissão real por MLB, direto na Variação).
    #                  *_amostra guarda quantas variações entraram na média
    #                  (None enquanto não houver nenhuma). Recalculada por
    #                  mercado_livre.funcoes_auxiliares.recalcular_comissao_media
    #                  — nunca via Django signal (decisão explícita). Campo de
    #                  timestamp PRÓPRIO (não reaproveita atualizado_em acima,
    #                  que é da sincronização do dump de categorias — coisas
    #                  diferentes). Ver Checkpoint - Investigação da Comissão
    #                  Real de Venda via API do Mercado Livre, seção 9.
    comissao_media_classico = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    comissao_media_classico_amostra = models.PositiveIntegerField(null=True, blank=True)
    comissao_media_premium = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    comissao_media_premium_amostra = models.PositiveIntegerField(null=True, blank=True)
    comissao_media_atualizado_em = models.DateTimeField(null=True, blank=True)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['categoria_raiz_id']),
            models.Index(fields=['nome']),
        ]

    def __str__(self):
        return f"{self.category_id} — {self.nome}"