# precificacao/views/modal_comum.py

# Função Objetivo: Dataclasses de exibição do modal de auditoria — puro formato, sem
# nenhuma lógica de marketplace embutida. Reaproveitadas pelos modais de TODOS os
# marketplaces (ML, Magalu, e os que vierem depois).
#
# Taxonomia de proveniência (campo `origem` em LinhaPercentualValor/LinhaValorUnico) —
# 5 categorias, usadas pela tela de auditoria pra marcar "isso veio de onde":
#   'produto'   → cadastro do produto (custo, dimensão declarada, frete_fornecedor%...)
#   'nf'        → nota fiscal de entrada / crédito fiscal (ICMS/IPI/PIS/COFINS entrada)
#   'saida'     → imposto aplicado na venda (ICMS/PIS/COFINS saída)
#   'config'    → parâmetro operacional (fator de coleta, comissão, margem-alvo, faixas)
#   'calculado' → resultado de fórmula, não é dado bruto (default)
#
# Campos de prova (10/09, Camada 3) — ipi_valor_nota/icms_valor_nota/etc + quantidade_nota
# vêm de DadosEntrada.prova_fiscal (Camada 2). Todos opcionais (None em linha calculada
# ANTES da Camada 2) — o template só mostra a mini-fórmula quando o valor existe.
#
# Nota fiscal usada como base (09/10/2026) — NotaFiscalBase/montar_nota_fiscal_base: de qual NF
# vieram os créditos fiscais do cálculo (lida da foto DadosEntrada.prova_fiscal), comparada com a
# NF que o produto usa HOJE, pra tela mostrar "NF 12345" e o botão "Ver NF".
#
# Regra do tributo já pago explícita (Matheus, 13/10/2026) — RegraPisCofinsAplicada/
# montar_regra_pis_cofins_aplicada: quando o crédito de PIS/COFINS da grade foi zerado pela regra
# (CST 02/04/06 no XML do fornecedor — dona única em pis_cofins_tributo_ja_pago.py), a auditoria
# mostra o valor REAL que veio no XML E "considerado = 0", em todos os lugares onde PIS/COFINS
# aparece (Passo 4, Passo 5, tabela única de itens e Visão 2). Lida da foto
# DadosEntrada.prova_fiscal (campos cst_xml/zerado_pela_regra) — linha calculada antes disso não
# tem esses campos e a tela mostra como sempre, sem inventar explicação (precisa recalcular).

from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ObjectDoesNotExist

from impostos.funcoes_auxiliares.entrada.pis_cofins_tributo_ja_pago import (
    TEXTO_REGRA_TRIBUTO_JA_PAGO, saida_diverge_da_regra,
)


@dataclass
class LinhaPercentualValor:
    label: str
    percentual: object
    valor: object
    origem: str = 'calculado'
    # RegraPisCofinsAplicada quando esta linha (PIS/COFINS saída) foi zerada pela regra do
    # tributo já pago; None em qualquer outra linha — o template só mostra a explicação se existir.
    regra: object = None


# Função Objetivo: A regra do tributo já pago aplicada a 1 imposto (PIS ou COFINS) de 1 cálculo da
# grade, com os textos EXPLÍCITOS prontos pra tela (Matheus, 13/10/2026): o que veio no XML, o que
# foi considerado (sempre 0) e por quê. Os textos nascem aqui, uma vez, e todas as telas só os
# exibem — nunca reescrevem a explicação. A regra em si mora em pis_cofins_tributo_ja_pago.py.
#   texto_credito  → linha do CRÉDITO de entrada: "veio no XML R$ X por unidade, considerado R$ 0,00".
#   texto_saida    → linha do PIS/COFINS de SAÍDA: "veio no XML CST 02 (alíq. X%...), considerado 0,00%".
#                    Se saida_divergente (a grade usou % de saída diferente de zero), vira o AVISO
#                    "a regra manda 0%, mas esta grade usou X% — rode preencher_impostos_saida".
@dataclass
class RegraPisCofinsAplicada:
    cst_xml: object
    texto_regra: str
    texto_credito: str
    texto_saida: str
    saida_divergente: bool = False


@dataclass
class LinhaValorUnico:
    label: str
    valor: object
    origem: str = 'produto'


# Função Objetivo: Bloco de PIS/COFINS (2 usos, bases diferentes) — usado pelos marketplaces
# que ainda não migraram pro padrão de campos separados do ML (Raia/Magalu/Shopee/TikTok/
# Amazon). Restaurado em 10/09: tinha sido removido junto com a Camada 3 do ML, mas
# modal_comum.py é compartilhado — os outros 5 marketplaces ainda chamam montar_pis_cofins()
# direto daqui, e a remoção quebrava o import deles (ImportError em cascata na app inteira).
@dataclass
class BlocoPisCofins:
    percentual: object
    credito_entrada: object
    taxa_saida: object


@dataclass
class DimensaoUsada:
    origem_label: str
    altura: object
    largura: object
    comprimento: object
    peso: object
    peso_fisico: object = None
    peso_cubico: object = None


@dataclass
class PassoCustoFinal:
    custo_com_boni: object
    ipi_valor: object
    frete_fornecedor_valor: object
    resultado: object
    ipi_valor_nota: object = None
    quantidade_nota: object = None


@dataclass
class PassoColeta:
    metro_cubico: object
    fator_coleta: object
    resultado: object


@dataclass
class PassoArmazenagem:
    origem: str
    periodo_dias: object
    resultado: object
    valor_diario: object = None


