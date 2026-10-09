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

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from impostos.models import ImpostosECustosXMLEntradaProduto, NotaFiscalEntrada

# * [EXPLICAÇÃO] → Campos que a API repete em TODOS os itens da nota (dados do
#                  cabeçalho) mais o número do item: já aparecem no topo do
#                  espelho / na 1ª coluna da tabela, então ficam fora das tabelas
#                  de detalhe de cada item.
CAMPOS_JA_MOSTRADOS = frozenset({
    'Chave', 'NR NF', 'Fornecedor', 'Empresa Fantasia', 'Emissão', 'Entrada NF', 'Item', 'itens_nf',
    'Produto',   # o nome do produto já é a 2ª coluna da tabela de itens
})

# * [EXPLICAÇÃO] → Tabela "Impostos deste item": 1 linha por imposto, e cada coluna aponta
#                  pro nome do campo no registro cru da API (None = esse imposto não tem
#                  essa coluna). Ex: o FCP do ICMS ST só tem alíquota e valor; o ICMS
#                  retido só tem base e valor. A redução de PIS/COFINS não vem na nota —
#                  o sistema calcula, por isso a coluna fica em branco pra eles.
IMPOSTOS_DO_ITEM = (
    # nome na tela, CST (XML), CST (cadastro), base de cálculo, alíquota, redução, valor
    ('ICMS', 'CST ICMS', 'CST ICMS Cadastro', 'Base Calculo ICMS', 'Aliquota ICMS', 'Redução ICMS', 'Valor ICMS'),
    ('ICMS ST', None, None, 'Base Calculo ICMS ST', 'Aliquota ICMS ST', 'Redução ICMS ST', 'Valor ICMS ST'),
    ('FCP do ICMS ST', None, None, None, '% FCP ST', None, 'Valor FCP ST'),
    ('ICMS retido', None, None, 'Base ICMS Ret', None, None, 'Valor ICMS Ret'),
    ('IPI', 'CST IPI', 'CST IPI Cadastro', 'Base Calculo IPI', 'Aliquota IPI', None, 'Valor IPI'),
    ('PIS', 'CST PIS', 'CST PIS Cadastro', 'Base Calculo PIS', 'Aliquota PIS', None, 'Valor PIS'),
    ('COFINS', 'CST COFINS', 'CST COFINS Cadastro', 'Base Calculo COFINS', 'Aliquota COFINS', None, 'Valor COFINS'),
)

# * [EXPLICAÇÃO] → Tabela "Classificação fiscal": o que a nota diz × o que o cadastro do
#                  Sysemp diz, lado a lado. `origem` define como a linha aparece:
#                  'ambos' (XML e Cadastro), 'so_cadastro' (só existe no cadastro) e
#                  'sem_origem' (campo único da API, sem par XML/Cadastro).
CLASSIFICACAO_FISCAL_DO_ITEM = (
    # rótulo, origem, chave XML, chave cadastro, descrição XML, descrição cadastro
    ('NCM', 'ambos', 'NCM XML', 'NCM Cadastro', None, None),
    ('CFOP', 'ambos', 'CFOP XML', 'CFOP Cadastro', None, None),
    ('Origem da mercadoria', 'ambos', 'Origem XML', 'Origem Cadastro', 'Origem Descricão XML', 'Origem Descricão Cadastro'),
    ('CEST', 'sem_origem', 'CEST', None, None, None),
    ('Natureza da operação', 'so_cadastro', None, 'Natureza da Operacao Cadastro', None, None),
    ('TES de saída', 'so_cadastro', None, 'TES Saida Cadastro', None, None),
)

# * [EXPLICAÇÃO] → Tabela "Produto e custos": rótulo na tela, chave no registro cru e formato
#                  ('texto' nunca é formatado como número — EAN/ID/código perderiam zeros
#                  ou ganhariam separador de milhar).
PRODUTO_E_CUSTOS_DO_ITEM = (
    ('ID no Sysemp', 'ID Produto', 'texto'),
    ('Código de barras (EAN)', 'Código Barras', 'texto'),
    ('Código auxiliar', 'Código Auxiliar', 'texto'),
    ('Código do fabricante', 'Código Fabricante', 'texto'),
    ('Quantidade', 'Qtde', 'quantidade'),
    ('Custo unitário', 'Custo Unitário', 'dinheiro'),
    ('Custo total', 'Custo Total', 'dinheiro'),
)

