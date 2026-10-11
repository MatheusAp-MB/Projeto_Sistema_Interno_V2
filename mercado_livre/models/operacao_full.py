# mercado_livre/models/operacao_full.py
# ============================================================================================================================
# AVISO — ENDPOINT DE OPERAÇÕES DO FULL ABANDONADO PARA O HISTÓRICO DE VENDAS (decisão do Matheus, 10/10/2026, 20:04)
# ============================================================================================================================
# Este código usa GET /stock/fulfillment/operations/search. Ele FUNCIONA (90 dias de 1 SKU = 3 Códigos ML foram coletados),
# mas foi ABANDONADO: o endpoint é instável e a necessidade é rodar para MAIS DE MIL SKUs. NÃO APAGUE — guarda o que foi
# aprendido. Notas completas no vault: 05_Integracao_Mercado_Livre/Historico_de_Vendas/ (descoberta, decisão, dúvida, checkpoint).
#
# PROBLEMAS OBSERVADOS (10/10/2026, dado real, conta Magazine, 1 SKU = 3 Códigos ML):
#  1) 429 FREQUENTE: 8 de 25 chamadas na sondagem (18:33-18:38) e 34 de 51 tentativas nas 3 rodadas reais do coletor (19:43-19:46).
#     Corpo: {"message": "Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota", "error": "over_quota"}
#     NÃO é o texto "requests por minuto" da doc: cita uma entidade interna; o ESCOPO da cota é DESCONHECIDO (app, vendedor, global?).
#  2) SEM PISTA DE QUANDO TENTAR DE NOVO: nenhuma resposta traz Retry-After nem cabeçalho de limite.
#  3) PESO E ESPAÇAMENTO NÃO MUDAM A TAXA: chamada leve (1 Código, limit=1) 3/8 x pesada (3 Códigos, limit=1000) 2/8 com 429;
#     esperar 15 s entre as chamadas ainda deu 5 de 16 primeiras páginas com 429. Os 429 vêm em rajadas e a taxa variou no tempo
#     (32% às 18:33 x 67% às 19:43) — a causa é desconhecida.
#  4) SCROLL FRÁGIL: repetir o MESMO scroll depois de um 429 costuma virar 404 {"message": "Operation not found"} (2 de 2 nas
#     rodadas reais; 1 de 3 passou na sondagem). O coletor recomeça a janela e descarta as linhas repetidas (2000 na rodada de 90 dias).
#  5) Chamadas SEM scroll: 13 de 15 terminaram em 200 nas rodadas reais; 1 esgotou as 5 tentativas com 429 e 1 foi interrompida.
#  6) 120 e 150 dias NÃO foram testados (Ctrl+C durante a espera de 60 s, antes da parte antiga): só 90 dias foram validados.
#  7) A profundidade do histórico NÃO é a causa: o 429 apareceu também na janela dos 7 dias mais recentes (11 de 14 tentativas).
#
# NUNCA TESTADO: máximo de Códigos ML por chamada; omitir "type" (1 chamada em vez de 4 por janela); dividir a janela por data até
# caber em 1000 operações (sem scroll); se o horário muda a taxa. Não há contato com o Mercado Livre por ora.
#
# CAMINHO NOVO: GET /orders/search (ver o checkpoint 'Checkpoint - Historico de Vendas e Calendario de Vendas' no vault).
# Textos mais abaixo que dizem que o limite é "por minuto" ou que o 429 "passa depois de esperar" foram escritos ANTES desses
# testes: valem os fatos deste aviso.
#
# ESCOPO: estas tabelas (OperacaoFullMercadoLivre e CoberturaOperacaoFullMercadoLivre, migração 0035) FICAM por enquanto: o destino
# delas é decidido depois que o /orders/search for medido. Não apagar nem alterar agora.
# ============================================================================================================================

from datetime import date, timedelta

from django.db import models
from django.utils import timezone


class OperacaoFullMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Cada linha é 1 operação de estoque do Full, do jeito que
    #                  o ML registra em GET /stock/fulfillment/operations/search:
    #                  1 venda confirmada, 1 cancelamento, 1 venda não entregue
    #                  ou 1 devolução do comprador, de 1 Código ML.
    #                  É a ÚNICA origem das "vendas do Full por dia" (por Código
    #                  ML e, somando os Códigos do produto, por produto). Telas
    #                  e cálculos leem SÓ daqui: nunca de JSON, nunca de uma
    #                  chamada ao vivo feita pela tela. Quem grava é o coletor
    #                  (botão manual), que limpa e tipa o que a API devolveu.
    #                  Só campos já limpos: nada do JSON cru da API é guardado.
    #
    #                  O que a operação NÃO traz: o MLB. Dividir um Código ML
    #                  entre os MLBs dele precisa dos pedidos, não está aqui.
    #
    #                  O LÍQUIDO (venda menos cancelamento) NÃO é gravado: é
    #                  calculado na leitura, casando cada SALE_CANCELATION com
    #                  a venda do mesmo envio + Código ML e descontando no DIA
    #                  DA VENDA (nunca no dia em que foi cancelada). Regra de
    #                  negócio decidida em 10/10/2026: só SALE_CANCELATION tira
    #                  a venda do dia original; SALE_DELIVERY_CANCELATION e
    #                  SALE_RETURN são observação à parte, não entram no
    #                  líquido. Conferido com dado real em 10/10/2026: 61 dos
    #                  62 cancelamentos casaram com a venda por envio + Código.

    class Tipo(models.TextChoices):
        # * [EXPLICAÇÃO] → O valor guardado é o nome do tipo exatamente como o
        #                  ML manda (maiúsculo). Só estes 4 são gravados aqui.
        VENDA        = 'SALE_CONFIRMATION',         'Venda confirmada'
        CANCELAMENTO = 'SALE_CANCELATION',          'Venda cancelada'
        NAO_ENTREGUE = 'SALE_DELIVERY_CANCELATION', 'Venda não entregue'
        DEVOLUCAO    = 'SALE_RETURN',               'Devolução pelo comprador'

    # * [EXPLICAÇÃO] → O id que o próprio ML deu à operação (número de 19
    #                  dígitos nos dados reais). É ele que impede gravar a mesma
    #                  operação duas vezes: reler um período já coberto não
    #                  duplica nada.
    id_operacao = models.BigIntegerField(unique=True)

    # * [EXPLICAÇÃO] → O Código ML (inventory_id da API, ex.: QAVX18725). Mesmo
    #                  dado e mesmo formato de VariacaoAnuncioMercadoLivre.
    #                  inventory_id; quando existir uma tabela própria do Código
    #                  ML, este campo vira a ligação com ela.
    inventory_id = models.CharField(max_length=20)

    tipo = models.CharField(max_length=30, choices=Tipo.choices)

    # * [EXPLICAÇÃO] → Quando o ML criou a operação (date_created da API, que
    #                  vem em UTC). O Django guarda com fuso; o DIA da venda
    #                  que a tela mostra é o dia no horário de Brasília,
    #                  convertido na leitura.
    data_operacao = models.DateTimeField()

    # * [EXPLICAÇÃO] → Quantas unidades a operação moveu, sempre positivo. Na
    #                  API a venda vem com sinal negativo (a unidade sai do
    #                  estoque); o coletor guarda o valor sem o sinal. Nunca 0:
    #                  operação sem quantidade não é gravada como "0 unidade"
    #                  (ausente não é zero), o coletor avisa em vez de inventar.
    unidades = models.PositiveIntegerField()

    # * [EXPLICAÇÃO] → Número do envio (shipment_id). É o que casa o
    #                  cancelamento com a venda dele. Vazio se a API não
    #                  informou (aí o cancelamento não tem como ser casado).
    shipment_id = models.CharField(max_length=30, blank=True)

    # * [EXPLICAÇÃO] → Quando NÓS gravamos a linha (não é data do ML). Mostra,
    #                  por exemplo, quanto tempo uma operação demora para
    #                  aparecer na API depois de criada.
    gravado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'Operação Full Mercado Livre'
        verbose_name_plural = 'Operações Full Mercado Livre'
        indexes = [
            # * [EXPLICAÇÃO] → Para somar por Código (ou lista de Códigos do
            #                  produto), por tipo, em um intervalo de datas.
            models.Index(fields=['inventory_id', 'tipo', 'data_operacao'], name='opfull_cod_tipo_data_idx'),
            # * [EXPLICAÇÃO] → Para casar cancelamento com venda (envio + Código).
            models.Index(fields=['shipment_id', 'inventory_id'], name='opfull_envio_cod_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unidades__gte=1),
                name='opfull_unidades_maior_que_zero',
            ),
        ]

    def __str__(self):
        return f'{self.inventory_id} · {self.get_tipo_display()} · {self.data_operacao:%d/%m/%Y %H:%M}'


class CoberturaOperacaoFullMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Até onde as operações de CADA Código ML já foram buscadas
    #                  na API: 1 linha por Código ML. Mesmo princípio da cobertura
    #                  do XML de notas de entrada (SincronizacaoXmlManifesto
    #                  NotaEntrada): guardar a janela já coberta para a próxima
    #                  busca ser incremental, em vez de reler tudo. A API só
    #                  guarda 12 meses e aceita no máximo 60 dias por chamada
    #                  (doc oficial de operações do Full).
    #                  Só é escrita DEPOIS de uma busca bem-sucedida (mesmo que
    #                  tenha vindo 0 operação). Falha só marca quando foi e por
    #                  quê, nunca mexe nas datas.
    #                  O estado e as regras moram juntos aqui (qual janela buscar
    #                  na próxima vez, margem de segurança, o que é lacuna): quem
    #                  coleta só chama os métodos, nunca mexe nas datas por conta
    #                  própria.

    class Status(models.TextChoices):
        SINCRONIZADO = 'sincronizado', 'Sincronizado'
        FALHA        = 'falha',        'Falha ao sincronizar'

    # * [EXPLICAÇÃO] → RETENCAO_ML_DIAS = o mais longe que dá para pedir: 360 dias =
    #                  os 12 meses que o ML guarda (doc "Envios Fulfillment": "só
    #                  disponibilizamos a informação correspondente aos últimos 12
    #                  meses") menos 5 dias de folga, para não pedir exatamente a
    #                  borda da retenção. É também o teto do --dias do comando.
    RETENCAO_ML_DIAS = 360

    # * [EXPLICAÇÃO] → DIAS_PRIMEIRA_CARGA = a profundidade padrão da 1ª busca de um
    #                  Código (a tela mostra 90 dias). Em 10/10/2026 Matheus decidiu
    #                  que não precisa de 1 ano e que vai testar 90, 120, 150... com
    #                  o --dias do comando até achar até onde a API aguenta. O que o
    #                  ML apagar depois dos 12 meses não se recupera.
    DIAS_PRIMEIRA_CARGA = 90

    # * [EXPLICAÇÃO] → Cada busca recomeça alguns dias ANTES de onde a anterior parou,
    #                  para pegar operação que ainda não tinha aparecido na API.
    #                  Reler é grátis (o id da operação é único). PROVISÓRIO (7 dias =
    #                  o mesmo valor da cobertura do XML): ainda não medimos quanto
    #                  tempo uma operação demora para aparecer — OperacaoFull
    #                  MercadoLivre.gravado_em x data_operacao vai mostrar isso.
    MARGEM_DE_SEGURANCA_DIAS = 7

    inventory_id = models.CharField(max_length=20, unique=True)

    # * [EXPLICAÇÃO] → As datas são as mesmas que a API recebe nos parâmetros
    #                  date_from / date_to: dias no calendário UTC (conferido
    #                  com dado real: a primeira operação de date_from=11/07
    #                  veio às 00:02 UTC). data_inicial_cobertura é o 1º dia
    #                  coberto (inclusive). data_final_cobertura_exclusiva é o
    #                  date_to da última busca bem-sucedida, e a API trata o
    #                  date_to como EXCLUSIVO: é o primeiro dia que AINDA NÃO
    #                  foi coberto. A nova busca parte dele (ou antes, com margem).
    data_inicial_cobertura         = models.DateField(null=True, blank=True)
    data_final_cobertura_exclusiva = models.DateField(null=True, blank=True)

    # * [EXPLICAÇÃO] → Guarda hora, não só data: a última tentativa, com sucesso
    #                  ou falha.
    data_ultima_chamada = models.DateTimeField(null=True, blank=True)

    # * [EXPLICAÇÃO] → "Desatualizada" não é valor deste campo: é só o tempo
    #                  passando (calculada), não resultado de uma tentativa.
    #                  Só os 2 resultados reais de uma tentativa ficam aqui.
    status          = models.CharField(max_length=20, choices=Status.choices, blank=True)
    motivo_da_falha = models.TextField(blank=True)

    class Meta:
        verbose_name        = 'Cobertura das Operações do Full Mercado Livre'
        verbose_name_plural = 'Coberturas das Operações do Full Mercado Livre'

    def __str__(self):
        return f'{self.inventory_id} — cobertura até {self.data_final_cobertura_exclusiva or "nunca buscado"}'

    @classmethod
    def obter(cls, inventory_id: str) -> 'CoberturaOperacaoFullMercadoLivre':
        """A linha deste Código ML, criada vazia (nunca buscado) se ainda não existir."""
        registro, _ = cls.objects.get_or_create(inventory_id=inventory_id)
        return registro

    @classmethod
    def resolver_dias_de_historico(cls, dias_de_historico: int | None) -> int:
        """Profundidade pedida, já validada: None vira DIAS_PRIMEIRA_CARGA; fora de 1 a RETENCAO_ML_DIAS levanta ValueError."""
        dias = cls.DIAS_PRIMEIRA_CARGA if dias_de_historico is None else dias_de_historico
        if isinstance(dias, bool) or not isinstance(dias, int) or not 1 <= dias <= cls.RETENCAO_ML_DIAS:
            raise ValueError(f'Histórico inválido ({dias!r}): use um número inteiro de 1 a {cls.RETENCAO_ML_DIAS} dias.')
        return dias

    def calcular_buscas(
        self, hoje_utc: date, dias_de_historico: int | None = None,
    ) -> tuple[tuple[date, date] | None, tuple[date, date] | None]:
        """(parte_nova, parte_antiga) a pedir na API; cada uma é (data_de, data_ate) em dias UTC com data_ate EXCLUSIVO, ou None.
        parte_nova: do ponto onde a cobertura parou até amanhã (assim a busca inclui hoje, que ainda está parcial). Nunca buscado:
        começa em hoje menos dias_de_historico. Já buscado: recomeça MARGEM_DE_SEGURANCA_DIAS antes de onde parou, mas nunca antes
        do que o ML ainda guarda (RETENCAO_ML_DIAS).
        parte_antiga: só existe quando a cobertura já existe e começa DEPOIS de hoje menos dias_de_historico: vai dali até o início
        da cobertura, encostada nela (sem buraco). É assim que um --dias maior estende o histórico para trás."""
        dias = self.resolver_dias_de_historico(dias_de_historico)
        data_ate = hoje_utc + timedelta(days=1)
        profundidade = hoje_utc - timedelta(days=dias)
        if self.data_inicial_cobertura is None or self.data_final_cobertura_exclusiva is None:
            return (profundidade, data_ate), None
        inicio_da_retencao = hoje_utc - timedelta(days=self.RETENCAO_ML_DIAS)
        data_de = max(self.data_final_cobertura_exclusiva - timedelta(days=self.MARGEM_DE_SEGURANCA_DIAS), inicio_da_retencao)
        parte_antiga = (profundidade, self.data_inicial_cobertura) if profundidade < self.data_inicial_cobertura else None
        return (data_de, data_ate), parte_antiga

    def registrar_busca_bem_sucedida(self, data_de: date, data_ate: date, agora=None) -> None:
        """Único ponto que avança a cobertura, depois de uma busca COMPLETA de um intervalo (os 4 tipos, todas as páginas). O coletor chama 1 vez por
        janela concluída, e não só no fim. Recebe as
        datas da própria busca. A cobertura é sempre UM intervalo contínuo: se a busca começou depois de onde a cobertura
        terminava (lacuna: ficou tempo demais sem buscar e o ML já apagou o meio), a cobertura recomeça nesta busca. Uma busca
        mais ANTIGA que a cobertura (estender o histórico para trás) só é aceita se encostar no início dela; senão levanta
        ValueError, porque aceitar deixaria um buraco no meio do intervalo."""
        if agora is None:
            agora = timezone.now()
        sem_continuidade = (
            self.data_inicial_cobertura is None
            or self.data_final_cobertura_exclusiva is None
            or data_de > self.data_final_cobertura_exclusiva
        )
        if not sem_continuidade and data_ate < self.data_inicial_cobertura:
            raise ValueError(
                f'Busca de {data_de} até {data_ate} termina antes do início da cobertura ({self.data_inicial_cobertura}): '
                'ficaria um buraco no meio. Estenda para trás sempre encostando no início da cobertura.'
            )
        if sem_continuidade:
            self.data_inicial_cobertura = data_de
        else:
            self.data_inicial_cobertura = min(self.data_inicial_cobertura, data_de)
        self.data_final_cobertura_exclusiva = max(self.data_final_cobertura_exclusiva or data_ate, data_ate)
        self.data_ultima_chamada = agora
        self.status = self.Status.SINCRONIZADO
        self.motivo_da_falha = ''
        self.save()

    def registrar_falha(self, motivo: str, agora=None) -> None:
        """Marca que uma tentativa aconteceu e falhou. Nunca mexe nas datas de cobertura."""
        if agora is None:
            agora = timezone.now()
        self.data_ultima_chamada = agora
        self.status = self.Status.FALHA
        self.motivo_da_falha = motivo
        self.save()
