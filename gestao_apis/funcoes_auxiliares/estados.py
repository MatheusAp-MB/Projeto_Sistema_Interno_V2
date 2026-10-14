# gestao_apis/funcoes_auxiliares/estados.py

# Função Objetivo: Define os 5 estados possíveis de uma conexão e o formato do
# resultado de uma verificação. Fonte única — a tela, o histórico e os
# verificadores usam todos estas mesmas constantes.
#
# * [REGRA] → "Funcionando" SÓ existe quando uma resposta VÁLIDA do serviço
#   externo confirmou (um teste que deu certo). Ler a configuração ou o relógio
#   do token nunca vira "Funcionando": no máximo "Não verificada".

from dataclasses import dataclass

FUNCIONANDO = 'funcionando'
ATENCAO = 'atencao'
COM_PROBLEMA = 'com_problema'
NAO_VERIFICADA = 'nao_verificada'
NAO_CONFIGURADA = 'nao_configurada'

ESTADOS_VISUAIS = {
    FUNCIONANDO: {'rotulo': 'Funcionando', 'icone': 'fa-circle-check'},
    ATENCAO: {'rotulo': 'Atenção', 'icone': 'fa-triangle-exclamation'},
    COM_PROBLEMA: {'rotulo': 'Com problema', 'icone': 'fa-circle-xmark'},
    NAO_VERIFICADA: {'rotulo': 'Não verificada', 'icone': 'fa-circle-question'},
    NAO_CONFIGURADA: {'rotulo': 'Não configurada', 'icone': 'fa-plug-circle-xmark'},
}

# * [EXPLICAÇÃO] → Estados que entram na faixa de urgência do topo e no
#                  contador "Ver todos". Quanto menor o número, mais urgente.
ORDEM_DE_URGENCIA = {COM_PROBLEMA: 0, ATENCAO: 1}

# * [EXPLICAÇÃO] → Quanto tempo um "teste deu certo" continua valendo como
#                  "Funcionando" na tela. 6 h = a duração do token de acesso
#                  do Mercado Livre; passou disso, volta pra "Não verificada".
JANELA_DE_VALIDADE_DO_TESTE_HORAS = 6


@dataclass
class Resultado:
    estado: str
    motivo: str
    impacto: str = ''
    como_resolver: str = ''
    evidencia: str = ''
    # * [EXPLICAÇÃO] → Resposta REAL da API, já pronta para a tela (vem de preparar_resposta_para_exibir).
    resposta: str = ''
