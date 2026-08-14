# integracao_sysemp/servicos/dados_xml_nf.py

# Função Objetivo: Modelar os dados de 1 nota fiscal (já filtrada por CFOP e
# selecionada como a mais recente por produto — ver
# nota_mais_recente_por_produto.json) em objetos de domínio organizados por
# tipo de dado/imposto, pra uso nos cálculos de imposto sem precisar navegar
# dict cru com chaves em string. Objetos de processo (dataclass), nunca
# persistidos — refletem o XML/Cadastro da NF tal como veio da Sysemp.
#
# Reorganizado (14/08/2026) pra API nova da Sysemp, que passou a trazer
# vários campos em par — valor do XML e valor do Cadastro do próprio
# produto — pra permitir comparação e correção futura (ver "XML da Nota
# Fiscal É a Fonte Única de Verdade Quando o Dado Existir" no vault). Todo
# campo com essa dualidade tem sufixo explícito "_xml"/"_cadastro", sem
# exceção — nunca um dos dois lados fica implícito. `DadosNF` e
# `IdentificadorRegra` (versão anterior) deixaram de existir — seus campos
# foram consolidados em `IdentificacaoNF` (identificação pura da nota) e
# `ClassificacaoFiscalItem` (todo campo comparável XML×Cadastro), já que os
# 2 dataclasses antigos misturavam os dois propósitos sem necessidade real.
#
# Campos sem uso confirmado (Item, Empresa Fantasia, % FCP ST, Valor FCP ST)
# continuam de fora por decisão do usuário — seguem disponíveis no dict cru
# se precisarem voltar a ser usados.

from dataclasses import dataclass


def _calcular_percentual_de_reducao(base_calculo: float, custo_total: float) -> float:
    # * [EXPLICAÇÃO] → fórmula usada tanto em Pis quanto em Cofins: a API não
    # devolve "Redução PIS"/"Redução COFINS" direto (só devolve pra
    # ICMS/ICMS ST) — só entrega a base de cálculo já reduzida e o custo
    # total antes da redução. Reconstrói de trás pra frente: quanto a base
    # representa do total, 1 menos isso (em %) é a redução. Único lugar que
    # calcula isso (ver "Integridade e Fonte Unica de Dado" no vault) —
    # Pis/Cofins guardam o resultado já pronto, ninguém recalcula por fora.
    quanto_a_base_representa_do_total = base_calculo / custo_total
    return round((1.0 - quanto_a_base_representa_do_total) * 100, 2)


def _float_ou_zero(valor) -> float:
    # * [EXPLICAÇÃO] → decisão do usuário (10/08/2026): campo de IMPOSTO que
    # vem null da API (dado incompleto do lado da Sysemp — não é "imposto
    # zero de verdade", ver achado no vault) passa a virar 0 explicitamente,
    # e só aqui — nunca um if solto em outro lugar do pipeline. Só usado nos
    # 6 impostos — Custo Total/Unitário e Qtde continuam com float() direto
    # de propósito, porque null ali é mais grave e não deve ser mascarado.
    return float(valor) if valor is not None else 0.0


def _int_ou_zero(valor) -> int:
    # * [EXPLICAÇÃO] → mesma decisão acima, pra campo inteiro de imposto
    # (CST) — mesmo escopo, nunca usado fora dos 6 impostos. TES Cadastro
    # NÃO usa este helper de propósito — não é campo de imposto, é campo de
    # classificação, fora do escopo original desta decisão.
    return int(valor) if valor is not None else 0


@dataclass(frozen=True)
class IdentificacaoProduto:
    id_produto_sysemp: int
    nome_produto: str
    codigo_barras: str
    codigo_auxiliar: str
    codigo_fabricante: str
    quantidade_nota: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'IdentificacaoProduto':
        return cls(
            id_produto_sysemp=int(registro['ID Produto']),
            nome_produto=registro['Produto'],
            codigo_barras=registro['Código Barras'],
            codigo_auxiliar=registro['Código Auxiliar'],
            codigo_fabricante=registro['Código Fabricante'],
            quantidade_nota=float(registro['Qtde']),
        )


@dataclass(frozen=True)
class IdentificacaoNF:
    numero_nf: str
    chave_acesso_nf: str
    fornecedor: str
    data_emissao_nf: str
    data_entrada_nf: str | None

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'IdentificacaoNF':
        return cls(
            numero_nf=registro['NR NF'],
            chave_acesso_nf=registro['Chave'],
            fornecedor=registro['Fornecedor'],
            data_emissao_nf=registro['Emissão'],
            data_entrada_nf=registro['Entrada NF'],
        )


@dataclass(frozen=True)
class ClassificacaoFiscalItem:
    # * [EXPLICAÇÃO] → Consolida o que antes estava espalhado entre DadosNF
    # (cfop, natureza_da_operacao) e IdentificadorRegra (ncm, origem,
    # origem_descricao, tes_saida) — todos são, agora, campos de
    # classificação fiscal comparável entre o XML da nota e o Cadastro do
    # produto no Sysemp. `natureza_operacao_cadastro` e `tes_saida_cadastro`
    # não têm par XML — só existem como Cadastro mesmo, por isso não levam
    # o sufixo "_cadastro" redundante de forma diferente dos outros (mantém
    # o sufixo mesmo assim, pra nunca duvidar se é XML ou Cadastro só de
    # olhar o nome do campo).
    natureza_operacao_cadastro: str
    ncm_xml: str
    ncm_cadastro: str
    cfop_xml: str
    cfop_cadastro: str
    origem_mercadoria_xml: str
    origem_mercadoria_cadastro: str
    descricao_origem_mercadoria_xml: str
    descricao_origem_mercadoria_cadastro: str
    tes_saida_cadastro: int

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'ClassificacaoFiscalItem':
        return cls(
            natureza_operacao_cadastro=registro['Natureza da Operacao Cadastro'],
            ncm_xml=registro['NCM XML'],
            ncm_cadastro=registro['NCM Cadastro'],
            cfop_xml=registro['CFOP XML'],
            cfop_cadastro=registro['CFOP Cadastro'],
            origem_mercadoria_xml=registro['Origem XML'],
            origem_mercadoria_cadastro=registro['Origem Cadastro'],
            descricao_origem_mercadoria_xml=registro['Origem Descrição XML'],
            descricao_origem_mercadoria_cadastro=registro['Origem Descrição Cadastro'],
            tes_saida_cadastro=int(registro['TES Saida Cadastro']),
        )