@dataclass
class PassoFixo:
    coleta: object
    armazenagem: object
    custo_final: object
    credito_icms: object
    credito_pis: object
    credito_cofins: object
    resultado: object
    icms_valor_nota: object = None
    icms_base_calculo: object = None
    icms_aliquota: object = None
    tem_icms_st: bool = False
    pis_valor_nota: object = None
    cofins_valor_nota: object = None
    quantidade_nota: object = None
    # RegraPisCofinsAplicada de PIS/COFINS quando o crédito foi zerado pela regra do tributo já
    # pago (None caso contrário); texto_regra é o texto único da regra, '' quando nenhuma vale.
    regra_pis: object = None
    regra_cofins: object = None
    texto_regra: str = ''


@dataclass
class PassoTaxa:
    itens: list
    resultado: object
    # Texto único da regra do tributo já pago, preenchido só quando PIS ou COFINS saída foi
    # zerado por ela ('' caso contrário). Cada item carrega a própria RegraPisCofinsAplicada.
    texto_regra: str = ''
    # * [EXPLICAÇÃO] → R$ equivalente do resultado (% sobre o preço
    #                  final) — pedido explícito de auditoria: todo
    #                  percentual mostra o par em R$ ao lado (11/09).
    resultado_valor: object = None


@dataclass
class PassoDenominador:
    taxa_percentual: object
    margem_alvo_percentual: object
    resultado: object
    # * [EXPLICAÇÃO] → R$ dos 2 componentes do denominador — mesmo
    #                  motivo do PassoTaxa.resultado_valor acima. O
    #                  denominador em si (resultado) continua sem par
    #                  em R$: é um fator (0-1), não um valor monetário.
    taxa_valor: object = None
    margem_alvo_valor: object = None


# Função Objetivo: Passo 7 — faixa de frete escolhida (de PREÇO no ML, de PESO no Magalu).
@dataclass
class PassoFaixaFrete:
    peso: object
    faixa_min: object
    faixa_max: object
    resultado: object
    # * [EXPLICAÇÃO] → Frete real da API (22/09) — só o ML usa, os outros 5
    #                  marketplaces nunca setam (ficam None), mesmo padrão
    #                  já usado em PassoPrecoExato.rebate.
    frete_real: object = None
    dimensoes_ml: object = None
    peso_billable: object = None
    # * [EXPLICAÇÃO] → Correção do Passo 7 (29/09/2026) — qual caminho decidiu
    #                  'resultado' de verdade: 'api_real' (Frente A, simulação)
    #                  ou 'tabela_calculada'. Só o ML usa (lido de
    #                  GradePrecificacaoML.origem_frete, campo que não existe
    #                  nos outros marketplaces — mesmo padrão de frete_real
    #                  acima). None trata como tabela (linhas antigas de antes
    #                  da Frente A, ou marketplace sem esse campo).
    origem_frete: object = None
    # * [EXPLICAÇÃO] → Pendência #1 (28/09/2026) — detalhamento cru da chamada
    #                  de API que CONFIRMOU o frete usado no cálculo (Frente
    #                  A): dict com billable_weight/discount_type/
    #                  discount_rate/discount_promoted_amount, do jeito que a
    #                  API devolveu. Só existe no caminho 'api_real'
    #                  (origem_frete) — None na tabela, e None também em
    #                  linhas calculadas antes dessa mudança.
    frete_detalhamento_api: object = None


@dataclass
class PassoPrecoExato:
    frete: object
    fixo: object
    rebate: object
    denominador: object
    resultado: object
    # * [EXPLICAÇÃO] → None por padrão — o ML não tem esse conceito
    #                  (nunca finge dado que não existe). Só o Magalu
    #                  preenche de verdade.
    taxa_unidade: object = None


@dataclass
class LinhaSaida:
    label: str
    valor: object
    tipo: str  # 'reais' ou 'percentual'
    destaque: bool = False
    # * [EXPLICAÇÃO] → par no OUTRO formato (R$ quando tipo='percentual',
    #                  e vice-versa) — pedido explícito de auditoria:
    #                  todo percentual mostra o R$ ao lado (11/09). None
    #                  quando o item não tem um par natural (ex: preço
    #                  final não tem "% de quê").
    valor_par: object = None


# Função Objetivo: 1 linha da Visão 2 (De onde vem o lucro) — desmontagem do preço final até
# sobrar o lucro. 'sinal' controla o símbolo e o estilo visual no template: 'inicio' (preço
# final, ponto de partida), 'menos'/'mais' (linhas normais de subtração/soma), 'checkpoint'
# (conferência interna, não soma na conta visual — só confirma que os componentes do FIXO
# batem com o FIXO da Visão 1) e 'final' (lucro, resultado).
@dataclass
class LinhaTeardown:
    label: str
    valor_reais: object
    valor_percentual: object
    sinal: str
    mini_explicacao: str = ''


# Função Objetivo: Resultado da contraprova da Visão 1 — chama calcular_margem() (calculo_margem.py,
# implementação independente) de verdade, com o preço final já persistido. 'disponivel=False'
# quando o produto não tem dados fiscais de entrada sincronizados ou não há faixa de frete pra
# esse preço (calcular_margem já devolve None nesses casos — nunca finge um número).
# 'bate' (14/09): antes o template mostrava "✓ Bate" fixo, sem comparar nada de verdade — agora
# 'bate' vem de uma comparação real (tolerância de R$ 0,05) entre esta margem e a oficial.
@dataclass
class ContraprovaVisao1:
    disponivel: bool
    margem_valor: object = None
    margem_percentual: object = None
    motivo_indisponivel: str = ''
    bate: bool = False
    diferenca_valor: object = None


