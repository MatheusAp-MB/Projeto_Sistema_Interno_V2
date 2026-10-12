# gestao_ruptura/funcoes_auxiliares/ruptura_pagina.py
#
# Função Objetivo: Monta tudo o que a tela "Previsão de Ruptura de estoque" mostra, a partir da query string.
#   - SEM sku: a LISTA por urgência, por Produto (SKU), Anúncio (MLB) ou Código ML (ruptura_lista.py; gran, q, nivel, ord, por, pag).
#   - COM sku: o DETALHE de um item, com a curva, os cartões e o diagnóstico: o próprio SKU, ou um MLB / Código ML dele (gran=mlb|codigo + item). Parâmetros: sku, gran, item,
#     visao (full | fora | produto), estoque (digitado, opcional).
#   - Em qualquer um: dias (o ritmo dos últimos N dias), lead (lead time em dias; sem digitar vale o padrão provisório de ruptura_calculo.LEAD_TIME_PADRAO), margem (margem de segurança, em % do
#     lead time; padrão 100), cobre (quantos dias cada remessa cobre; sem digitar vale o lead time, padrão provisório) e caminho (=1: a opção "Considerar as unidades a caminho", que soma o
#     "a caminho" ao estoque lido do Full; desmarcada por padrão). Todos são lidos em ruptura_parametros.py.
# LÊ SÓ DO BANCO (as vendas já coletadas pela tela de Vendas e a última consulta salva do estoque do Full) e NUNCA chama sozinha a API do Mercado Livre nem a do ERP (o ML só é chamado por CLIQUE, no botão "Consultar no Mercado Livre" da tabela de estoque; ver views_ruptura.view_ruptura_consultar). Nada do que a pessoa
# digita é guardado: fica só no endereço da página.
#
# REGRAS DO MATHEUS que moram aqui:
#   - O ritmo vem das vendas reais, com as MESMAS regras da tela de Vendas (vendas_ml.unidades_por_dia): só dias completos, venda cancelada não conta, "ausente não é zero".
#     Quem decide No Full / Fora do Full é a regra única de origem (vendas_ml.classificar_origem).
#   - O estoque do Full vem da última consulta salva de cada Código ML (ruptura_estoque.py: estoque considerado = disponível + em transferência + em processo interno; regra provisória).
#     Fora do Full a API de estoque ainda precisa ser corrigida: lá o estoque continua DIGITADO. Em qualquer visão, o que for digitado vale no lugar do lido (para simular).
#   - O "a caminho" só entra no estoque quando a opção "Considerar as unidades a caminho" está marcada (ruptura_estoque.estoque_para_cobertura): como se já estivesse no Full hoje. Estoque
#     DIGITADO nunca recebe o a caminho: o que a pessoa digitou vale como está.
#   - O ritmo "dos últimos N dias" segue a regra do período da tela de Vendas: N dias completos + o dia de hoje (parcial, que fica fora da média).
#   - "Enviar até" tem MARGEM DE SEGURANÇA: ruptura − lead time − margem (padrão: margem = 100% do lead time). O último dia possível (ruptura − lead time) continua aparecendo no detalhe.
#     A sugestão do SISTEMA de "quanto enviar" é a que deixa, na chegada, a margem + os dias que cada remessa cobre (ruptura_calculo.sugestao_do_sistema).
#   - DUAS REFERÊNCIAS (decisão do Matheus, 12/10/2026): a URGÊNCIA e a QUANTIDADE a enviar podem vir do MERCADO LIVRE (lidas da consulta de reposição salva: ruptura_estoque.resumir_ml) ou do SISTEMA (a regra
#     da tela); a quantidade também pode ser DIGITADA ("Minha quantidade"). A escolhida manda no gráfico (linha verde "Com o envio") e nos cartões; a outra aparece pequena ao lado. Quando o ML não tem número,
#     a tela diz "sem número do ML": nunca vira urgência ou quantidade zero.
#
# * [EXPLICAÇÃO] → Cada peça mora no seu arquivo: ruptura_calculo.py (contas), ruptura_estoque.py (estoque do Full), ruptura_grafico.py (curva), ruptura_lista.py (lista) e ruptura_texto.py
#                  (formatadores). Este só LIGA tudo e escreve os textos do detalhe.
# * [EXPLICAÇÃO] → Os textos já saem prontos para o template (strings), e a tela é rígida na vertical: cada cartão tem 1 linha de valor e 1 de apoio (o resto vai no "title" do cartão), então
#                  nada muda de altura conforme o texto.
# * [EXPLICAÇÃO] → O ritmo do DETALHE usa a cobertura do PRÓPRIO produto (como a tela de Vendas do produto) e o da LISTA usa a cobertura da conta toda (como a lista de Vendas). Se um produto foi
#                  atualizado sozinho além do que a conta toda coletou, os dois podem diferir um pouco: é a mesma diferença que já existe entre a lista e o calendário de Vendas.

from datetime import datetime, timedelta
from math import ceil, floor
from zoneinfo import ZoneInfo

from django.urls import reverse

from gestao_full.funcoes_auxiliares.full_estoque_ml import a_caminho_dos_codigos, estoque_do_erp, estoque_full_dos_codigos, ml_dos_codigos
from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares import ruptura_estoque as full
from gestao_ruptura.funcoes_auxiliares.ruptura_grafico import montar_grafico
from gestao_ruptura.funcoes_auxiliares.ruptura_lista import montar_lista
from gestao_ruptura.funcoes_auxiliares.ruptura_parametros import ler_comuns, para_url
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import (
    aviso_do_deposito, data as _data, data_do_ml, inteiro as _inteiro, pct as _pct, plural as _plural, porque_da_urgencia_do_sistema, quantidade_do_ml, un_dia as _un_dia,
)
from gestao_vendas.funcoes_auxiliares.vendas_ml import numero, unidades_por_dia, url_da_tela

FUSO = ZoneInfo('America/Sao_Paulo')
ATALHOS_DE_DIAS = (7, 15, 30, 60, 90, 120)   # + "1 ano" (o máximo do Mercado Livre), montado em montar_pagina
VISOES = (
    ('full', 'No Full', 'Só as vendas cujo estoque saiu de um centro do Full. O estoque é o do Full (lido da última consulta salva, ou digitado).'),
    ('fora', 'Fora do Full', 'Só as vendas do estoque próprio (coleta, agência, Flex). O estoque é o do seu estoque: digite o valor (a API de estoque ainda será corrigida).'),
    ('produto', 'Produto (tudo)', 'Todas as vendas, Full e fora do Full. O estoque é a soma dos dois: digite o valor.'),
)
ROTULO_DO_ESTOQUE = {'full': 'Estoque no Full', 'fora': 'Estoque fora do Full', 'produto': 'Estoque total'}
GRANULARIDADES_DO_DETALHE = ('sku', 'mlb', 'codigo')
# a cor do cartão de urgência segue o selo do Mercado Livre (vermelho = urgente ... verde = sem urgência); "Excedente" (sobra) fica azul, a cor de informação do diagnóstico
TOM_DA_URGENCIA = {'URGENT': 'vermelho', 'THIS_WEEK': 'laranja', 'NEXT_WEEK': 'laranja', 'IN_TWO_WEEKS': 'azul', 'NO_URGENCY': 'verde', 'EXCEDENT': 'azul'}
FONTE_DA_QUANTIDADE = {'sistema': 'sugestão do Sistema', 'ml': 'sugestão do Mercado Livre', 'manual': 'quantidade digitada por você'}
CHAMADAS_POR_CODIGO = 3   # quase sempre 3 chamadas ao Mercado Livre por Código ML: estoque, reposição e depósito/Flex (o mesmo número da tela "Estoque no Full")
ROTULO_DA_RECOMENDACAO = {'REPLENISH': 'repor', 'NO_REPLENISHMENT': 'não repor', 'NO_REPLENISHMENT_BY_RESTRICTION': 'não repor, por restrição'}   # as mesmas palavras da tela de Planejamento


