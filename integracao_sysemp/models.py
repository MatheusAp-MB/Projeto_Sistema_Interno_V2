# integracao_sysemp/models.py

# Função Objetivo: Estado de sincronização do manifesto de nota de entrada
# (XML) com o Sysemp — guarda até onde os dados de imposto de entrada já
# foram cobertos, pra sincronização incremental não precisar reler período
# gigantesco a cada vez. Ver decisão completa no vault: "Sincronizacao
# Incremental com Watermark para Manifesto de Notas de Entrada". Só serve
# essa função (impostos de entrada) — outras integrações futuras com o
# Sysemp (cadastro de produtos, dados de saída) ganham tabela própria
# quando existirem de verdade, não antes (Regra dos Três).

from datetime import date, timedelta

from django.db import models
from django.utils import timezone


class SincronizacaoXmlManifestoNotaEntrada(models.Model):
    # * [EXPLICAÇÃO] → Só deve existir 1 linha (acessada via obter()) —
    #                  não é o Singleton do GoF (sem restrição de
    #                  linguagem/metaclasse), é o mesmo esquema de linha
    #                  única já usado em ConfiguracaoOperacional.

    MARGEM_DE_SEGURANCA_DIAS = 7

    # * [EXPLICAÇÃO] → Data mínima real de dados úteis do sistema,
    #                  validada manualmente pelo usuário — nada antes
    #                  disso importa. Usada só na 1ª sincronização
    #                  (sem cobertura registrada ainda).
    DATA_INICIAL_PRIMEIRA_CARGA = date(2020, 5, 1)

    class Status(models.TextChoices):
        SINCRONIZADO = 'sincronizado', 'Sincronizado'
        FALHA = 'falha', 'Falha ao sincronizar'

    # * [EXPLICAÇÃO] → data_inicial_cobertura só é escrita 1 vez, na
    #                  primeira sincronização bem-sucedida (enquanto
    #                  estiver vazia) — nunca mais é tocada depois disso.
    #                  data_final_cobertura avança a cada sincronização
    #                  bem-sucedida. Único ponto de escrita dos dois:
    #                  registrar_sincronizacao_bem_sucedida().
    data_inicial_cobertura = models.DateField(null=True, blank=True)
    data_final_cobertura = models.DateField(null=True, blank=True)

    # * [EXPLICAÇÃO] → Guarda hora, não só data — sustenta o cooldown
    #                  entre tentativas (o servidor local reinicia várias
    #                  vezes ao dia durante desenvolvimento; sem precisão
    #                  de hora não dá pra saber se a última tentativa foi
    #                  há 2 minutos ou há 2 dias).
    data_ultima_chamada = models.DateTimeField(null=True, blank=True)

    # * [EXPLICAÇÃO] → "Desatualizada" não é um valor deste campo — é
    #                  calculada (ver esta_desatualizada), porque não é
    #                  resultado de uma ação, é só o tempo passando. Só
    #                  os 2 resultados reais de uma tentativa entram aqui.
    status = models.CharField(max_length=20, choices=Status.choices, blank=True)
    motivo_da_falha = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Sincronização do Manifesto de Nota de Entrada (XML)'
        verbose_name_plural = 'Sincronização do Manifesto de Nota de Entrada (XML)'

    def __str__(self):
        return 'Sincronização do Manifesto de Nota de Entrada (XML)'

    @classmethod
    def obter(cls) -> 'SincronizacaoXmlManifestoNotaEntrada':
        """Busca a única linha existente, criando vazia se ainda não
        existir — antes da primeira sincronização, todos os campos
        ficam em branco/nulos."""
        registro, _ = cls.objects.get_or_create(pk=1)
        return registro

    def esta_desatualizada(self, data_referencia: date | None = None) -> bool:
        """Nunca sincronizado, ou cobertura + margem de segurança já
        ficou no passado em relação a data_referencia (hoje, se não
        informado)."""
        if data_referencia is None:
            data_referencia = date.today()
        if self.data_final_cobertura is None:
            return True
        limite = self.data_final_cobertura + timedelta(days=self.MARGEM_DE_SEGURANCA_DIAS)
        return limite < data_referencia

    def calcular_janela_da_proxima_busca(
        self, data_referencia: date | None = None,
    ) -> tuple[date, date]:
        """Data inicial/final a pedir na próxima chamada à API. Sem
        cobertura ainda (1ª sincronização), usa a data mínima real de
        dados úteis do sistema. Com cobertura, reaplica a mesma margem
        de segurança de esta_desatualizada()."""
        if data_referencia is None:
            data_referencia = date.today()
        if self.data_final_cobertura is None:
            return self.DATA_INICIAL_PRIMEIRA_CARGA, data_referencia
        data_inicial = self.data_final_cobertura - timedelta(days=self.MARGEM_DE_SEGURANCA_DIAS)
        return data_inicial, data_referencia

    def registrar_sincronizacao_bem_sucedida(
        self, data_inicial_chamada: date, data_final_chamada: date, agora=None,
    ) -> None:
        """Único ponto que avança a cobertura, depois de uma chamada
        bem-sucedida à API. Recebe as datas de parâmetro da própria
        chamada — não recalcula nem supõe nada por conta própria."""
        if agora is None:
            agora = timezone.now()
        if self.data_inicial_cobertura is None:
            self.data_inicial_cobertura = data_inicial_chamada
        self.data_final_cobertura = data_final_chamada
        self.data_ultima_chamada = agora
        self.status = self.Status.SINCRONIZADO
        self.motivo_da_falha = ''
        self.save()

    def registrar_falha(self, motivo: str, agora=None) -> None:
        """Registra que uma tentativa aconteceu e falhou — nunca toca
        nas datas de cobertura, só marca quando foi e por quê (sustenta
        o cooldown entre tentativas)."""
        if agora is None:
            agora = timezone.now()
        self.data_ultima_chamada = agora
        self.status = self.Status.FALHA
        self.motivo_da_falha = motivo
        self.save()