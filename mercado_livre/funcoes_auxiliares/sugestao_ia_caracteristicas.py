# mercado_livre/funcoes_auxiliares/sugestao_ia_caracteristicas.py
#
# Função Objetivo: Botão "Sugerir com IA" da tela "Características dos anúncios" — pede ao Claude
# (Haiku 5.5, esforço low) sugestões de valor para os campos de UM produto e confere cada sugestão
# antes de a tela mostrar. A IA NUNCA escreve no Mercado Livre nem na tela sozinha: ela só devolve
# sugestões; quem aceita é a pessoa (botão "Aceitar" do card) e quem envia é o "Revisar e enviar".
#
# * [EXPLICAÇÃO] → O fluxo, em 4 passos:
#   1) montar_pedido(): monta o texto que vai para a IA — dados do produto (título, marca, descrição do
#      cadastro, títulos dos anúncios) e uma LINHA por campo EDITÁVEL (id, nome, tipo, opções/unidades/
#      limite). Marca e campos de vários valores não entram (a tela não os edita).
#   2) UMA chamada à API, só deste produto. Nunca em lote.
#   3) A resposta vem num formato FIXO (JSON schema — a API garante que o JSON é válido). O formato é o
#      mesmo para todo produto, de propósito: um formato novo por produto teria de ser "compilado" pela
#      API toda vez e tem limites de campos opcionais.
#   4) validar_respostas(): cada sugestão é conferida contra as regras do card (a opção existe? a
#      unidade é permitida? o texto cabe no limite?) E contra o texto do cadastro (a evidência é um
#      trecho de verdade? o número está nela? "Não" tem uma negação? a opção é citada?). O que não
#      passa é DESCARTADO — nunca chega à tela.
#
# * [DECISÃO, 15/10/2026] → Prompt reescrito com base nas boas práticas da documentação da Anthropic
#   (instrução direta com o PORQUÊ das regras, tags XML, exemplos que incluem "não devolver", dados no
#   topo e pedido no fim, citar o trecho ANTES de dar o valor). Por isso, no formato de resposta,
#   "evidencia" vem ANTES de "valor": a API devolve as propriedades na ordem do schema, então a IA
#   escreve a citação primeiro e só depois o valor. Técnica de prompt não elimina invenção — por isso
#   o servidor confere tudo (item 4) e descarta o que não tem prova no texto.
#
# * [DECISÃO, 15/10/2026] → A IA não recebe mais o "hoje" (valores que os anúncios já têm): na primeira
#   chamada real ela repetia esses valores sem a descrição sustentar. Agora a única fonte é o texto do
#   cadastro; menos texto no pedido também = menos tokens.
#
# * [PLANO B] → Se a API recusar o pedido com saída estruturada (erro 400 — a documentação não diz
#   explicitamente que ela vale com raciocínio desligado + esforço low), repete UMA vez pedindo o JSON
#   só no texto do prompt e valida tudo no código. Erro 400 não é cobrado. O resultado informa qual
#   modo foi usado ("estruturada" ou "prompt").
#
# * [IMPORTANTE] → Cliente sem tentativas automáticas (max_retries=0): cada clique é UMA chamada paga,
#   nunca repetida em silêncio. A chave nunca é escrita em lugar nenhum nem devolvida à tela.
#   `import anthropic` só acontece dentro de _criar_cliente: se a biblioteca faltar, só este botão avisa.
#   Quem GRAVA o resultado no banco é a view (sugestoes_ia_salvas.py); este módulo não grava nada.

import html
import json
import os
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation

VARIAVEL_CHAVE = 'ANTHROPIC_API_KEY'
VARIAVEL_WORKSPACE = 'ANTHROPIC_WORKSPACE_ID'

# Decisão de 14/10/2026: padrão em TODO uso da IA no sistema = menor modelo, menor esforço.
MODELO_ID = 'claude-haiku-5-5'
ROTULO_MODELO = 'Haiku 5.5'
ESFORCO = 'low'

# * [EXPLICAÇÃO] → Cada sugestão ocupa ~45 tokens (campo + trecho de até 12 palavras + valor); 65 campos
#   no máximo ≈ 3.000 tokens. O Haiku 5.5 gasta ~30% mais tokens que o 4.5 para o mesmo texto, então
#   4.096 dá folga sem abrir a porta para um gasto grande (teto de ~US$ 0,002 por chamada só na saída).
MAX_TOKENS_SAIDA = 4096
TIMEOUT_SEGUNDOS = 60.0

# Tarifas em USD por 1 milhão de tokens (documentação oficial, 12/10/2026 — as mesmas de
# integracao_claude/config_claude.py). Acima de 100 mil tokens de entrada a tarifa é maior.
LIMITE_ENTRADA_TARIFA_BAIXA = 100_000
TARIFA_ENTRADA_ATE_100K = Decimal('0.10')
TARIFA_SAIDA_ATE_100K = Decimal('0.50')
TARIFA_ENTRADA_ACIMA_100K = Decimal('0.50')
TARIFA_SAIDA_ACIMA_100K = Decimal('2.50')
MILHAO = Decimal('1000000')

MAX_OPCOES_POR_CAMPO = 300     # lista maior que isso vai cortada (a IA é avisada); a conferência usa a lista inteira
MAX_EXEMPLOS_POR_CAMPO = 30
MAX_CARACTERES_DESCRICAO = 8000
MAX_TITULOS_DE_ANUNCIOS = 6
MIN_CARACTERES_DE_TEXTO = 20   # menos que isso de texto do cadastro: nem vale chamar a IA (não há o que ler)