def _em_dias(n):
    return 'ainda hoje' if n == 0 else f'em {_plural(n, "dia", "dias")}'



# ==================================================== cartões ====================================================

# Função Objetivo: Um cartão "Ruptura · ritmo de N dias": a data em que o estoque acaba nesse ritmo, em quantos dias, o ritmo e o nível. Sem estoque ou sem ritmo, o cartão
# fica com "—" e diz o que falta (mesmo tamanho: a tela não muda de altura).
def _cartao_de_ruptura(rotulo, explicacao, ritmo, estoque, lead, folga, hoje, destaque=False):
    cartao = {'rotulo': rotulo, 'destaque': destaque, 'nivel': None, 'nivel_rotulo': '', 'nivel_titulo': '', 'valor': '—', 'sub': ''}
    media = ritmo['media']
    if media is None:
        cartao['sub'] = 'sem dias completos coletados'
    elif estoque is None:
        cartao['sub'] = f'{_un_dia(media)} un/dia · informe o estoque'
    else:
        projecao = calc.projetar(estoque, media, hoje)
        nivel = calc.nivel_do_estoque(projecao, lead, folga)
        ritmo_texto = f'{_un_dia(media)} un/dia'
        if projecao['situacao'] == 'zerado':
            cartao['valor'], cartao['sub'] = 'Em ruptura', f'estoque zerado · {ritmo_texto}'
        elif projecao['situacao'] == 'sem_vendas':
            cartao['valor'], cartao['sub'] = 'Sem previsão', 'nenhuma venda nos dias completos'
        elif projecao['situacao'] == 'longe':
            cartao['valor'], cartao['sub'] = 'Sem previsão', f'dura mais de {numero(calc.DIAS_MAXIMOS_DA_PROJECAO)} dias · {ritmo_texto}'
        else:
            cartao['valor'], cartao['sub'] = _data(projecao['data']), f'{_em_dias(projecao["dias"])} · {ritmo_texto}'
        if nivel:
            cartao['nivel'], cartao['nivel_rotulo'], cartao['nivel_titulo'] = nivel, calc.NIVEIS_CURTOS[nivel], calc.NIVEIS[nivel]
    cartao['dica'] = f'{explicacao} {cartao["sub"]}.'
    return cartao


# ==================================================== diagnóstico ====================================================

# * [EXPLICAÇÃO] → O diagnóstico é uma lista de CARTÕES EXPANSÍVEIS (pedido do Matheus, 12/10/2026: "muito texto; algo que mostre de forma chamativa o que o usuário precisa ver rápido, e se quiser
#                  ele abre e vê os detalhes"). Cada cartão tem o RÓTULO ("Data de ruptura"), o VALOR em destaque ("13/12/2026"), um APOIO curto ("em 62 dias") e o DETALHE (a frase explicativa),
#                  que só aparece ao abrir. A COR (`tom`) segue o mesmo significado do gráfico: vermelho = ruptura / prazo vencido / estoque zerado; verde = dá tempo (enviar até); laranja = atenção
#                  (último dia de envio, abaixo do ponto de pedido, ritmo acelerou); azul = informação; cinza = sem dado ou sem previsão. A cor nunca é a única pista: o rótulo está escrito.
def _cartao(tom, icone, rotulo, valor, apoio, detalhe):
    return {'tom': tom, 'icone': icone, 'rotulo': rotulo, 'valor': valor, 'apoio': apoio, 'detalhe': detalhe}


# Função Objetivo: O texto do cartão "Enviar até" (e o do "title") para cada estado da data de envio (ruptura_calculo.envio): `ok` (ainda dá tempo, com a margem inteira), `hoje` (último dia COM margem),
# `ja` (a data recomendada passou, mas ainda dá tempo de enviar: chega com menos margem) e `vencido` (mesmo enviando hoje vai faltar estoque). Devolve (tom, ícone, valor, apoio, detalhe).
def _cartao_do_envio(envio, lead, folga):
    lead_txt, folga_txt = _plural(lead, 'dia', 'dias'), _plural(folga, 'dia', 'dias')
    regra = f'ruptura − lead time ({lead_txt}) − margem de segurança ({folga_txt})' if folga else f'ruptura − lead time ({lead_txt})'
    if envio['estado'] == 'vencido':
        return _cartao('vermelho', 'fa-triangle-exclamation', 'Enviar até', 'Prazo vencido', f'vai faltar {_plural(envio["faltam_dias"], "dia", "dias")}',
                       f'O prazo de envio acabou em {_data(envio["ultimo_dia"])}: com lead time de {lead_txt}, mesmo enviando hoje o produto só fica disponível em '
                       f'{_data(envio["chegada"])} e vão faltar cerca de {_plural(envio["faltam_dias"], "dia", "dias")} de estoque.')
    if envio['estado'] == 'ja':
        sobra = envio['folga_na_chegada']
        return _cartao('laranja', 'fa-truck-fast', 'Enviar até', 'Enviar já', f'chega com {sobra} d de folga',
                       f'A data recomendada ({_data(envio["enviar_ate"])} = {regra}) já passou, mas ainda dá tempo: enviando hoje, o produto fica disponível em {_data(envio["chegada"])} '
                       f'com {_plural(sobra, "dia", "dias")} de estoque sobrando (a margem de segurança é de {folga_txt}). O último dia possível é {_data(envio["ultimo_dia"])}.')
    ultimo = envio['estado'] == 'hoje'
    margem_txt = (f'Enviando até essa data, o produto chega com pelo menos {folga_txt} de estoque sobrando. O último dia possível (sem margem) é {_data(envio["ultimo_dia"])}.' if folga
                  else f'Com lead time de {lead_txt}, o produto fica disponível quando o estoque acabar.')
    return _cartao('laranja' if ultimo else 'verde', 'fa-truck-fast', 'Enviar até', _data(envio['enviar_ate']),
                   'hoje, último dia com margem' if ultimo and folga else ('hoje, último dia' if ultimo else f'daqui a {_plural(envio["em_dias"], "dia", "dias")}'),
                   f'Data recomendada = {regra}. {margem_txt}')


# Função Objetivo: O cartão "Quanto enviar" com a sugestão do SISTEMA (ruptura_calculo.sugestao_do_sistema): a quantidade que deixa, na chegada, a margem de segurança + os dias que a remessa cobre.
# Sugestão zero vira o cartão verde "Nada agora" (o que sobra na chegada já é mais que a meta).
def _cartao_de_quanto_enviar(sug, media, lead, folga, cobre):
    ritmo_texto = f'{_un_dia(media)} un/dia'
    meta, sobra = ceil(sug['meta']), ceil(sug['sobra_na_chegada'])
    conta = (f'Na chegada (daqui a {_plural(lead, "dia", "dias")}) o estoque ainda terá cerca de {numero(sobra)} un. A meta é ter nesse dia a margem de segurança ({_plural(folga, "dia", "dias")}) '
             f'mais os dias que a remessa cobre ({_plural(cobre, "dia", "dias")}): {ritmo_texto} × {folga + cobre} = {numero(meta)} un.')
    if sug['qtd'] == 0:
        return _cartao('verde', 'fa-circle-check', 'Quanto enviar', 'Nada agora', 'estoque suficiente', f'{conta} Como o que sobra já passa da meta, não é preciso enviar agora.')
    return _cartao('azul', 'fa-boxes-packing', 'Quanto enviar', f'{numero(sug["qtd"])} un', f'cobre {_plural(cobre, "dia", "dias")}',
                   f'Sugestão do Sistema: {numero(sug["qtd"])} un. {conta} Meta − o que sobra = {numero(meta)} − {numero(sobra)}.')


