# gestao_ruptura/funcoes_auxiliares/ruptura_pagina.py
#
# Função Objetivo: Monta tudo o que a tela "Previsão de Ruptura de estoque" mostra, a partir da query string.
#   - SEM sku: a LISTA do mundo escolhido. Envios Full: por urgência, por Produto (SKU), Anúncio (MLB) ou Código ML (ruptura_lista.py; gran, q, nivel, ord, por, pag). Fora do Full: por Produto (SKU) ou Anúncio (MLB), com
#     vendas, ritmo, ponto de pedido e quantidade a pedir, e o estoque em "—" (ruptura_lista_fora.py; gran, q, ord, por, pag).
#   - COM sku: o DETALHE de um item, com a curva, os cartões e o diagnóstico: o próprio SKU, ou um MLB / Código ML dele (gran=mlb|codigo + item). Parâmetros: sku, gran, item.
#   - DOIS MUNDOS ISOLADOS (decisão do Matheus, 12/10/2026): ENVIOS FULL (padrão) e FORA DO FULL (`mundo=fora`), cada um com as SUAS regras e o SEU estoque digitado: dias (o ritmo dos últimos N dias),
#     lead (prazo até vender; sem digitar vale o padrão provisório de ruptura_calculo.LEAD_TIME_PADRAO), ante (chegar N dias antes da ruptura; padrão 3), folga (dias de estoque que o envio acrescenta; sem digitar
#     vale o prazo, provisório) e estoque (digitado, opcional, só no detalhe). O Fora do Full usa os mesmos nomes com o sufixo `_f`. Só o Full tem caminho (=1: a opção "Contar o que está a caminho", que soma o
#     "a caminho" ao estoque lido do Full; desmarcada por padrão) e "Quem recomenda" (ref_urg, ref_qtd, qtd), porque o Mercado Livre só recomenda para o Full. Todos são lidos em ruptura_parametros.py.
#   - O Código ML é o estoque do Full: o detalhe de um Código ML só existe no mundo Full.
# LÊ SÓ DO BANCO (as vendas já coletadas pela tela de Vendas e a última consulta salva do estoque do Full) e NUNCA chama sozinha a API do Mercado Livre nem a do ERP (o ML só é chamado por CLIQUE, no botão "Consultar no Mercado Livre" da tabela de estoque; ver views_ruptura.view_ruptura_consultar). Nada do que a pessoa
# digita é guardado: fica só no endereço da página.
#
# REGRAS DO MATHEUS que moram aqui:
#   - O ritmo vem das vendas reais, com as MESMAS regras da tela de Vendas (vendas_ml.unidades_por_dia): só dias completos, venda cancelada não conta, "ausente não é zero".
#     Quem decide No Full / Fora do Full é a regra única de origem (vendas_ml.classificar_origem).
#   - O estoque do Full vem da última consulta salva de cada Código ML (ruptura_estoque.py: estoque considerado = disponível + em transferência + em processo interno; regra provisória).
#     Fora do Full o estoque ainda não tem fonte ligada: na lista fica em "—" e no detalhe ele é DIGITADO. Em qualquer mundo, o que for digitado vale no lugar do lido (para simular).
#   - O "a caminho" só entra no estoque quando a opção "Contar o que está a caminho" está marcada (ruptura_estoque.estoque_para_cobertura): como se já estivesse no Full hoje. Estoque
#     DIGITADO nunca recebe o a caminho: o que a pessoa digitou vale como está.
#   - O ritmo "dos últimos N dias" segue a regra do período da tela de Vendas: N dias completos + o dia de hoje (parcial, que fica fora da média).
#   - "Enviar até" (no Fora do Full, "Pedir até"): o envio tem que CHEGAR até `ante` dias (padrão 3) antes da ruptura: ruptura − prazo − ante. O último dia possível (ruptura − prazo) continua aparecendo no detalhe.
#     A sugestão do SISTEMA de "quanto enviar" é ritmo × folga: a nova ruptura passa a vir `folga` dias depois da atual (ruptura_calculo.sugestao_do_sistema).
#   - DUAS REFERÊNCIAS (decisão do Matheus, 12/10/2026): a URGÊNCIA e a QUANTIDADE a enviar podem vir do MERCADO LIVRE (lidas da consulta de reposição salva: ruptura_estoque.resumir_ml) ou do SISTEMA (a regra
#     da tela); a quantidade também pode ser DIGITADA ("Minha quantidade"). A escolhida manda no gráfico (linha verde "Com o envio") e nos cartões; a outra aparece pequena ao lado. Quando o ML não tem número,
#     a tela diz "sem número do ML": nunca vira urgência ou quantidade zero.
#
# * [EXPLICAÇÃO] → Cada peça mora no seu arquivo: ruptura_calculo.py (contas), ruptura_estoque.py (estoque do Full), ruptura_grafico.py (curva), ruptura_lista.py (lista do Full), ruptura_lista_fora.py (lista do Fora do Full) e ruptura_texto.py
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
from gestao_ruptura.funcoes_auxiliares.ruptura_lista_fora import montar_lista_fora
from gestao_ruptura.funcoes_auxiliares.ruptura_parametros import campos_escondidos, ler_comuns, nomes_do_mundo, para_url
from gestao_ruptura.funcoes_auxiliares.ruptura_avisos import aviso, organizar_avisos
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import (
    aviso_do_deposito, data as _data, data_do_ml, palavras, pct as _pct, plural as _plural, porque_da_urgencia_do_sistema, quantidade_do_ml, un_dia as _un_dia,
)
from gestao_vendas.funcoes_auxiliares.vendas_ml import numero, unidades_por_dia, url_da_tela

FUSO = ZoneInfo('America/Sao_Paulo')
ATALHOS_DE_DIAS = (7, 15, 30, 60, 90, 120)   # + "1 ano" (o máximo do Mercado Livre), montado em montar_pagina
# * [EXPLICAÇÃO] → Os DOIS MUNDOS da tela (o seletor do topo). Cada um tem as suas regras: no Full vale o estoque do Full, as vendas que saíram do Full e o prazo de abrir o Mercado Livre até a mercadoria chegar ao Full;
#                  fora do Full valem o estoque e as vendas de fora do Full e o prazo do pedido até a transportadora entregar para a gente. "Produto (tudo)" (soma dos dois) deixou de existir.
MUNDOS_DA_TELA = (
    ('full', 'Envios Full', 'Estoque do Full e vendas que saíram do Full. O prazo vai de abrir o Mercado Livre, planejar o envio, escolher a data e a coleta acontecer até a mercadoria chegar ao Full. É o único mundo com a recomendação do Mercado Livre.'),
    ('fora', 'Fora do Full', 'Estoque e vendas de fora do Full (coleta, agência, Flex). O prazo vai do pedido até a transportadora entregar para a gente. Na lista o estoque fica em "—" (ainda não há fonte ligada) e é digitado no item para simular.'),
)
ROTULO_DO_ESTOQUE = {'full': 'Estoque no Full', 'fora': 'Estoque fora do Full'}
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