# Função Objetivo: 1 item da tabela única de auditoria (Item | Como foi obtido | Valor | %).
@dataclass
class LinhaItemAuditoria:
    label: str
    origem: str  # 'produto' | 'nf' | 'saida' | 'config' | 'calculado'
    valor_reais: object = None
    valor_percentual: object = None
    mini_form: str = ''
    # unidade controla como o template formata `valor_reais`:
    # 'reais' (padrão, R$ 0,00) | 'reais_dia' (R$ 0,0000/dia) | 'cm' | 'kg' | 'm3' | 'dias' | 'fator' (número puro, sem sufixo)
    unidade: str = 'reais'
    # Explicação EXPLÍCITA da regra do tributo já pago ('' quando não se aplica a esta linha) —
    # regra_divergente=True quando é o AVISO de que a saída usada não bate com a regra.
    regra_texto: str = ''
    regra_divergente: bool = False


# Função Objetivo: 1 grupo (seção) da tabela única de auditoria — ex: "Comissão", "Taxas".
@dataclass
class GrupoItensAuditoria:
    titulo: str
    linhas: list


# Função Objetivo: Qual nota fiscal foi a BASE de 1 cálculo da grade — mostrada no topo de "Todos
# os itens usados no cálculo" e no PDF, com o botão "Ver NF" (só no modal).
# Explicação em detalhe:
#   estado 'registrada' → a foto do cálculo guardou a nota (numero_nf/chave_acesso/...). É a
#                         nota USADA no cálculo, não necessariamente a atual do produto.
#   estado 'antiga'     → cálculo feito antes de a foto guardar a nota (ou produto sem dado fiscal):
#                         não dá pra afirmar qual NF foi a base — a tela avisa e pede recálculo,
#                         em vez de mostrar a nota atual como se fosse a usada.
#   mudou               → a nota usada no cálculo é diferente da que o produto usa hoje (chegou NF
#                         mais nova depois do cálculo) — a grade está defasada, precisa recalcular.
#   *_espelho_disponivel → o espelho completo (todos os itens) dessa nota está guardado; sem ele o
#                         botão "Ver NF" não aparece (nota mais antiga que a janela sincronizada).
@dataclass
class NotaFiscalBase:
    estado: str
    numero_nf: object = None
    chave_acesso: object = None
    chave_formatada: str = ''
    emissao: object = None
    data_entrada_nota: object = None
    fornecedor: object = None
    empresa_fantasia: object = None
    espelho_disponivel: bool = False
    atual_conhecida: bool = False
    atual_numero_nf: object = None
    atual_chave_acesso: object = None
    atual_espelho_disponivel: bool = False
    mudou: bool = False


# Função Objetivo: ISO (AAAA-MM-DD, como a foto guarda) → date; None se vazio ou inválido.
def _data_de_texto_iso(texto):
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


# Função Objetivo: Monta NotaFiscalBase a partir da foto do cálculo (`e` = DadosEntrada em dict) e
# do produto (pra descobrir a nota que ele usa hoje). Máx. 2 consultas: o retrato atual do
# produto e quais das 2 notas têm espelho completo guardado.
def montar_nota_fiscal_base(e, produto):
    from impostos.funcoes_auxiliares.entrada.espelho_nota_fiscal import formatar_chave_acesso
    from impostos.models import NotaFiscalEntrada

    prova = e.get('prova_fiscal') or {}
    chave_usada = prova.get('chave_acesso')

    try:
        retrato_atual = produto.impostos_entrada
    except ObjectDoesNotExist:
        retrato_atual = None
    chave_atual = retrato_atual.chave_acesso if retrato_atual else None
    numero_atual = retrato_atual.nr_nf if retrato_atual else None

    chaves_a_consultar = [chave for chave in (chave_usada, chave_atual) if chave]
    chaves_com_espelho = set(
        NotaFiscalEntrada.objects.filter(chave_acesso__in=chaves_a_consultar).values_list('chave_acesso', flat=True)
    ) if chaves_a_consultar else set()

    if not chave_usada:
        return NotaFiscalBase(
            estado='antiga',
            atual_conhecida=bool(chave_atual),
            atual_numero_nf=numero_atual,
        )

    return NotaFiscalBase(
        estado='registrada',
        numero_nf=prova.get('numero_nf'),
        chave_acesso=chave_usada,
        chave_formatada=formatar_chave_acesso(chave_usada),
        emissao=_data_de_texto_iso(prova.get('emissao')),
        data_entrada_nota=_data_de_texto_iso(prova.get('data_entrada_nota')),
        fornecedor=prova.get('fornecedor'),
        empresa_fantasia=prova.get('empresa_fantasia'),
        espelho_disponivel=chave_usada in chaves_com_espelho,
        atual_conhecida=bool(chave_atual),
        atual_numero_nf=numero_atual,
        atual_chave_acesso=chave_atual,
        atual_espelho_disponivel=bool(chave_atual) and chave_atual in chaves_com_espelho,
        mudou=bool(chave_atual) and chave_atual != chave_usada,
    )


# Função Objetivo: Lê o Frete Fornecedor (percentual e R$ por unidade) do snapshot gravado da grade.
# * [EXPLICAÇÃO] → Compatibilidade de LEITURA (14/10/2026): grades calculadas ANTES do rename
#                  frete_cif_fob → frete_fornecedor guardam o frete no detalhamento com as chaves
#                  antigas. Sem este fallback o modal dessas linhas mostraria o frete em branco
#                  (e o Passo 1 não fecharia, ou quebraria o teardown) até a grade ser recalculada.
#                  Só LÊ — nada grava com o nome antigo. Remover quando todas as grades (Magazine
#                  e Samvale) tiverem sido recalculadas.
_CHAVE_ANTIGA_FRETE_PERCENTUAL = 'frete_cif_fob_percentual'
_CHAVE_ANTIGA_FRETE_VALOR = 'frete_cif_fob_valor'


def _frete_fornecedor_do_snapshot(e, i):
    percentual = e.get('frete_fornecedor_percentual', e.get(_CHAVE_ANTIGA_FRETE_PERCENTUAL))
    valor = i.get('frete_fornecedor_valor', i.get(_CHAVE_ANTIGA_FRETE_VALOR))
    return percentual, valor


