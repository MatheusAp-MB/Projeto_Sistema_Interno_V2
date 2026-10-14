# gestao_apis/funcoes_auxiliares/protecao_de_segredos.py

# Função Objetivo: Última barreira antes de qualquer texto vindo de fora (erro
# de API, mensagem de biblioteca) ser mostrado na tela ou gravado no histórico.
# Esconde sequências longas (cara de token/chave) e cabeçalhos "Bearer ...".
#
# * [IMPORTANTE] → Regra da tela inteira: nenhum token, chave ou senha chega ao
#   navegador. Os textos da tela são escritos por nós; só trechos curtos de
#   erro externo passam por aqui antes.

import re

_PADRAO_BEARER = re.compile(r'(?i)bearer\s+\S+')
_PADRAO_SEQUENCIA_LONGA = re.compile(r'[A-Za-z0-9_\-\.]{24,}')


def limpar_texto_externo(texto, limite=200):
    texto = str(texto or '')
    texto = _PADRAO_BEARER.sub('Bearer ***', texto)
    texto = _PADRAO_SEQUENCIA_LONGA.sub('***', texto)
    texto = ' '.join(texto.split())
    return texto[:limite]
