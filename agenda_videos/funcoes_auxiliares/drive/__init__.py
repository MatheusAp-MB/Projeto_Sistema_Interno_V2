# agenda_videos/funcoes_auxiliares/drive/__init__.py

# Função Objetivo: Ponto de entrada público do pacote de integração com o
# Google Drive — quem está FORA deste pacote (views.py, a_fazer_hoje.py,
# contexto_tela_agenda_videos.py) importa daqui, nunca de um módulo interno
# específico. Isso reorganiza os módulos internos sem quebrar quem consome
# de fora, e deixa explícito qual é a API pública do pacote.

from .verificador import verificar_produto_no_drive, verificar_todos_no_drive
from .diagnostico import calcular_diagnostico_preparo_drive