# Função Objetivo: Monta a tabela de valores de entrada (créditos de NF + saída + config) —
# comum a qualquer marketplace.
def montar_tabela_percentuais(e, i, dec, label_comissao='Comissão'):
    frete_fornecedor_percentual, frete_fornecedor_valor = _frete_fornecedor_do_snapshot(e, i)
    return [
        LinhaPercentualValor('IPI (crédito de entrada)', None, dec(i.get('ipi_valor')), origem='nf'),
        LinhaPercentualValor('Frete Fornecedor', dec(frete_fornecedor_percentual), dec(frete_fornecedor_valor), origem='produto'),
        LinhaPercentualValor('Crédito ICMS (entrada)', None, dec(i.get('credito_icms_entrada')), origem='nf'),
        LinhaPercentualValor('Crédito PIS (entrada)', None, dec(i.get('credito_pis')), origem='nf'),
        LinhaPercentualValor('Crédito COFINS (entrada)', None, dec(i.get('credito_cofins')), origem='nf'),
        LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor')), origem='saida'),
        LinhaPercentualValor(label_comissao, dec(e.get('comissao_percentual')), dec(i.get('comissao_valor')), origem='config'),
        LinhaPercentualValor('Margem-alvo', dec(e.get('margem_alvo_percentual')), dec(i.get('margem_alvo_valor')), origem='config'),
    ]


# Função Objetivo: Monta o bloco de PIS/COFINS (2 usos, bases diferentes) — usado pelos
# marketplaces que ainda não migraram pro padrão de campos separados do ML. Nota: 'percentual'
# e 'taxa_saida' já vinham sempre em branco antes da Camada 3 também (pis_cofins_percentual/
# pis_cofins_valor não existem em NENHUMA das 6 fórmulas — mesma causa raiz do Duble antigo
# quebrado); só 'credito_entrada' é dado real. Restaurado tal como estava — corrigir isso de
# verdade é migrar os outros 5 marketplaces pro padrão do ML, fora de escopo por ora.
def montar_pis_cofins(e, i, dec):
    return BlocoPisCofins(
        percentual=dec(e.get('pis_cofins_percentual')),
        credito_entrada=dec(i.get('credito_pis')),
        taxa_saida=dec(i.get('pis_cofins_valor')),
    )


# Função Objetivo: Monta a lista de valores soltos (custo, fator de coleta...) — comum.
def montar_valores_soltos(e, dec):
    return [
        LinhaValorUnico('Custo do produto', dec(e.get('custo')), origem='produto'),
        LinhaValorUnico('Custo com bonificação', dec(e.get('custo_com_boni')), origem='produto'),
        LinhaValorUnico('Fator de coleta', dec(e.get('fator_coleta')), origem='config'),
        LinhaValorUnico('Período de armazenagem (dias)', dec(e.get('periodo_armazenagem')), origem='config'),
    ]


# Função Objetivo: Monta a dimensão usada — comum, só a origem_label varia por chamador.
def montar_dimensao(e, dec, origem_label):
    return DimensaoUsada(
        origem_label=origem_label,
        altura=dec(e.get('altura')), largura=dec(e.get('largura')),
        comprimento=dec(e.get('comprimento')), peso=dec(e.get('peso')),
        peso_fisico=dec(e.get('peso_fisico')), peso_cubico=dec(e.get('peso_cubico')),
    )


# Função Objetivo: Lê 1 imposto de dentro de DadosEntrada.prova_fiscal — (valor, base, alíquota).
# Explicação em detalhe: None nos 3 quando prova_fiscal não existe (linha calculada antes da
# Camada 2) ou quando o imposto específico não existe (só acontece com icms_st, quando o
# produto não é ST — nunca finge um ICMS ST que não existe).
def _prova_imposto(e, nome):
    prova = e.get('prova_fiscal') or {}
    imposto = prova.get(nome)
    if not imposto:
        return None, None, None
    return imposto.get('valor'), imposto.get('base_calculo'), imposto.get('aliquota')


def _quantidade_nota(e):
    prova = e.get('prova_fiscal') or {}
    return prova.get('quantidade_nota')


# Função Objetivo: Formata número no padrão brasileiro (milhar com ponto, decimal com vírgula) —
# os textos da regra do tributo já pago nascem em Python, então precisam sair no mesmo formato que
# o floatformat dos templates (vírgula), nunca "2.47".
def _numero_br(valor, casas=2):
    texto = f'{valor:,.{casas}f}'
    return texto.replace(',', 'X').replace('.', ',').replace('X', '.')


# Função Objetivo: Quantidade da nota sem zeros à direita (15.000 → "15", 2.5 → "2,5").
def _quantidade_br(valor):
    return format(valor.normalize(), 'f').replace('.', ',')


