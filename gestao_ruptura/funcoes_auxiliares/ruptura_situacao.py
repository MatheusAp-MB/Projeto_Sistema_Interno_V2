# gestao_ruptura/funcoes_auxiliares/ruptura_situacao.py
#
# Função Objetivo: O DONO ÚNICO da faixa "Situação" da lista da tela "Previsão de Ruptura de estoque" (12/10/2026): os CARTÕES DE SITUAÇÃO (como se chamam, o que dizem embaixo, como se agrupam, quanto cada um conta e a explicação
# deles, o "?") e os INDICADORES DE DADOS (o quanto dá para confiar nos números: vendas coletadas e estoque consultado). A lista do Full e a do Fora do Full só PEDEM estas coisas por aqui; os templates
# (parciais/estrutura_parcial_situacao.html e estrutura_parcial_dados.html) só DESENHAM o que sai daqui. Só texto e contagem: nada de banco, API ou conta de ruptura (as contas ficam em ruptura_calculo.py).
#
# REGRAS DO MATHEUS que moram aqui:
#   - A faixa responde, NESTA ORDEM, a três perguntas: "o que precisa de ação agora?" (os cartões, em grupos), "posso confiar nesses números?" (os indicadores de dados) e "o que cada cartão quer dizer?" (o "?").
#   - Item com o estoque zerado fica em "Em ruptura" MESMO sem venda no período (decisão do Matheus, 12/10/2026): não há grupo separado para "zerado sem venda".
#   - As regras da conta (ritmo, prazo, chegar antes, folga) NÃO se repetem aqui: o dono delas são os cartões de controle do topo (estrutura_parcial_controles.html).
#
# * [EXPLICAÇÃO] → Os cartões dividem a lista em categorias que NÃO se sobrepõem: a soma dos seis dá o total ("Todos"). Estão em 3 grupos pelo que a pessoa faz com eles: "Pedem ação" (Em ruptura, Crítico, Baixo), "Tranquilo" (Alto) e
#                  "Não analisados" (Sem vendas e Sem estoque lido: o sistema não tem como calcular a ruptura). "Divergem" NÃO é uma situação: é um filtro à parte que COMBINA com qualquer cartão (por isso fica fora dos grupos).
# * [EXPLICAÇÃO] → As contagens seguem o que se vê (faceta): os seis cartões e o "Todos" contam os itens da busca já cortados pelo "Divergem" (quando ligado); o "Divergem" conta os divergentes dentro da situação escolhida.
# * [EXPLICAÇÃO] → "Sem vendas" (chave sem_previsao, a mesma da URL) é o item que TEM estoque e não vendeu nada nos dias completos do período: é estoque parado, e não falta de dado. Só quando NENHUM dia do período foi coletado
#                  (a conta toda, por isso é o mesmo para todos os itens) o cartão passa a se chamar "Sem previsão": aí o motivo é falta de coleta de vendas, e não do item.

from gestao_full.funcoes_auxiliares.full_estoque_ml import HORAS_PARA_DESATUALIZADO
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import plural
from gestao_vendas.funcoes_auxiliares.vendas_ml import numero

CHAVES_DE_NIVEL = ('ruptura', 'critico', 'baixo', 'alto', 'sem_previsao', 'sem_estoque')   # as chaves do filtro "nivel" da URL; "divergem" não é uma delas (é o parâmetro "diverge")
GRUPOS_DOS_CARTOES = (
    ('acao', 'Pedem ação', ('ruptura', 'critico', 'baixo')),
    ('tranquilo', 'Tranquilo', ('alto',)),
    ('nao_analisados', 'Não analisados', ('sem_previsao', 'sem_estoque')),
)
ANCORA = 'rup-situacao'   # o clique num cartão recarrega a página: o endereço leva este #id para a pessoa continuar vendo a faixa (e não voltar ao topo)


