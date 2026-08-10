# impostos/models.py

# Função Objetivo: Retrato mais atual dos impostos e custos de entrada de 1
# produto, vindos do XML da nota fiscal (via Sysemp) — guarda-chuva que liga
# o produto à identificação da nota de origem e ao custo_total (usado pelo
# PIS/COFINS pra calcular a própria redução). Sem histórico: cada
# sincronização bem-sucedida SOBRESCREVE o retrato anterior (Regra dos Três
# — histórico fica pra quando/se a necessidade real aparecer). Ver decisão
# completa no vault: "Modelagem de Impostos e Custos de Entrada via XML
# (ImpostosECustosXMLEntradaProduto)".
#
# Aditivo, não substitui nada: Produto já tem campos fiscais genéricos
# (icms_entrada, ipi, pis_cofins) lidos hoje pelas 6 fórmulas de
# precificação reais — este app não toca neles. Migrar as fórmulas pra ler
# daqui é decisão futura separada.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import models, transaction

from produtos.models import Produto

if TYPE_CHECKING:
    # * [EXPLICAÇÃO] → Só pra tipagem (mypy/IDE) — dados_xml_nf não depende
    #                  de Django nem de impostos, então importar de
    #                  verdade aqui seria seguro, mas mantemos só type
    #                  hint por enquanto, sem necessidade real de mudar.
    from integracao_sysemp.servicos.dados_xml_nf import DadosXmlNF


def _converter_para_decimal(valor: float) -> Decimal:
    # * [EXPLICAÇÃO] → Nunca Decimal(valor) direto num float — captura o
    #                  valor binário exato (ex: 18.100000000000001...), não
    #                  o número que o XML de fato informou. Decimal(str(valor))
    #                  converte pela representação textual do float, que é
    #                  a decimal correta.
    return Decimal(str(valor))


# Função Objetivo: Representa 1 linha da tabela de exibição de impostos de
# entrada (modal de Produto) — 1 imposto por linha, já padronizado.
@dataclass
class LinhaImpostoEntrada:
    # * [EXPLICAÇÃO] → Nem todo imposto tem os 5 campos (ex: ICMS Retido não
    #                  tem cst/alíquota/redução; IPI não tem redução). Campo
    #                  ausente = None — o template decide como exibir, nunca
    #                  inventa ou recalcula valor por fora. base_calculo e
    #                  valor aqui já vêm POR UNIDADE (decisão do usuário,
    #                  10/08/2026) — nunca o valor bruto da nota. Ficam None
    #                  quando o produto ainda não tem quantidade_nota/
    #                  custo_unitario sincronizados (pendente resync).
    nome: str
    cst: int | None
    base_calculo: Decimal | None
    aliquota: Decimal | None
    reducao: Decimal | None
    valor: Decimal | None


# Função Objetivo: Agrupa os dados de impostos de entrada (XML) de 1 produto,
# já padronizados pra exibição — cabeçalho da nota + 1 linha por imposto.
@dataclass
class DetalhesImpostosEntradaProduto:
    nr_nf: str
    data_entrada_nota: date | None
    emissao: date | None
    fornecedor: str
    custo_unitario: Decimal | None
    linhas: list[LinhaImpostoEntrada]


class ImpostoComAliquota(models.Model):
    # * [EXPLICAÇÃO] → Classe-base abstrata só com os 3 campos que se
    #                  repetem de verdade em 5 dos 6 impostos (ICMS, ICMS
    #                  ST, IPI, PIS, COFINS). ICMS Ret não herda daqui —
    #                  não tem alíquota (ver IcmsRetEntradaProduto). cst e
    #                  redução ficam fora da base por não serem uniformes
    #                  nem entre os 5 que têm alíquota (IPI não tem
    #                  redução; ICMS ST não tem cst).

    base_calculo = models.DecimalField(max_digits=12, decimal_places=2)
    aliquota = models.DecimalField(max_digits=7, decimal_places=4)
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        abstract = True