# Função Objetivo: O cartão "Com o envio": o que acontece com o estoque se a quantidade escolhida for enviada HOJE (ruptura_calculo.com_envio). A remessa chega em `lead` dias; o cartão mostra a data da
# NOVA ruptura. Verde = a cobertura logo depois da chegada atinge a meta do Sistema (margem + dias que a remessa cobre); laranja = a remessa chega a tempo, mas cobre menos que a meta; vermelho = o estoque
# atual acaba antes de a remessa chegar (vai faltar produto, e nenhuma quantidade conserta isso).
def _cartao_com_o_envio(com, lead, folga, cobre, hoje):
    chegada, nova = hoje + timedelta(days=lead), hoje + timedelta(days=com['dia_nova_ruptura'])
    meta, dias_apos = folga + cobre, floor(com['dias_apos'])
    base = (f'Enviando {numero(com["qtd"])} un hoje, a remessa chega em {_data(chegada)} (lead time de {_plural(lead, "dia", "dias")}). Nesse dia o estoque terá cerca de {numero(round(com["apos"]))} un '
            f'({numero(ceil(com["antes"]))} que sobram + {numero(com["qtd"])} da remessa), o que dura cerca de {_plural(dias_apos, "dia", "dias")}: nova ruptura em {_data(nova)}.')
    if com['faltam'] > 0:
        return _cartao('vermelho', 'fa-circle-exclamation', 'Com o envio', _data(nova), f'falta {com["faltam"]} d antes de chegar',
                       f'{base} Mas o estoque atual acaba antes de a remessa chegar: vão faltar cerca de {_plural(com["faltam"], "dia", "dias")} de produto, e nenhuma quantidade conserta isso (só enviar mais cedo).')
    if dias_apos >= meta:
        return _cartao('verde', 'fa-arrow-trend-up', 'Com o envio', _data(nova), _em_dias(com['dia_nova_ruptura']),
                       f'{base} A meta do Sistema ({_plural(folga, "dia", "dias")} de margem + {_plural(cobre, "dia", "dias")} de remessa = {_plural(meta, "dia", "dias")}) foi atingida.')
    return _cartao('laranja', 'fa-triangle-exclamation', 'Com o envio', _data(nova), f'cobre {dias_apos} d (meta {meta} d)',
                   f'{base} A meta do Sistema é ter {_plural(meta, "dia", "dias")} de cobertura na chegada ({_plural(folga, "dia", "dias")} de margem + {_plural(cobre, "dia", "dias")} de remessa): esta quantidade fica abaixo dela.')


# Função Objetivo: O cartão "Urgência de envio": a urgência da referência escolhida (Mercado Livre ou Sistema) em destaque e a outra no apoio ("Sistema: Urgente"). O detalhe diz as duas e se concordam. Sem
# número do ML: "Sem número do ML" (cinza), nunca uma urgência inventada. `cat`/`envio` são os da projeção (para escrever o porquê da urgência do Sistema).
def _cartao_de_urgencia(ref_urg, urg_sistema, ml, cat, envio):
    urg_ml, ml_principal = ml['urgencia'], ref_urg == 'ml'
    selo_ml, selo_sistema = full.selo_da_urgencia(urg_ml), full.selo_da_urgencia(urg_sistema)
    selo, chave, outra, rotulo_outra = (selo_ml, urg_ml, selo_sistema, 'Sistema') if ml_principal else (selo_sistema, urg_sistema, selo_ml, 'ML')
    if selo_ml:
        prazo = f' O prazo para repor, segundo o ML, é {data_do_ml(ml["prazo"])}.' if ml['prazo'] else ''
        texto_ml = f'Mercado Livre: {selo_ml["label"]}.{prazo}'
    else:
        texto_ml = f'Mercado Livre: sem número ({ml["motivo"] or "a consulta não trouxe a urgência"}).'
    texto_sistema = f'Sistema: {selo_sistema["label"]} — {porque_da_urgencia_do_sistema(cat, envio)}.' if selo_sistema else 'Sistema: sem leitura do estoque.'
    if calc.urgencias_divergem(urg_sistema, urg_ml):
        comparacao = ' As duas referências estão em faixas diferentes: vale conferir os dois lados.'
    else:
        comparacao = ' As duas referências concordam.' if (selo_ml and selo_sistema) else ''
    detalhe = f'Referência escolhida: {"Mercado Livre" if ml_principal else "Sistema"}. {texto_ml} {texto_sistema}{comparacao}'
    apoio = f'{rotulo_outra}: {outra["label"] if outra else "sem número"}'
    if selo is None:
        return _cartao('cinza', 'fa-gauge', 'Urgência de envio', 'Sem número do ML' if ml_principal else 'Sem leitura', apoio, detalhe)
    return _cartao(TOM_DA_URGENCIA.get(chave, 'azul'), selo['icone'] or 'fa-gauge', 'Urgência de envio', selo['label'], apoio, detalhe)


# Função Objetivo: O cartão "O que o ML recomenda": a sugestão de envio do Mercado Livre (número, faixa ou "Não repor") com a urgência dele no apoio, e no detalhe tudo o que a consulta de reposição trouxe: o tipo
# de recomendação, o prazo para repor, o selo Estrela e a linha de cada Código ML (quando o item tem mais de um). `ml` é o resultado de ruptura_estoque.resumir_ml. Sem número: cinza e o motivo.
def _cartao_do_ml(ml):
    texto, dica = quantidade_do_ml(ml)
    selo = full.selo_da_urgencia(ml['urgencia'])
    if texto is None:
        return _cartao('cinza', 'fa-store', 'O que o ML recomenda', 'Sem número do ML', f'urgência: {selo["label"]}' if selo else '', dica)
    partes = [dica]
    if selo:
        partes.append(f'Urgência: {selo["label"]}.')
    tipos = sorted({ROTULO_DA_RECOMENDACAO.get(c['recomendacao'], c['recomendacao']) for c in ml['por_codigo'] if c['recomendacao']})
    if tipos:
        partes.append(f'Recomendação: {", ".join(tipos)}.')
    if ml['prazo']:
        partes.append(f'Prazo para repor: {data_do_ml(ml["prazo"])}.')
    if ml['estrela']:
        partes.append('Produto Estrela do Full.')
    if len(ml['por_codigo']) > 1:
        linhas = []
        for c in ml['por_codigo']:
            selo_c = full.selo_da_urgencia(c['urgencia'])
            sug = c['sugestao']
            qtd_c = '—' if not sug else (numero(sug['min']) if sug['min'] == sug['max'] else f'{numero(sug["min"])}–{numero(sug["max"])}')
            linhas.append(f'{c["codigo"]}: {selo_c["label"] if selo_c else "sem urgência"} · {qtd_c} un' if c['estado'] == 'ok' else f'{c["codigo"]}: sem número do ML')
        partes.append('Por Código ML — ' + '; '.join(linhas) + '.')
    if any(c['n_produtos'] > 1 for c in ml['por_codigo']):
        partes.append('Algum Código ML tem mais de um produto do vendedor na consulta: vale o primeiro com dados (como na tela de Planejamento).')
    valor = 'Não repor' if ml['nao_repor'] else f'{texto} un'
    return _cartao('azul', 'fa-store', 'O que o ML recomenda', valor, f'urgência: {selo["label"]}' if selo else 'sem urgência informada', ' '.join(partes))