# Função Objetivo: O nome, o apoio (a linha embaixo do número) e a explicação de cada cartão, já com os números de agora. `sem_dados` = nenhum dia do período está completo na coleta de vendas.
# * [EXPLICAÇÃO] → Todos os apoios de "dura..." falam em DIAS, do mesmo jeito: crítico = menos que o prazo, baixo = do prazo até prazo + folga, alto = mais que isso (os níveis PROVISÓRIOS de ruptura_calculo.nivel_do_estoque).
def _textos_dos_niveis(lead, folga, sem_dados):
    limite = lead + folga
    dias_do_prazo = plural(lead, 'dia', 'dias')
    dias_do_limite = plural(limite, 'dia', 'dias')
    critico = f'dura menos de {dias_do_prazo}' if lead >= 1 else 'dura menos que o prazo'
    if sem_dados:
        sem_previsao = ('Sem previsão', 'nenhum dia do período coletado',
                        'Nenhum dia do período foi coletado da conta toda: sem ritmo de vendas não dá para prever a ruptura. Colete o período na tela de Vendas.')
    else:
        sem_previsao = ('Sem vendas', 'tem estoque e não vendeu no período',
                        'Tem estoque, mas o Full não vendeu nada nos dias completos do período: o estoque não acaba neste ritmo (é estoque parado, não falta de dado).')
    return {
        'ruptura': ('Em ruptura', 'estoque zerado no Full', 'O estoque do Full está zerado. Conta mesmo que o item não tenha vendido no período.'),
        'critico': ('Crítico', critico, f'O estoque dura menos que o prazo ({dias_do_prazo}): mesmo enviando hoje, a remessa chega depois de o estoque acabar.'),
        'baixo': ('Baixo', f'dura de {lead} a {dias_do_limite}', f'O estoque dura do prazo até o prazo + a folga ({lead} a {dias_do_limite}): está na hora de planejar o envio.'),
        'alto': ('Alto', f'dura mais de {dias_do_limite}', f'O estoque dura mais de {dias_do_limite} neste ritmo.'),
        'sem_previsao': sem_previsao,
        'sem_estoque': ('Sem estoque lido', 'estoque ainda não consultado',
                        'Nenhum Código ML do item tem consulta de estoque salva. Não é estoque zero: é estoque desconhecido. Faça a consulta na tela "Estoque no Full".'),
    }


# Função Objetivo: A faixa "Situação" pronta para o template: o título (com o total), o cartão "Todos", os 3 grupos de cartões, o filtro "Divergem" e o texto do "?".
# `base` = as linhas da lista depois da BUSCA (cada uma com `cat` e `diverge`); `filtro` = a situação escolhida ('todos' ou uma de CHAVES_DE_NIVEL); `diverge` = o filtro "Divergem" está ligado;
# `url(**mudancas)` = o dono dos endereços da lista (ruptura_lista.montar_lista); `sem_dados` = nenhum dia completo.
def montar_situacao(base, filtro, diverge, url, unidade_plural, unidade_singular, lead, folga, sem_dados):
    textos = _textos_dos_niveis(lead, folga, sem_dados)
    na_situacao = [l for l in base if l['diverge'] or not diverge]
    contagem = {chave: sum(1 for l in na_situacao if l['cat'] == chave) for chave in CHAVES_DE_NIVEL}
    total = len(na_situacao)
    n_diverge = sum(1 for l in base if l['diverge'] and (filtro == 'todos' or l['cat'] == filtro))

    def ancorado(endereco):
        return f'{endereco}#{ANCORA}'

    def cartao(chave):
        rotulo, apoio, _ = textos[chave]
        n = contagem[chave]
        return {'chave': chave, 'rotulo': rotulo, 'apoio': apoio, 'n': numero(n), 'vazio': n == 0, 'ativo': filtro == chave,
                'url': ancorado(url(nivel='todos' if filtro == chave else chave))}

    titulo = (f'Situação do 1 {unidade_singular}' if total == 1 else f'Situação dos {numero(total)} {unidade_plural}') + ((' que diverge' if total == 1 else ' que divergem') if diverge else '')
    ajuda = [{'rotulo': textos[chave][0], 'texto': textos[chave][2]} for _, _, chaves in GRUPOS_DOS_CARTOES for chave in chaves]
    ajuda.append({'rotulo': 'Divergem', 'texto': 'Itens em que a urgência do Mercado Livre e a do Sistema estão em faixas diferentes. Não é uma situação: combina com qualquer cartão (escolha, por exemplo, "Em ruptura" e depois "Divergem").'})
    return {
        'id': ANCORA, 'titulo': titulo,
        'todos': {'n': numero(total), 'ativo': filtro == 'todos', 'url': ancorado(url(nivel='todos'))},
        'grupos': [{'chave': chave, 'rotulo': rotulo, 'cartoes': [cartao(c) for c in chaves]} for chave, rotulo, chaves in GRUPOS_DOS_CARTOES],
        'divergem': {'n': numero(n_diverge), 'vazio': n_diverge == 0 and not diverge, 'ativo': diverge, 'url': ancorado(url(diverge=None if diverge else '1'))},
        'ajuda': ajuda,
        'ajuda_nota': 'Os níveis (crítico, baixo, alto) são provisórios: dependem do prazo e da folga dos cartões de Regras de envio. Clicar num cartão mostra só aqueles itens; clicar de novo volta a mostrar todos.',
    }