# Tudo que as 3 tabelas acima já mostram — o que sobrar do registro cru vai pra "Outros campos".
CAMPOS_MOSTRADOS_NAS_TABELAS = frozenset(
    {chave for linha in IMPOSTOS_DO_ITEM for chave in linha[1:] if chave}
    | {chave for linha in CLASSIFICACAO_FISCAL_DO_ITEM for chave in (linha[2], linha[3], linha[4], linha[5]) if chave}
    | {chave for _, chave, _ in PRODUTO_E_CUSTOS_DO_ITEM}
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
class LinhaImpostoItem:
    # Função Objetivo: 1 linha da tabela "Impostos deste item". None em qualquer coluna =
    # "—" na tela (o imposto não tem essa coluna, ou a nota não trouxe o dado).
    nome: str
    cst_xml: str | None
    cst_cadastro: str | None
    base_calculo: Decimal | None
    aliquota: Decimal | None
    reducao: Decimal | None
    valor: Decimal | None


@dataclass
class LinhaClassificacaoItem:
    rotulo: str
    origem: str                  # 'ambos' | 'so_cadastro' | 'sem_origem'
    xml: str | None
    cadastro: str | None


@dataclass
class LinhaProdutoCustoItem:
    rotulo: str
    formato: str                 # 'texto' | 'quantidade' | 'dinheiro'
    texto: str | None
    numero: Decimal | None


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
    # * [EXPLICAÇÃO] → `aberto`: a tela já mostra o detalhe deste item sem precisar clicar no
    #                  "+" (o item do produto auditado, ou todos quando a nota tem poucos itens).
    aberto: bool = False
    impostos: list[LinhaImpostoItem] = field(default_factory=list)
    classificacao: list[LinhaClassificacaoItem] = field(default_factory=list)
    produto_e_custos: list[LinhaProdutoCustoItem] = field(default_factory=list)
    outros_campos: list[CampoBrutoItem] = field(default_factory=list)


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


def _montar_campo_bruto(rotulo: str, valor) -> CampoBrutoItem:
    # * [EXPLICAÇÃO] → float = número decimal de verdade (alíquota, valor) —
    #                  a tela formata. int/str = código ou identificador
    #                  (ID, EAN, CST "00") — vai como texto, sem formatação.
    if isinstance(valor, float):
        return CampoBrutoItem(rotulo=rotulo, texto=None, numero=valor)
    if isinstance(valor, bool):
        return CampoBrutoItem(rotulo=rotulo, texto='Sim' if valor else 'Não', numero=None)
    return CampoBrutoItem(rotulo=rotulo, texto=_texto_ou_none(valor), numero=None)


def _valor_da_chave(bruto: dict, chave: str | None):
    return bruto.get(chave) if chave else None


def _montar_linhas_de_impostos(bruto: dict) -> list[LinhaImpostoItem]:
    return [
        LinhaImpostoItem(
            nome=nome,
            cst_xml=_texto_ou_none(_valor_da_chave(bruto, chave_cst_xml)),
            cst_cadastro=_texto_ou_none(_valor_da_chave(bruto, chave_cst_cadastro)),
            base_calculo=_numero(_valor_da_chave(bruto, chave_base)),
            aliquota=_numero(_valor_da_chave(bruto, chave_aliquota)),
            reducao=_numero(_valor_da_chave(bruto, chave_reducao)),
            valor=_numero(_valor_da_chave(bruto, chave_valor)),
        )
        for nome, chave_cst_xml, chave_cst_cadastro, chave_base, chave_aliquota, chave_reducao, chave_valor
        in IMPOSTOS_DO_ITEM
    ]


def _texto_com_descricao(bruto: dict, chave: str | None, chave_descricao: str | None) -> str | None:
    # Ex: origem da mercadoria — a descrição ("0 - Nacional, exceto...") já traz o código; se a
    # API não mandou a descrição, mostra só o código.
    return _texto_ou_none(_valor_da_chave(bruto, chave_descricao)) or _texto_ou_none(_valor_da_chave(bruto, chave))


def _montar_linhas_de_classificacao(bruto: dict) -> list[LinhaClassificacaoItem]:
    return [
        LinhaClassificacaoItem(
            rotulo=rotulo,
            origem=origem,
            xml=_texto_com_descricao(bruto, chave_xml, descricao_xml),
            cadastro=_texto_com_descricao(bruto, chave_cadastro, descricao_cadastro),
        )
        for rotulo, origem, chave_xml, chave_cadastro, descricao_xml, descricao_cadastro
        in CLASSIFICACAO_FISCAL_DO_ITEM
    ]


def _montar_linhas_de_produto_e_custos(bruto: dict) -> list[LinhaProdutoCustoItem]:
    linhas = []
    for rotulo, chave, formato in PRODUTO_E_CUSTOS_DO_ITEM:
        valor = bruto.get(chave)
        linhas.append(LinhaProdutoCustoItem(
            rotulo=rotulo,
            formato=formato,
            texto=_texto_ou_none(valor) if formato == 'texto' else None,
            numero=_numero(valor) if formato != 'texto' else None,
        ))
    return linhas


def _montar_outros_campos(bruto: dict) -> list[CampoBrutoItem]:
    # Nada some: campo que a API mandar e que não está em nenhuma das tabelas aparece aqui.
    return sorted(
        (
            _montar_campo_bruto(rotulo, valor)
            for rotulo, valor in bruto.items()
            if rotulo not in CAMPOS_JA_MOSTRADOS and rotulo not in CAMPOS_MOSTRADOS_NAS_TABELAS
        ),
        key=lambda campo: campo.rotulo,
    )


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
        impostos=_montar_linhas_de_impostos(bruto),
        classificacao=_montar_linhas_de_classificacao(bruto),
        produto_e_custos=_montar_linhas_de_produto_e_custos(bruto),
        outros_campos=_montar_outros_campos(bruto),
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


# * [EXPLICAÇÃO] → Nota pequena (até 3 itens): o detalhe de todos já vem aberto — o usuário
#                  bate o olho na nota inteira sem clicar. Nota grande: só o item do produto
#                  auditado vem aberto (os outros abrem no "+", ou no "Expandir todos").
MAXIMO_DE_ITENS_PARA_ABRIR_TODOS = 3


def _marcar_itens_abertos(itens: list[ItemEspelhoNota]) -> None:
    abrir_todos = len(itens) <= MAXIMO_DE_ITENS_PARA_ABRIR_TODOS
    for item in itens:
        item.aberto = abrir_todos or item.eh_do_produto


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
        _marcar_itens_abertos(itens)
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
