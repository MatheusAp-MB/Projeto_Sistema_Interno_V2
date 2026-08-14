# impostos/models.py

# Função Objetivo: Retrato mais atual dos impostos e custos de entrada de 1
# produto, vindos do XML/Cadastro da nota fiscal (via Sysemp) — guarda-chuva
# que liga o produto à identificação da nota de origem e ao custo_total
# (usado pelo PIS/COFINS pra calcular a própria redução). Sem histórico:
# cada sincronização bem-sucedida SOBRESCREVE o retrato anterior (Regra dos
# Três — histórico fica pra quando/se a necessidade real aparecer). Ver
# decisão completa no vault: "Modelagem de Impostos e Custos de Entrada via
# XML (ImpostosECustosXMLEntradaProduto)".
#
# Reorganizado (14/08/2026) junto com integracao_sysemp/servicos/dados_xml_nf.py:
# campos que agora vêm em par XML/Cadastro (CST de cada imposto, NCM) ganharam
# sufixo explícito "_xml"/"_cadastro" nos 2 lados, sem exceção — e o campo
# `base` do ICMS Ret virou `base_calculo`, igual aos outros 5 impostos
# (inconsistência antiga, corrigida agora).
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
    #                  ausente = None. base_calculo e valor aqui já vêm POR
    #                  UNIDADE (decisão do usuário, 10/08/2026). `cst` aqui
    #                  representa sempre o valor XML (fonte de verdade) —
    #                  exibir também o Cadastro no modal é trabalho de tela
    #                  separado, ainda não feito.
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
    ncm: str | None
    fornecedor: str
    custo_unitario: Decimal | None
    linhas: list[LinhaImpostoEntrada]


class ImpostoComAliquota(models.Model):
    # * [EXPLICAÇÃO] → Classe-base abstrata só com os 3 campos que se
    #                  repetem de verdade em 5 dos 6 impostos (ICMS, ICMS
    #                  ST, IPI, PIS, COFINS). ICMS Ret não herda daqui —
    #                  não tem alíquota. cst e redução ficam fora da base
    #                  por não serem uniformes nem entre os 5 que têm
    #                  alíquota (IPI não tem redução; ICMS ST não tem cst).

    base_calculo = models.DecimalField(max_digits=12, decimal_places=2)
    aliquota = models.DecimalField(max_digits=7, decimal_places=4)
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        abstract = True