@dataclass(frozen=True)
class IcmsSt:
    base_calculo: float
    aliquota: float
    reducao: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'IcmsSt':
        return cls(
            base_calculo=_float_ou_zero(registro['Base Calculo ICMS ST']),
            aliquota=_float_ou_zero(registro['Aliquota ICMS ST']),
            reducao=_float_ou_zero(registro['Redução ICMS ST']),
            valor=_float_ou_zero(registro['Valor ICMS ST']),
        )


@dataclass(frozen=True)
class Icms:
    cst_xml: int
    cst_cadastro: int
    base_calculo: float
    aliquota: float
    reducao: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'Icms':
        return cls(
            cst_xml=_int_ou_zero(registro['CST ICMS']),
            cst_cadastro=_int_ou_zero(registro['CST ICMS Cadastro']),
            base_calculo=_float_ou_zero(registro['Base Calculo ICMS']),
            aliquota=_float_ou_zero(registro['Aliquota ICMS']),
            reducao=_float_ou_zero(registro['Redução ICMS']),
            valor=_float_ou_zero(registro['Valor ICMS']),
        )


@dataclass(frozen=True)
class IcmsRet:
    base_calculo: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'IcmsRet':
        return cls(
            base_calculo=_float_ou_zero(registro['Base ICMS Ret']),
            valor=_float_ou_zero(registro['Valor ICMS Ret']),
        )


@dataclass(frozen=True)
class Ipi:
    cst_xml: int
    cst_cadastro: int
    base_calculo: float
    aliquota: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'Ipi':
        return cls(
            cst_xml=_int_ou_zero(registro['CST IPI']),
            cst_cadastro=_int_ou_zero(registro['CST IPI Cadastro']),
            base_calculo=_float_ou_zero(registro['Base Calculo IPI']),
            aliquota=_float_ou_zero(registro['Aliquota IPI']),
            valor=_float_ou_zero(registro['Valor IPI']),
        )


@dataclass(frozen=True)
class Pis:
    cst_xml: int
    cst_cadastro: int
    base_calculo: float
    aliquota: float
    reducao: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict, custo_total: float) -> 'Pis':
        base_calculo = _float_ou_zero(registro['Base Calculo PIS'])
        return cls(
            cst_xml=_int_ou_zero(registro['CST PIS']),
            cst_cadastro=_int_ou_zero(registro['CST PIS Cadastro']),
            base_calculo=base_calculo,
            aliquota=_float_ou_zero(registro['Aliquota PIS']),
            reducao=_calcular_percentual_de_reducao(base_calculo, custo_total),
            valor=_float_ou_zero(registro['Valor PIS']),
        )


@dataclass(frozen=True)
class Cofins:
    cst_xml: int
    cst_cadastro: int
    base_calculo: float
    aliquota: float
    reducao: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict, custo_total: float) -> 'Cofins':
        base_calculo = _float_ou_zero(registro['Base Calculo COFINS'])
        return cls(
            cst_xml=_int_ou_zero(registro['CST COFINS']),
            cst_cadastro=_int_ou_zero(registro['CST COFINS Cadastro']),
            base_calculo=base_calculo,
            aliquota=_float_ou_zero(registro['Aliquota COFINS']),
            reducao=_calcular_percentual_de_reducao(base_calculo, custo_total),
            valor=_float_ou_zero(registro['Valor COFINS']),
        )


@dataclass(frozen=True)
class Custos:
    total: float
    unitario: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'Custos':
        return cls(
            total=float(registro['Custo Total']),
            unitario=float(registro['Custo Unitário']),
        )


@dataclass(frozen=True)
class DadosXmlNF:
    identificacao_produto: IdentificacaoProduto
    identificacao_nf: IdentificacaoNF
    classificacao_fiscal: ClassificacaoFiscalItem
    icms_st: IcmsSt
    icms: Icms
    icms_ret: IcmsRet
    ipi: Ipi
    pis: Pis
    cofins: Cofins
    custos: Custos

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'DadosXmlNF':
        custos = Custos.a_partir_do_registro(registro)
        return cls(
            identificacao_produto=IdentificacaoProduto.a_partir_do_registro(registro),
            identificacao_nf=IdentificacaoNF.a_partir_do_registro(registro),
            classificacao_fiscal=ClassificacaoFiscalItem.a_partir_do_registro(registro),
            icms_st=IcmsSt.a_partir_do_registro(registro),
            icms=Icms.a_partir_do_registro(registro),
            icms_ret=IcmsRet.a_partir_do_registro(registro),
            ipi=Ipi.a_partir_do_registro(registro),
            pis=Pis.a_partir_do_registro(registro, custos.total),
            cofins=Cofins.a_partir_do_registro(registro, custos.total),
            custos=custos,
        )   