# Função Objetivo: Os cartões de "quanto enviar": o "Quanto enviar" da referência escolhida (a sugestão do Sistema ou a quantidade digitada) e, havendo quantidade, o "Com o envio". `escolha` vem de
# _quantidade_escolhida e `com` de ruptura_calculo.com_envio (None sem quantidade).
def _cartoes_de_quanto_enviar(escolha, com, media, lead, folga, cobre, hoje, deposito=None):
    sug, ml = escolha['sugestao'], escolha['ml']
    if escolha['ref'] == 'ml':
        texto, dica = quantidade_do_ml(ml)
        do_sistema = f' A sugestão do Sistema é {numero(sug["qtd"])} un.' if sug else ''
        if texto is None:
            cartoes = [_cartao('cinza', 'fa-store', 'Quanto enviar', 'Sem número do ML', 'sem consulta' if ml['estado'] == 'sem_dados' else '', f'{dica}{do_sistema}')]
        elif ml['nao_repor']:
            cartoes = [_cartao('verde', 'fa-circle-check', 'Quanto enviar', 'Não repor', 'recomendação do ML', f'{dica}{do_sistema}')]
        else:
            cartoes = [_cartao('azul', 'fa-store', 'Quanto enviar', f'{texto} un', 'sugestão do ML', f'{dica}{do_sistema}')]
    elif escolha['ref'] == 'manual':
        do_sistema = f' A sugestão do Sistema é {numero(sug["qtd"])} un.' if sug else ''
        if escolha['qtd'] is None:
            cartoes = [_cartao('cinza', 'fa-pen-to-square', 'Quanto enviar', 'Digite a quantidade', '', f'Você escolheu "Minha quantidade", mas ainda não digitou quantas unidades quer enviar.{do_sistema}')]
        else:
            cartoes = [_cartao('azul', 'fa-pen-to-square', 'Quanto enviar', f'{numero(escolha["qtd"])} un', 'sua quantidade', f'Quantidade digitada por você.{do_sistema}')]
    elif sug is not None:
        cartoes = [_cartao_de_quanto_enviar(sug, media, lead, folga, cobre)]
    else:
        cartoes = []
    if cartoes:
        _avisar_do_deposito(cartoes[0], escolha['qtd'], deposito)
    if com is not None:
        cartoes.append(_cartao_com_o_envio(com, lead, folga, cobre, hoje))
    return cartoes


# Função Objetivo: Junta o estoque do depósito (ERP) ao cartão "Quanto enviar": na dica diz quanto há no depósito; se a quantidade passa dele, o cartão vira laranja com o aviso "só há N un no depósito" no lugar do apoio
# (a quantidade continua inteira, em destaque; o texto do apoio é curto porque o cartão é estreito). Sem número do ERP ou sem quantidade, o cartão fica como está.
def _avisar_do_deposito(cartao, qtd, deposito):
    if deposito is None or qtd is None:
        return
    curto, longo = aviso_do_deposito(qtd, deposito)
    if not curto:
        cartao['detalhe'] += f' Estoque do depósito (ERP): {numero(deposito)} un.'
        return
    cartao.update({'tom': 'laranja', 'icone': 'fa-triangle-exclamation', 'apoio': f'só {numero(deposito)} un no depósito', 'detalhe': f'{longo} {cartao["detalhe"]}'})   # no cartão cabe a frase curta (a inteira, "só há N un no depósito", vai na dica)


# Função Objetivo: A quantidade que vale para o gráfico e para os cartões: a sugestão do Sistema (referência "Do Sistema"), a do Mercado Livre (referência "Do Mercado Livre"; numa faixa vale o COMEÇO dela) ou
# a digitada (referência "Minha quantidade"; None enquanto não digitou). `sugestao` = ruptura_calculo.sugestao_do_sistema (ou None) e `ml` = ruptura_estoque.resumir_ml. Devolve {ref, qtd, sugestao, ml, digitada}.
def _quantidade_escolhida(comuns, sugestao, ml):
    ref = comuns['ref_qtd']
    if ref == 'manual':
        qtd = comuns['qtd']
    elif ref == 'ml':
        qtd = ml['sugestao_min']
    else:
        qtd = sugestao['qtd'] if sugestao else None
    return {'ref': ref, 'qtd': qtd, 'sugestao': sugestao, 'ml': ml, 'digitada': comuns['qtd']}