# Função Objetivo: O texto do cartão "Enviar até" (no Fora do Full, "Pedir até"; e o do "title") para cada estado da data (ruptura_calculo.envio): `ok` (ainda dá tempo, chegando `ante` dias antes da ruptura), `hoje`
# (último dia para isso), `ja` (a data recomendada passou, mas ainda dá tempo: chega menos de `ante` dias antes da ruptura) e `vencido` (mesmo enviando hoje vai faltar estoque). `P` = as palavras do mundo
# (ruptura_texto.palavras). Devolve o cartão (tom, ícone, rótulo, valor, apoio, detalhe).
def _cartao_do_envio(envio, lead, ante, P):
    lead_txt, ante_txt = _plural(lead, 'dia', 'dias'), _plural(ante, 'dia', 'dias')
    regra = f'ruptura − prazo ({lead_txt}) − chegar antes ({ante_txt})' if ante else f'ruptura − prazo ({lead_txt})'
    rotulo = P['enviar_ate']
    if envio['estado'] == 'vencido':
        return _cartao('vermelho', 'fa-triangle-exclamation', rotulo, 'Prazo vencido', f'vai faltar {_plural(envio["faltam_dias"], "dia", "dias")}',
                       f'O prazo {P["do_envio"]} acabou em {_data(envio["ultimo_dia"])}: com prazo de {lead_txt}, mesmo {P["gerundio"]} hoje o produto só fica disponível em '
                       f'{_data(envio["chegada"])} e vão faltar cerca de {_plural(envio["faltam_dias"], "dia", "dias")} de estoque.')
    if envio['estado'] == 'ja':
        sobra = envio['sobra_na_chegada']
        quando = 'no próprio dia da ruptura' if sobra == 0 else f'{_plural(sobra, "dia", "dias")} antes da ruptura'
        return _cartao('laranja', 'fa-truck-fast', rotulo, P['enviar_ja'], 'chega no dia da ruptura' if sobra == 0 else f'chega {sobra} d antes',
                       f'A data recomendada ({_data(envio["enviar_ate"])} = {regra}) já passou, mas ainda dá tempo: {P["gerundio"]} hoje, o produto fica disponível em {_data(envio["chegada"])}, '
                       f'{quando} (o desejado é chegar {ante_txt} antes). O último dia possível é {_data(envio["ultimo_dia"])}.')
    ultimo = envio['estado'] == 'hoje'
    chega_txt = (f'{P["gerundio"].capitalize()} até essa data, o produto chega pelo menos {ante_txt} antes da ruptura. O último dia possível (chegando em cima da ruptura) é {_data(envio["ultimo_dia"])}.' if ante
                 else f'Com prazo de {lead_txt}, o produto fica disponível quando o estoque acabar.')
    return _cartao('laranja' if ultimo else 'verde', 'fa-truck-fast', rotulo, _data(envio['enviar_ate']),
                   'hoje, último dia' if ultimo else f'daqui a {_plural(envio["em_dias"], "dia", "dias")}',
                   f'Data recomendada = {regra}. {chega_txt}')


# Função Objetivo: O cartão "Quanto enviar" (no Fora do Full, "Quanto pedir") com a sugestão do SISTEMA (ruptura_calculo.sugestao_do_sistema): ritmo × folga, a quantidade que acrescenta `folga` dias de estoque
# (a nova ruptura vem `folga` dias depois da atual). Folga zero dá quantidade zero: cartão cinza que diz isso.
def _cartao_de_quanto_enviar(sug, media, lead, folga, P):
    ritmo_texto = f'{_un_dia(media)} un/dia'
    folga_txt = _plural(folga, 'dia', 'dias')
    if sug['qtd'] == 0:
        return _cartao('cinza', 'fa-circle-minus', P['quanto'], '0 un', 'folga de 0 dias',
                       f'A folga está em 0 dias: sem folga, {P["o_envio"]} não acrescenta estoque. Digite quantos dias de estoque {P["o_envio"]} deve acrescentar (campo Folga).')
    return _cartao('azul', 'fa-boxes-packing', P['quanto'], f'{numero(sug["qtd"])} un', f'dá {folga} d de folga',
                   f'Sugestão do Sistema: {numero(sug["qtd"])} un = ritmo ({ritmo_texto}) × folga ({folga_txt}). É a quantidade que acrescenta {folga_txt} de estoque: a nova ruptura passa a vir {folga_txt} depois '
                   f'da atual (ou depois da chegada, se o estoque acabar antes dela). O cartão "{P["com"]}" mostra a data.')


