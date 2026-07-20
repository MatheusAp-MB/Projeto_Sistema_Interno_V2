# core/funcoes_auxiliares/chave_cache_segura.py

# Função Objetivo: Sanitiza um texto (ex: nome de marca) pra virar um pedaço seguro
# de chave de cache — sem espaço, acento ou caractere especial.
# Explicação em detalhe: backends de cache tipo memcached rejeitam espaço/unicode em
# chave. Hoje usamos cache em memória (que não liga pra isso), mas a chave já nasce
# limpa — evita reescrever isso quando o backend virar Redis/memcached de verdade.

import re
import unicodedata


def chave_cache_segura(texto):
    texto_sem_acento = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-zA-Z0-9]+', '_', texto_sem_acento).strip('_').lower()