# ==================================================== os indicadores de dados ====================================================

# Função Objetivo: O indicador das VENDAS ("posso confiar no ritmo?"): quantos dos últimos N dias estão completos na coleta da conta toda e quando ela foi atualizada. `classe` = ok (verde) | parcial (âmbar) | vazio (vermelho).
# * [EXPLICAÇÃO] → A idade da coleta já está contida na conta: um dia só conta como completo se foi coletado DEPOIS de acabar, então coleta velha derruba o "30/30" e o indicador fica âmbar sozinho.
def indicador_de_vendas(n_completos, n_dias, nada_coletado, ultima):
    if nada_coletado:
        return {'classe': 'vazio', 'icone': 'fa-database', 'texto': 'Vendas: nada coletado neste período', 'dica': 'Nenhum dia do período foi coletado da conta toda.', 'link': ''}
    completo = n_completos >= n_dias
    return {'classe': 'ok' if completo else 'parcial', 'icone': 'fa-circle-check' if completo else 'fa-circle-exclamation',
            'texto': f'Vendas: {n_completos}/{n_dias} dias completos · atualizadas {ultima}',
            'dica': f'O ritmo usa a coleta da CONTA TODA: {n_completos} de {n_dias} dias completos (coletados depois que o dia acabou; hoje nunca é completo). Hoje e dias parciais não entram na média por dia.', 'link': ''}


# Função Objetivo: Conta as consultas de estoque dos Códigos ML da lista (`cartoes` = estoque_full_dos_codigos): quantos têm leitura, quantos nunca foram consultados, quantos deram erro e quantos têm a consulta antiga
# (mais de HORAS_PARA_DESATUALIZADO h). É a MESMA conta do indicador de estoque e dos avisos "Código ML sem consulta / com erro / com consulta antiga": ela mora só aqui.
def contar_consultas(cartoes):
    estados = [c['estado'] for c in cartoes.values()]
    return {'total': len(estados), 'lidas': estados.count('ok'), 'sem_consulta': estados.count('sem_consulta'), 'erro': estados.count('erro'),
            'antigas': sum(1 for c in cartoes.values() if c['estado'] == 'ok' and c['desatualizado'])}


# Função Objetivo: O indicador do ESTOQUE ("o estoque que a lista usa está em dia?"): None quando a lista não tem nenhum Código ML. Verde = todos com consulta de até HORAS_PARA_DESATUALIZADO h; âmbar = algum sem consulta, com erro
# ou com consulta antiga (com link para a tela "Estoque no Full", onde se atualiza); vermelho = nenhum Código com estoque lido.
# * [EXPLICAÇÃO] → O estoque é o que mais pesa em "Em ruptura" (zerado = ruptura) e vem da ÚLTIMA consulta salva: por isso a idade dela aparece aqui, ao lado dos cartões, e não só na caixa de avisos.
def indicador_de_estoque(consultas, link):
    total = consultas['total']
    if not total:
        return None
    partes = []
    if consultas['sem_consulta']:
        partes.append(f'{numero(consultas["sem_consulta"])} sem consulta')
    if consultas['erro']:
        partes.append(f'{numero(consultas["erro"])} com erro')
    if consultas['antigas']:
        partes.append(f'{numero(consultas["antigas"])} com consulta antiga')
    if not partes:
        return {'classe': 'ok', 'icone': 'fa-circle-check', 'texto': 'Estoque: consultas em dia',
                'dica': f'Os {plural(total, "Código ML", "Códigos ML")} desta lista têm a consulta de estoque salva nas últimas {HORAS_PARA_DESATUALIZADO} h.', 'link': ''}
    return {'classe': 'vazio' if not consultas['lidas'] else 'parcial', 'icone': 'fa-circle-exclamation', 'texto': 'Estoque: ' + ' · '.join(partes),
            'dica': f'Dos {plural(total, "Código ML", "Códigos ML")} desta lista: {" · ".join(partes)} (consulta antiga = mais de {HORAS_PARA_DESATUALIZADO} h). O estoque do Full vem da última consulta salva: clique para abrir a tela "Estoque no Full" e atualizar.',
            'link': link}