# * [EXPLICAÇÃO] → Limites da conferência (validar_respostas):
#   - evidência com 3+ palavras pode ter até 15% de palavras fora do texto (IA que pula uma palavra
#     ao copiar); com menos de 3 palavras tem de bater inteira;
#   - texto livre: pelo menos 75% das palavras do valor têm de existir no cadastro; número + unidade
#     ("12 V", "12V") conta como certo só se a evidência traz esse número seguido dessa unidade
#     ("12 volts") — o "8 V" de "8 amperes" não passa;
#   - o número sugerido pode diferir do número da evidência só por uma potência de 10 (conversão
#     simples de unidade: 1.200 g → 1,2 kg);
#   - campo "lista" (ex.: cor): se a evidência veio dos TÍTULOS dos anúncios e eles citam outra opção
#     da mesma lista (um "Laranja", outro "Amarelo"), a IA não pode escolher por eles: descarta;
#   - campo Sim/Não: a evidência tem de citar as palavras do NOME do campo (um trecho sobre "válvula
#     interna" não prova "Válvula de segurança") e "Não" ainda exige uma palavra de negação. Se a IA
#     citou o trecho errado mas o cadastro TEM uma frase com todas as palavras do campo (sem negação
#     para o "Sim"), o servidor usa essa frase como evidência; se não tem, descarta;
#   - peso e medidas: a evidência não pode falar de produto cheio/carregado/"operacional" nem de
#     embalagem (o "1,2 kg com o reservatório cheio" não é o peso do produto).
COBERTURA_MINIMA_DA_EVIDENCIA = 0.85
COBERTURA_MINIMA_DO_TEXTO_LIVRE = 0.75
FATORES_DE_CONVERSAO = (
    Decimal('1'), Decimal('10'), Decimal('100'), Decimal('1000'),
    Decimal('0.1'), Decimal('0.01'), Decimal('0.001'),
)
PALAVRAS_DE_NEGACAO = frozenset({
    'nao', 'sem', 'nenhum', 'nenhuma', 'nunca', 'livre', 'isento', 'isenta', 'desprovido', 'desprovida',
})
# Palavras do nome de um campo Sim/Não que não identificam o recurso ("Pilhas incluídas", "Tipo de ...").
PALAVRAS_GENERICAS_DO_CAMPO = frozenset({'produto', 'tipo', 'item', 'itens', 'para', 'possui', 'acompanha'})
# Abreviação de unidade → começo da palavra por extenso ("12 V" vale quando o texto diz "12 volts").
ABREVIACOES_DE_UNIDADE = {
    'v': 'volt', 'w': 'watt', 'kw': 'watt', 'a': 'amper', 'ah': 'amper', 'mah': 'amper', 'hz': 'hertz',
    'l': 'litro', 'ml': 'mililitr', 'kg': 'quilo', 'g': 'grama', 'mm': 'milimetr', 'cm': 'centimetr',
    'm': 'metro', 'bar': 'bar', 'psi': 'psi', 'db': 'decibel',
}
UNIDADES_DE_PESO_E_MEDIDA = frozenset({'g', 'kg', 'lb', 'oz', 'mm', 'cm', 'm', 'ft', '"'})
PALAVRAS_DE_MEDIDA_QUE_NAO_E_DO_PRODUTO = frozenset({
    'embalagem', 'pacote', 'operacional', 'cheio', 'cheia', 'abastecido', 'abastecida',
    'carregado', 'carregada', 'bruto', 'bruta',
})

