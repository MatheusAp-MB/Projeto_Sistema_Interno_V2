# scripts_exploracao_ERP/dados_xml_nf.py

# Função Objetivo: Modelar os dados de 1 nota fiscal (já filtrada por CFOP e
# selecionada como a mais recente por produto — ver
# nota_mais_recente_por_produto.json) em objetos de domínio organizados por
# tipo de dado/imposto, pra uso nos testes de cálculo de imposto sem precisar
# navegar dict cru com chaves em string. Objetos de processo (dataclass),
# nunca persistidos — refletem o XML da NF tal como veio da Sysemp. Campos
# sem uso confirmado (Item, Empresa Fantasia, % FCP ST, Valor FCP ST) ficaram
# de fora por decisão do usuário (07/08/2026) — continuam no json cru se
# precisar voltar a usá-los.

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
    # e só aqui — nunca um if solto em outro lugar do pipeline. Sem isso, o
    # null ou estoura na hora (float(None)) ou se propaga como problema pra
    # tratar em cada cálculo/soma adiante. Só usado nos 6 impostos — Custo
    # Total/Unitário e Qtde continuam com float() direto de propósito,
    # porque null ali é mais grave e não deve ser mascarado.
    return float(valor) if valor is not None else 0.0


def _int_ou_zero(valor) -> int:
    # * [EXPLICAÇÃO] → mesma decisão acima, pra campo inteiro de imposto
    # (CST) — mesmo escopo, nunca usado fora dos 6 impostos.
    return int(valor) if valor is not None else 0


@dataclass(frozen=True)
class IdentificacaoProduto:
    id_produto: int
    produto: str
    codigo_barras: str
    codigo_auxiliar: str
    codigo_fabricante: str
    qtde: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'IdentificacaoProduto':
        return cls(
            id_produto=int(registro['ID Produto']),
            produto=registro['Produto'],
            codigo_barras=registro['Código Barras'],
            codigo_auxiliar=registro['Código Auxiliar'],
            codigo_fabricante=registro['Código Fabricante'],
            qtde=float(registro['Qtde']),
        )


@dataclass(frozen=True)
class IdentificacaoNF:
    nr_nf: str
    data_entrada_nota: str | None
    emissao: str

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'IdentificacaoNF':
        return cls(
            nr_nf=registro['NR NF'],
            data_entrada_nota=registro['Data Entrada da Nota'],
            emissao=registro['Emissão'],
        )


@dataclass(frozen=True)
class DadosNF:
    fornecedor: str
    cfop: str
    natureza_da_operacao: str
    chave: str

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'DadosNF':
        return cls(
            fornecedor=registro['Fornecedor'],
            cfop=registro['CFOP'],
            natureza_da_operacao=registro['Natureza da Operacao'],
            chave=registro['Chave'],
        )


@dataclass(frozen=True)
class IdentificadorRegra:
    tes_saida: int
    ncm: str
    origem: str
    origem_descricao: str

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'IdentificadorRegra':
        return cls(
            tes_saida=int(registro['TES Saida']),
            ncm=registro['NCM'],
            origem=registro['Origem'],
            origem_descricao=registro['Origem Descricao'],
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
    cst: int
    base_calculo: float
    aliquota: float
    reducao: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'Icms':
        return cls(
            cst=_int_ou_zero(registro['CST ICMS']),
            base_calculo=_float_ou_zero(registro['Base Calculo ICMS']),
            aliquota=_float_ou_zero(registro['Aliquota ICMS']),
            reducao=_float_ou_zero(registro['Redução ICMS']),
            valor=_float_ou_zero(registro['Valor ICMS']),
        )


@dataclass(frozen=True)
class IcmsRet:
    base: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'IcmsRet':
        return cls(
            base=_float_ou_zero(registro['Base ICMS Ret']),
            valor=_float_ou_zero(registro['Valor ICMS Ret']),
        )


@dataclass(frozen=True)
class Ipi:
    cst: int
    base_calculo: float
    aliquota: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict) -> 'Ipi':
        return cls(
            cst=_int_ou_zero(registro['CST IPI']),
            base_calculo=_float_ou_zero(registro['Base Calculo IPI']),
            aliquota=_float_ou_zero(registro['Aliquota IPI']),
            valor=_float_ou_zero(registro['Valor IPI']),
        )


@dataclass(frozen=True)
class Pis:
    cst: int
    base_calculo: float
    aliquota: float
    reducao: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict, custo_total: float) -> 'Pis':
        base_calculo = _float_ou_zero(registro['Base Calculo PIS'])
        return cls(
            cst=_int_ou_zero(registro['CST PIS']),
            base_calculo=base_calculo,
            aliquota=_float_ou_zero(registro['Aliquota PIS']),
            reducao=_calcular_percentual_de_reducao(base_calculo, custo_total),
            valor=_float_ou_zero(registro['Valor PIS']),
        )


@dataclass(frozen=True)
class Cofins:
    cst: int
    base_calculo: float
    aliquota: float
    reducao: float
    valor: float

    @classmethod
    def a_partir_do_registro(cls, registro: dict, custo_total: float) -> 'Cofins':
        base_calculo = _float_ou_zero(registro['Base Calculo COFINS'])
        return cls(
            cst=_int_ou_zero(registro['CST COFINS']),
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
    dados_nf: DadosNF
    identificador_regra: IdentificadorRegra
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
            dados_nf=DadosNF.a_partir_do_registro(registro),
            identificador_regra=IdentificadorRegra.a_partir_do_registro(registro),
            icms_st=IcmsSt.a_partir_do_registro(registro),
            icms=Icms.a_partir_do_registro(registro),
            icms_ret=IcmsRet.a_partir_do_registro(registro),
            ipi=Ipi.a_partir_do_registro(registro),
            pis=Pis.a_partir_do_registro(registro, custos.total),
            cofins=Cofins.a_partir_do_registro(registro, custos.total),
            custos=custos,
        )