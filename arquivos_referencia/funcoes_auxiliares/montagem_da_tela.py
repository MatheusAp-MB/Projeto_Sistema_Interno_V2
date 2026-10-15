# arquivos_referencia/funcoes_auxiliares/montagem_da_tela.py

# Função Objetivo: Monta, para a tela "Arquivos de referência", os dados de cada cartão (1 por arquivo do catálogo)
# e dos grupos. A tela só desenha o que vem daqui: rótulo e ícone do estado, textos, e o relatório da auditoria
# quando a pessoa já escolheu um arquivo.
#
# * [EXPLICAÇÃO] → Cada cartão está em 1 de 6 estados (sempre ícone + texto, nunca só cor):
#   "Sem arquivo" (nada conferido nesta visita), "Válido", "Com avisos", "Com erros", "Não consegui ler"
#   (nem abriu como planilha) e "Em breve" (Busca Legal, que ainda não tem auditoria: a auditoria chega na próxima etapa).
# * [DECISÃO, 15/10/2026] → 1º ciclo sem banco e sem Drive: o resultado da auditoria vive só na resposta da tela.
#   Ao recarregar a página (F5) os cartões voltam a "Sem arquivo". O que passa a ser guardado (e onde) é decisão
#   do ciclo do envio ao Drive.

from .catalogo_arquivos import arquivos_por_grupo
from .relatorio_auditoria import STATUS_COM_AVISOS, STATUS_COM_ERROS, STATUS_ILEGIVEL, STATUS_VALIDO

ESTADO_SEM_ARQUIVO = 'sem_arquivo'
ESTADO_EM_BREVE = 'em_breve'

# estado -> (rótulo, ícone do Font Awesome 6)
ESTADOS = {
    ESTADO_SEM_ARQUIVO: ('Sem arquivo', 'fa-circle-minus'),
    STATUS_VALIDO: ('Válido', 'fa-circle-check'),
    STATUS_COM_AVISOS: ('Com avisos', 'fa-triangle-exclamation'),
    STATUS_COM_ERROS: ('Com erros', 'fa-circle-xmark'),
    STATUS_ILEGIVEL: ('Não consegui ler', 'fa-file-circle-exclamation'),
    ESTADO_EM_BREVE: ('Em breve', 'fa-hourglass-half'),
}


# Função Objetivo: Dados de 1 cartão. `relatorio` (RelatorioDeAuditoria) e `quando` (datetime) só existem depois
# de a pessoa escolher um arquivo.
def montar_cartao(arquivo, relatorio=None, quando=None):
    if not arquivo.auditoria_pronta:
        estado = ESTADO_EM_BREVE
    elif relatorio is None:
        estado = ESTADO_SEM_ARQUIVO
    else:
        estado = relatorio.status
    rotulo, icone = ESTADOS[estado]
    return {
        'id': arquivo.id,
        'nome': arquivo.nome,
        'icone': arquivo.icone,
        'nome_no_drive': arquivo.nome_no_drive,
        'para_que_serve': arquivo.para_que_serve,
        'formato_esperado': arquivo.formato_esperado,
        'upload_habilitado': arquivo.auditoria_pronta,
        'estado': estado,
        'estado_rotulo': rotulo,
        'estado_icone': icone,
        'relatorio': relatorio,
        'quando': quando,
    }


# Função Objetivo: Os grupos da tela, na ordem, cada um com seus cartões ainda sem arquivo.
def montar_grupos():
    return [
        {'id': id_do_grupo, 'titulo': titulo, 'subtitulo': subtitulo, 'cartoes': [montar_cartao(a) for a in arquivos]}
        for id_do_grupo, titulo, subtitulo, arquivos in arquivos_por_grupo()
    ]