# Função Objetivo: Monta a RegraPisCofinsAplicada de 1 imposto (chave 'pis' ou 'cofins') a partir
# da foto do cálculo (`e` = DadosEntrada em dict). None quando a regra NÃO foi o motivo do crédito
# zero — inclusive em linha calculada antes dos campos cst_xml/zerado_pela_regra existirem (nunca
# inventa uma explicação que a foto não registrou).
def montar_regra_pis_cofins_aplicada(e, dec, chave, rotulo):
    prova = e.get('prova_fiscal') or {}
    imposto = prova.get(chave) or {}
    if not imposto.get('zerado_pela_regra'):
        return None

    cst_xml = imposto.get('cst_xml')
    valor_nota = dec(imposto.get('valor'))
    aliquota_xml = dec(imposto.get('aliquota'))
    quantidade_nota = dec(prova.get('quantidade_nota'))
    valor_por_unidade = valor_nota / quantidade_nota if valor_nota is not None and quantidade_nota else None

    if valor_por_unidade is not None:
        veio_no_xml = (
            f'R$ {_numero_br(valor_por_unidade)} por unidade '
            f'(R$ {_numero_br(valor_nota)} na nota ÷ {_quantidade_br(quantidade_nota)} unid.)'
        )
    elif valor_nota is not None:
        veio_no_xml = f'R$ {_numero_br(valor_nota)} na nota (sem quantidade registrada pra dividir por unidade)'
    else:
        veio_no_xml = 'um valor que não ficou registrado nesta linha'

    texto_credito = (
        f'Veio no XML {veio_no_xml}, mas foi considerado R$ 0,00 seguindo a regra '
        f'(CST XML {cst_xml}: tributo já pago pelo fornecedor, sem crédito).'
    )

    partes_do_xml = [f'CST {cst_xml}']
    if aliquota_xml is not None:
        partes_do_xml.append(f'alíquota {_numero_br(aliquota_xml)}%')
    if valor_por_unidade is not None:
        partes_do_xml.append(f'{rotulo} de R$ {_numero_br(valor_por_unidade)} por unidade')

    percentual_saida_usado = dec(e.get(f'{chave}_saida_percentual'))
    saida_divergente = saida_diverge_da_regra(cst_xml, percentual_saida_usado)

    if saida_divergente:
        texto_saida = (
            f'A regra manda 0,00% (CST XML {cst_xml}: tributo já pago pelo fornecedor), mas esta grade usou '
            f'{_numero_br(percentual_saida_usado)}% de {rotulo} de saída — o que estava no cadastro do produto '
            f'quando ela foi calculada. Rode preencher_impostos_saida e recalcule a grade.'
        )
    else:
        texto_saida = (
            f'Veio no XML (entrada): {", ".join(partes_do_xml)} — mas foi considerado 0,00% seguindo a regra '
            f'(tributo já pago pelo fornecedor: nada a recolher na saída).'
        )

    return RegraPisCofinsAplicada(
        cst_xml=cst_xml, texto_regra=TEXTO_REGRA_TRIBUTO_JA_PAGO,
        texto_credito=texto_credito, texto_saida=texto_saida, saida_divergente=saida_divergente,
    )


# Função Objetivo: Monta os passos 1-6 (custo final até denominador) — IDÊNTICOS entre
# marketplaces. Passos 7/8 (frete + preço exato) ficam por conta de quem chama, já que
# o significado da faixa (preço vs peso) e a existência de rebate diferem por canal.
def montar_passos_1_a_6(e, i, dec, label_comissao='Comissão'):
    qtd_nota = dec(_quantidade_nota(e))

    ipi_valor_nota, _, _ = _prova_imposto(e, 'ipi')
    _, frete_fornecedor_valor = _frete_fornecedor_do_snapshot(e, i)
    passo_1 = PassoCustoFinal(
        custo_com_boni=dec(e.get('custo_com_boni')), ipi_valor=dec(i.get('ipi_valor')),
        frete_fornecedor_valor=dec(frete_fornecedor_valor),
        resultado=dec(i.get('custo_final')),
        ipi_valor_nota=dec(ipi_valor_nota), quantidade_nota=qtd_nota,
    )
    passo_2 = PassoColeta(
        metro_cubico=dec(i.get('metro_cubico')), fator_coleta=dec(e.get('fator_coleta')),
        resultado=dec(i.get('coleta')),
    )
    passo_3 = PassoArmazenagem(
        origem=i.get('armazenagem_origem'), periodo_dias=dec(e.get('periodo_armazenagem')),
        resultado=dec(i.get('armazenagem')), valor_diario=dec(i.get('armazenagem_valor_diario')),
    )

    icms_valor_nota, icms_base, icms_aliquota = _prova_imposto(e, 'icms')
    pis_valor_nota, _, _ = _prova_imposto(e, 'pis')
    cofins_valor_nota, _, _ = _prova_imposto(e, 'cofins')
    tem_icms_st = bool((e.get('prova_fiscal') or {}).get('tem_icms_st', False))

    # Regra do tributo já pago (CST 02/04/06 no XML) — explícita no crédito (Passo 4) e na saída
    # (Passo 5). None quando não se aplica (ou linha calculada antes dos campos existirem).
    regra_pis = montar_regra_pis_cofins_aplicada(e, dec, 'pis', 'PIS')
    regra_cofins = montar_regra_pis_cofins_aplicada(e, dec, 'cofins', 'COFINS')
    texto_regra = TEXTO_REGRA_TRIBUTO_JA_PAGO if (regra_pis or regra_cofins) else ''

    passo_4 = PassoFixo(
        coleta=dec(i.get('coleta')), armazenagem=dec(i.get('armazenagem')),
        custo_final=dec(i.get('custo_final')), credito_icms=dec(i.get('credito_icms_entrada')),
        credito_pis=dec(i.get('credito_pis')), credito_cofins=dec(i.get('credito_cofins')),
        resultado=dec(i.get('fixo')),
        icms_valor_nota=dec(icms_valor_nota), icms_base_calculo=dec(icms_base), icms_aliquota=dec(icms_aliquota),
        tem_icms_st=tem_icms_st, pis_valor_nota=dec(pis_valor_nota), cofins_valor_nota=dec(cofins_valor_nota),
        quantidade_nota=qtd_nota,
        regra_pis=regra_pis, regra_cofins=regra_cofins, texto_regra=texto_regra,
    )

    passo_5 = PassoTaxa(
        itens=[
            LinhaPercentualValor(label_comissao, dec(e.get('comissao_percentual')), dec(i.get('comissao_valor')), origem='config'),
            LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor')), origem='saida'),
            LinhaPercentualValor('PIS saída', dec(e.get('pis_saida_percentual')), dec(i.get('pis_saida_valor')), origem='saida', regra=regra_pis),
            LinhaPercentualValor('COFINS saída', dec(e.get('cofins_saida_percentual')), dec(i.get('cofins_saida_valor')), origem='saida', regra=regra_cofins),
        ],
        resultado=dec(i.get('taxa_percentual')),
        resultado_valor=dec(i.get('taxa_valor')),
        texto_regra=texto_regra,
    )
    passo_6 = PassoDenominador(
        taxa_percentual=dec(i.get('taxa_percentual')), margem_alvo_percentual=dec(e.get('margem_alvo_percentual')),
        resultado=dec(i.get('denominador')),
        taxa_valor=dec(i.get('taxa_valor')), margem_alvo_valor=dec(i.get('margem_alvo_valor')),
    )
    return passo_1, passo_2, passo_3, passo_4, passo_5, passo_6


