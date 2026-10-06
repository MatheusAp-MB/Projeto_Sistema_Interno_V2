# mercado_livre/funcoes_auxiliares/envio_caracteristicas_ml.py
#
# Regras do ENVIO de características ao Mercado Livre (botões "Revisar e
# enviar" e "Confirmar envio" da tela "Características dos anúncios"). TUDO
# aqui lê só do BANCO — nenhuma função deste arquivo chama a API do ML; quem
# fala com o ML é integracao_mercado_livre.servicos.sincronizar_caracteristicas_ml
# (enviar_produto).
#
# REGRA DESTA TELA (Matheus): não existe rascunho. O que o usuário digita vive
# só na página, até ele enviar. Este arquivo recebe esses valores, confere, e
# monta — sem gravar nada em lugar nenhum — o PLANO do envio: para cada
# anúncio do produto, o que ele tem hoje, o que vai receber e o corpo exato
# que seria mandado ao ML.
#
# O que o plano decide:
#   - cada valor é conferido contra a regra do campo (a mesma "fusão" dos
#     cards: lista fechada, limite de caracteres, número, unidade). UM valor
#     inválido trava o envio inteiro, até ser corrigido ou apagado;
#   - cada anúncio recebe só os campos que a categoria dele pede;
#   - anúncio que já tem exatamente o valor digitado NÃO entra no envio (não
#     gasta chamada à API);
#   - anúncio não lido, ou que deixou de estar ativo/pausado no ML, fica de
#     fora e o motivo aparece na prévia.
#
# Fora desta versão (o plano recusa com mensagem clara, em vez de arriscar):
# a Marca (vem do ERP), as 4 medidas do pacote (SELLER_PACKAGE_*, que só
# valem juntas), campos que aceitam mais de um valor, valor fora da lista
# (valor próprio), remover um valor e marcar N/A.

import re
from decimal import Decimal, InvalidOperation

from mercado_livre.funcoes_auxiliares.caracteristicas_ml import (
    ATRIBUTO_MARCA, STATUS_ACEITOS, carregar_contexto_produto, fundir_atributo, interpretar_valor,
)

PREFIXO_PACOTE = 'SELLER_PACKAGE_'

# * [EXPLICAÇÃO] → Limite de caracteres quando o ML não informa um para o
#                  campo de texto. Nos dados reais das categorias, TODO campo
#                  de texto traz 255 — este é só o teto de segurança.
LIMITE_TEXTO_PADRAO = 255

LIMITE_CARACTERES_NUMERO = 20

PADRAO_NUMERO = re.compile(r'^-?\d+(?:[.,]\d+)?$')
PADRAO_NUMERO_UNIDADE = re.compile(r'^(-?\d+(?:[.,]\d+)?)\s*(\S.*)$')


def _texto(valor):
    return '' if valor is None else str(valor).strip()


# Função Objetivo: "4,5" -> "4.5" (o ML guarda número com ponto: "1.25 L").
# Devolve None se o texto não for um número.
def _numero_como_ml(texto):
    if len(texto) > LIMITE_CARACTERES_NUMERO or not PADRAO_NUMERO.match(texto):
        return None
    return texto.replace(',', '.')


def _decimal(texto):
    try:
        return Decimal(str(texto).replace(',', '.'))
    except InvalidOperation:
        return None


# Função Objetivo: Como o valor que o anúncio tem hoje aparece na prévia.
def descrever_hoje(hoje):
    if hoje['estado'] == 'valor':
        return hoje['texto']
    if hoje['estado'] == 'na':
        return 'N/A (não se aplica)'
    return 'em branco'


