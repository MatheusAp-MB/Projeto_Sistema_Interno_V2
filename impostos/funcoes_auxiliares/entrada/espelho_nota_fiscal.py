# impostos/funcoes_auxiliares/entrada/espelho_nota_fiscal.py

# Função Objetivo: Monta, pronto pra exibição, o "espelho" de 1 nota fiscal de
# entrada — todos os itens dela, com os impostos de cada um, do jeito que a
# Sysemp devolveu. Alimenta o botão "Ver NF" da grade de precificação.
#
# Não é o documento fiscal (DANFE): é só a nota inteira reunida numa tela pro
# usuário poder dizer "é essa NF, desse dia, com esses produtos, com esses
# dados". Lê só o que já está gravado (NotaFiscalEntrada/ItemNotaFiscalEntrada,
# gravados por sincronizacao_nota_fiscal_entrada.py) — nunca chama a API.
#
# Leitura TOLERANTE de propósito (diferente de DadosXmlNF, que é estrito): o
# espelho mostra a nota como ela é, inclusive itens de produtos que o sistema
# nem usa e itens com dado incompleto no Sysemp (ex: TES de saída vazio). 1
# campo estranho vira "—" na tela, nunca um erro que impede de ver a nota.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from impostos.models import ImpostosECustosXMLEntradaProduto, NotaFiscalEntrada

# * [EXPLICAÇÃO] → Campos que a API repete em TODOS os itens da nota (dados do
#                  cabeçalho) mais o número do item: já aparecem no topo do
#                  espelho / na 1ª coluna da tabela, então ficam fora da lista
#                  "todos os campos" de cada item.
CAMPOS_JA_MOSTRADOS = frozenset({
    'Chave', 'NR NF', 'Fornecedor', 'Empresa Fantasia', 'Emissão', 'Entrada NF', 'Item', 'itens_nf',
})

CAMPOS_DE_IDENTIFICACAO_DO_PRODUTO = frozenset({
    'ID Produto', 'Produto', 'Código Barras', 'Código Auxiliar', 'Código Fabricante', 'Qtde',
})

# * [EXPLICAÇÃO] → Ordem em que os grupos aparecem na lista "todos os campos".
#                  O MySQL reordena as chaves de uma coluna JSON (por tamanho,
#                  depois alfabético) — então a ordem da API se perde no banco;
#                  agrupar por assunto devolve uma ordem que faz sentido.
ORDEM_DOS_GRUPOS = (
    'Produto', 'Custos', 'ICMS', 'ICMS ST', 'ICMS retido', 'IPI', 'PIS', 'COFINS',
    'Classificação fiscal', 'Outros campos',
)


@dataclass
class CampoBrutoItem:
    # Função Objetivo: 1 campo do registro cru de 1 item. `numero` vem
    # preenchido só quando a API mandou um número decimal (a tela formata);
    # senão vai `texto` (código, descrição, inteiro como ID/EAN) — que nunca
    # pode ser formatado como número (ex: separador de milhar num EAN).
    rotulo: str
    texto: str | None
    numero: float | None


@dataclass
class GrupoCamposItem:
    titulo: str
    campos: list[CampoBrutoItem]


@dataclass
class ItemEspelhoNota:
    numero_item: int
    nome_produto: str
    codigo_barras: str | None
    codigo_auxiliar: str | None
    quantidade: Decimal | None
    custo_unitario: Decimal | None
    custo_total: Decimal | None
    ncm: str | None
    cfop_cadastro: str | None
    icms_valor: Decimal | None
    icms_aliquota: Decimal | None
    icms_st_valor: Decimal | None
    icms_st_aliquota: Decimal | None
    ipi_valor: Decimal | None
    ipi_aliquota: Decimal | None
    pis_valor: Decimal | None
    pis_aliquota: Decimal | None
    cofins_valor: Decimal | None
    cofins_aliquota: Decimal | None
    eh_do_produto: bool
    grupos_de_campos: list[GrupoCamposItem] = field(default_factory=list)


@dataclass
class TotaisEspelho:
    # * [EXPLICAÇÃO] → Soma dos itens que a tela mostra — NÃO é o total oficial
    #                  da nota (a API do manifesto não manda o rodapé da NF:
    #                  frete, seguro, desconto...). Por isso a tela chama de
    #                  "soma dos itens".
    quantidade_de_itens: int
    custo_total: Decimal
    icms: Decimal
    icms_st: Decimal
    ipi: Decimal
    pis: Decimal
    cofins: Decimal