# Função Objetivo: Monta o bloco de saída (5 linhas) — comum a qualquer marketplace.
def montar_saida(i, s, dec):
    return [
        LinhaSaida('Preço exato', dec(i.get('preco_exato_antes_arredondar')), 'reais'),
        LinhaSaida('Margem exata', dec(s.get('margem_exata_percentual')), 'percentual', valor_par=dec(s.get('margem_exata_valor'))),
        LinhaSaida('Preço final (arredondado pra ,90)', dec(s.get('preco_final')), 'reais', destaque=True),
        LinhaSaida('Margem final', dec(s.get('margem_percentual_obtida')), 'percentual', destaque=True, valor_par=dec(s.get('margem_valor'))),
        LinhaSaida('Custo de frete final', dec(s.get('frete_usado')), 'reais'),
    ]


# Função Objetivo: Monta a tabela única de auditoria (Item | Como foi obtido | R$ | %),
# TODOS os itens que a fórmula usa, agrupados por tipo em ordem lógica — pra bater linha a
# linha com uma planilha de referência que usa cada valor solto. Só ML por enquanto (usa
# faixa_frete_peso_min/max, que é conceito específico do ML — Magalu usa faixa por peso).
def montar_tabela_itens_agrupada(e, i, s, dec):
    qtd_nota = dec(_quantidade_nota(e))
    # * [CORREÇÃO] → _prova_imposto devolve os valores CRUS do JSON
    #                (string, não Decimal) — precisa passar por dec()
    #                aqui, igual montar_passos_1_a_6 já fazia no ponto
    #                de uso. Sem isso, o f'{valor:.2f}' de mini() quebra
    #                com ValueError pra qualquer produto que tenha prova
    #                fiscal com alíquota (ex: crédito ICMS normal, não-ST).
    ipi_valor_nota_raw, _, _ = _prova_imposto(e, 'ipi')
    icms_valor_nota_raw, _, icms_aliquota_raw = _prova_imposto(e, 'icms')
    pis_valor_nota_raw, _, pis_aliquota_raw = _prova_imposto(e, 'pis')
    cofins_valor_nota_raw, _, cofins_aliquota_raw = _prova_imposto(e, 'cofins')

    ipi_valor_nota = dec(ipi_valor_nota_raw)
    icms_valor_nota, icms_aliquota = dec(icms_valor_nota_raw), dec(icms_aliquota_raw)
    pis_valor_nota, pis_aliquota = dec(pis_valor_nota_raw), dec(pis_aliquota_raw)
    cofins_valor_nota, cofins_aliquota = dec(cofins_valor_nota_raw), dec(cofins_aliquota_raw)

    frete_fornecedor_percentual, frete_fornecedor_valor = _frete_fornecedor_do_snapshot(e, i)

    def mini(valor_nota, aliquota):
        if valor_nota is None or qtd_nota is None:
            return ''
        if aliquota is not None:
            return f'R$ {valor_nota:.2f} nota × {aliquota:.2f}% ÷ {qtd_nota:.0f} unid.'
        return f'R$ {valor_nota:.2f} nota ÷ {qtd_nota:.0f} unid.'

    # * [EXPLICAÇÃO] → O grupo 3 é o único cujos valores vêm da nota fiscal — o título
    #                  carrega o número da NF pra ficar 100% explícito de qual nota são.
    #                  Cálculo antigo (sem NF registrada) mantém o título de sempre.
    # Regra do tributo já pago explícita nas 4 linhas de PIS/COFINS (crédito e saída) — ver
    # montar_regra_pis_cofins_aplicada. None = a regra não se aplica a esta linha.
    regra_pis = montar_regra_pis_cofins_aplicada(e, dec, 'pis', 'PIS')
    regra_cofins = montar_regra_pis_cofins_aplicada(e, dec, 'cofins', 'COFINS')

    numero_nf_usada = (e.get('prova_fiscal') or {}).get('numero_nf')
    titulo_creditos = (
        f'3. Créditos fiscais de entrada — NF {numero_nf_usada}' if numero_nf_usada
        else '3. Créditos fiscais de entrada (NF)'
    )

    return [
        GrupoItensAuditoria('1. Produto / Custo base', [
            LinhaItemAuditoria('Custo do produto', 'produto', valor_reais=dec(e.get('custo'))),
            LinhaItemAuditoria('Custo com bonificação', 'produto', valor_reais=dec(e.get('custo_com_boni'))),
        ]),
        GrupoItensAuditoria('2. Dimensões e peso', [
            LinhaItemAuditoria('Altura', 'produto', valor_reais=dec(e.get('altura')), unidade='cm'),
            LinhaItemAuditoria('Largura', 'produto', valor_reais=dec(e.get('largura')), unidade='cm'),
            LinhaItemAuditoria('Comprimento', 'produto', valor_reais=dec(e.get('comprimento')), unidade='cm'),
            LinhaItemAuditoria('Peso físico', 'produto', valor_reais=dec(e.get('peso_fisico')), unidade='kg'),
            LinhaItemAuditoria('Peso cúbico', 'calculado', valor_reais=dec(e.get('peso_cubico')), unidade='kg'),
            LinhaItemAuditoria('Peso usado (maior entre físico e cúbico)', 'calculado', valor_reais=dec(e.get('peso')), unidade='kg'),
        ]),
        GrupoItensAuditoria(titulo_creditos, [
            LinhaItemAuditoria('IPI', 'nf', valor_reais=dec(i.get('ipi_valor')), mini_form=mini(ipi_valor_nota, None)),
            LinhaItemAuditoria('Crédito ICMS entrada', 'nf', valor_reais=dec(i.get('credito_icms_entrada')), valor_percentual=dec(icms_aliquota), mini_form=mini(icms_valor_nota, icms_aliquota)),
            LinhaItemAuditoria(
                'Crédito PIS entrada', 'nf', valor_reais=dec(i.get('credito_pis')), valor_percentual=dec(pis_aliquota),
                mini_form=mini(pis_valor_nota, pis_aliquota), regra_texto=regra_pis.texto_credito if regra_pis else '',
            ),
            LinhaItemAuditoria(
                'Crédito COFINS entrada', 'nf', valor_reais=dec(i.get('credito_cofins')), valor_percentual=dec(cofins_aliquota),
                mini_form=mini(cofins_valor_nota, cofins_aliquota), regra_texto=regra_cofins.texto_credito if regra_cofins else '',
            ),
        ]),
        GrupoItensAuditoria('4. Frete do Fornecedor (entrada)', [
            LinhaItemAuditoria('Frete Fornecedor', 'produto', valor_reais=dec(frete_fornecedor_valor), valor_percentual=dec(frete_fornecedor_percentual)),
        ]),
        GrupoItensAuditoria('5. Coleta e armazenagem', [
            LinhaItemAuditoria('Metro cúbico', 'calculado', valor_reais=dec(i.get('metro_cubico')), unidade='m3'),
            LinhaItemAuditoria('Fator de coleta', 'config', valor_reais=dec(e.get('fator_coleta')), unidade='fator'),
            LinhaItemAuditoria('Coleta', 'calculado', valor_reais=dec(i.get('coleta'))),
            LinhaItemAuditoria('Faixa de armazenagem (valor/dia)', 'config', valor_reais=dec(i.get('armazenagem_valor_diario')), unidade='reais_dia'),
            LinhaItemAuditoria('Período de armazenagem', 'config', valor_reais=dec(e.get('periodo_armazenagem')), unidade='dias'),
            LinhaItemAuditoria('Armazenagem', 'calculado', valor_reais=dec(i.get('armazenagem'))),
        ]),
        GrupoItensAuditoria('6. Comissão', [
            LinhaItemAuditoria('Comissão', 'config', valor_reais=dec(i.get('comissao_valor')), valor_percentual=dec(e.get('comissao_percentual'))),
        ]),
        GrupoItensAuditoria('7. Impostos de saída', [
            LinhaItemAuditoria('ICMS saída', 'saida', valor_reais=dec(i.get('icms_saida_valor')), valor_percentual=dec(e.get('icms_saida_percentual'))),
            LinhaItemAuditoria(
                'PIS saída', 'saida', valor_reais=dec(i.get('pis_saida_valor')), valor_percentual=dec(e.get('pis_saida_percentual')),
                regra_texto=regra_pis.texto_saida if regra_pis else '', regra_divergente=regra_pis.saida_divergente if regra_pis else False,
            ),
            LinhaItemAuditoria(
                'COFINS saída', 'saida', valor_reais=dec(i.get('cofins_saida_valor')), valor_percentual=dec(e.get('cofins_saida_percentual')),
                regra_texto=regra_cofins.texto_saida if regra_cofins else '', regra_divergente=regra_cofins.saida_divergente if regra_cofins else False,
            ),
        ]),
        GrupoItensAuditoria('8. Taxas (soma)', [
            LinhaItemAuditoria('Taxa total', 'calculado', valor_reais=dec(i.get('taxa_valor')), valor_percentual=dec(i.get('taxa_percentual'))),
            LinhaItemAuditoria('Margem-alvo', 'config', valor_reais=dec(i.get('margem_alvo_valor')), valor_percentual=dec(e.get('margem_alvo_percentual'))),
            LinhaItemAuditoria('Denominador', 'calculado', mini_form='1 − taxa − margem-alvo (fator, sem R$/% próprio)'),
        ]),
        GrupoItensAuditoria('9. Frete de saída (Mercado Livre)', [
            LinhaItemAuditoria('Peso usado pra faixa', 'calculado', valor_reais=dec(e.get('peso')), unidade='kg'),
            LinhaItemAuditoria('Frete final usado (faixa FreteML)', 'config', valor_reais=dec(s.get('frete_usado'))),
        ]),
        GrupoItensAuditoria('10. Resultado', [
            LinhaItemAuditoria('Custo final', 'calculado', valor_reais=dec(i.get('custo_final'))),
            LinhaItemAuditoria('FIXO', 'calculado', valor_reais=dec(i.get('fixo'))),
            LinhaItemAuditoria('Rebate de promoção', 'calculado', valor_reais=dec(i.get('rebate_valor')), valor_percentual=dec(e.get('rebate_percentual'))),
            LinhaItemAuditoria('Preço exato (antes de arredondar)', 'calculado', valor_reais=dec(i.get('preco_exato_antes_arredondar'))),
            LinhaItemAuditoria('Preço final (arredondado ,90)', 'calculado', valor_reais=dec(s.get('preco_final'))),
            LinhaItemAuditoria('Margem exata (antes de arredondar)', 'calculado', valor_reais=dec(s.get('margem_exata_valor')), valor_percentual=dec(s.get('margem_exata_percentual'))),
            LinhaItemAuditoria('Margem final', 'calculado', valor_reais=dec(s.get('margem_valor')), valor_percentual=dec(s.get('margem_percentual_obtida'))),
        ]),
    ]