# Função Objetivo: O diagnóstico em cartões: a data de ruptura, até quando enviar (com a margem de segurança), a urgência (do Mercado Livre ou do Sistema), quanto enviar (a sugestão do Sistema, a do ML ou a
# quantidade digitada), o que acontece com o envio, o que o ML recomenda, o ponto de pedido, o ritmo recente contra o do período e, se a opção estiver marcada, o "a caminho" que já está na conta. O nível mostrado é o do ritmo do período escolhido. Sem ritmo ou sem estoque
# não há cartões: só o `resumo` (uma frase dizendo o que falta).
def _diagnostico(estoque, lead, folga, cobre, dias, recente, ritmo_p, ritmo_r, mesmo_ritmo, hoje, a_caminho_somado=0, escolha=None, com=None, ml=None, ref_urg='sistema', deposito=None):
    media = ritmo_p['media']
    sem = {'nivel': None, 'nivel_rotulo': '', 'cartoes': []}
    if media is None:
        return {**sem, 'resumo': f'Nenhum dia completo dos últimos {dias} foi coletado para este recorte: sem isso não dá para calcular o ritmo de vendas.'}
    ritmo_texto = f'{_un_dia(media)} un/dia'
    if estoque is None:
        return {**sem, 'resumo': f'O ritmo dos últimos {dias} dias é de {ritmo_texto}. Informe o estoque atual (e o lead time) para ver a projeção.'}

    projecao = calc.projetar(estoque, media, hoje)
    situacao = projecao['situacao']
    nivel = calc.nivel_do_estoque(projecao, lead, folga)
    envio_do_item = calc.envio(projecao, lead, hoje, folga) if situacao == 'normal' and lead is not None else None
    cartoes = []

    # ---- 1) a ruptura: sempre VERMELHA quando há data (a mesma cor do "Ruptura" do gráfico) ----
    if situacao == 'zerado':
        resumo = 'O estoque está zerado: o produto já está em ruptura.'
        cartoes.append(_cartao('vermelho', 'fa-circle-exclamation', 'Situação atual', 'Estoque zerado', 'em ruptura agora', resumo))
    elif situacao == 'sem_vendas':
        resumo = f'Nos últimos {dias} dias completos não houve nenhuma venda: com {numero(estoque)} un em estoque não há ruptura prevista neste ritmo.'
        cartoes.append(_cartao('cinza', 'fa-calendar-xmark', 'Data de ruptura', 'Sem previsão', 'sem vendas no período', resumo))
    elif situacao == 'longe':
        resumo = f'Com {ritmo_texto}, o estoque de {numero(estoque)} un dura mais de {numero(calc.DIAS_MAXIMOS_DA_PROJECAO)} dias.'
        cartoes.append(_cartao('cinza', 'fa-calendar-xmark', 'Data de ruptura', 'Sem previsão', f'dura mais de {numero(calc.DIAS_MAXIMOS_DA_PROJECAO)} dias', resumo))
    else:
        resumo = f'Com {ritmo_texto} (ritmo dos últimos {dias} dias), o estoque de {numero(estoque)} un dura cerca de {_plural(projecao["dias"], "dia", "dias")}.'
        cartoes.append(_cartao('vermelho', 'fa-calendar-xmark', 'Data de ruptura', _data(projecao['data']), _em_dias(projecao['dias']), resumo))

    # ---- 2) o envio, 3) quanto enviar e 4) o ponto de pedido (dependem do lead time e da margem de segurança) ----
    if lead is None:
        cartoes.append(_cartao('cinza', 'fa-truck-fast', 'Enviar até', 'Informe o lead time', '', 'Informe o lead time para ver a data limite do envio e o nível do estoque.'))
    elif situacao == 'zerado':
        quando = 'assim que for enviado' if lead == 0 else f'{_plural(lead, "dia", "dias")} depois do envio'
        cartoes.append(_cartao('vermelho', 'fa-truck-fast', 'Enviar', 'O quanto antes', 'sem espera' if lead == 0 else f'demora {_plural(lead, "dia", "dias")}',
                               f'Com lead time de {_plural(lead, "dia", "dias")}, o produto só volta a ficar disponível {quando}: envie o quanto antes.'))
    elif situacao == 'normal':
        cartoes.append(_cartao_do_envio(envio_do_item, lead, folga))
    else:
        cartoes.append(_cartao('cinza', 'fa-truck-fast', 'Enviar até', 'Sem data limite', '', 'Sem ruptura prevista neste ritmo: não há data limite de envio.'))
    if lead is not None:
        if ml is not None:
            cartoes.append(_cartao_de_urgencia(ref_urg, calc.urgencia_do_sistema('ruptura' if situacao == 'zerado' else 'normal', envio_do_item), ml, 'ruptura' if situacao == 'zerado' else 'normal', envio_do_item))
        if escolha is not None and situacao in ('zerado', 'normal'):
            cartoes.extend(_cartoes_de_quanto_enviar(escolha, com, media, lead, folga, cobre, hoje, deposito))
        if ml is not None:
            cartoes.append(_cartao_do_ml(ml))
        if situacao == 'normal':
            pedido = calc.ponto_de_pedido(media, lead, folga)
            if pedido is not None:
                abaixo = estoque < media * (lead + folga)
                cartoes.append(_cartao('laranja' if abaixo else 'azul', 'fa-gauge-high', 'Ponto de pedido', f'{numero(pedido)} un', 'estoque abaixo dele' if abaixo else 'estoque acima dele',
                                       f'É o ritmo × (lead time + margem de segurança): quanto se vende em {_plural(lead + folga, "dia", "dias")} ({lead} do lead time + {folga} de margem). '
                                       f'O estoque atual {"já está abaixo" if abaixo else "ainda está acima"} dele.'))

    # ---- 4) o ritmo recente contra o do período ----
    comparacao = None if mesmo_ritmo or estoque <= 0 else calc.comparar_ritmos(ritmo_r['media'], media)
    if comparacao and media <= 0 and not ritmo_r['media']:
        comparacao = None   # nenhuma venda nos dois ritmos: não há o que comparar
    if comparacao:
        mr = ritmo_r['media']
        proj_r = calc.projetar(estoque, mr, hoje)
        pct = comparacao['pct']
        rotulo = f'Ritmo dos últimos {_plural(recente, "dia", "dias")}' if recente != 1 else 'Ritmo do último dia'
        recente_texto = f'nos últimos {recente} dias foram {_un_dia(mr)} un/dia, contra {ritmo_texto} no período'
        if comparacao['sentido'] == 'acelerou':
            texto = f'O ritmo acelerou: {recente_texto}{f" ({_pct(pct)})" if pct is not None else ""}.'
            if proj_r['situacao'] == 'normal':
                antes = projecao['dias'] - proj_r['dias'] if situacao == 'normal' else 0
                complemento = f', {_plural(antes, "dia", "dias")} antes' if antes > 0 else ''
                texto += f' Nesse ritmo a ruptura vem em {_data(proj_r["data"])} ({_em_dias(proj_r["dias"])}){complemento}.'
            cartoes.append(_cartao('laranja', 'fa-gauge-simple-high', rotulo, f'{_un_dia(mr)} un/dia', f'acelerou {_pct(pct)}' if pct is not None else 'acelerou', texto))
        elif comparacao['sentido'] == 'caiu':
            texto = f'O ritmo caiu: {recente_texto} ({_pct(pct)}).'
            if proj_r['situacao'] == 'normal':
                texto += f' Nesse ritmo o estoque dura até {_data(proj_r["data"])}.'
            cartoes.append(_cartao('azul', 'fa-gauge-simple', rotulo, f'{_un_dia(mr)} un/dia', f'caiu {_pct(pct)}', texto))
        else:
            cartoes.append(_cartao('verde', 'fa-circle-check', rotulo, f'{_un_dia(mr)} un/dia', 'estável', f'Ritmo estável: {recente_texto}.'))

    # ---- 5) o "a caminho" que já está na conta (opção marcada) ----
    if a_caminho_somado:
        cartoes.append(_cartao('azul', 'fa-truck', 'A caminho (já incluído)', f'{numero(a_caminho_somado)} un', 'somadas ao estoque',
                               f'O estoque de {numero(estoque)} un inclui {numero(a_caminho_somado)} un a caminho (enviadas ao Full e ainda não recebidas): a conta trata essas unidades como se já estivessem lá hoje.'))
    return {'nivel': nivel, 'nivel_rotulo': calc.NIVEIS.get(nivel, ''), 'resumo': resumo, 'cartoes': cartoes}


# ==================================================== o detalhe de um item ====================================================

def _escolher(parametros, nome, validos, padrao):
    valor = (parametros.get(nome) or '').strip()
    return valor if valor in validos else padrao


# Função Objetivo: Os números de uma soma de estoque (ruptura_estoque.somar_codigos) já como texto para a tabela do detalhe; "—" quando nenhum Código foi lido ("ausente não é zero").
def _numeros_da_tabela(r):
    if r['estado'] == 'sem_leitura':
        return {k: '—' for k in ('total', 'disponivel', 'transferencia', 'processo', 'nao_conta', 'considerado', 'a_caminho')}
    return {'total': numero(r['total']), 'disponivel': numero(r['disponivel']), 'transferencia': numero(r['transferencia']), 'processo': numero(r['processo']),
            'nao_conta': numero(r['nao_conta']), 'considerado': numero(r['considerado']),
            'a_caminho': '—' if r['a_caminho'] is None else numero(r['a_caminho']) + ('*' if r['a_caminho_parcial'] else '')}


# Função Objetivo: A tabela "Estoque no Full por Código ML" do detalhe (o detalhamento do estoque do Full): para cada Código do item, o total, o disponível, o que está em transferência e em
# processo interno, o que fica fora da conta, o estoque considerado (a conta da regra provisória) e o a caminho; e a linha da soma, que é o número que a tela usa quando o estoque não é digitado.
def _tabela_de_codigos(codigos, cartoes, mlbs_do_codigo, soma, caminho=False):
    linhas = []
    for codigo in sorted(codigos):
        r = full.somar_codigos([codigo], cartoes)
        full.preencher_a_caminho(r, [codigo], cartoes)
        lido = r['estado'] == 'ok'
        if lido:
            consulta = r['idade'] + (' · consulta antiga' if r['desatualizados'] else '')
        else:
            consulta = 'erro na última consulta' if r['com_erro'] else 'sem consulta salva'
        linhas.append({'codigo': codigo, 'mlbs': ', '.join(mlbs_do_codigo.get(codigo, [])), 'consulta': consulta, 'atencao': (not lido) or bool(r['desatualizados']), **_numeros_da_tabela(r)})
    return {'linhas': linhas, 'soma': _numeros_da_tabela(soma), 'soma_parcial': soma['estado'] == 'parcial', 'conta': full.texto_da_conta(soma, numero, caminho),
            'n_chamadas': len(linhas) * CHAMADAS_POR_CODIGO}   # quanto custa "Consultar todos" (o botão só avisa: a API só é chamada por clique)


