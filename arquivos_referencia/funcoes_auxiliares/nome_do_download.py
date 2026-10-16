# arquivos_referencia/funcoes_auxiliares/nome_do_download.py

# Função Objetivo: O nome com que o navegador grava o arquivo quando a pessoa clica em "Baixar" (cópia do arquivo que está no Drive).
#
# * [DECISÃO, 16/10/2026] → O nome leva a data e a hora em que o arquivo foi enviado ao Drive ("Data do envio do arquivo" do cartão), no horário do
#   sistema (Brasília). Motivo: o uso principal é o BACKUP antes de uma mudança; com a data no nome, duas cópias baixadas em momentos diferentes
#   nunca se sobrescrevem no computador e dá para saber de que versão cada uma é. Sem a data (o Drive não informou), vale o nome fixo do Drive.
# * [IMPORTANTE] → `nome_no_drive` vem do catálogo fechado (nada digitado por quem usa a tela) e a data só tem dígitos: nenhum caractere proibido
#   em nome de arquivo do Windows ("h" no lugar de ":" justamente por isso).

import os

from django.utils import timezone


# Exemplo: ('TABELA SAIDA POR UF MAGAZINE.xlsx', 16/10/2026 10:24) -> 'TABELA SAIDA POR UF MAGAZINE (Drive 16-10-2026 10h24).xlsx'
def nome_do_download(nome_no_drive, enviado_em=None):
    if enviado_em is None:
        return nome_no_drive
    quando = enviado_em if timezone.is_naive(enviado_em) else timezone.localtime(enviado_em)
    base, extensao = os.path.splitext(nome_no_drive)
    return f'{base} (Drive {quando:%d-%m-%Y} {quando:%Hh%M}){extensao}'
