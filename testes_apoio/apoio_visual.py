# agenda_videos/tests/apoio_visual.py

# Função Objetivo: Registra 1 resultado de teste nos 2 formatos — tabela
# Rich (pro terminal, bonita mas larga) e lista simples (pro log em texto,
# sem corte nenhum). Único lugar que decide como um resultado vira essas 2
# coisas, pra nunca ficar inconsistente entre arquivos de teste diferentes.

def registrar_resultado(registrador, teste, entrada, esperado, motivo, obtido, passou, dado_bruto=None):
    registrador.adicionar(teste, entrada, esperado, motivo, obtido, passou, dado_bruto)