# Função Objetivo: A linha de apoio sob o campo de estoque do detalhe: diz DE ONDE vem o estoque usado (lido do Full ou digitado) e o que fazer. Sempre uma linha só (a tela é rígida na vertical).
def _dica_do_estoque(visao, digitado, lido, resumo, rotulo, caminho=False):
    parcial = f' Atenção: o lido é parcial ({resumo["n_lidos"]} de {resumo["n_codigos"]} Códigos).' if resumo['estado'] == 'parcial' and visao == 'full' else ''
    if digitado is not None:
        if lido is not None:
            aviso_caminho = ' O "a caminho" não é somado ao valor digitado.' if caminho else ''
            return {'texto': f'Usando o estoque DIGITADO: {numero(digitado)} un. O lido do Full é {numero(lido)} un: apague o campo para voltar ao lido.{aviso_caminho}', 'classe': 'atencao'}
        return {'texto': f'Usando o estoque DIGITADO: {numero(digitado)} un.', 'classe': 'atencao'}
    if visao != 'full':
        return {'texto': f'{rotulo}: digite o valor (só o estoque do Full é lido; a API de estoque do ERP ainda será corrigida).', 'classe': 'atencao'}
    if lido is None:
        return {'texto': 'O estoque do Full deste item não foi lido (sem consulta salva). Digite o estoque para ver a projeção ou clique em "Consultar no Mercado Livre" na tabela de estoque, mais abaixo.', 'classe': 'atencao'}
    if caminho and resumo['a_caminho']:
        return {'texto': f'Usando o estoque lido do Full: {numero(resumo["considerado"])} un + {numero(resumo["a_caminho"])} a caminho = {numero(lido)} un.{parcial} Digite um valor para simular outro estoque.',
                'classe': 'atencao' if parcial else ''}
    sem_caminho = ' Sem o número de "a caminho" para este item: só o estoque do Full entra.' if caminho and resumo['a_caminho'] is None else ''
    return {'texto': f'Usando o estoque lido do Full: {numero(lido)} un (da última consulta salva).{sem_caminho}{parcial} Digite um valor para simular outro estoque.', 'classe': 'atencao' if parcial or sem_caminho else ''}


# Função Objetivo: As opções do seletor "Quanto enviar" (a referência da quantidade): [{chave, rotulo, dica, ativo}]. "Do Mercado Livre" usa a sugestão que o ML manda na consulta de reposição; "Do Sistema" usa
# a sugestão calculada pela regra da tela; "Minha quantidade" (só no detalhe de um item) usa o número que a pessoa digita, para criar a própria sugestão.
def _opcoes_de_quanto_enviar(ref, com_manual):
    opcoes = [
        ('ml', 'Do Mercado Livre', 'A quantidade que o Mercado Livre sugere (a mesma da tela "Full — Planejamento de envios", lida da última consulta de reposição salva). Numa faixa vale o começo dela.'),
        ('sistema', 'Do Sistema', 'A quantidade que o Sistema sugere: a que deixa, na chegada da remessa, a margem de segurança + os dias que cada remessa cobre.'),
    ]
    if com_manual:
        opcoes.append(('manual', 'Minha quantidade', 'Digite quantas unidades você quer enviar: a tela mostra o que acontece com o estoque (a linha verde do gráfico e o cartão "Com o envio").'))
    return [{'chave': chave, 'rotulo': rotulo, 'dica': dica, 'ativo': chave == ref} for chave, rotulo, dica in opcoes]


# Função Objetivo: As opções do seletor "Referência de urgência": de quem é a urgência que manda na ordem da lista e no selo grande (a outra aparece pequena ao lado).
def _opcoes_de_urgencia(ref):
    opcoes = (
        ('ml', 'Mercado Livre', 'A urgência que o Mercado Livre calcula (Urgente, Esta semana, Próxima semana, Em 2 semanas, Sem urgência, Excedente), lida da última consulta de reposição salva: a mesma da tela "Full — Planejamento de envios".'),
        ('sistema', 'Sistema', 'A urgência da regra desta tela, pela data de "Enviar até": hoje ou já passou = Urgente; em até 7 dias = Esta semana; até 14 = Próxima semana; até 21 = Em 2 semanas; depois = Sem urgência.'),
    )
    return [{'chave': chave, 'rotulo': rotulo, 'dica': dica, 'ativo': chave == ref} for chave, rotulo, dica in opcoes]