# Função Objetivo: Monta a lista de alertas do veredito (topo da tela) — comum a qualquer
# marketplace, já que FIXO/custo/dimensão/margem são conceitos universais entre canais.
# Explicação em detalhe: cada alerta carrega 'alvo' (número do passo ou 'produto') pro
# clique da lista rolar e expandir o passo certo. Os FLAGS visuais em cada passo (borda
# vermelha) são calculados direto no template por comparação simples — isso aqui só
# gera o TEXTO da lista do topo.
def montar_alertas(fixo, custo, custo_com_boni, altura, largura, comprimento, margem_alvo, margem_obtida):
    alertas = []

    sem_custo = not custo and not custo_com_boni
    sem_dimensao = not altura and not largura and not comprimento
    if sem_custo or sem_dimensao:
        if sem_custo and sem_dimensao:
            texto = 'Produto sem custo e sem dimensões cadastrados'
        elif sem_custo:
            texto = 'Produto sem custo cadastrado (custo e custo com bonificação zerados)'
        else:
            texto = 'Produto sem dimensões cadastradas (altura/largura/comprimento zerados)'
        alertas.append({'texto': texto, 'alvo': 'produto'})

    if fixo is not None and fixo < 0:
        alertas.append({
            'texto': f'Crédito fiscal de entrada maior que o custo final — FIXO negativo (R$ {fixo:.2f})',
            'alvo': 4,
        })

    if margem_alvo is not None and margem_obtida is not None and margem_obtida < margem_alvo:
        alertas.append({
            'texto': f'Margem obtida ({margem_obtida:.2f}%) abaixo da margem-alvo ({margem_alvo:.2f}%)',
            'alvo': 8,
        })

    return alertas


