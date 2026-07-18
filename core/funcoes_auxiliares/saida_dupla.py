# core/funcoes_auxiliares/saida_dupla.py

# Função Objetivo: Espelha tudo que é escrito também num arquivo de log.
# Explicação em detalhe: substitui o "arquivo" por trás do self.stdout do Django —
# todo lugar que já chama stdout.write(...) (todos os importadores) continua
# funcionando exatamente igual, sem precisar mudar nada neles. Remove os códigos
# ANSI de cor (usados por style.SUCCESS/style.ERROR) antes de gravar no arquivo,
# já que cor só faz sentido no terminal, não num .log de texto puro.

import re
import sys

_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')


class SaidaDupla:

    # Função Objetivo: Recebe o arquivo de log já aberto, guarda o console real.
    def __init__(self, arquivo_log):
        self.console = sys.stdout
        self.arquivo = arquivo_log

    # Função Objetivo: Escreve no console (com cor) e no arquivo (sem cor).
    def write(self, texto):
        self.console.write(texto)
        self.arquivo.write(_ANSI_ESCAPE.sub('', texto))

    # Função Objetivo: Repassa flush pros 2 destinos.
    def flush(self):
        self.console.flush()
        self.arquivo.flush()

    # Função Objetivo: Repassa isatty — Django usa isso pra decidir se aplica cor.
    def isatty(self):
        return self.console.isatty()