# Função Objetivo: Preenche `pagina` com o detalhe de UM item (o SKU, ou um MLB / Código ML dele): quem é, o estoque (lido do Full ou digitado), o ritmo, os 4 cartões, a curva, o diagnóstico e a
# tabela de estoque por Código ML. Item que não existe vira um aviso de erro (estado "erro"), nunca uma tela quebrada.
def _montar_detalhe(parametros, base_url, hoje, comuns, pagina, sku):
    dias, lead, folga, cobre, recente, caminho = comuns['dias'], comuns['lead'], comuns['folga'], comuns['cobre'], comuns['recente'], comuns['caminho']
    ref_qtd = comuns['ref_qtd']
    gran = _escolher(parametros, 'gran', GRANULARIDADES_DO_DETALHE, 'sku')
    item = sku if gran == 'sku' else (parametros.get('item') or '').strip().upper()
    visao = _escolher(parametros, 'visao', ('full',) if gran == 'codigo' else tuple(v[0] for v in VISOES), 'full')
    estoque_digitado = _inteiro(parametros.get('estoque'), 0, 10_000_000)
    # * [EXPLICAÇÃO] → O recorte das vendas: no SKU é a visão escolhida; no MLB é aquele anúncio (e, se a visão é Full ou Fora, só essa origem dele); no Código ML é aquele código só no Full
    #                  (o Código ML é o estoque do Full: venda do mesmo anúncio que saiu de outro lugar não é dele).
    nivel, origem = {'sku': (visao, ''), 'mlb': ('mlb', visao if visao in ('full', 'fora') else ''), 'codigo': ('codigo', 'full')}[gran]
    rotulo_do_estoque = ROTULO_DO_ESTOQUE[visao]
    pagina.update({
        'estado': 'erro', 'sku': sku, 'gran': gran, 'item': item, 'visao': visao, 'rotulo_do_estoque': rotulo_do_estoque, 'mostra_visoes': gran != 'codigo',
        'visoes': [{'chave': chave, 'rotulo': rotulo, 'dica': dica, 'ativo': chave == visao} for chave, rotulo, dica in VISOES],
        'estoque_valor': '' if estoque_digitado is None else str(estoque_digitado), 'estoque_placeholder': 'unidades',
        'qtd_valor': '' if (ref_qtd != 'manual' or comuns['qtd'] is None) else str(comuns['qtd']), 'qtd_placeholder': 'un', 'qtd_ajuda': '',
        'ocultos': [{'nome': 'sku', 'valor': sku}] + ([{'nome': 'gran', 'valor': gran}, {'nome': 'item', 'valor': item}] if gran != 'sku' else []),
        'url_lista': url_da_tela(base_url, gran=gran if gran != 'sku' else None, **para_url(comuns)),
        'cartoes': [], 'grafico': None, 'diagnostico': None, 'alvo': None, 'tabela_de_codigos': None, 'dica_do_estoque': {'texto': '', 'classe': ''}, 'deposito': None,
        'url_consultar': reverse('gestao_ruptura_consultar'), 'chamadas_por_codigo': CHAMADAS_POR_CODIGO,
    })

    de = hoje - timedelta(days=max(dias, recente, max(calc.DIAS_DOS_RITMOS_DO_GRAFICO)))   # o gráfico compara 3, 7, 15 e 30 dias: as vendas desses dias já estão no banco (nada de API)
    dados = unidades_por_dia(sku, nivel, de, hoje, '' if gran == 'sku' else item, origem)
    cadastro = dados['cadastro']
    if cadastro is None:
        pagina['avisos'].append({'classe': 'erro', 'texto': f'O SKU "{sku}" não está no cadastro de Produto. Confira o código: ele precisa ser igual ao da tela de Vendas.'})
        return
    mlbs_cad = cadastro['mlbs']
    codigos_do_sku = {c for m in mlbs_cad.values() for _, c in m['variacoes'] if c}
    if gran == 'mlb' and item not in mlbs_cad:
        pagina['avisos'].append({'classe': 'erro', 'texto': f'O anúncio "{item}" não está entre os anúncios do SKU {sku}.'})
        return
    if gran == 'codigo' and item not in codigos_do_sku:
        pagina['avisos'].append({'classe': 'erro', 'texto': f'O Código ML "{item}" não está entre os Códigos ML do SKU {sku}.'})
        return
    codigos = codigos_do_sku if gran == 'sku' else ({c for _, c in mlbs_cad[item]['variacoes'] if c} if gran == 'mlb' else {item})
    mlbs_do_codigo = {c: sorted(m for m, info in mlbs_cad.items() if any(cc == c for _, cc in info['variacoes'])) for c in codigos}

    # ---- o estoque: lido do Full (só na visão "No Full") ou digitado ----
    cartoes = estoque_full_dos_codigos(sorted(codigos)) if codigos else {}
    a_caminho_dos_codigos(cartoes)
    ml_dos_codigos(cartoes, guardar_no_cache=False)   # o que o Mercado Livre recomenda (urgência e sugestão): lê o cache dos resumos, sem trocá-lo pelo pedacinho deste item
    ml = full.resumir_ml(codigos, cartoes)
    if visao != 'full':
        ml = {**ml, 'estado': 'sem_dados', 'urgencia': None, 'sugestao_min': None, 'sugestao_max': None, 'n_com_sugestao': 0, 'nao_repor': False,
              'motivo': 'a recomendação do Mercado Livre vale só para o estoque do Full: escolha a visão "No Full"'}
    resumo = full.somar_codigos(codigos, cartoes)
    full.preencher_a_caminho(resumo, codigos, cartoes)
    deposito = estoque_do_erp([sku]).get(sku)   # o estoque do ERP (depósito) do SKU: só para avisar quando a quantidade a enviar passa dele
    pagina['deposito'] = None if deposito is None else {'texto': f'{numero(deposito)} un', 'dica': 'O Estoque do cadastro do Produto no ERP (o depósito, de onde sai o que você envia ao Full). Vale para o SKU inteiro, mesmo quando você olha um anúncio ou um Código ML.'}
    lido = full.estoque_para_cobertura(resumo, caminho) if visao == 'full' else None   # com a opção marcada, já inclui o a caminho
    a_caminho_somado = (resumo['a_caminho'] or 0) if (caminho and lido is not None) else 0
    estoque = estoque_digitado if estoque_digitado is not None else lido
    a_caminho_somado = a_caminho_somado if estoque_digitado is None else 0   # o valor digitado vale como está: o a caminho não é somado a ele
    origem_do_estoque = 'digitado' if estoque_digitado is not None else (('lido do Full' + (' + a caminho' if a_caminho_somado else '')) if lido is not None else '')
    pagina['estoque_placeholder'] = numero(lido) if lido is not None else 'unidades'
    pagina['dica_do_estoque'] = _dica_do_estoque(visao, estoque_digitado, lido, resumo, rotulo_do_estoque, caminho)
    if codigos:
        pagina['tabela_de_codigos'] = _tabela_de_codigos(codigos, cartoes, mlbs_do_codigo, resumo, caminho)

    def janela(n):   # n dias completos para trás + hoje
        return [hoje - timedelta(days=i) for i in range(n, -1, -1)]

    ritmo_p = calc.ritmo_da_janela(janela(dias), dados['por_dia'], dados['estados'])
    ritmo_r = calc.ritmo_da_janela(janela(recente), dados['por_dia'], dados['estados'])
    mesmo_ritmo = dias <= recente
    media = ritmo_p['media']
    n_ok = ritmo_p['n_completos']
    pagina['estado'] = 'ok'

    nivel_vendas = {'sku': visao if visao != 'produto' else None, 'mlb': 'mlb', 'codigo': 'codigo'}[gran]
    url_vendas = url_da_tela(reverse('gestao_vendas_principal'), sku=sku, nivel=nivel_vendas, item=item if gran != 'sku' else None)
    coletado_em = dados['coletado_em']
    atualizado = coletado_em.astimezone(FUSO).strftime('%d/%m %H:%M') if coletado_em else ''
    marca = cadastro['marca']
    if gran == 'sku':
        alvo = {'tipo': 'Produto (SKU)', 'titulo': cadastro['titulo'] or sku, 'imagem': cadastro['imagem'],
                'meta': [('SKU', sku), ('Marca', marca), ('', _plural(len(mlbs_cad), 'anúncio (MLB)', 'anúncios (MLB)')), ('', _plural(len(codigos), 'Código ML', 'Códigos ML'))]}
    elif gran == 'mlb':
        anuncio = mlbs_cad[item]
        alvo = {'tipo': 'Anúncio (MLB)', 'titulo': anuncio['titulo'] or cadastro['titulo'] or item, 'imagem': anuncio['imagem'] or cadastro['imagem'],
                'meta': [('MLB', item), ('SKU', sku), ('Marca', marca), ('', _plural(len(codigos), 'Código ML', 'Códigos ML') if codigos else 'sem Código ML')]}
    else:
        usados = mlbs_do_codigo.get(item, [])
        foto = next((mlbs_cad[m]['imagem'] for m in usados if mlbs_cad[m]['imagem']), '') or cadastro['imagem']
        alvo = {'tipo': 'Código ML', 'titulo': f'{item} — {cadastro["titulo"] or sku}', 'imagem': foto,
                'meta': [('Código ML', item), ('SKU', sku), ('', _plural(len(usados), 'anúncio (MLB)', 'anúncios (MLB)'))]}
    alvo['meta'] = [{'rotulo': rotulo, 'valor': valor} for rotulo, valor in alvo['meta'] if valor]
    alvo.update({'url_vendas': url_vendas, 'atualizado': atualizado})
    pagina['alvo'] = alvo
    if n_ok == 0:
        pagina['avisos'].append({'classe': 'erro', 'texto': f'Nenhum dia completo dos últimos {dias} foi coletado para este recorte, então não dá para calcular o ritmo.',
                                 'link': url_vendas, 'link_texto': 'Atualizar na tela de Vendas'})
    elif n_ok < dias:
        pagina['avisos'].append({'classe': 'aviso', 'texto': f'Faltam dados de {dias - n_ok} dos últimos {dias} dias: a média usa só os {n_ok} dias completos que foram coletados.',
                                 'link': url_vendas, 'link_texto': 'Atualizar na tela de Vendas'})

    # ---- os 4 cartões ----
    de_periodo = hoje - timedelta(days=dias)
    explicacao_periodo = f'Média dos últimos {dias} dias (de {_data(de_periodo)} até ontem). Só dias completos entram: hoje (parcial) e dias sem coleta ficam de fora; venda cancelada não conta.'
    explicacao_recente = f'Média dos últimos {recente} dias completos: mostra se o ritmo mudou há pouco tempo.'
    cartao_vendas = {'rotulo': f'Vendas nos últimos {dias} dias', 'destaque': False, 'nivel': None, 'nivel_rotulo': '', 'nivel_titulo': '', 'valor': f'{numero(ritmo_p["unidades"])} un',
                     'sub': f'média {_un_dia(media)} un/dia · {n_ok}/{dias} dias' if media is not None else 'nenhum dia completo coletado'}
    cartao_vendas['dica'] = f'{explicacao_periodo} Entraram {n_ok} dos {dias} dias; {cartao_vendas["sub"]}.'
    sub_estoque = f'{origem_do_estoque} · lead time de {_plural(lead, "dia", "dias")}' if estoque is not None else 'informe o estoque'
    cartao_estoque = {'rotulo': 'Estoque e lead time', 'destaque': False, 'nivel': None, 'nivel_rotulo': '', 'nivel_titulo': '', 'valor': '—' if estoque is None else f'{numero(estoque)} un',
                      'sub': sub_estoque}
    cartao_estoque['dica'] = (f'{rotulo_do_estoque} ({origem_do_estoque or "não informado"}) e lead time (dias até o produto ficar disponível para venda; margem de segurança de {_plural(folga, "dia", "dias")}). '
                              f'{"Estoque do Full = " + full.texto_da_conta(resumo, numero, caminho) if lido is not None else ""}')
    pagina['cartoes'] = [
        _cartao_de_ruptura(f'Ruptura · ritmo de {recente} dias', explicacao_recente, ritmo_r, estoque, lead, folga, hoje),
        _cartao_de_ruptura(f'Ruptura · ritmo de {dias} dias', explicacao_periodo, ritmo_p, estoque, lead, folga, hoje, destaque=True),
        cartao_vendas,
        cartao_estoque,
    ]

    # ---- a curva e o diagnóstico ----
    # * [EXPLICAÇÃO] → O gráfico mostra os ritmos de 3, 7, 15 e 30 dias (+ o período digitado, se for outro). Clicar num deles RECARREGA a tela com aquele período (dias=N): assim o ritmo em destaque
    #                  do gráfico e todo o resto da tela (cartões, diagnóstico, ritmo do formulário) nunca divergem. O "#rup-grafico" faz o navegador voltar para o gráfico, em vez do topo da página.
    def endereco_do_ritmo(n):
        return url_da_tela(base_url, sku=sku, gran=gran if gran != 'sku' else None, item=item if gran != 'sku' else None, visao=visao if visao != 'full' else None, estoque=estoque_digitado,
                           **para_url(comuns, dias=n, detalhe=True)) + '#rup-grafico'

    def ritmo_de(n):
        if n == dias:
            return ritmo_p
        if n == recente:
            return ritmo_r
        return calc.ritmo_da_janela(janela(n), dados['por_dia'], dados['estados'])

    dias_do_grafico = sorted({n for n in calc.DIAS_DOS_RITMOS_DO_GRAFICO if n <= comuns['maximo']} | {dias})
    series = [{'dias': n, 'media': ritmo_de(n)['media'], 'url': endereco_do_ritmo(n)} for n in dias_do_grafico]
    # ---- quanto enviar: a sugestão do Sistema, a quantidade escolhida e o que acontece com o estoque se ela for enviada hoje ----
    sugestao = calc.sugestao_do_sistema(estoque, media, lead, folga, cobre)
    escolha = _quantidade_escolhida(comuns, sugestao, ml)
    com = calc.com_envio(estoque, media, lead, escolha['qtd'])
    if com:
        com = {**com, 'fonte': FONTE_DA_QUANTIDADE[ref_qtd]}   # o cartão da linha verde diz de quem é a quantidade (do Sistema, do Mercado Livre ou digitada)
    pagina['qtd_placeholder'] = numero(sugestao['qtd']) if sugestao else 'un'
    texto_ml, _ = quantidade_do_ml(ml)
    if ref_qtd == 'manual':
        pagina['qtd_ajuda'] = 'Digite quantas unidades enviar: a linha verde do gráfico e o cartão "Com o envio" mostram como o estoque fica.'
    elif ref_qtd == 'ml':
        pagina['qtd_ajuda'] = (f'Sugestão do Mercado Livre: {texto_ml} un' + (' (no gráfico vale o começo da faixa).' if '–' in texto_ml else '.')) if texto_ml else f'Sem número do ML ({ml["motivo"] or "sem sugestão de envio"}).'
    else:
        pagina['qtd_ajuda'] = (f'Sugestão do Sistema: {numero(sugestao["qtd"])} un (deixa {folga} d de margem + {cobre} d de cobertura na chegada).' if sugestao else 'Sem sugestão do Sistema (falta estoque ou ritmo).')
    pagina['grafico'] = montar_grafico(estoque, lead, folga, series, dias, hoje, com, cobre)
    pagina['diagnostico'] = _diagnostico(estoque, lead, folga, cobre, dias, recente, ritmo_p, ritmo_r, mesmo_ritmo, hoje, a_caminho_somado, escolha, com, ml, comuns['ref_urg'], deposito)