@dataclass
class EspelhoNotaFiscal:
    chave_acesso: str
    chave_formatada: str
    numero_nf: str
    fornecedor: str | None
    empresa_fantasia: str | None
    emissao: date | None
    data_entrada_nota: date | None
    atualizada_em: datetime | None
    itens_guardados: bool
    itens: list[ItemEspelhoNota]
    totais: TotaisEspelho
    itens_do_produto: int


def formatar_chave_acesso(chave: str | None) -> str:
    # Função Objetivo: Chave de acesso (44 dígitos) em blocos de 4 — legível,
    # igual ao que aparece no DANFE.
    if not chave:
        return ''
    limpa = str(chave).strip()
    return ' '.join(limpa[inicio:inicio + 4] for inicio in range(0, len(limpa), 4))


def _numero(valor) -> Decimal | None:
    # Função Objetivo: Qualquer coisa que a API mandou → Decimal, ou None se
    # não der (None, '', texto estranho, NaN). Nunca levanta erro.
    if valor is None or valor == '' or isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        return None
    return numero if numero.is_finite() else None


def _texto_ou_none(valor) -> str | None:
    if valor is None or valor == '':
        return None
    return str(valor).strip() or None


def _grupo_do_campo(rotulo: str) -> str:
    # * [EXPLICAÇÃO] → Compara por PALAVRAS (não por trecho de texto) pra
    #                  "IPI" não casar com o meio de outra palavra.
    palavras = set(re.findall(r'\w+', rotulo.upper()))

    if 'FCP' in palavras or ('ICMS' in palavras and 'ST' in palavras):
        return 'ICMS ST'
    if 'ICMS' in palavras and 'RET' in palavras:
        return 'ICMS retido'
    if 'ICMS' in palavras:
        return 'ICMS'
    if 'IPI' in palavras:
        return 'IPI'
    if 'PIS' in palavras:
        return 'PIS'
    if 'COFINS' in palavras:
        return 'COFINS'
    if 'CUSTO' in palavras:
        return 'Custos'
    if palavras & {'NCM', 'CFOP', 'ORIGEM', 'TES', 'NATUREZA'}:
        return 'Classificação fiscal'
    if rotulo in CAMPOS_DE_IDENTIFICACAO_DO_PRODUTO:
        return 'Produto'
    return 'Outros campos'


def _montar_campo_bruto(rotulo: str, valor) -> CampoBrutoItem:
    # * [EXPLICAÇÃO] → float = número decimal de verdade (alíquota, valor) —
    #                  a tela formata. int/str = código ou identificador
    #                  (ID, EAN, CST "00") — vai como texto, sem formatação.
    if isinstance(valor, float):
        return CampoBrutoItem(rotulo=rotulo, texto=None, numero=valor)
    if isinstance(valor, bool):
        return CampoBrutoItem(rotulo=rotulo, texto='Sim' if valor else 'Não', numero=None)
    return CampoBrutoItem(rotulo=rotulo, texto=_texto_ou_none(valor), numero=None)


def _agrupar_campos(registro_bruto: dict) -> list[GrupoCamposItem]:
    campos_por_grupo: dict[str, list[CampoBrutoItem]] = {}
    for rotulo, valor in registro_bruto.items():
        if rotulo in CAMPOS_JA_MOSTRADOS:
            continue
        campos_por_grupo.setdefault(_grupo_do_campo(rotulo), []).append(_montar_campo_bruto(rotulo, valor))

    return [
        GrupoCamposItem(titulo=titulo, campos=sorted(campos_por_grupo[titulo], key=lambda campo: campo.rotulo))
        for titulo in ORDEM_DOS_GRUPOS
        if titulo in campos_por_grupo
    ]