# Função Objetivo: Prefixa o texto da regra do tributo já pago com o selo em texto, pras linhas
# da Visão 2 (que não têm selo visual, só a descrição pequena) — nunca deixa o zero sem explicação.
# divergente=True quando o texto é o AVISO de que a saída usada não bate com a regra.
def _mini_explicacao_regra(texto, divergente=False):
    return f'{"DIVERGE DA REGRA" if divergente else "ZERADO PELA REGRA"} — {texto}'


# Função Objetivo: Monta a Visão 2 (De onde vem o lucro) — mesmo preço final e mesmos dados
# da Visão 1, só que de trás pra frente: parte do preço de venda e vai subtraindo cada custo,
# 1 de cada vez (inclusive os que valem R$ 0,00), até sobrar só o lucro. Pedido explícito
# (14/09): nada resumido em bloco — cada componente do FIXO também vira linha própria aqui,
# na mesma ordem das camadas 1/2/3 da Visão 1 (custo final → coleta → armazenagem). Não
# recalcula nada — só reapresenta de trás pra frente os mesmos passos 1-8 já calculados.
def montar_visao_2_teardown(passo_1, passo_2, passo_3, passo_4, passo_5, passo_8, preco_final, margem_valor, margem_percentual, dec):
    def pct(valor):
        if valor is None or not preco_final:
            return None
        return (valor / preco_final) * 100

    linhas = [
        LinhaTeardown('Preço final de venda', preco_final, dec('100'), 'inicio'),
    ]

    for item in passo_5.itens:
        linhas.append(LinhaTeardown(
            item.label, item.valor, item.percentual, 'menos',
            _mini_explicacao_regra(item.regra.texto_saida, item.regra.saida_divergente) if item.regra else '',
        ))

    linhas.append(LinhaTeardown('Frete', passo_8.frete, pct(passo_8.frete), 'menos'))

    linhas.append(LinhaTeardown('Custo do produto', passo_1.custo_com_boni, pct(passo_1.custo_com_boni), 'menos'))
    linhas.append(LinhaTeardown('IPI (crédito da nota de entrada)', passo_1.ipi_valor, pct(passo_1.ipi_valor), 'menos'))
    linhas.append(LinhaTeardown('Frete Fornecedor', passo_1.frete_fornecedor_valor, pct(passo_1.frete_fornecedor_valor), 'menos'))
    linhas.append(LinhaTeardown('Coleta', passo_2.resultado, pct(passo_2.resultado), 'menos'))
    linhas.append(LinhaTeardown('Armazenagem', passo_3.resultado, pct(passo_3.resultado), 'menos'))

    linhas.append(LinhaTeardown(
        'Crédito de ICMS (nota de entrada)', passo_4.credito_icms, pct(passo_4.credito_icms), 'mais',
        'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))
    linhas.append(LinhaTeardown(
        'Crédito de PIS (nota de entrada)', passo_4.credito_pis, pct(passo_4.credito_pis), 'mais',
        _mini_explicacao_regra(passo_4.regra_pis.texto_credito) if passo_4.regra_pis
        else 'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))
    linhas.append(LinhaTeardown(
        'Crédito de COFINS (nota de entrada)', passo_4.credito_cofins, pct(passo_4.credito_cofins), 'mais',
        _mini_explicacao_regra(passo_4.regra_cofins.texto_credito) if passo_4.regra_cofins
        else 'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))

    linhas.append(LinhaTeardown(
        'Conferência: soma dos 8 itens acima', passo_4.resultado, pct(passo_4.resultado), 'checkpoint',
        'Deve bater com o FIXO da Visão 1 (Passo 4).',
    ))

    linhas.append(LinhaTeardown(
        'Rebate', passo_8.rebate, pct(passo_8.rebate), 'mais',
        'Desconto de promoção que o ML devolve — soma de volta ao preço.',
    ))

    linhas.append(LinhaTeardown('Lucro (margem valor)', margem_valor, margem_percentual, 'final'))

    return linhas