# ==================================================== a página ====================================================

# Função Objetivo: Junta os avisos da página e os da lista num só conjunto e diz como mostrar: com 2 ou mais avisos (e nenhum de erro) eles vão AGRUPADOS numa caixa recolhida de uma linha
# ("N avisos sobre os dados"), para não empurrar os cartões e a tabela para baixo; erro nunca fica escondido (aí cada aviso continua sendo uma faixa).
def _organizar_avisos(pagina):
    todos = list(pagina['avisos']) + (list(pagina['lista']['avisos']) if pagina['lista'] else [])
    pagina['avisos_todos'] = todos
    pagina['avisos_agrupar'] = len(todos) > 1 and not any(a['classe'] == 'erro' for a in todos)
    pagina['avisos_tem_atencao'] = any(a['classe'] == 'aviso' for a in todos)


# Função Objetivo: Tudo da tela a partir da query string. Sem SKU: a LISTA (ruptura_lista.montar_lista). Com SKU: o DETALHE de um item (_montar_detalhe). Os parâmetros comuns (ritmo, lead time,
# margem de segurança, dias que cada remessa cobre e "a caminho") são lidos em ruptura_parametros.ler_comuns; o lead time e os dias que a remessa cobre, sem digitar, são padrões PROVISÓRIOS e a tela
# avisa isso ao lado de cada campo.
def montar_pagina(parametros, base_url, hoje=None):
    hoje = hoje or datetime.now(FUSO).date()
    sku = (parametros.get('sku') or '').strip()
    comuns = ler_comuns(parametros, hoje)
    dias, lead, folga, maximo = comuns['dias'], comuns['lead'], comuns['folga'], comuns['maximo']
    pagina = {
        'modo': 'detalhe' if sku else 'lista', 'url_ruptura': base_url, 'hoje': hoje, 'dias_valor': str(dias), 'lead_valor': str(lead), 'caminho': comuns['caminho'],
        'lead_e_padrao': comuns['lead_digitado'] is None or comuns['lead_digitado'] == calc.LEAD_TIME_PADRAO,   # o formulário reenvia o "7" já preenchido: continua sendo o padrão provisório
        # * [EXPLICAÇÃO] → O campo "Cada remessa cobre" fica VAZIO enquanto vale o padrão (o lead time, mostrado em cinza dentro do campo): assim, ao mudar o lead time, ele acompanha. Só um valor digitado
        #                  fixa o número.
        'margem_valor': str(comuns['margem']), 'folga_dias': folga, 'folga_texto': _plural(folga, 'dia', 'dias'),
        'cobre_valor': '' if comuns['cobre_digitado'] is None else str(comuns['cobre_digitado']), 'cobre_placeholder': str(comuns['cobre']), 'cobre_e_padrao': comuns['cobre_digitado'] is None,
        'regra_texto': (f'Enviar até = ruptura − {lead} d (lead time) − {folga} d (margem). Sugestão do Sistema = o que deixa {folga} d de margem + {comuns["cobre"]} d de cobertura na chegada.'),
        'avisos': [], 'lista': None, 'estado': 'lista',
        # * [EXPLICAÇÃO] → Os dois seletores de referência existem na lista e no detalhe. "Minha quantidade" só existe no detalhe de um item (a lista não tem quantidade digitada: lá vale "Do Sistema").
        'urg_opcoes': _opcoes_de_urgencia(comuns['ref_urg']),
        'qtd_opcoes': _opcoes_de_quanto_enviar(comuns['ref_qtd'] if (sku or comuns['ref_qtd'] != 'manual') else 'sistema', bool(sku)),
        'referencia_ajuda': 'Referência de urgência e de quantidade: Mercado Livre = a recomendação dele (lida da consulta de reposição salva); Sistema = a regra desta tela. A escolhida manda; a outra aparece pequena.',
        'atalhos': [{'dias': d, 'rotulo': str(d), 'ativo': d == dias} for d in ATALHOS_DE_DIAS] + [{'dias': maximo, 'rotulo': '1 ano', 'ativo': dias == maximo}],
        'maximo_de_dias': maximo,
    }
    if comuns['dias_pedidos'] and comuns['dias_pedidos'] > maximo:
        pagina['avisos'].append({'classe': 'info', 'texto': f'O Mercado Livre guarda cerca de 12 meses de pedidos: o ritmo usa {dias} dias (o máximo disponível).'})
    if sku:
        _montar_detalhe(parametros, base_url, hoje, comuns, pagina, sku)
    else:
        pagina['lista'] = montar_lista(parametros, base_url, hoje, comuns)
    _organizar_avisos(pagina)
    return pagina