# Função Objetivo: O cartão "Com o envio" (no Fora do Full, "Com o pedido"): o que acontece com o estoque se a quantidade escolhida for enviada HOJE (ruptura_calculo.com_envio). A remessa chega em `lead` dias; o cartão
# mostra a data da NOVA ruptura e a folga que a quantidade dá. Verde = a quantidade acrescenta pelo menos a folga desejada; laranja = a remessa chega a tempo, mas acrescenta menos que a folga desejada;
# vermelho = o estoque atual acaba antes de a remessa chegar (vai faltar produto, e nenhuma quantidade conserta isso).
def _cartao_com_o_envio(com, lead, folga, hoje, P):
    chegada, nova = hoje + timedelta(days=lead), hoje + timedelta(days=com['dia_nova_ruptura'])
    dias_apos, dada = floor(com['dias_apos']), floor(round(com['folga_dada'], 6))
    base = (f'{P["gerundio"].capitalize()} {numero(com["qtd"])} un hoje, {P["a_remessa"]} chega em {_data(chegada)} (prazo de {_plural(lead, "dia", "dias")}). Nesse dia o estoque terá cerca de {numero(round(com["apos"]))} un '
            f'({numero(ceil(com["antes"]))} que sobram + {numero(com["qtd"])} {P["da_remessa"]}), o que dura cerca de {_plural(dias_apos, "dia", "dias")}: nova ruptura em {_data(nova)}.')
    if com['faltam'] > 0:
        return _cartao('vermelho', 'fa-circle-exclamation', P['com'], _data(nova), f'falta {com["faltam"]} d antes de chegar',
                       f'{base} Mas o estoque atual acaba antes de {P["a_remessa"]} chegar: vão faltar cerca de {_plural(com["faltam"], "dia", "dias")} de produto, e nenhuma quantidade conserta isso (só {P["verbo"]} mais cedo).')
    if dada >= folga:
        return _cartao('verde', 'fa-arrow-trend-up', P['com'], _data(nova), f'folga de {dada} d',
                       f'{base} Esta quantidade acrescenta {_plural(dada, "dia", "dias")} de estoque: a folga desejada ({_plural(folga, "dia", "dias")}) foi atingida.')
    return _cartao('laranja', 'fa-triangle-exclamation', P['com'], _data(nova), f'folga de {dada} d (meta {folga} d)',
                   f'{base} Esta quantidade acrescenta só {_plural(dada, "dia", "dias")} de estoque, abaixo da folga desejada ({_plural(folga, "dia", "dias")}).')


# Função Objetivo: O cartão "Urgência de envio": a urgência da referência escolhida (Mercado Livre ou Sistema) em destaque e a outra no apoio ("Sistema: Urgente"). O detalhe diz as duas e se concordam. Sem
# número do ML: "Sem número do ML" (cinza), nunca uma urgência inventada. `cat`/`envio` são os da projeção (para escrever o porquê da urgência do Sistema).
def _cartao_de_urgencia(ref_urg, urg_sistema, ml, cat, envio, P, mundo='full'):
    if ml is None:   # Fora do Full: o Mercado Livre não recomenda, só existe a urgência do Sistema
        selo_sistema = full.selo_da_urgencia(urg_sistema)
        if selo_sistema is None:
            return _cartao('cinza', 'fa-gauge', P['urgencia'], 'Sem leitura', '', 'Sistema: sem estoque informado.')
        return _cartao(TOM_DA_URGENCIA.get(urg_sistema, 'azul'), selo_sistema['icone'] or 'fa-gauge', P['urgencia'], selo_sistema['label'], 'regra do Sistema',
                       f'Sistema: {selo_sistema["label"]} — {porque_da_urgencia_do_sistema(cat, envio, mundo)}. Fora do Full só existe a urgência do Sistema (o Mercado Livre só recomenda para o Full).')
    urg_ml, ml_principal = ml['urgencia'], ref_urg == 'ml'
    selo_ml, selo_sistema = full.selo_da_urgencia(urg_ml), full.selo_da_urgencia(urg_sistema)
    selo, chave, outra, rotulo_outra = (selo_ml, urg_ml, selo_sistema, 'Sistema') if ml_principal else (selo_sistema, urg_sistema, selo_ml, 'ML')
    if selo_ml:
        prazo = f' O prazo para repor, segundo o ML, é {data_do_ml(ml["prazo"])}.' if ml['prazo'] else ''
        texto_ml = f'Mercado Livre: {selo_ml["label"]}.{prazo}'
    else:
        texto_ml = f'Mercado Livre: sem número ({ml["motivo"] or "a consulta não trouxe a urgência"}).'
    texto_sistema = f'Sistema: {selo_sistema["label"]} — {porque_da_urgencia_do_sistema(cat, envio, mundo)}.' if selo_sistema else 'Sistema: sem leitura do estoque.'
    if calc.urgencias_divergem(urg_sistema, urg_ml):
        comparacao = ' As duas referências estão em faixas diferentes: vale conferir os dois lados.'
    else:
        comparacao = ' As duas referências concordam.' if (selo_ml and selo_sistema) else ''
    detalhe = f'Referência escolhida: {"Mercado Livre" if ml_principal else "Sistema"}. {texto_ml} {texto_sistema}{comparacao}'
    apoio = f'{rotulo_outra}: {outra["label"] if outra else "sem número"}'
    if selo is None:
        return _cartao('cinza', 'fa-gauge', P['urgencia'], 'Sem número do ML' if ml_principal else 'Sem leitura', apoio, detalhe)
    return _cartao(TOM_DA_URGENCIA.get(chave, 'azul'), selo['icone'] or 'fa-gauge', P['urgencia'], selo['label'], apoio, detalhe)


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
def _cartoes_de_quanto_enviar(escolha, com, media, lead, folga, hoje, P, deposito=None):
    sug, ml = escolha['sugestao'], escolha['ml']
    if escolha['ref'] == 'ml':
        texto, dica = quantidade_do_ml(ml)
        do_sistema = f' A sugestão do Sistema é {numero(sug["qtd"])} un.' if sug else ''
        if texto is None:
            cartoes = [_cartao('cinza', 'fa-store', P['quanto'], 'Sem número do ML', 'sem consulta' if ml['estado'] == 'sem_dados' else '', f'{dica}{do_sistema}')]
        elif ml['nao_repor']:
            cartoes = [_cartao('verde', 'fa-circle-check', P['quanto'], 'Não repor', 'recomendação do ML', f'{dica}{do_sistema}')]
        else:
            cartoes = [_cartao('azul', 'fa-store', P['quanto'], f'{texto} un', 'sugestão do ML', f'{dica}{do_sistema}')]
    elif escolha['ref'] == 'manual':
        do_sistema = f' A sugestão do Sistema é {numero(sug["qtd"])} un.' if sug else ''
        if escolha['qtd'] is None:
            cartoes = [_cartao('cinza', 'fa-pen-to-square', P['quanto'], 'Digite a quantidade', '', f'Você escolheu "Minha quantidade", mas ainda não digitou quantas unidades quer enviar.{do_sistema}')]
        else:
            cartoes = [_cartao('azul', 'fa-pen-to-square', P['quanto'], f'{numero(escolha["qtd"])} un', 'sua quantidade', f'Quantidade digitada por você.{do_sistema}')]
    elif sug is not None:
        cartoes = [_cartao_de_quanto_enviar(sug, media, lead, folga, P)]
    else:
        cartoes = []
    if cartoes:
        _avisar_do_deposito(cartoes[0], escolha['qtd'], deposito)
    if com is not None:
        cartoes.append(_cartao_com_o_envio(com, lead, folga, hoje, P))
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


