# agenda_videos/tests/apoio_visual.py

# Função Objetivo: Formata e registra 1 linha de resultado na tabela de testes
# — único lugar que decide como "passou"/"falhou" aparece visualmente, pra
# nunca ficar inconsistente entre arquivos de teste diferentes.

def registrar_resultado(tabela, teste, entrada, esperado, obtido, passou):
    status = '[green]✓ PASSOU[/green]' if passou else '[red]✗ FALHOU[/red]'
    tabela.add_row(teste, entrada, esperado, obtido, status)