# * [EXPLICAÇÃO] → O prompt segue as boas práticas da documentação da Anthropic: papel + objetivo no
#   começo; o PORQUÊ da regra mais importante (para a IA decidir bem nos casos que as regras não
#   cobrem); tags XML separando as partes; regras positivas e numeradas; exemplos variados, com os
#   casos em que NÃO se devolve; formato no fim. Os dados do produto e a lista de campos vão na
#   mensagem do usuário (dados no topo, pedido no fim). Mexer aqui = mexer no comportamento da IA:
#   teste com um produto real antes de confiar.
PROMPT_DO_SISTEMA = """Você preenche a ficha técnica de UM produto de anúncios do Mercado Livre Brasil, usando apenas o texto do cadastro dele.

<por_que_importa>
O que você devolver vira valor de anúncio real, visto por compradores. Um valor errado prejudica a venda; um campo sem resposta não custa nada (a pessoa preenche depois). Por isso, na dúvida, NÃO devolva o campo. Devolver pouco e certo é o objetivo.
</por_que_importa>

<fonte>
A única fonte é o bloco <produto> da mensagem (título, marca, títulos dos anúncios e descrição). Os títulos dos anúncios valem tanto quanto a descrição (costumam trazer cor, capacidade e quantidade); se eles divergirem entre si sobre um dado, não devolva esse dado. Não use conhecimento sobre a marca ou o modelo, nem o que "costuma ser" nesse tipo de produto.
</fonte>

<regras>
1. Devolva um campo só se o texto afirma o valor com clareza. Se for preciso deduzir ou adivinhar, não devolva.
2. Todo campo devolvido traz em "evidencia" o trecho do texto copiado exatamente como está (até 12 palavras). Só o trecho: nada de explicação ou comentário. Se não existe um trecho que prove o valor, não devolva o campo.
3. Campo Sim/Não: o trecho citado tem de falar do recurso que o campo pergunta (use as palavras do nome do campo). Não citar o recurso NÃO significa "Não". Responda "Não" só se o texto negar de forma explícita (ex.: "não acompanha", "sem válvula"); responda "Sim" só se o texto afirmar esse mesmo recurso — uma peça parecida não vale (uma "válvula interna" não é "válvula de segurança").
4. Material, cor e tipo: use só o que o texto diz sobre AQUELA peça. Não generalize de uma peça para outra (ex.: "tanque de plástico" não diz o material do bico nem o do corpo). Se os títulos dos anúncios citam duas opções diferentes do mesmo campo (ex.: "Laranja" num título e "Amarelo" noutro), não devolva o campo.
5. Medidas: copie o número que o texto dá para aquela característica. Não calcule, não estime e não confunda a medida do produto com a da embalagem, do pacote ou da caixa, nem com a do produto cheio, carregado ou "operacional" (o "peso com o reservatório cheio" não é o peso do produto). Se o texto não deixa claro a que a medida se refere, não devolva.
6. Campo "lista": "valor" é o id de UMA opção, copiado da lista do próprio campo. Se nenhuma opção corresponde com exatidão, não devolva. Se a lista veio cortada, só devolva se a opção certa estiver nela.
7. Campo "número com unidade": "valor" é só o número (ponto decimal, sem separador de milhar: 1200, 5.8) e "unidade" é uma das permitidas. Use a unidade do texto quando ela for permitida; converta (g↔kg, mm↔cm↔m, ml↔L) só quando a do texto não for permitida.
8. Campo "número": "valor" é só o número; "unidade" vai vazia.
9. Campo "texto": "valor" curto, no padrão do Mercado Livre, dentro do limite de caracteres, sem emoji e sem repetir o nome do campo, com palavras que existam no texto. Se houver "exemplos" e um deles for o que o texto diz, use-o exatamente. "unidade" vai vazia.
10. Cada campo aparece no máximo uma vez na resposta, e nunca com "valor" vazio: campo sem resposta simplesmente não entra.
</regras>

<exemplos>
Texto do produto: "Pulverizador manual de jardim 2 litros, tanque em polipropileno. Peso: 1.200 g. Embalagem: 20 x 30 cm."
Campos:
TYPE | Tipo | lista | 111=Manual; 112=Elétrico
CAPACITY | Capacidade | número com unidade | unidades: L, mL
WEIGHT | Peso | número com unidade | unidades: g, kg
WITH_VALVE | Válvula | lista | 10=Sim; 11=Não
DIAMETER | Diâmetro | número com unidade | unidades: cm, mm
BODY_MATERIAL | Material do corpo | lista | 31=Plástico; 32=Metal
Resposta certa:
{"sugestoes":[{"campo":"TYPE","evidencia":"Pulverizador manual de jardim","valor":"111","unidade":""},{"campo":"CAPACITY","evidencia":"2 litros","valor":"2","unidade":"L"},{"campo":"WEIGHT","evidencia":"Peso: 1.200 g","valor":"1200","unidade":"g"}]}
Ficaram de fora de propósito: WITH_VALVE (o texto não fala de válvula, e não falar não é "Não"), DIAMETER (20 x 30 cm é a embalagem, não o produto) e BODY_MATERIAL (o polipropileno é do tanque, e o texto não diz de que é o corpo).

Texto do produto: "Lanterna recarregável de luz branca. Não acompanha pilhas."
Campos:
INCLUDES_BATTERIES | Pilhas incluídas | lista | 10=Sim; 11=Não
LIGHT_COLOR | Cor da luz | lista | 41=Branca; 42=Amarela
MODEL | Modelo | texto | até 255 caracteres
Resposta certa:
{"sugestoes":[{"campo":"INCLUDES_BATTERIES","evidencia":"Não acompanha pilhas","valor":"11","unidade":""},{"campo":"LIGHT_COLOR","evidencia":"luz branca","valor":"41","unidade":""}]}
MODEL ficou de fora: o texto não traz modelo.
</exemplos>

<formato>
Responda somente com o JSON {"sugestoes":[{"campo":"ID","evidencia":"trecho copiado","valor":"...","unidade":""}]}, sem texto fora dele. Se o texto não prova nenhum campo, responda {"sugestoes":[]}.
</formato>"""