class ImpostosECustosXMLEntradaProduto(models.Model):
    produto = models.OneToOneField(Produto, on_delete=models.CASCADE, related_name='impostos_entrada')
    nr_nf = models.CharField(max_length=20)
    data_entrada_nota = models.DateField(null=True, blank=True)
    # * [EXPLICAÇÃO] → Data de emissão da nota — campo novo (10/08/2026),
    #                  mesma situação de quantidade_nota/custo_unitario: já
    #                  vinha parseado em dados.identificacao_nf.emissao, só
    #                  nunca tinha sido persistido. Guardado como texto cru
    #                  (CharField), igual a dataclass IdentificacaoNF já faz
    #                  — nunca confirmamos o formato exato desse campo na
    #                  API pra arriscar converter em date.
    # * [EXPLICAÇÃO] → Atualizado (10/08/2026): confirmado com dado real
    #                  ("2026-08-04") que a API entrega em ISO — mesmo
    #                  formato de data_entrada_nota. Convertido pra DateField
    #                  de verdade, igual o campo irmão, em vez de texto cru.
    emissao = models.DateField(null=True, blank=True)
    fornecedor = models.CharField(max_length=255)

    # * [EXPLICAÇÃO] → Não é imposto — é apoio: PisEntradaProduto e
    #                  CofinsEntradaProduto usam esse valor pra calcular a
    #                  própria redução (a API não devolve "Redução
    #                  PIS/COFINS" direto, só a base já reduzida). Fica
    #                  aqui porque é dado de nível de NOTA, não de 1
    #                  imposto específico — nenhum dos 2 é dono exclusivo.
    custo_total = models.DecimalField(max_digits=12, decimal_places=2)

    # * [EXPLICAÇÃO] → Achado real (10/08/2026): faltava guardar isso — sem
    #                  quantidade/custo unitário não tem como converter
    #                  base/valor de "por nota" pra "por unidade", que é
    #                  como o dublê de precificação (e qualquer fórmula
    #                  real) trabalha. Os 2 já vêm parseados do XML em
    #                  dados.identificacao_produto.qtde e dados.custos.unitario
    #                  — só nunca tinham sido persistidos aqui. null=True
    #                  porque produtos já sincronizados antes desta mudança
    #                  não têm esse dado até serem resincronizados.
    quantidade_nota = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    custo_unitario = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = 'Impostos e Custos de Entrada (XML) do Produto'
        verbose_name_plural = 'Impostos e Custos de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'Impostos de Entrada — {self.produto} (NF {self.nr_nf})'

    @classmethod
    def sincronizar_a_partir_de(cls, produto: Produto, dados: 'DadosXmlNF') -> 'ImpostosECustosXMLEntradaProduto':
        """Único ponto de escrita deste retrato inteiro — sempre sobrescreve
        o anterior (sem histórico) e sempre grava as 6 tabelas de imposto
        juntas, mesmo as com valor zero (nunca deixa 1 delas ausente)."""
        data_entrada = date.fromisoformat(dados.identificacao_nf.data_entrada_nota) \
            if dados.identificacao_nf.data_entrada_nota else None
        emissao = date.fromisoformat(dados.identificacao_nf.emissao) \
            if dados.identificacao_nf.emissao else None

        with transaction.atomic():
            guarda_chuva, _ = cls.objects.update_or_create(
                produto=produto,
                defaults={
                    'nr_nf': dados.identificacao_nf.nr_nf,
                    'data_entrada_nota': data_entrada,
                    'emissao': emissao,
                    'fornecedor': dados.dados_nf.fornecedor,
                    'custo_total': _converter_para_decimal(dados.custos.total),
                    'quantidade_nota': _converter_para_decimal(dados.identificacao_produto.qtde),
                    'custo_unitario': _converter_para_decimal(dados.custos.unitario),
                },
            )
            IcmsEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'cst': dados.icms.cst,
                    'base_calculo': _converter_para_decimal(dados.icms.base_calculo),
                    'aliquota': _converter_para_decimal(dados.icms.aliquota),
                    'reducao': _converter_para_decimal(dados.icms.reducao),
                    'valor': _converter_para_decimal(dados.icms.valor),
                },
            )
            IcmsStEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'base_calculo': _converter_para_decimal(dados.icms_st.base_calculo),
                    'aliquota': _converter_para_decimal(dados.icms_st.aliquota),
                    'reducao': _converter_para_decimal(dados.icms_st.reducao),
                    'valor': _converter_para_decimal(dados.icms_st.valor),
                },
            )
            IcmsRetEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'base': _converter_para_decimal(dados.icms_ret.base),
                    'valor': _converter_para_decimal(dados.icms_ret.valor),
                },
            )
            IpiEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'cst': dados.ipi.cst,
                    'base_calculo': _converter_para_decimal(dados.ipi.base_calculo),
                    'aliquota': _converter_para_decimal(dados.ipi.aliquota),
                    'valor': _converter_para_decimal(dados.ipi.valor),
                },
            )
            PisEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'cst': dados.pis.cst,
                    'base_calculo': _converter_para_decimal(dados.pis.base_calculo),
                    'aliquota': _converter_para_decimal(dados.pis.aliquota),
                    'reducao': _converter_para_decimal(dados.pis.reducao),
                    'valor': _converter_para_decimal(dados.pis.valor),
                },
            )
            CofinsEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'cst': dados.cofins.cst,
                    'base_calculo': _converter_para_decimal(dados.cofins.base_calculo),
                    'aliquota': _converter_para_decimal(dados.cofins.aliquota),
                    'reducao': _converter_para_decimal(dados.cofins.reducao),
                    'valor': _converter_para_decimal(dados.cofins.valor),
                },
            )
        return guarda_chuva

    # Função Objetivo: Devolve os 6 impostos de entrada já padronizados pra
    # exibição (aba "Impostos" do modal de Produto) — 1 linha por imposto.
    def obter_detalhes_para_exibicao(self) -> DetalhesImpostosEntradaProduto:
        # * [EXPLICAÇÃO] → Base/Valor no XML vêm em nível de NOTA (pra
        #                  quantidade inteira comprada), não por unidade —
        #                  achado real comparando com o dublê de
        #                  precificação (10/08/2026). Converte pra unidade
        #                  aqui, 1 vez só — quem consome (template) nunca
        #                  recalcula por fora.
        quantidade = self.quantidade_nota

        def _por_unidade(valor_da_nota: Decimal | None) -> Decimal | None:
            if valor_da_nota is None or not quantidade:
                return None
            return valor_da_nota / quantidade

        return DetalhesImpostosEntradaProduto(
            nr_nf=self.nr_nf,
            data_entrada_nota=self.data_entrada_nota,
            emissao=self.emissao,
            fornecedor=self.fornecedor,
            custo_unitario=self.custo_unitario,
            linhas=[
                LinhaImpostoEntrada(
                    nome='ICMS', cst=self.icms.cst, base_calculo=_por_unidade(self.icms.base_calculo),
                    aliquota=self.icms.aliquota, reducao=self.icms.reducao, valor=_por_unidade(self.icms.valor),
                ),
                LinhaImpostoEntrada(
                    nome='ICMS ST', cst=None, base_calculo=_por_unidade(self.icms_st.base_calculo),
                    aliquota=self.icms_st.aliquota, reducao=self.icms_st.reducao, valor=_por_unidade(self.icms_st.valor),
                ),
                LinhaImpostoEntrada(
                    nome='ICMS Retido', cst=None, base_calculo=_por_unidade(self.icms_ret.base),
                    aliquota=None, reducao=None, valor=_por_unidade(self.icms_ret.valor),
                ),
                LinhaImpostoEntrada(
                    nome='IPI', cst=self.ipi.cst, base_calculo=_por_unidade(self.ipi.base_calculo),
                    aliquota=self.ipi.aliquota, reducao=None, valor=_por_unidade(self.ipi.valor),
                ),
                LinhaImpostoEntrada(
                    nome='PIS', cst=self.pis.cst, base_calculo=_por_unidade(self.pis.base_calculo),
                    aliquota=self.pis.aliquota, reducao=self.pis.reducao, valor=_por_unidade(self.pis.valor),
                ),
                LinhaImpostoEntrada(
                    nome='COFINS', cst=self.cofins.cst, base_calculo=_por_unidade(self.cofins.base_calculo),
                    aliquota=self.cofins.aliquota, reducao=self.cofins.reducao, valor=_por_unidade(self.cofins.valor),
                ),
            ],
        )


class IcmsEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='icms',
    )
    cst = models.PositiveSmallIntegerField()
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'ICMS de Entrada (XML) do Produto'
        verbose_name_plural = 'ICMS de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'ICMS — {self.impostos_e_custos}'


class IcmsStEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='icms_st',
    )
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'ICMS ST de Entrada (XML) do Produto'
        verbose_name_plural = 'ICMS ST de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'ICMS ST — {self.impostos_e_custos}'


class IcmsRetEntradaProduto(models.Model):
    # * [EXPLICAÇÃO] → Não herda de ImpostoComAliquota — ICMS Ret nunca teve
    #                  alíquota nem redução no domínio real, só base e
    #                  valor. Nunca foi usado até hoje, mas como vem do
    #                  XML, é guardado mesmo assim (decisão do usuário).

    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='icms_ret',
    )
    base = models.DecimalField(max_digits=12, decimal_places=2)
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'ICMS Retido de Entrada (XML) do Produto'
        verbose_name_plural = 'ICMS Retido de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'ICMS Ret — {self.impostos_e_custos}'


class IpiEntradaProduto(ImpostoComAliquota):
    # * [EXPLICAÇÃO] → Sem campo de redução — IPI nunca tem esse dado no
    #                  domínio real (diferente de ICMS/ICMS ST/PIS/COFINS).

    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='ipi',
    )
    cst = models.PositiveSmallIntegerField()

    class Meta:
        verbose_name = 'IPI de Entrada (XML) do Produto'
        verbose_name_plural = 'IPI de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'IPI — {self.impostos_e_custos}'


class PisEntradaProduto(ImpostoComAliquota):
    # * [EXPLICAÇÃO] → reducao aqui é CALCULADA (base_calculo do próprio PIS
    #                  ÷ custo_total do guarda-chuva) — não vem direto do
    #                  XML, mesma lógica já usada na dataclass Pis (ver
    #                  "Calculo de Reducao PIS e COFINS via Base de Calculo
    #                  e Custo Total" no vault). Guardada pronta,
    #                  calculada 1 vez em sincronizar_a_partir_de — nunca
    #                  recalculada por fora.

    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='pis',
    )
    cst = models.PositiveSmallIntegerField()
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'PIS de Entrada (XML) do Produto'
        verbose_name_plural = 'PIS de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'PIS — {self.impostos_e_custos}'


class CofinsEntradaProduto(ImpostoComAliquota):
    # * [EXPLICAÇÃO] → Mesma lógica de redução calculada do PisEntradaProduto.

    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='cofins',
    )
    cst = models.PositiveSmallIntegerField()
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'COFINS de Entrada (XML) do Produto'
        verbose_name_plural = 'COFINS de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'COFINS — {self.impostos_e_custos}'