def _montar_item(item, ean_destaque: str | None) -> ItemEspelhoNota:
    bruto = item.dados_brutos if isinstance(item.dados_brutos, dict) else {}

    return ItemEspelhoNota(
        numero_item=item.numero_item,
        nome_produto=item.nome_produto,
        codigo_barras=item.codigo_barras,
        codigo_auxiliar=item.codigo_auxiliar,
        quantidade=_numero(bruto.get('Qtde')),
        custo_unitario=_numero(bruto.get('Custo Unitário')),
        custo_total=_numero(bruto.get('Custo Total')),
        ncm=_texto_ou_none(bruto.get('NCM XML')) or _texto_ou_none(bruto.get('NCM Cadastro')),
        cfop_cadastro=_texto_ou_none(bruto.get('CFOP Cadastro')),
        icms_valor=_numero(bruto.get('Valor ICMS')),
        icms_aliquota=_numero(bruto.get('Aliquota ICMS')),
        icms_st_valor=_numero(bruto.get('Valor ICMS ST')),
        icms_st_aliquota=_numero(bruto.get('Aliquota ICMS ST')),
        ipi_valor=_numero(bruto.get('Valor IPI')),
        ipi_aliquota=_numero(bruto.get('Aliquota IPI')),
        pis_valor=_numero(bruto.get('Valor PIS')),
        pis_aliquota=_numero(bruto.get('Aliquota PIS')),
        cofins_valor=_numero(bruto.get('Valor COFINS')),
        cofins_aliquota=_numero(bruto.get('Aliquota COFINS')),
        eh_do_produto=bool(ean_destaque) and item.codigo_barras == ean_destaque,
        grupos_de_campos=_agrupar_campos(bruto),
    )


def _somar(valores) -> Decimal:
    return sum((valor for valor in valores if valor is not None), Decimal('0'))


def _montar_totais(itens: list[ItemEspelhoNota]) -> TotaisEspelho:
    return TotaisEspelho(
        quantidade_de_itens=len(itens),
        custo_total=_somar(item.custo_total for item in itens),
        icms=_somar(item.icms_valor for item in itens),
        icms_st=_somar(item.icms_st_valor for item in itens),
        ipi=_somar(item.ipi_valor for item in itens),
        pis=_somar(item.pis_valor for item in itens),
        cofins=_somar(item.cofins_valor for item in itens),
    )


def montar_espelho_nota_fiscal(chave_acesso: str, ean_destaque: str | None = None) -> EspelhoNotaFiscal | None:
    # Função Objetivo: Devolve o espelho da nota de chave `chave_acesso`, ou
    # None se o sistema não conhece essa nota de jeito nenhum.
    #
    # * [EXPLICAÇÃO] → 2 situações:
    #                  1) espelho completo guardado → cabeçalho + todos os
    #                     itens (itens_guardados=True);
    #                  2) só o retrato do produto conhece a nota (ela é mais
    #                     antiga que a janela da última sincronização, ver
    #                     --desde) → só o cabeçalho, sem itens
    #                     (itens_guardados=False) — a tela avisa em vez de
    #                     fingir que a nota tem 0 itens.
    #                  `ean_destaque` marca o(s) item(ns) do produto que está
    #                  sendo auditado, pra o usuário achar de cara.
    nota = NotaFiscalEntrada.objects.filter(chave_acesso=chave_acesso).first()

    if nota is not None:
        itens = [_montar_item(item, ean_destaque) for item in nota.itens.all()]
        return EspelhoNotaFiscal(
            chave_acesso=nota.chave_acesso,
            chave_formatada=formatar_chave_acesso(nota.chave_acesso),
            numero_nf=nota.numero_nf,
            fornecedor=nota.fornecedor,
            empresa_fantasia=nota.empresa_fantasia,
            emissao=nota.emissao,
            data_entrada_nota=nota.data_entrada_nota,
            atualizada_em=nota.atualizada_em,
            itens_guardados=bool(itens),
            itens=itens,
            totais=_montar_totais(itens),
            itens_do_produto=sum(1 for item in itens if item.eh_do_produto),
        )

    retrato = ImpostosECustosXMLEntradaProduto.objects.filter(chave_acesso=chave_acesso).first()
    if retrato is None:
        return None

    return EspelhoNotaFiscal(
        chave_acesso=chave_acesso,
        chave_formatada=formatar_chave_acesso(chave_acesso),
        numero_nf=retrato.nr_nf,
        fornecedor=retrato.fornecedor,
        empresa_fantasia=retrato.empresa_fantasia,
        emissao=retrato.emissao,
        data_entrada_nota=retrato.data_entrada_nota,
        atualizada_em=None,
        itens_guardados=False,
        itens=[],
        totais=_montar_totais([]),
        itens_do_produto=0,
    )
