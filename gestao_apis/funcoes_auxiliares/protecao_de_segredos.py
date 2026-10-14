# gestao_apis/funcoes_auxiliares/protecao_de_segredos.py

# Função Objetivo: Última barreira antes de qualquer texto vindo de fora (erro
# de API, mensagem de biblioteca, resposta real da API) ser mostrado na tela ou
# gravado no histórico. Tem 2 portas:
#   - limpar_texto_externo(): para TRECHOS CURTOS de erro dentro de frases nossas. Esconde
#     sequências longas (cara de token/chave) e cabeçalhos "Bearer ...".
#   - preparar_resposta_para_exibir(): para a RESPOSTA REAL da API mostrada em "Ver detalhes".
#     Mantém a resposta como veio (JSON bonitinho), mas tira tokens/chaves e corta o tamanho.
#
# * [IMPORTANTE] → Regra da tela inteira: nenhum token, chave ou senha chega ao
#   navegador. Os textos de "O que aconteceu / Próximo passo" são escritos por nós; a resposta
#   real da API vem num bloco separado e SEMPRE passa por preparar_resposta_para_exibir().

import json
import os
import re

_PADRAO_BEARER = re.compile(r'(?i)bearer\s+\S+')
_PADRAO_SEQUENCIA_LONGA = re.compile(r'[A-Za-z0-9_\-\.]{24,}')

# * [DECISÃO, 14/10/2026] → O Matheus quer ver a resposta REAL da API em "Ver detalhes" (o que o
#   Mercado Livre, o Claude, o Sysemp e o Google de fato devolveram). Por isso a resposta NÃO passa
#   pela máscara de sequências longas (ela esconderia IDs legítimos, como o ID de pasta do Drive ou a
#   chave de acesso da nota fiscal). Em vez disso, 4 proteções que não estragam dado legítimo:
#     1) campo de NOME secreto (token, secret, password, authorization...) com valor texto → "***";
#     2) qualquer valor secreto CONHECIDO do ambiente (.env) que apareça no texto → "***";
#     3) "Bearer xxx" e prefixos conhecidos de chave (sk-ant-, APP_USR-, TG-, ya29., JWT) → "***";
#     4) corte de tamanho (a resposta de uma lista de notas pode ser enorme).
LIMITE_DA_RESPOSTA_EXIBIDA = 4000

_PADRAO_NOME_DE_CAMPO_SECRETO = re.compile(r'(?i)token|secret|password|passwd|senha|authorization|api[_-]?key|credential|cookie')
_PARTES_DE_NOME_DE_VARIAVEL_SECRETA = ('TOKEN', 'SECRET', 'KEY', 'PASSWORD', 'PASSWD', 'SENHA')
_TAMANHO_MINIMO_DE_SEGREDO_DO_AMBIENTE = 8
_PADRAO_PREFIXO_DE_CHAVE = re.compile(
    r'(?:sk-ant-[A-Za-z0-9_\-]+|APP_USR-[A-Za-z0-9_\-]+|TG-[A-Za-z0-9_\-]+|ya29\.[A-Za-z0-9_\-\.]+'
    r'|eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)'
)


def limpar_texto_externo(texto, limite=200):
    texto = str(texto or '')
    texto = _PADRAO_BEARER.sub('Bearer ***', texto)
    texto = _PADRAO_SEQUENCIA_LONGA.sub('***', texto)
    texto = ' '.join(texto.split())
    return texto[:limite]


def _valores_secretos_do_ambiente():
    valores = set()
    for nome, valor in os.environ.items():
        nome_em_maiusculas = nome.upper()
        valor = (valor or '').strip()
        if len(valor) >= _TAMANHO_MINIMO_DE_SEGREDO_DO_AMBIENTE and any(
            parte in nome_em_maiusculas for parte in _PARTES_DE_NOME_DE_VARIAVEL_SECRETA
        ):
            valores.add(valor)
    return valores


def _esconder_campos_secretos(objeto):
    if isinstance(objeto, dict):
        escondido = {}
        for chave, valor in objeto.items():
            if isinstance(valor, str) and valor and _PADRAO_NOME_DE_CAMPO_SECRETO.search(str(chave)):
                escondido[chave] = '***'
            else:
                escondido[chave] = _esconder_campos_secretos(valor)
        return escondido
    if isinstance(objeto, list):
        return [_esconder_campos_secretos(item) for item in objeto]
    return objeto


def preparar_resposta_para_exibir(corpo, segredos=(), limite=LIMITE_DA_RESPOSTA_EXIBIDA):
    """
    Devolve o texto da resposta real da API pronto para a tela e para o histórico: JSON em várias
    linhas (se for JSON), sem tokens/chaves, cortado em `limite` caracteres. `corpo` pode ser dict,
    lista, texto ou bytes; vazio/None → ''. `segredos` = valores que o chamador sabe que são secretos
    (ex.: o token usado na chamada), além dos que já vêm do .env.
    """
    if corpo is None:
        return ''
    if isinstance(corpo, (bytes, bytearray)):
        corpo = bytes(corpo).decode('utf-8', errors='replace')

    estrutura = corpo
    if isinstance(corpo, str):
        if not corpo.strip():
            return ''
        try:
            estrutura = json.loads(corpo)
        except ValueError:
            estrutura = None

    if isinstance(estrutura, (dict, list)):
        texto = json.dumps(_esconder_campos_secretos(estrutura), indent=2, ensure_ascii=False, default=str)
    else:
        texto = str(corpo).strip()

    texto = _PADRAO_BEARER.sub('Bearer ***', texto)
    texto = _PADRAO_PREFIXO_DE_CHAVE.sub('***', texto)
    todos_os_segredos = _valores_secretos_do_ambiente() | {str(s).strip() for s in segredos if s}
    for segredo in sorted(todos_os_segredos, key=len, reverse=True):
        if len(segredo) >= _TAMANHO_MINIMO_DE_SEGREDO_DO_AMBIENTE:
            texto = texto.replace(segredo, '***')

    if len(texto) > limite:
        total = len(texto)
        texto = texto[:limite].rstrip() + f'\n… (resposta cortada: {total} caracteres no total, mostrando os primeiros {limite})'
    return texto