# Função Objetivo: A quantidade que vale para o gráfico e para os cartões: a sugestão do Sistema (referência "Sistema"), a do Mercado Livre (referência "Mercado Livre"; numa faixa vale o COMEÇO dela) ou
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


# Função Objetivo: O diagnóstico em cartões: a data de ruptura, até quando enviar (chegando `ante` dias antes da ruptura), a urgência (do Mercado Livre ou do Sistema; fora do Full só a do Sistema), quanto enviar
# (a sugestão do Sistema, a do ML ou a quantidade digitada), o que acontece com o envio, o que o ML recomenda (só no Full), o ponto de pedido, o ritmo recente contra o do período e, se a opção estiver marcada, o
# "a caminho" que já está na conta. O nível mostrado é o do ritmo do período escolhido. Sem ritmo ou sem estoque não há cartões: só o `resumo` (uma frase dizendo o que falta). `mundo` = 'full' | 'fora' (as palavras).
def _diagnostico(estoque, lead, ante, folga, dias, recente, ritmo_p, ritmo_r, mesmo_ritmo, hoje, a_caminho_somado=0, escolha=None, com=None, ml=None, ref_urg='sistema', deposito=None, mundo='full'):
    P = palavras(mundo)
    media = ritmo_p['media']
    sem = {'nivel': None, 'nivel_rotulo': '', 'cartoes': []}
    if media is None:
        return {**sem, 'resumo': f'Nenhum dia completo dos últimos {dias} foi coletado para este recorte: sem isso não dá para calcular o ritmo de vendas.'}
    ritmo_texto = f'{_un_dia(media)} un/dia'
    if estoque is None:
        return {**sem, 'resumo': f'O ritmo dos últimos {dias} dias é de {ritmo_texto}. Informe o estoque atual (e o prazo até vender) para ver a projeção.'}

    projecao = calc.projetar(estoque, media, hoje)
    situacao = projecao['situacao']
    nivel = calc.nivel_do_estoque(projecao, lead, folga)
    envio_do_item = calc.envio(projecao, lead, hoje, ante) if situacao == 'normal' and lead is not None else None
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

    # ---- 2) o envio, 3) quanto enviar e 4) o ponto de pedido (dependem do prazo, dos dias de antecedência e da folga) ----
    if lead is None:
        cartoes.append(_cartao('cinza', 'fa-truck-fast', P['enviar_ate'], 'Informe o prazo', '', 'Informe o prazo até vender para ver a data limite e o nível do estoque.'))
    elif situacao == 'zerado':
        quando = f'assim que for {P["enviado"]}' if lead == 0 else f'{_plural(lead, "dia", "dias")} depois d{P["o_envio"]}'
        cartoes.append(_cartao('vermelho', 'fa-truck-fast', P['acao_cartao'], 'O quanto antes', 'sem espera' if lead == 0 else f'demora {_plural(lead, "dia", "dias")}',
                               f'Com prazo de {_plural(lead, "dia", "dias")}, o produto só volta a ficar disponível {quando}: {P["verbo"]} o quanto antes.'))
    elif situacao == 'normal':
        cartoes.append(_cartao_do_envio(envio_do_item, lead, ante, P))
    else:
        cartoes.append(_cartao('cinza', 'fa-truck-fast', P['enviar_ate'], 'Sem data limite', '', f'Sem ruptura prevista neste ritmo: não há data limite {P["do_envio"]}.'))
    if lead is not None:
        if ml is not None or mundo == 'fora':
            cat_do_sistema = 'ruptura' if situacao == 'zerado' else 'normal'
            cartoes.append(_cartao_de_urgencia(ref_urg, calc.urgencia_do_sistema(cat_do_sistema, envio_do_item), ml, cat_do_sistema, envio_do_item, P, mundo))
        if escolha is not None and situacao in ('zerado', 'normal'):
            cartoes.extend(_cartoes_de_quanto_enviar(escolha, com, media, lead, folga, hoje, P, deposito))
        if ml is not None:
            cartoes.append(_cartao_do_ml(ml))
        if situacao == 'normal':
            pedido = calc.ponto_de_pedido(media, lead, ante)
            if pedido is not None:
                abaixo = estoque < media * (lead + ante)
                cartoes.append(_cartao('laranja' if abaixo else 'azul', 'fa-gauge-high', 'Ponto de pedido', f'{numero(pedido)} un', 'estoque abaixo dele' if abaixo else 'estoque acima dele',
                                       f'É o ritmo × (prazo + chegar antes): quanto se vende em {_plural(lead + ante, "dia", "dias")} ({lead} de prazo + {ante} para chegar antes da ruptura). '
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
def _dica_do_estoque(mundo, digitado, lido, resumo, rotulo, caminho=False):
    parcial = f' Atenção: o lido é parcial ({resumo["n_lidos"]} de {resumo["n_codigos"]} Códigos).' if (resumo is not None and resumo['estado'] == 'parcial' and mundo == 'full') else ''
    if digitado is not None:
        if lido is not None:
            aviso_caminho = ' O "a caminho" não é somado ao valor digitado.' if caminho else ''
            return {'texto': f'Usando o estoque DIGITADO: {numero(digitado)} un. O lido do Full é {numero(lido)} un: apague o campo para voltar ao lido.{aviso_caminho}', 'classe': 'atencao'}
        return {'texto': f'Usando o estoque DIGITADO: {numero(digitado)} un.', 'classe': 'atencao'}
    if mundo != 'full':
        return {'texto': f'{rotulo}: digite o valor (só o estoque do Full é lido; a API de estoque do ERP ainda será corrigida).', 'classe': 'atencao'}
    if lido is None:
        return {'texto': 'O estoque do Full deste item não foi lido (sem consulta salva). Digite o estoque para ver a projeção ou clique em "Consultar no Mercado Livre" na tabela de estoque, mais abaixo.', 'classe': 'atencao'}
    if caminho and resumo['a_caminho']:
        return {'texto': f'Usando o estoque lido do Full: {numero(resumo["considerado"])} un + {numero(resumo["a_caminho"])} a caminho = {numero(lido)} un.{parcial} Digite um valor para simular outro estoque.',
                'classe': 'atencao' if parcial else ''}
    sem_caminho = ' Sem o número de "a caminho" para este item: só o estoque do Full entra.' if caminho and resumo['a_caminho'] is None else ''
    return {'texto': f'Usando o estoque lido do Full: {numero(lido)} un (da última consulta salva).{sem_caminho}{parcial} Digite um valor para simular outro estoque.', 'classe': 'atencao' if parcial or sem_caminho else ''}


# Função Objetivo: As opções do seletor "Quantidade segundo" (era "Quanto enviar"; a referência da quantidade): [{chave, rotulo, dica, ativo}]. "Mercado Livre" usa a sugestão que o ML manda na consulta de reposição; "Sistema" usa
# a sugestão calculada pela regra da tela; "Minha quantidade" (só no detalhe de um item) usa o número que a pessoa digita, para criar a própria sugestão.
def _opcoes_de_quanto_enviar(ref, com_manual):
    opcoes = [
        ('ml', 'Mercado Livre', 'A quantidade que o Mercado Livre sugere (a mesma da tela "Full — Planejamento de envios", lida da última consulta de reposição salva). Numa faixa vale o começo dela.'),
        ('sistema', 'Sistema', 'A quantidade que o Sistema sugere: ritmo × folga, a que acrescenta a folga desejada de dias de estoque (a nova ruptura vem esses dias depois da atual).'),
    ]
    if com_manual:
        opcoes.append(('manual', 'Minha quantidade', 'Digite quantas unidades você quer enviar: a tela mostra o que acontece com o estoque (a linha verde do gráfico e o cartão "Com o envio").'))
    return [{'chave': chave, 'rotulo': rotulo, 'dica': dica, 'ativo': chave == ref} for chave, rotulo, dica in opcoes]


# Função Objetivo: As opções do seletor "Urgência segundo" (era "Referência de urgência"): de quem é a urgência que manda na ordem da lista e no selo grande (a outra aparece pequena ao lado).
def _opcoes_de_urgencia(ref):
    opcoes = (
        ('ml', 'Mercado Livre', 'A urgência que o Mercado Livre calcula (Urgente, Esta semana, Próxima semana, Em 2 semanas, Sem urgência, Excedente), lida da última consulta de reposição salva: a mesma da tela "Full — Planejamento de envios".'),
        ('sistema', 'Sistema', 'A urgência da regra desta tela, pela data de "Enviar até": hoje ou já passou = Urgente; em até 7 dias = Esta semana; até 14 = Próxima semana; até 21 = Em 2 semanas; depois = Sem urgência.'),
    )
    return [{'chave': chave, 'rotulo': rotulo, 'dica': dica, 'ativo': chave == ref} for chave, rotulo, dica in opcoes]


# Função Objetivo: Preenche `pagina` com o detalhe de UM item (o SKU, ou um MLB / Código ML dele) no mundo escolhido (Envios Full ou Fora do Full): quem é, o estoque (lido do Full ou digitado), o ritmo, os 4 cartões,
# a curva, o diagnóstico e, no Full, a tabela de estoque por Código ML. Item que não existe vira um aviso de erro (estado "erro"), nunca uma tela quebrada.
# * [EXPLICAÇÃO] → O Fora do Full NÃO lê estoque, NÃO consulta o Mercado Livre nem o ERP e não tem a recomendação do ML: o estoque é o digitado e a quantidade é sempre a sugestão do Sistema.
def _montar_detalhe(parametros, base_url, hoje, comuns, pagina, sku):
    dias, lead, ante, folga, recente, caminho = comuns['dias'], comuns['lead'], comuns['ante'], comuns['folga'], comuns['recente'], comuns['caminho']
    ref_qtd = comuns['ref_qtd']
    mundo = comuns['mundo']
    P, e_full = palavras(mundo), mundo == 'full'
    gran = _escolher(parametros, 'gran', GRANULARIDADES_DO_DETALHE, 'sku')
    item = sku if gran == 'sku' else (parametros.get('item') or '').strip().upper()
    estoque_digitado = comuns['estoque']
    # * [EXPLICAÇÃO] → O recorte das vendas: no SKU é o mundo escolhido (vendas do Full ou de fora do Full); no MLB é aquele anúncio, só a origem do mundo; no Código ML é aquele código só no Full
    #                  (o Código ML é o estoque do Full: venda do mesmo anúncio que saiu de outro lugar não é dele).
    nivel, origem = {'sku': (mundo, ''), 'mlb': ('mlb', mundo), 'codigo': ('codigo', 'full')}[gran]
    rotulo_do_estoque = ROTULO_DO_ESTOQUE[mundo]
    pagina.update({
        'estado': 'erro', 'sku': sku, 'gran': gran, 'item': item, 'rotulo_do_estoque': rotulo_do_estoque,
        'estoque_valor': '' if estoque_digitado is None else str(estoque_digitado), 'estoque_placeholder': 'unidades',
        'qtd_valor': '' if (ref_qtd != 'manual' or comuns['qtd'] is None) else str(comuns['qtd']), 'qtd_placeholder': 'un', 'qtd_ajuda': '',
        'ocultos': [{'nome': 'sku', 'valor': sku}] + ([{'nome': 'gran', 'valor': gran}, {'nome': 'item', 'valor': item}] if gran != 'sku' else []) + campos_escondidos(comuns, detalhe=True),
        'url_lista': url_da_tela(base_url, gran=gran if gran != 'sku' else None, **para_url(comuns)),
        'cartoes': [], 'grafico': None, 'diagnostico': None, 'alvo': None, 'tabela_de_codigos': None, 'dica_do_estoque': {'texto': '', 'classe': ''}, 'deposito': None,
        'url_consultar': reverse('gestao_ruptura_consultar'), 'chamadas_por_codigo': CHAMADAS_POR_CODIGO,
    })

    de = hoje - timedelta(days=max(dias, recente, max(calc.DIAS_DOS_RITMOS_DO_GRAFICO)))   # o gráfico compara 3, 7, 15 e 30 dias: as vendas desses dias já estão no banco (nada de API)
    dados = unidades_por_dia(sku, nivel, de, hoje, '' if gran == 'sku' else item, origem)
    cadastro = dados['cadastro']
    if cadastro is None:
        pagina['avisos'].append(aviso('erro', f'O SKU "{sku}" não está no cadastro de Produto', 'Confira o código: ele precisa ser igual ao da tela de Vendas.'))
        return
    mlbs_cad = cadastro['mlbs']
    codigos_do_sku = {c for m in mlbs_cad.values() for _, c in m['variacoes'] if c}
    if gran == 'mlb' and item not in mlbs_cad:
        pagina['avisos'].append(aviso('erro', f'O anúncio "{item}" não está entre os anúncios do SKU {sku}', 'Confira o MLB: ele precisa ser de um anúncio deste produto.'))
        return
    if gran == 'codigo' and item not in codigos_do_sku:
        pagina['avisos'].append(aviso('erro', f'O Código ML "{item}" não está entre os Códigos ML do SKU {sku}', 'Confira o Código ML: ele precisa ser de um anúncio deste produto.'))
        return
    codigos = codigos_do_sku if gran == 'sku' else ({c for _, c in mlbs_cad[item]['variacoes'] if c} if gran == 'mlb' else {item})
    mlbs_do_codigo = {c: sorted(m for m, info in mlbs_cad.items() if any(cc == c for _, cc in info['variacoes'])) for c in codigos}

    # ---- o estoque: lido do Full (só no mundo Full) ou digitado ----
    resumo = ml = deposito = lido = None
    if e_full:
        cartoes_do_full = estoque_full_dos_codigos(sorted(codigos)) if codigos else {}
        a_caminho_dos_codigos(cartoes_do_full)
        ml_dos_codigos(cartoes_do_full, guardar_no_cache=False)   # o que o Mercado Livre recomenda (urgência e sugestão): lê o cache dos resumos, sem trocá-lo pelo pedacinho deste item
        ml = full.resumir_ml(codigos, cartoes_do_full)
        resumo = full.somar_codigos(codigos, cartoes_do_full)
        full.preencher_a_caminho(resumo, codigos, cartoes_do_full)
        deposito = estoque_do_erp([sku]).get(sku)   # o estoque do ERP (depósito) do SKU: só para avisar quando a quantidade a enviar passa dele
        pagina['deposito'] = None if deposito is None else {'texto': f'{numero(deposito)} un', 'dica': 'O Estoque do cadastro do Produto no ERP (o depósito, de onde sai o que você envia ao Full). Vale para o SKU inteiro, mesmo quando você olha um anúncio ou um Código ML.'}
        lido = full.estoque_para_cobertura(resumo, caminho)   # com a opção marcada, já inclui o a caminho
        if codigos:
            pagina['tabela_de_codigos'] = _tabela_de_codigos(codigos, cartoes_do_full, mlbs_do_codigo, resumo, caminho)
    a_caminho_somado = (resumo['a_caminho'] or 0) if (e_full and caminho and lido is not None) else 0
    estoque = estoque_digitado if estoque_digitado is not None else lido
    a_caminho_somado = a_caminho_somado if estoque_digitado is None else 0   # o valor digitado vale como está: o a caminho não é somado a ele
    origem_do_estoque = 'digitado' if estoque_digitado is not None else (('lido do Full' + (' + a caminho' if a_caminho_somado else '')) if lido is not None else '')
    pagina['estoque_placeholder'] = numero(lido) if lido is not None else 'unidades'
    pagina['dica_do_estoque'] = _dica_do_estoque(mundo, estoque_digitado, lido, resumo, rotulo_do_estoque, caminho)

    def janela(n):   # n dias completos para trás + hoje
        return [hoje - timedelta(days=i) for i in range(n, -1, -1)]

    ritmo_p = calc.ritmo_da_janela(janela(dias), dados['por_dia'], dados['estados'])
    ritmo_r = calc.ritmo_da_janela(janela(recente), dados['por_dia'], dados['estados'])
    mesmo_ritmo = dias <= recente
    media = ritmo_p['media']
    n_ok = ritmo_p['n_completos']
    pagina['estado'] = 'ok'

    nivel_vendas = {'sku': mundo, 'mlb': 'mlb', 'codigo': 'codigo'}[gran]
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
        pagina['avisos'].append(aviso('erro', f'Nenhum dia completo dos últimos {dias} foi coletado para este recorte', 'Sem dias completos não dá para calcular o ritmo.',
                                      link=url_vendas, link_texto='Atualizar na tela de Vendas'))
    elif n_ok < dias:
        pagina['avisos'].append(aviso('aviso', 'dias completos na coleta de vendas deste recorte', f'Faltam dados de {dias - n_ok} dos últimos {dias} dias: a média usa só os {n_ok} dias completos que foram coletados.',
                                      numero_texto=f'{n_ok}/{dias}', link=url_vendas, link_texto='Atualizar na tela de Vendas'))

    # ---- os 4 cartões ----
    de_periodo = hoje - timedelta(days=dias)
    explicacao_periodo = (f'Média dos últimos {dias} dias (de {_data(de_periodo)} até ontem), só das vendas {P["vendas_de"]}. Só dias completos entram: hoje (parcial) e dias sem coleta ficam de fora; venda cancelada não conta.')
    explicacao_recente = f'Média dos últimos {recente} dias completos: mostra se o ritmo mudou há pouco tempo.'
    cartao_vendas = {'rotulo': f'Vendas nos últimos {dias} dias', 'destaque': False, 'nivel': None, 'nivel_rotulo': '', 'nivel_titulo': '', 'valor': f'{numero(ritmo_p["unidades"])} un',
                     'sub': f'média {_un_dia(media)} un/dia · {n_ok}/{dias} dias' if media is not None else 'nenhum dia completo coletado'}
    cartao_vendas['dica'] = f'{explicacao_periodo} Entraram {n_ok} dos {dias} dias; {cartao_vendas["sub"]}.'
    sub_estoque = f'{origem_do_estoque} · prazo de {_plural(lead, "dia", "dias")}' if estoque is not None else 'informe o estoque'
    cartao_estoque = {'rotulo': 'Estoque e prazo', 'destaque': False, 'nivel': None, 'nivel_rotulo': '', 'nivel_titulo': '', 'valor': '—' if estoque is None else f'{numero(estoque)} un',
                      'sub': sub_estoque}
    cartao_estoque['dica'] = (f'{rotulo_do_estoque} ({origem_do_estoque or "não informado"}) e prazo até vender ({_plural(lead, "dia", "dias")}; o envio deve chegar {_plural(ante, "dia", "dias")} antes da ruptura; folga de {_plural(folga, "dia", "dias")}). '
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
        return url_da_tela(base_url, sku=sku, gran=gran if gran != 'sku' else None, item=item if gran != 'sku' else None, **para_url(comuns, dias=n, detalhe=True)) + '#rup-grafico'

    def ritmo_de(n):
        if n == dias:
            return ritmo_p
        if n == recente:
            return ritmo_r
        return calc.ritmo_da_janela(janela(n), dados['por_dia'], dados['estados'])

    dias_do_grafico = sorted({n for n in calc.DIAS_DOS_RITMOS_DO_GRAFICO if n <= comuns['maximo']} | {dias})
    series = [{'dias': n, 'media': ritmo_de(n)['media'], 'url': endereco_do_ritmo(n)} for n in dias_do_grafico]
    # ---- quanto enviar: a sugestão do Sistema (ritmo × folga), a quantidade escolhida e o que acontece com o estoque se ela for enviada hoje ----
    sugestao = calc.sugestao_do_sistema(estoque, media, lead, folga)
    escolha = _quantidade_escolhida(comuns, sugestao, ml)
    com = calc.com_envio(estoque, media, lead, escolha['qtd'])
    if com:
        com = {**com, 'fonte': FONTE_DA_QUANTIDADE[ref_qtd]}   # o cartão da linha verde diz de quem é a quantidade (do Sistema, do Mercado Livre ou digitada)
    pagina['qtd_placeholder'] = numero(sugestao['qtd']) if sugestao else 'un'
    if ref_qtd == 'manual':
        pagina['qtd_ajuda'] = f'Digite quantas unidades enviar: a linha verde do gráfico e o cartão "{P["com"]}" mostram como o estoque fica.'
    elif ref_qtd == 'ml':
        texto_ml, _ = quantidade_do_ml(ml)
        pagina['qtd_ajuda'] = (f'Sugestão do Mercado Livre: {texto_ml} un' + (' (no gráfico vale o começo da faixa).' if '–' in texto_ml else '.')) if texto_ml else f'Sem número do ML ({ml["motivo"] or "sem sugestão de envio"}).'
    else:
        pagina['qtd_ajuda'] = (f'Sugestão do Sistema: {numero(sugestao["qtd"])} un (ritmo × {folga} d de folga).' if sugestao else 'Sem sugestão do Sistema (falta estoque ou ritmo).') if e_full else ''
    pagina['grafico'] = montar_grafico(estoque, lead, ante, series, dias, hoje, com, folga, mundo)
    pagina['diagnostico'] = _diagnostico(estoque, lead, ante, folga, dias, recente, ritmo_p, ritmo_r, mesmo_ritmo, hoje, a_caminho_somado, escolha, com, ml, comuns['ref_urg'], deposito, mundo)


# ==================================================== a página ====================================================

# Função Objetivo: Junta os avisos da página e os da lista num só conjunto e entrega a CAIXA pronta (`pagina['avisos_caixa']`): a ordem, o agrupamento e os resumos são do dono único dos avisos (ruptura_avisos.organizar_avisos).
# Com 2 ou mais avisos (e nenhum de erro) eles vão AGRUPADOS numa caixa recolhida de uma linha, para não empurrar os cartões e a tabela para baixo; erro nunca fica escondido (aí cada aviso é uma faixa).
def _organizar_avisos(pagina):
    todos = list(pagina['avisos']) + (list(pagina['lista']['avisos']) if pagina['lista'] else [])
    pagina['avisos_caixa'] = organizar_avisos(todos)


# Função Objetivo: Os textos do cartão "Regras" que mudam de um mundo para o outro (título, apoio, "?", etiquetas dos campos e a conta em palavras do rodapé), já com os números de agora. As frases do
# Full falam de ENVIO ao Full; as do Fora do Full, de PEDIDO. A folga é a mesma ideia nos dois: "estou mandando este envio e quero ter X dias de estoque de folga".
# * [EXPLICAÇÃO] → O PERÍODO do ritmo ("de 12/09/2026 até hoje") mora aqui, no apoio do campo "Vendas dos últimos N dias" (decisão do Matheus, 12/10/2026): o dono dos valores do ritmo são os cartões de controle, e a lista
#                  não repete mais uma linha de contexto com eles.
def _textos_do_mundo(mundo, lead, ante, folga, dias, hoje):
    P = palavras(mundo)
    full_ = mundo == 'full'
    de = _data(hoje - timedelta(days=dias))
    ate = P['enviar_ate']
    enviar_ate = f'ruptura − {lead} d (prazo) − {ante} d (chegar antes)' if ante else f'ruptura − {lead} d (prazo)'
    return {
        'regras_titulo': 'Regras de envio ao Full' if full_ else 'Regras de pedido',
        'regras_sub': 'Quando e quanto enviar' if full_ else 'Quando e quanto pedir',
        'prazo_dica': ('Prazo até vender: o tempo desde o ZERO, ou seja, desde abrir o Mercado Livre, planejar o envio, escolher a data, a coleta acontecer e a mercadoria chegar ao Full. Entra no "Enviar até" e no nível do estoque.' if full_
                       else 'Prazo até vender: o tempo entre fazer o pedido e a transportadora entregar para a gente. Entra no "Pedir até" e no nível do estoque.'),
        'prazo_apoio': 'Do planejamento do envio até chegar ao Full.' if full_ else 'Do pedido até a entrega para a gente.',
        'ante_dica': (f'Chegar antes da ruptura: {P["o_envio"]} tem que chegar até {ante} dias ANTES de o estoque acabar de vez, para nunca ficarmos sem venda, mas também para não mandar envios muito antes e sobrecarregar o estoque. '
                      f'{ate} = ruptura − prazo − este número.'),
        'ante_apoio': f'Dias antes da ruptura em que {P["o_envio"]} chega.',
        'folga_dica': ('Folga: "estou mandando este envio e quero ter X dias de estoque de folga". É quantos dias de estoque o envio ACRESCENTA: com a ruptura em 15/10 e folga de 15 dias, a sugestão leva a nova ruptura para 30/10. '
                       'Quantidade sugerida = ritmo × folga. Ainda não foi definida: enquanto você não digitar, vale o prazo (provisório).'),
        'folga_apoio': f'Dias de estoque que {P["o_envio"]} acrescenta (nova ruptura).',
        'folga_provisoria_dica': 'Você ainda não digitou a folga: está valendo o padrão provisório da tela (o prazo). Esse número depende do responsável pelo Full.',
        'regra_texto': f'{ate} = {enviar_ate}. Quantidade sugerida = ritmo × {folga} d de folga: a nova ruptura vem {folga} d depois da atual.',
        'regra_enviar_ate': enviar_ate,
        'regra_quantidade': f'ritmo × {folga} d (a ruptura vai {folga} d para frente)',
        'vendas_dica': ('Quantos dias de vendas entram na média por dia (o "ritmo"). Só contam os dias completos e só o que saiu do Full.' if full_
                        else 'Quantos dias de vendas entram na média por dia (o "ritmo"). Só contam os dias completos e só o que saiu de fora do Full.'),
        'ritmo_apoio': f'De {de} até hoje · média por dia que projeta a ruptura.',
        'ritmo_apoio_dica': f'A média de vendas por dia (o "ritmo"), de {de} até ontem (hoje é parcial e não entra), projeta quando o estoque acaba: estoque ÷ ritmo = quantos dias o estoque dura.',
    }


# Função Objetivo: O endereço de um mundo (para o seletor "Envios Full | Fora do Full"): leva os parâmetros dos DOIS mundos (trocar de mundo não perde o que foi digitado no outro) e o que identifica a tela
# (o item aberto no detalhe; a busca, a situação, o "Divergem" e a ordem na lista).
def _endereco_do_mundo(base_url, parametros, comuns, chave, sku, gran, item):
    destino = {**comuns, 'mundo': chave}
    if sku:
        identificacao = {'sku': sku, 'gran': gran if gran != 'sku' else None, 'item': item if gran != 'sku' else None}
    else:
        identificacao = {k: (parametros.get(k) or '').strip() or None for k in ('gran', 'q', 'nivel', 'diverge', 'ord', 'por')}
    return url_da_tela(base_url, **identificacao, **para_url(destino, detalhe=bool(sku)))


# Função Objetivo: Tudo da tela a partir da query string. Sem SKU: a LISTA do mundo escolhido (Full: ruptura_lista.montar_lista; Fora do Full: ruptura_lista_fora.montar_lista_fora). Com SKU: o DETALHE de um item (_montar_detalhe). Os parâmetros comuns (ritmo, prazo, chegar antes, folga e "a caminho") são lidos em ruptura_parametros.ler_comuns; o prazo e a folga, sem digitar,
# são padrões PROVISÓRIOS e a tela avisa isso ao lado de cada campo.
def montar_pagina(parametros, base_url, hoje=None):
    hoje = hoje or datetime.now(FUSO).date()
    sku = (parametros.get('sku') or '').strip()
    if sku and (parametros.get('gran') or '').strip() == 'codigo' and (parametros.get('mundo') or '').strip() == 'fora':
        parametros = parametros.copy()   # copy() (e não dict(parametros.items())): os filtros do Hub têm vários valores por parâmetro e dict() ficaria só com o último
        parametros['mundo'] = 'full'   # o Código ML é o estoque do Full: não existe "fora do Full" para ele
    comuns = ler_comuns(parametros, hoje)
    mundo, P = comuns['mundo'], palavras(comuns['mundo'])
    dias, lead, ante, folga, maximo = comuns['dias'], comuns['lead'], comuns['ante'], comuns['folga'], comuns['maximo']
    pagina = {
        'modo': 'detalhe' if sku else 'lista', 'url_ruptura': base_url, 'hoje': hoje, 'mundo': mundo, 'e_full': mundo == 'full', 'palavras': P, 'nomes': nomes_do_mundo(mundo),
        'dias_valor': str(dias), 'lead_valor': str(lead), 'caminho': comuns['caminho'],
        'lead_e_padrao': comuns['lead_digitado'] is None or comuns['lead_digitado'] == calc.LEAD_TIME_PADRAO,   # o formulário reenvia o "7" já preenchido: continua sendo o padrão provisório
        'ante_valor': str(ante),
        # * [EXPLICAÇÃO] → O campo "Folga" fica VAZIO enquanto vale o padrão (o prazo, mostrado em cinza dentro do campo): assim, ao mudar o prazo, ele acompanha. Só um valor digitado fixa o número.
        'folga_dias': folga, 'folga_texto': _plural(folga, 'dia', 'dias'), 'folga_valor': '' if comuns['folga_digitada'] is None else str(comuns['folga_digitada']), 'folga_placeholder': str(folga),
        'folga_e_padrao': comuns['folga_digitada'] is None,
        'txt': _textos_do_mundo(mundo, lead, ante, folga, dias, hoje),
        'avisos': [], 'lista': None, 'estado': 'lista', 'ocultos': [],
        # * [EXPLICAÇÃO] → Os dois seletores de referência só existem no Full (o Mercado Livre só recomenda para o Full) e na lista e no detalhe. "Minha quantidade" só existe no detalhe de um item (a lista não tem quantidade digitada: lá vale "Sistema").
        'urg_opcoes': _opcoes_de_urgencia(comuns['ref_urg']),
        'qtd_opcoes': _opcoes_de_quanto_enviar(comuns['ref_qtd'] if (sku or comuns['ref_qtd'] != 'manual') else 'sistema', bool(sku)),
        'atalhos': [{'dias': d, 'rotulo': str(d), 'ativo': d == dias} for d in ATALHOS_DE_DIAS] + [{'dias': maximo, 'rotulo': '1 ano', 'ativo': dias == maximo}],
        'maximo_de_dias': maximo,
    }
    if comuns['dias_pedidos'] and comuns['dias_pedidos'] > maximo:
        pagina['avisos'].append(aviso('info', 'O Mercado Livre guarda cerca de 12 meses de pedidos', f'O ritmo usa {dias} dias (o máximo disponível).'))
    if sku:
        _montar_detalhe(parametros, base_url, hoje, comuns, pagina, sku)
    elif mundo == 'full':
        pagina['lista'] = montar_lista(parametros, base_url, hoje, comuns)
    else:
        pagina['lista'] = montar_lista_fora(parametros, base_url, hoje, comuns)
    gran, item = pagina.get('gran', ''), pagina.get('item', '')
    pagina['mundos'] = [{'chave': chave, 'rotulo': rotulo, 'dica': dica, 'ativo': chave == mundo,
                         'desativado': bool(sku) and gran == 'codigo' and chave == 'fora',
                         'url': _endereco_do_mundo(base_url, parametros, comuns, chave, sku, gran, item)} for chave, rotulo, dica in MUNDOS_DA_TELA]
    _organizar_avisos(pagina)
    return pagina
