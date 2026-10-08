# mercado_livre/models/full_ml.py
from django.db import models


class ConsultaFullMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Cada clique em "Consultar no Mercado Livre" da tela do
    #                  Full grava 1 linha aqui: o que o ML respondeu para 1
    #                  código (Código ML ou "#MLB") naquele momento. A tela só
    #                  LÊ daqui — nunca chama a API sozinha. Cada consulta fica
    #                  guardada (não sobrescreve a anterior), para dar para
    #                  comparar a mesma ficha em momentos diferentes; a tela
    #                  mostra a mais recente.
    #                  Os 4 campos JSON guardam o dado CRU, do jeito que o ML
    #                  mandou (nada é renomeado nem corrigido):
    #                    - estoque:  {inventory_id: pacote da API de estoque};
    #                    - reposicao: {user_product_id: pacote da API de reposição};
    #                    - flex: {user_product_id: pacote da API de estoque por local}
    #                      (o que está no Full e o que está no depósito do vendedor;
    #                      campo criado em 08/10/2026 — consultas antigas ficam com {});
    #                    - registros_arquivo: os registros do detalhes_mlbs.json
    #                      que pertencem ao código (a "foto" local do dia em que
    #                      o buscar_detalhes rodou), para a ficha mostrar de onde
    #                      cada valor veio.
    #                  "pacote" = {endpoint, params, http, x_content_missing,
    #                  erro, dados} (ver PacoteFull em api_mercado_livre/full_ml.py).

    codigo = models.CharField(max_length=40, db_index=True)
    consultado_em = models.DateTimeField(auto_now_add=True)

    # * [EXPLICAÇÃO] → Quem apertou o botão (nome de usuário do Django).
    usuario = models.CharField(max_length=150, blank=True)

    # * [EXPLICAÇÃO] → Quando o detalhes_mlbs.json foi gerado (texto, do jeito
    #                  que está no arquivo). Vazio se o arquivo não registra.
    arquivo_gerado_em = models.CharField(max_length=40, blank=True)

    registros_arquivo = models.JSONField(default=list, blank=True)
    estoque = models.JSONField(default=dict, blank=True)
    reposicao = models.JSONField(default=dict, blank=True)
    flex = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name        = 'Consulta Full Mercado Livre'
        verbose_name_plural = 'Consultas Full Mercado Livre'
        ordering            = ['-consultado_em']

    def __str__(self):
        return f'{self.codigo} — {self.consultado_em:%d/%m/%Y %H:%M}'


class CampoFullMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → O "registro de campos" do Full: para cada informação que
    #                  aparece na ficha (identificada por fonte + caminho do
    #                  campo, ex.: REPOS + "stock.total_stock"), o nome que a
    #                  equipe dá a ela, se já foi conferida com a tela do ML, e
    #                  uma observação. É conhecimento, não dado de anúncio:
    #                  vale para qualquer código. Só existe linha aqui depois
    #                  que alguém preenche algo na tela; campo sem linha aparece
    #                  como "A validar". Quais campos existem na ficha mora no
    #                  catálogo do código (mercado_livre/funcoes_auxiliares/
    #                  full_ml.py), não aqui.

    class Situacao(models.TextChoices):
        A_VALIDAR = 'a_validar', 'A validar'
        HIPOTESE  = 'hipotese',  'Hipótese'
        VALIDO    = 'valido',    'Válido'
        INVALIDO  = 'invalido',  'Inválido'

    # * [EXPLICAÇÃO] → REPOS, ESTOQUE, ARQUIVO ou TELA (campo que só existe na
    #                  tela do ML — o "caminho" é então um nome curto nosso).
    fonte   = models.CharField(max_length=10)
    caminho = models.CharField(max_length=120)

    nome_interno = models.CharField(max_length=120, blank=True)
    situacao     = models.CharField(max_length=10, choices=Situacao.choices, default=Situacao.A_VALIDAR)
    observacao   = models.TextField(blank=True)

    atualizado_em  = models.DateTimeField(auto_now=True)
    atualizado_por = models.CharField(max_length=150, blank=True)

    class Meta:
        unique_together     = ['fonte', 'caminho']
        verbose_name        = 'Campo Full Mercado Livre'
        verbose_name_plural = 'Campos Full Mercado Livre'
        ordering            = ['fonte', 'caminho']

    def __str__(self):
        return f'{self.fonte} · {self.caminho} — {self.get_situacao_display()}'