class ImpostosECustosXMLEntradaProduto(models.Model):
    produto = models.OneToOneField(Produto, on_delete=models.CASCADE, related_name='impostos_entrada')
    nr_nf = models.CharField(max_length=20)
    data_entrada_nota = models.DateField(null=True, blank=True)
    emissao = models.DateField(null=True, blank=True)
    # * [EXPLICAÇÃO] → NCM agora vem em par XML/Cadastro (14/08/2026) — antes
    #                  era 1 campo único (`ncm`), só com o valor do XML. O
    #                  valor Cadastro é novo, existe especificamente pra
    #                  comparar contra o XML e detectar cadastro desatualizado
    #                  no Sysemp (mesmo motivo do par nos outros campos de
    #                  classificação fiscal — ver ClassificacaoFiscalItem em
    #                  dados_xml_nf.py). null=True/blank=True nos 2 — mesma
    #                  situação de produtos já sincronizados antes da mudança.
    ncm_xml = models.CharField(max_length=20, null=True, blank=True)
    ncm_cadastro = models.CharField(max_length=20, null=True, blank=True)
    fornecedor = models.CharField(max_length=255)
    custo_total = models.DecimalField(max_digits=12, decimal_places=2)
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
        data_entrada = date.fromisoformat(dados.identificacao_nf.data_entrada_nf) \
            if dados.identificacao_nf.data_entrada_nf else None
        emissao = date.fromisoformat(dados.identificacao_nf.data_emissao_nf) \
            if dados.identificacao_nf.data_emissao_nf else None

        with transaction.atomic():
            guarda_chuva, _ = cls.objects.update_or_create(
                produto=produto,
                defaults={
                    'nr_nf': dados.identificacao_nf.numero_nf,
                    'data_entrada_nota': data_entrada,
                    'emissao': emissao,
                    'ncm_xml': dados.classificacao_fiscal.ncm_xml,
                    'ncm_cadastro': dados.classificacao_fiscal.ncm_cadastro,
                    'fornecedor': dados.identificacao_nf.fornecedor,
                    'custo_total': _converter_para_decimal(dados.custos.total),
                    'quantidade_nota': _converter_para_decimal(dados.identificacao_produto.quantidade_nota),
                    'custo_unitario': _converter_para_decimal(dados.custos.unitario),
                },
            )
            IcmsEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'cst_xml': dados.icms.cst_xml,
                    'cst_cadastro': dados.icms.cst_cadastro,
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
                    'base_calculo': _converter_para_decimal(dados.icms_ret.base_calculo),
                    'valor': _converter_para_decimal(dados.icms_ret.valor),
                },
            )
            IpiEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'cst_xml': dados.ipi.cst_xml,
                    'cst_cadastro': dados.ipi.cst_cadastro,
                    'base_calculo': _converter_para_decimal(dados.ipi.base_calculo),
                    'aliquota': _converter_para_decimal(dados.ipi.aliquota),
                    'valor': _converter_para_decimal(dados.ipi.valor),
                },
            )
            PisEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'cst_xml': dados.pis.cst_xml,
                    'cst_cadastro': dados.pis.cst_cadastro,
                    'base_calculo': _converter_para_decimal(dados.pis.base_calculo),
                    'aliquota': _converter_para_decimal(dados.pis.aliquota),
                    'reducao': _converter_para_decimal(dados.pis.reducao),
                    'valor': _converter_para_decimal(dados.pis.valor),
                },
            )
            CofinsEntradaProduto.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults={
                    'cst_xml': dados.cofins.cst_xml,
                    'cst_cadastro': dados.cofins.cst_cadastro,
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
        quantidade = self.quantidade_nota

        def _por_unidade(valor_da_nota: Decimal | None) -> Decimal | None:
            if valor_da_nota is None or not quantidade:
                return None
            return valor_da_nota / quantidade

        return DetalhesImpostosEntradaProduto(
            nr_nf=self.nr_nf,
            data_entrada_nota=self.data_entrada_nota,
            emissao=self.emissao,
            ncm=self.ncm_xml,
            fornecedor=self.fornecedor,
            custo_unitario=self.custo_unitario,
            linhas=[
                LinhaImpostoEntrada(
                    nome='ICMS', cst=self.icms.cst_xml, base_calculo=_por_unidade(self.icms.base_calculo),
                    aliquota=self.icms.aliquota, reducao=self.icms.reducao, valor=_por_unidade(self.icms.valor),
                ),
                LinhaImpostoEntrada(
                    nome='ICMS ST', cst=None, base_calculo=_por_unidade(self.icms_st.base_calculo),
                    aliquota=self.icms_st.aliquota, reducao=self.icms_st.reducao, valor=_por_unidade(self.icms_st.valor),
                ),
                LinhaImpostoEntrada(
                    nome='ICMS Retido', cst=None, base_calculo=_por_unidade(self.icms_ret.base_calculo),
                    aliquota=None, reducao=None, valor=_por_unidade(self.icms_ret.valor),
                ),
                LinhaImpostoEntrada(
                    nome='IPI', cst=self.ipi.cst_xml, base_calculo=_por_unidade(self.ipi.base_calculo),
                    aliquota=self.ipi.aliquota, reducao=None, valor=_por_unidade(self.ipi.valor),
                ),
                LinhaImpostoEntrada(
                    nome='PIS', cst=self.pis.cst_xml, base_calculo=_por_unidade(self.pis.base_calculo),
                    aliquota=self.pis.aliquota, reducao=self.pis.reducao, valor=_por_unidade(self.pis.valor),
                ),
                LinhaImpostoEntrada(
                    nome='COFINS', cst=self.cofins.cst_xml, base_calculo=_por_unidade(self.cofins.base_calculo),
                    aliquota=self.cofins.aliquota, reducao=self.cofins.reducao, valor=_por_unidade(self.cofins.valor),
                ),
            ],
        )


class IcmsEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='icms',
    )
    cst_xml = models.PositiveSmallIntegerField()
    cst_cadastro = models.PositiveSmallIntegerField(null=True, blank=True)
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
    #                  valor. `base_calculo` (antes `base`) — corrigido
    #                  14/08/2026 pra ficar consistente com os outros 5
    #                  impostos, que sempre usaram esse nome.

    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='icms_ret',
    )
    base_calculo = models.DecimalField(max_digits=12, decimal_places=2)
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'ICMS Retido de Entrada (XML) do Produto'
        verbose_name_plural = 'ICMS Retido de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'ICMS Ret — {self.impostos_e_custos}'


class IpiEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='ipi',
    )
    cst_xml = models.PositiveSmallIntegerField()
    cst_cadastro = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'IPI de Entrada (XML) do Produto'
        verbose_name_plural = 'IPI de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'IPI — {self.impostos_e_custos}'


class PisEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='pis',
    )
    cst_xml = models.PositiveSmallIntegerField()
    cst_cadastro = models.PositiveSmallIntegerField(null=True, blank=True)
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'PIS de Entrada (XML) do Produto'
        verbose_name_plural = 'PIS de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'PIS — {self.impostos_e_custos}'


class CofinsEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='cofins',
    )
    cst_xml = models.PositiveSmallIntegerField()
    cst_cadastro = models.PositiveSmallIntegerField(null=True, blank=True)
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'COFINS de Entrada (XML) do Produto'
        verbose_name_plural = 'COFINS de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'COFINS — {self.impostos_e_custos}'