# * [EXPLICAÇÃO] → O formato da resposta é o MESMO para qualquer produto (ver o cabeçalho).
#   A API só aceita este subconjunto de JSON schema: tudo obrigatório e additionalProperties=false.
#   A ORDEM das propriedades importa: a API as devolve nessa ordem, então "evidencia" (a citação
#   do texto) é escrita antes de "valor".
ESQUEMA_DA_RESPOSTA = {
    'type': 'object',
    'properties': {
        'sugestoes': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'campo': {'type': 'string'},
                    'evidencia': {'type': 'string'},
                    'valor': {'type': 'string'},
                    'unidade': {'type': 'string'},
                },
                'required': ['campo', 'evidencia', 'valor', 'unidade'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['sugestoes'],
    'additionalProperties': False,
}


class ErroSugestaoIA(Exception):
    """Erro já explicado em português para a tela (mensagem) com o status HTTP que a view devolve."""

    def __init__(self, mensagem, status=502, detalhe=''):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.detalhe = detalhe


class _Fonte(str):
    """O texto do cadastro (tudo junto) + as partes dele — a conferência precisa saber se uma evidência
    veio dos títulos dos anúncios ou da descrição. Para quem só lê, é uma string comum."""
    titulos = ()
    descricao = ''


class _SugestaoInvalida(Exception):
    pass


# ─── CONFIGURAÇÃO ────────────────────────────────────────────────────────

def _valor_do_env(nome):
    return (os.environ.get(nome) or '').strip()


# Função Objetivo: A chave da API está no .env? Não chama a internet — só decide se o botão fica ligado.
def ia_configurada():
    return bool(_valor_do_env(VARIAVEL_CHAVE))


def _criar_cliente():
    # * [EXPLICAÇÃO] → Função à parte só para os testes trocarem o cliente por um falso. O cabeçalho do
    #   workspace só vai se existir no .env (chave presa a um workspace não precisa dele).
    try:
        import anthropic
    except ImportError as erro:
        raise ErroSugestaoIA(
            'A biblioteca "anthropic" não está instalada neste ambiente do sistema.', 503, str(erro),
        ) from erro
    workspace = _valor_do_env(VARIAVEL_WORKSPACE)
    return anthropic.Anthropic(
        api_key=_valor_do_env(VARIAVEL_CHAVE),
        default_headers={'anthropic-workspace-id': workspace} if workspace else None,
        max_retries=0,
        timeout=TIMEOUT_SEGUNDOS,
    )


# ─── TEXTO: normalização e índice de palavras ────────────────────────────

def _normalizar(texto):
    texto = unicodedata.normalize('NFKD', str(texto if texto is not None else ''))
    texto = ''.join(letra for letra in texto if not unicodedata.combining(letra))
    return re.sub(r'\s+', ' ', texto).strip().casefold()


def _limpar_texto(texto):
    return re.sub(r'\s+', ' ', str(texto if texto is not None else '')).strip()


# Função Objetivo: Quebra um texto em palavras "comparáveis": sem acento, sem maiúscula, sem pontuação.
# Números iguais viram a mesma palavra qualquer que seja o jeito de escrever: "1.200" e "1200" (milhar)
# e "1,5" e "1.5" (decimal).
def _palavras(texto):
    texto = _normalizar(texto)
    texto = re.sub(r'(?<=\d)\.(?=\d{3}(?!\d))', '', texto)
    texto = re.sub(r'(?<=\d)[.,](?=\d)', 'd', texto)
    return re.findall(r'[a-z0-9]+', texto)


class _Indice:
    """As palavras de um texto, prontas para perguntar "esta palavra / este trecho está aqui?"."""

    def __init__(self, texto):
        self.texto = str(texto if texto is not None else '')
        self.palavras = _palavras(texto)
        self.conjunto = set(self.palavras)
        self.juncao = f' {" ".join(self.palavras)} '
        # Prefixo de 4 letras das palavras com 5+ letras: "preta" e "preto" casam, "metal" e "metalica" também.
        self.prefixos = {palavra[:4] for palavra in self.palavras if len(palavra) >= 5}

    def tem_palavra(self, palavra):
        if palavra in self.conjunto:
            return True
        return len(palavra) >= 5 and palavra[:4] in self.prefixos

    def tem_trecho(self, palavras):
        return bool(palavras) and f' {" ".join(palavras)} ' in self.juncao

    def cobertura(self, palavras):
        if not palavras:
            return 0.0
        return sum(1 for palavra in palavras if self.tem_palavra(palavra)) / len(palavras)


# ─── PEDIDO ──────────────────────────────────────────────────────────────

# Função Objetivo: A descrição do cadastro vem "bruta" do ERP (pode ter HTML e linhas em excesso).
def _preparar_descricao(descricao):
    if not descricao:
        return ''
    texto = re.sub(r'(?i)<br\s*/?>|</(p|div|li|tr|h[1-6])>', '\n', str(descricao))
    texto = html.unescape(re.sub(r'<[^>]+>', ' ', texto))
    texto = re.sub(r'[ \t\r\f\v]+', ' ', texto)
    texto = re.sub(r' ?\n[\s]*', '\n', texto).strip()     # tira espaços em volta das quebras e as linhas em branco
    return texto[:MAX_CARACTERES_DESCRICAO]


def _sem_separadores(texto):
    # Os separadores da linha do campo ("|" e ";") não podem aparecer dentro dos nomes.
    return _limpar_texto(str(texto or '').replace('|', '/').replace(';', ','))


# Função Objetivo: A linha de UM campo no pedido: "ID | Nome | tipo | detalhes". Uma linha por campo
# gasta bem menos tokens que o mesmo campo em JSON e é mais fácil de a IA ler.
def _linha_do_campo(card):
    base = f"{card['atributo_id']} | {_sem_separadores(card['label'])}"
    tipo = card['tipo']
    if tipo == 'lista':
        pares = card.get('opcoes_pares') or []
        opcoes = '; '.join(f"{par['id']}={_sem_separadores(par['name'])}" for par in pares[:MAX_OPCOES_POR_CAMPO])
        aviso = ' (lista cortada: só devolva se a opção certa estiver aqui)' if len(pares) > MAX_OPCOES_POR_CAMPO else ''
        return f'{base} | lista | {opcoes}{aviso}'
    if tipo == 'numero_unidade':
        unidades = ', '.join(str(u) for u in (card.get('unidades') or []))
        return f'{base} | número com unidade | unidades: {unidades}'
    if tipo == 'numero':
        return f'{base} | número'
    detalhe = f"até {card.get('limite') or 255} caracteres"
    if tipo == 'texto_sugestoes' and card.get('opcoes_exibidas'):
        exemplos = '; '.join(_sem_separadores(e) for e in card['opcoes_exibidas'][:MAX_EXEMPLOS_POR_CAMPO])
        detalhe += f' | exemplos: {exemplos}'
    return f'{base} | texto | {detalhe}'


# Função Objetivo: Monta o pedido de UM produto a partir da ficha (que já foi lida só do banco).
# Devolve (prompt_do_sistema, mensagem_do_usuario, campos_editaveis_por_id, texto_do_cadastro) — o
# último é a FONTE contra a qual validar_respostas confere as evidências.
def montar_pedido(ficha, descricao):
    produto = ficha['produto']
    campos = {}
    linhas = []
    for card in ficha['cards']:
        if not card.get('editavel'):
            continue
        campos[card['atributo_id']] = card
        linhas.append(_linha_do_campo(card))

    titulos = []
    for linha in ficha['tabela']['linhas']:
        titulo = _limpar_texto(linha.get('titulo'))
        if titulo and titulo not in titulos:
            titulos.append(titulo)
    titulos = titulos[:MAX_TITULOS_DE_ANUNCIOS]

    titulo_produto = _limpar_texto(produto.get('titulo'))
    marca = _limpar_texto(produto.get('marca'))
    descricao_limpa = _preparar_descricao(descricao)

    partes = ['<produto>']
    if titulo_produto:
        partes.append(f'<titulo>{titulo_produto}</titulo>')
    if marca:
        partes.append(f'<marca>{marca}</marca>')
    if titulos:
        partes.append('<titulos_dos_anuncios>\n' + '\n'.join(titulos) + '\n</titulos_dos_anuncios>')
    if descricao_limpa:
        partes.append(f'<descricao>\n{descricao_limpa}\n</descricao>')
    partes.append('</produto>')
    partes.append('<campos>\n' + '\n'.join(linhas) + '\n</campos>')
    partes.append(
        'Preencha só os campos de <campos> que o texto de <produto> prova, com o trecho copiado em '
        '"evidencia". Campo sem prova no texto fica de fora.'
    )
    mensagem = '\n\n'.join(partes)

    fonte = _Fonte('\n'.join([titulo_produto, marca, *titulos, descricao_limpa]))
    fonte.titulos = tuple(titulos)
    fonte.descricao = descricao_limpa
    return PROMPT_DO_SISTEMA, mensagem, campos, fonte


# ─── CONFERÊNCIA DAS SUGESTÕES ───────────────────────────────────────────

def _ler_numero(bruto):
    texto = str(bruto if bruto is not None else '').strip().replace(' ', '')
    if not texto:
        return None
    if ',' in texto and '.' in texto:      # "1.234,5" (pt-BR)
        texto = texto.replace('.', '').replace(',', '.')
    else:
        texto = texto.replace(',', '.')
    if not re.fullmatch(r'\d+(\.\d+)?', texto):
        return None
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        return None
    return numero if numero > 0 else None


def _formatar_numero(numero):
    # Como a pessoa digitaria no card (vírgula decimal); o envio aceita vírgula ou ponto.
    return format(numero.normalize(), 'f').replace('.', ',')


# Função Objetivo: Converte a sugestão da IA no formato que o card sabe preencher
# ({valor_id} | {numero, unidade} | {numero} | {texto}) e no texto que aparece no card.
# Levanta _SugestaoInvalida (com o motivo) quando a sugestão não respeita a regra do campo.
def _converter(card, item):
    tipo = card['tipo']
    bruto = item.get('valor')

    if tipo == 'lista':
        valor = _limpar_texto(bruto)
        pares = card.get('opcoes_pares') or []
        por_id = {par['id']: par['name'] for par in pares}
        if valor in por_id:
            return {'valor_id': valor}, por_id[valor]
        achados = [par for par in pares if _normalizar(par['name']) == _normalizar(valor)]
        if len(achados) == 1:
            return {'valor_id': achados[0]['id']}, achados[0]['name']
        raise _SugestaoInvalida('a opção sugerida não existe na lista deste campo')

    if tipo in ('numero_unidade', 'numero'):
        numero = _ler_numero(bruto)
        if numero is None:
            raise _SugestaoInvalida('o valor sugerido não é um número válido')
        texto_numero = _formatar_numero(numero)
        if tipo == 'numero':
            return {'numero': texto_numero}, texto_numero

        unidades = list(card.get('unidades') or [])
        unidade_bruta = _limpar_texto(item.get('unidade'))
        achadas = [u for u in unidades if _normalizar(u) == _normalizar(unidade_bruta)] if unidade_bruta else []
        if achadas:
            unidade = achadas[0]
        elif len(unidades) == 1:
            unidade = unidades[0]
        else:
            raise _SugestaoInvalida('a unidade sugerida não é uma das permitidas neste campo')
        return {'numero': texto_numero, 'unidade': unidade}, f'{texto_numero} {unidade}'

    texto = _limpar_texto(bruto)
    if not texto:
        raise _SugestaoInvalida('o texto sugerido veio vazio')
    limite = card.get('limite') or 255
    if len(texto) > limite:
        raise _SugestaoInvalida(f'o texto sugerido passa do limite de {limite} caracteres')
    return {'texto': texto}, texto


# Função Objetivo: Os números que a evidência contém, em todas as leituras possíveis ("1.200" = 1200 ou
# 1,2; "1,5" = 1,5). Serve para conferir que o número sugerido saiu do texto e não foi inventado.
def _numeros_da_evidencia(evidencia):
    candidatos = set()
    for bruto in re.findall(r'\d+(?:[.,]\d+)*', str(evidencia or '')):
        if re.fullmatch(r'\d{1,3}(\.\d{3})+', bruto):
            candidatos.add(Decimal(bruto.replace('.', '')))
        if re.fullmatch(r'\d{1,3}(\.\d{3})+,\d+', bruto):
            candidatos.add(Decimal(bruto.replace('.', '').replace(',', '.')))
        if re.fullmatch(r'\d+([.,]\d+)?', bruto):
            candidatos.add(Decimal(bruto.replace(',', '.')))
    return candidatos


def _numero_esta_na_evidencia(numero, evidencia):
    for candidato in _numeros_da_evidencia(evidencia):
        for fator in FATORES_DE_CONVERSAO:
            if abs(numero - candidato * fator) < Decimal('0.000001'):
                return True
    return False


_NUMERO = re.compile(r'\d+(?:d\d+)?')


def _numero_seguido_da_unidade(numero, unidade, palavras_da_evidencia):
    inicio = ABREVIACOES_DE_UNIDADE.get(unidade, unidade)
    colado = re.compile(rf'(?<!\d){re.escape(numero)}{re.escape(unidade)}(?![a-z])')
    for i, palavra in enumerate(palavras_da_evidencia):
        if colado.search(palavra):                           # "12v", "12v20ah"
            return True
        if palavra == numero and i + 1 < len(palavras_da_evidencia):
            proxima = palavras_da_evidencia[i + 1]
            if proxima == unidade or proxima.startswith(inicio):
                return True
    return False


# Função Objetivo: Procura no cadastro UMA frase (ou linha de título) que fale do recurso de um campo
# Sim/Não: tem todas as palavras do nome do campo e, para "Sim", nenhuma palavra de negação (para
# "Não", tem de ter uma). Devolve a frase (até 12 palavras ao redor do recurso) ou None.
def _frase_que_prova_o_recurso(palavras_do_campo, resposta, texto):
    melhor = None
    for segmento in re.split(r'[\n.;!?•]+', texto):
        palavras = _palavras(segmento)
        if not palavras or len(palavras) > 40:               # linha enorme (ex.: lista de tags) não prova nada
            continue
        indice = _Indice(segmento)
        if not all(indice.tem_palavra(palavra) for palavra in palavras_do_campo):
            continue
        if (resposta == 'nao') != bool(set(palavras) & PALAVRAS_DE_NEGACAO):
            continue
        if melhor is None or len(palavras) < len(melhor[0]):
            melhor = (palavras, segmento)
    if melhor is None:
        return None
    termos = _limpar_texto(melhor[1]).split(' ')
    posicao = next((i for i, termo in enumerate(termos) if any(_Indice(termo).tem_palavra(p) for p in palavras_do_campo)), 0)
    inicio = max(0, min(posicao - 4, len(termos) - 12))
    return ' '.join(termos[inicio:inicio + 12])


# Função Objetivo: Quanto (de 0 a 1) das palavras de um VALOR de texto livre está provado no cadastro.
# Palavra comum: tem de existir no cadastro. Número solto: tem de existir no cadastro E na evidência.
# Número + unidade ("12 V", "12V"): a evidência tem de trazer esse número seguido dessa unidade.
def _cobertura_do_texto_livre(palavras_valor, fonte, indice_evidencia):
    partes = []
    for palavra in palavras_valor:
        colada = re.fullmatch(r'(\d+(?:d\d+)?)([a-z]{1,3})', palavra)      # "12v" → "12" + "v"
        if colada and not fonte.tem_palavra(palavra):
            partes.extend([colada.group(1), colada.group(2)])
        else:
            partes.append(palavra)
    certas = 0
    i = 0
    while i < len(partes):
        palavra = partes[i]
        seguinte = partes[i + 1] if i + 1 < len(partes) else ''
        if _NUMERO.fullmatch(palavra) and seguinte in ABREVIACOES_DE_UNIDADE:
            # número + unidade valem juntos (2 palavras): a evidência tem de trazer "12 volts" / "12v" / "12v20ah"
            certas += 2 * _numero_seguido_da_unidade(palavra, seguinte, indice_evidencia.palavras)
            i += 2
            continue
        if _NUMERO.fullmatch(palavra):
            certas += fonte.tem_palavra(palavra) and indice_evidencia.tem_palavra(palavra)
        else:
            certas += fonte.tem_palavra(palavra)
        i += 1
    return certas / len(partes) if partes else 0.0


# Função Objetivo: Segunda barreira — confere a sugestão (já no formato do card) contra o TEXTO do
# cadastro. A IA já foi instruída a só devolver o que o texto prova; aqui o servidor não confia nisso
# e exige a prova. Levanta _SugestaoInvalida com o motivo.
def _conferir_com_o_texto(card, item, valor, texto_do_card, fonte, partes=None):
    evidencia = _limpar_texto(item.get('evidencia'))
    palavras_evidencia = _palavras(evidencia)
    if not palavras_evidencia:
        raise _SugestaoInvalida('veio sem o trecho do cadastro que justifica o valor')

    ok_trecho = fonte.tem_trecho(palavras_evidencia) or (
        len(palavras_evidencia) >= 3 and fonte.cobertura(palavras_evidencia) >= COBERTURA_MINIMA_DA_EVIDENCIA
    )
    if not ok_trecho:
        raise _SugestaoInvalida('o trecho citado como evidência não está no texto do cadastro')

    tipo = card['tipo']
    indice_evidencia = _Indice(evidencia)

    if tipo == 'lista':
        palavras_opcao = _palavras(texto_do_card)
        if palavras_opcao in (['sim'], ['nao']):
            if palavras_opcao == ['nao'] and not (set(palavras_evidencia) & PALAVRAS_DE_NEGACAO):
                raise _SugestaoInvalida('respondeu "Não" sem o texto negar de forma explícita')
            do_campo = []       # palavras do nome do campo que identificam o recurso (normalizadas)
            faltaram = []       # …e as que a evidência não tem (como estão escritas no nome do campo)
            for original in re.findall(r'[^\W_]+', str(card.get('label', ''))):
                palavra = ''.join(_palavras(original))
                if len(palavra) >= 4 and palavra not in PALAVRAS_GENERICAS_DO_CAMPO and not palavra.startswith('inclu'):
                    do_campo.append(palavra)
                    if not indice_evidencia.tem_palavra(palavra):
                        faltaram.append(original)
            if faltaram:
                frase = _frase_que_prova_o_recurso(do_campo, palavras_opcao[0], fonte.texto)
                if frase:
                    return frase                     # evidência corrigida pelo servidor
                nome = str(card.get('label', ''))
                complemento = '' if _normalizar(' '.join(faltaram)) == _normalizar(nome) else f' (o campo é "{nome}")'
                raise _SugestaoInvalida(f'o trecho citado não fala de "{" ".join(faltaram)}"{complemento} e nenhuma frase do cadastro fala')
            return
        com_letras = [p for p in palavras_opcao if re.fullmatch(r'[a-z]{4,}', p)]
        if com_letras and not any(indice_evidencia.tem_palavra(p) for p in com_letras):
            raise _SugestaoInvalida('a opção sugerida não é citada na evidência')
        if partes is not None:
            indice_titulos, indice_descricao = partes
            if not indice_descricao.tem_trecho(palavras_evidencia):        # a evidência veio dos títulos
                outras = [
                    par['name'] for par in (card.get('opcoes_pares') or [])
                    if _palavras(par['name']) != palavras_opcao and indice_titulos.tem_trecho(_palavras(par['name']))
                ]
                if outras:
                    raise _SugestaoInvalida(
                        f'os títulos dos anúncios citam mais de uma opção ({texto_do_card} e {outras[0]}): escolha você'
                    )
        return

    if tipo in ('numero_unidade', 'numero'):
        numero = _ler_numero(texto_do_card.split(' ')[0].replace(',', '.'))
        if numero is None or not _numero_esta_na_evidencia(numero, evidencia):
            raise _SugestaoInvalida('o número sugerido não aparece na evidência')
        eh_peso_ou_medida = bool({_normalizar(u) for u in (card.get('unidades') or [])} & UNIDADES_DE_PESO_E_MEDIDA)
        if eh_peso_ou_medida and (
            set(palavras_evidencia) & PALAVRAS_DE_MEDIDA_QUE_NAO_E_DO_PRODUTO or indice_evidencia.tem_trecho(['capacidade', 'maxima'])
        ):
            raise _SugestaoInvalida('o trecho fala de produto cheio/carregado ou de embalagem, não do produto em si')
        return

    palavras_valor = _palavras(valor.get('texto', ''))
    if palavras_valor and _cobertura_do_texto_livre(palavras_valor, fonte, indice_evidencia) < COBERTURA_MINIMA_DO_TEXTO_LIVRE:
        raise _SugestaoInvalida('o texto sugerido não vem do texto do cadastro')


# Função Objetivo: Confere cada sugestão da IA. Devolve ({atributo_id: sugestão}, [ignoradas]).
# Fica só a PRIMEIRA sugestão de cada campo; campo inexistente/não editável ou valor fora da regra
# é descartado e aparece em "ignoradas" (para a pessoa saber que a IA tentou). `texto_do_cadastro`
# é a fonte (devolvida por montar_pedido); sem ela só valem as regras do card (usado em testes).
def validar_respostas(campos, itens, texto_do_cadastro=None):
    fonte = _Indice(texto_do_cadastro) if texto_do_cadastro is not None else None
    partes = None
    if fonte is not None and getattr(texto_do_cadastro, 'titulos', None):
        partes = (_Indice(' \n '.join(texto_do_cadastro.titulos)), _Indice(getattr(texto_do_cadastro, 'descricao', '')))
    sugestoes = {}
    ignoradas = []
    for item in itens if isinstance(itens, list) else []:
        if not isinstance(item, dict):
            continue
        campo_id = _limpar_texto(item.get('campo'))
        card = campos.get(campo_id) or campos.get(campo_id.upper())
        if card is None:
            ignoradas.append({'campo': campo_id or '?', 'nome': '', 'motivo': 'esse campo não existe ou não é editável nesta ficha'})
            continue
        atributo_id = card['atributo_id']
        if atributo_id in sugestoes:
            continue
        evidencia_corrigida = None
        try:
            valor, texto = _converter(card, item)
            if fonte is not None:
                evidencia_corrigida = _conferir_com_o_texto(card, item, valor, texto, fonte, partes)
        except _SugestaoInvalida as erro:
            ignoradas.append({'campo': atributo_id, 'nome': card['label'], 'motivo': str(erro)})
            continue
        sugestoes[atributo_id] = {
            'valor': valor,
            'texto': texto,
            'evidencia': (evidencia_corrigida or _limpar_texto(item.get('evidencia')))[:200],
        }
    return sugestoes, ignoradas


# ─── CUSTO ───────────────────────────────────────────────────────────────

def calcular_custo_usd(tokens_entrada, tokens_saida):
    if tokens_entrada <= LIMITE_ENTRADA_TARIFA_BAIXA:
        tarifa_entrada, tarifa_saida = TARIFA_ENTRADA_ATE_100K, TARIFA_SAIDA_ATE_100K
    else:
        tarifa_entrada, tarifa_saida = TARIFA_ENTRADA_ACIMA_100K, TARIFA_SAIDA_ACIMA_100K
    return (Decimal(tokens_entrada) * tarifa_entrada + Decimal(tokens_saida) * tarifa_saida) / MILHAO


def _formatar_custo(custo):
    return format(custo.quantize(Decimal('0.000001')), 'f').replace('.', ',')


# ─── CHAMADA À API ───────────────────────────────────────────────────────

# Função Objetivo: Traduz o erro da API para uma frase em português (os textos são nossos; só o
# código de status vem da API — fatos da documentação de erros da Anthropic, conferidos em 14/10/2026).
def _traduzir_erro(erro):
    status = getattr(erro, 'status_code', None)
    detalhe = f'{type(erro).__name__}: {str(erro)[:500]}'
    if status is None and isinstance(erro, TypeError):
        return ErroSugestaoIA(
            'A biblioteca "anthropic" instalada não aceitou o pedido (versão antiga demais?). '
            'O detalhe está no terminal do servidor.',
            500, detalhe,
        )
    if status is None:
        return ErroSugestaoIA(
            'Não consegui falar com a API do Claude (conexão ou tempo esgotado). Nada foi gasto; tente de novo.',
            502, detalhe,
        )
    textos = {
        400: 'A API do Claude recusou o pedido (status 400).',
        401: 'A API do Claude recusou a chave (status 401): ela está errada, foi revogada ou expirou. '
             'Troque ANTHROPIC_API_KEY no .env e reinicie o servidor.',
        402: 'A API do Claude acusou problema de cobrança (status 402). Regularize no Claude Console.',
        403: 'A API do Claude negou a permissão (status 403): confira a chave e o workspace no Claude Console.',
        404: 'A API do Claude não achou o modelo ou o recurso (status 404): o nome do modelo pode ter mudado.',
        429: 'A API do Claude pediu para esperar (status 429): limite de uso ou teto de gasto atingido.',
    }
    mensagem = textos.get(status) or f'A API do Claude falhou (status {status}). Tente de novo em instantes.'
    return ErroSugestaoIA(mensagem, 502, detalhe)


def _chamar_api(cliente, sistema, mensagem, com_esquema):
    saida = {'effort': ESFORCO}
    if com_esquema:
        saida['format'] = {'type': 'json_schema', 'schema': ESQUEMA_DA_RESPOSTA}
    return cliente.messages.create(
        model=MODELO_ID,
        max_tokens=MAX_TOKENS_SAIDA,
        system=sistema,
        messages=[{'role': 'user', 'content': mensagem}],
        thinking={'type': 'disabled'},
        output_config=saida,
    )


def _extrair_json(texto):
    texto = (texto or '').strip()
    try:
        return json.loads(texto)
    except ValueError:
        pass
    inicio, fim = texto.find('{'), texto.rfind('}')
    if inicio != -1 and fim > inicio:
        try:
            return json.loads(texto[inicio:fim + 1])
        except ValueError:
            return None
    return None


# Função Objetivo: Pede e confere as sugestões para a ficha de UM produto. `descricao` é a descrição
# do cadastro (ERP); `cliente` só é passado nos testes. Faz UMA chamada paga (ou, no plano B, uma
# segunda só se a primeira foi recusada com 400, que não é cobrado).
def sugerir_para_ficha(ficha, descricao, cliente=None):
    sistema, mensagem, campos, fonte = montar_pedido(ficha, descricao)
    if not campos:
        raise ErroSugestaoIA(
            'Este produto ainda não tem campos para sugerir. Clique em "Atualizar" para ler os anúncios no Mercado Livre.',
            409,
        )
    if len(_limpar_texto(fonte)) < MIN_CARACTERES_DE_TEXTO:
        raise ErroSugestaoIA(
            'Este produto não tem texto no cadastro (título e descrição) para a IA ler. Nada foi enviado nem cobrado.',
            409,
        )

    if cliente is None:
        cliente = _criar_cliente()

    inicio = time.monotonic()
    modo = 'estruturada'
    try:
        resposta = _chamar_api(cliente, sistema, mensagem, com_esquema=True)
    except Exception as erro:
        if getattr(erro, 'status_code', None) != 400:
            raise _traduzir_erro(erro) from erro
        modo = 'prompt'
        try:
            resposta = _chamar_api(cliente, sistema, mensagem, com_esquema=False)
        except Exception as erro_b:
            raise _traduzir_erro(erro_b) from erro_b
    duracao = time.monotonic() - inicio

    if resposta.stop_reason == 'refusal':
        raise ErroSugestaoIA('A IA recusou responder a este pedido. Nada foi aplicado.', 502)
    if resposta.stop_reason == 'max_tokens':
        raise ErroSugestaoIA(
            'A resposta da IA foi cortada por ser grande demais (muitos campos). Nada foi aplicado.', 502,
        )

    texto_resposta = ''.join(bloco.text for bloco in resposta.content if getattr(bloco, 'type', '') == 'text')
    dados = _extrair_json(texto_resposta)
    if not isinstance(dados, dict) or not isinstance(dados.get('sugestoes'), list):
        raise ErroSugestaoIA(
            'A IA devolveu uma resposta fora do formato combinado. Nada foi aplicado.', 502, texto_resposta[:500],
        )

    sugestoes, ignoradas = validar_respostas(campos, dados['sugestoes'], fonte)

    tokens_entrada = int(resposta.usage.input_tokens)
    tokens_saida = int(resposta.usage.output_tokens)
    custo = calcular_custo_usd(tokens_entrada, tokens_saida)
    return {
        'sugestoes': sugestoes,
        'ignoradas': ignoradas,
        'n_sugestoes': len(sugestoes),
        'n_campos_enviados': len(campos),
        # Quais campos a IA viu: a tela só escreve "Sem sugestão" nestes (os outros ficam como estavam).
        'campos_enviados': list(campos),
        'modo': modo,
        'modelo': MODELO_ID,
        'modelo_rotulo': ROTULO_MODELO,
        'esforco': ESFORCO,
        'tokens_entrada': tokens_entrada,
        'tokens_saida': tokens_saida,
        'custo_usd': _formatar_custo(custo),
        'duracao_segundos': round(duracao, 1),
        # O que a gaveta "Entrada e saída" mostra: exatamente o que foi e o que voltou.
        'entrada': f'SISTEMA:\n{sistema}\n\nUSUÁRIO:\n{mensagem}',
        'saida': texto_resposta,
    }


# Função Objetivo: Ponto de entrada da view — lê a ficha DO BANCO (como a própria tela) e a descrição
# do cadastro, e chama sugerir_para_ficha. Devolve None se o SKU não existe. O resultado traz
# "produto_id" (a view usa para gravar e retira antes de responder à tela).
def sugerir_caracteristicas(sku):
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import montar_ficha_produto
    from produtos.models import Produto

    ficha = montar_ficha_produto(sku)
    if ficha is None:
        return None
    produto_id = ficha['produto']['id']
    descricao = Produto.objects.filter(id=produto_id).values_list('descricao', flat=True).first()
    resultado = sugerir_para_ficha(ficha, descricao or '')
    resultado['produto_id'] = produto_id
    return resultado