# Função Objetivo: Confere 1 valor digitado contra a regra do campo e devolve
# (valor, erro). "valor" traz o texto de exibição e o corpo exato que iria
# para o ML ({"id", "value_id"} ou {"id", "value_name"}); em caso de erro,
# valor é None e "erro" é a frase para o usuário.
def _interpretar_digitado(atributo_id, fusao, bruto):
    tipo = fusao['tipo']
    valor_id = _texto(bruto.get('valor_id'))
    texto = _texto(bruto.get('texto'))
    numero = _texto(bruto.get('numero'))
    unidade = _texto(bruto.get('unidade'))

    if tipo == 'lista':
        if not fusao['opcoes']:
            return None, 'O Mercado Livre não tem nenhuma opção em comum entre as categorias deste produto.'
        if not valor_id:
            return None, 'Escolha uma das opções da lista.'
        nomes = {str(o.get('id')): o.get('name') or '' for o in fusao['opcoes']}
        if valor_id not in nomes:
            return None, 'Essa opção não existe na lista aceita pelo Mercado Livre.'
        return {
            'tipo': tipo, 'valor_id': valor_id, 'texto': nomes[valor_id],
            'corpo': {'id': atributo_id, 'value_id': valor_id},
        }, None

    if tipo == 'numero_unidade':
        if not numero:
            return None, 'Digite o número.'
        canonico = _numero_como_ml(numero)
        if canonico is None:
            return None, 'Digite só o número (ex.: 4 ou 4,5).'
        if not fusao['unidades']:
            return None, 'O Mercado Livre não informou as unidades aceitas por este campo.'
        achada = next((u for u in fusao['unidades'] if u.lower() == unidade.lower()), None)
        if achada is None:
            return None, 'Escolha uma unidade: ' + ', '.join(fusao['unidades']) + '.'
        exibicao = f'{canonico} {achada}'
        return {
            'tipo': tipo, 'texto': exibicao, 'numero': _decimal(canonico), 'unidade': achada,
            'corpo': {'id': atributo_id, 'value_name': exibicao},
        }, None

    if tipo == 'numero':
        if not numero:
            return None, 'Digite o número.'
        canonico = _numero_como_ml(numero)
        if canonico is None:
            return None, 'Digite só o número (ex.: 4 ou 4,5).'
        return {
            'tipo': tipo, 'texto': canonico, 'numero': _decimal(canonico),
            'corpo': {'id': atributo_id, 'value_name': canonico},
        }, None

    # texto livre e texto com sugestões (as sugestões não obrigam nada)
    if not texto:
        return None, 'Digite o valor.'
    limite = fusao['limite'] or LIMITE_TEXTO_PADRAO
    if len(texto) > limite:
        return None, f'O texto tem {len(texto)} caracteres; o máximo é {limite}.'
    return {
        'tipo': tipo, 'texto': texto,
        'corpo': {'id': atributo_id, 'value_name': texto},
    }, None


# Função Objetivo: O anúncio JÁ tem este valor? "hoje" vem de
# interpretar_valor (o que a última leitura do ML trouxe). Na dúvida, diz que
# NÃO — é melhor enviar de novo do que deixar de enviar.
def _ja_esta_igual(valor, hoje):
    if hoje['estado'] != 'valor':
        return False
    tipo = valor['tipo']

    if tipo == 'lista':
        # Valor sem id no anúncio (valor próprio com o mesmo nome) não conta:
        # enviar o id corrige para o valor oficial da lista.
        return hoje['valor_id'] is not None and str(hoje['valor_id']) == valor['valor_id']

    if tipo == 'numero':
        atual = _decimal(hoje['texto'])
        return atual is not None and atual == valor['numero']

    if tipo == 'numero_unidade':
        achou = PADRAO_NUMERO_UNIDADE.match(hoje['texto'].strip())
        if not achou:
            return False
        atual = _decimal(achou.group(1))
        return (
            atual is not None
            and atual == valor['numero']
            and achou.group(2).strip().lower() == valor['unidade'].lower()
        )

    return hoje['texto'] == valor['texto']


# Função Objetivo: Monta o PLANO do envio de 1 produto, só com dados do banco
# (nada é gravado, nada é enviado). "digitados" = {atributo_id: {"valor_id",
# "texto", "numero", "unidade"}} — só os campos que o usuário preencheu.
# Devolve None se o SKU não existe. Estrutura:
#   erros (lista, 1 por campo inválido) e erros_por_campo (mesmo conteúdo, por id),
#   valores (atributo_id -> valor conferido, com o corpo do ML),
#   mlbs (1 por anúncio do produto: situação, motivo, itens e atributos_corpo),
#   totais (n_mlbs_enviar, n_campos_enviar, n_chamadas) e pode_enviar.
def preparar_envio(sku, digitados):
    contexto = carregar_contexto_produto(sku)
    if contexto is None:
        return None

    campos = contexto['campos']
    erros = []
    valores = {}

    def registrar_erro(atributo_id, label, mensagem):
        erros.append({'atributo_id': atributo_id, 'label': label, 'mensagem': mensagem})

    ordem = [a for a in contexto['ordem_campos'] if a in digitados]
    for atributo_id in digitados:
        if atributo_id not in campos:
            registrar_erro(atributo_id, atributo_id, 'Este campo não existe nas categorias dos anúncios deste produto.')

    for atributo_id in ordem:
        fusao = fundir_atributo(campos[atributo_id])
        label = fusao['label']
        if atributo_id == ATRIBUTO_MARCA:
            registrar_erro(atributo_id, label, 'A marca vem do cadastro do produto (ERP) e não é enviada por aqui.')
            continue
        if atributo_id.startswith(PREFIXO_PACOTE):
            registrar_erro(atributo_id, label, 'As 4 medidas do pacote só valem juntas; este envio ainda não suporta esse grupo.')
            continue
        if fusao['multi']:
            registrar_erro(atributo_id, label, 'Este campo aceita mais de um valor; o envio de vários valores ainda não existe aqui.')
            continue
        valor, erro = _interpretar_digitado(atributo_id, fusao, digitados[atributo_id])
        if erro:
            registrar_erro(atributo_id, label, erro)
            continue
        valor['label'] = label
        valores[atributo_id] = valor

    mlbs = []
    for anuncio in contexto['anuncios']:
        categoria = contexto['categoria_do_anuncio'].get(anuncio.id)
        categoria_exibida = categoria or contexto['categoria_do_banco'].get(anuncio.id)
        alvo = {
            'mlb': anuncio.mlb,
            'anuncio_id': anuncio.id,
            'titulo': anuncio.titulo_anuncio or '',
            'permalink': anuncio.permalink or '',
            'categoria_nome': contexto['nome_categoria'](categoria_exibida),
            'categoria_id': categoria_exibida or '',
            'situacao': 'pulado',
            'motivo': '',
            'itens': [],
            'atributos_corpo': [],
        }
        mlbs.append(alvo)

        if anuncio.atributos_ml_lido_em is None:
            alvo['motivo'] = 'Ainda não foi lido. Clique em "Atualizar" no produto para ler este anúncio antes de enviar.'
            continue
        if anuncio.atributos_ml_status and anuncio.atributos_ml_status not in STATUS_ACEITOS:
            alvo['motivo'] = 'No Mercado Livre este anúncio não está mais ativo nem pausado.'
            continue

        cru = contexto['cru_por_anuncio'].get(anuncio.id, {})
        for atributo_id, valor in valores.items():
            if categoria not in campos[atributo_id]:
                alvo['itens'].append({
                    'atributo_id': atributo_id, 'label': valor['label'], 'hoje_txt': '', 'hoje_estado': '',
                    'novo_txt': valor['texto'], 'situacao': 'nao_pede',
                })
                continue
            hoje = interpretar_valor(cru.get(atributo_id))
            igual = _ja_esta_igual(valor, hoje)
            alvo['itens'].append({
                'atributo_id': atributo_id, 'label': valor['label'],
                'hoje_txt': descrever_hoje(hoje), 'hoje_estado': hoje['estado'],
                'novo_txt': valor['texto'], 'situacao': 'igual' if igual else 'muda',
            })
            if not igual:
                alvo['atributos_corpo'].append(valor['corpo'])

        if alvo['atributos_corpo']:
            alvo['situacao'] = 'enviar'
        elif any(item['situacao'] == 'igual' for item in alvo['itens']):
            alvo['situacao'] = 'igual'
            alvo['motivo'] = 'Já está com esses valores; não precisa enviar.'
        else:
            alvo['situacao'] = 'nao_pede'
            alvo['motivo'] = 'A categoria deste anúncio não pede nenhum dos campos preenchidos.'

    a_enviar = [m for m in mlbs if m['situacao'] == 'enviar']
    campos_enviados = {corpo['id'] for m in a_enviar for corpo in m['atributos_corpo']}

    if not digitados:
        motivo_sem_envio = 'Preencha pelo menos um campo antes de enviar.'
    elif not valores:
        motivo_sem_envio = 'Corrija os campos marcados antes de enviar.'
    elif not a_enviar:
        motivo_sem_envio = 'Nenhum anúncio precisa receber esses valores: ou já estão iguais, ou o anúncio não pode receber envio agora (veja o motivo de cada um).'
    else:
        motivo_sem_envio = ''

    return {
        'produto': {
            'sku': sku,
            'titulo': contexto['produto'].titulo or '',
        },
        'erros': erros,
        'erros_por_campo': {e['atributo_id']: e['mensagem'] for e in erros},
        'valores': valores,
        'campos': [
            {'atributo_id': a, 'label': v['label'], 'novo_txt': v['texto']}
            for a, v in valores.items()
        ],
        'mlbs': mlbs,
        'n_mlbs_enviar': len(a_enviar),
        'n_campos_enviar': len(campos_enviados),
        # 1 chamada de envio + 1 de leitura de volta, para cada anúncio que vai receber.
        'n_chamadas': 2 * len(a_enviar),
        'pode_enviar': not erros and bool(a_enviar),
        'motivo_sem_envio': '' if erros else motivo_sem_envio,
    }


# Função Objetivo: Depois do envio e da leitura de volta, diz — campo a campo —
# se o que o ML guardou bate com o que foi enviado. "atributos_ml" é o array
# cru que a leitura de volta gravou no anúncio. Nada é "corrigido": se o ML
# guardou outra coisa (normalizou o texto, por exemplo), isso aparece como não
# confirmado, com o valor que ele guardou.
def conferir_depois_do_envio(valores, atributos_enviados, atributos_ml):
    cru = {item.get('id'): item for item in (atributos_ml or []) if isinstance(item, dict)}
    conferencia = []
    for corpo in atributos_enviados:
        atributo_id = corpo['id']
        valor = valores[atributo_id]
        hoje = interpretar_valor(cru.get(atributo_id))
        conferencia.append({
            'atributo_id': atributo_id,
            'label': valor['label'],
            'novo_txt': valor['texto'],
            'hoje_txt': descrever_hoje(hoje),
            'confirmado': _ja_esta_igual(valor, hoje),
        })
    return conferencia
