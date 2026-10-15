# arquivos_referencia/funcoes_auxiliares/montagem_da_tela.py

# Função Objetivo: Monta, para a tela "Arquivos de referência", os dados de cada cartão (1 por arquivo do catálogo)
# e dos grupos. A tela só desenha o que vem daqui: rótulo e ícone do estado, textos, e o relatório da auditoria
# quando a pessoa já escolheu um arquivo.
#
# * [EXPLICAÇÃO] → Cada cartão está em 1 de 9 estados (sempre ícone + texto, nunca só cor). Sem arquivo escolhido nesta visita, o
#   estado vem do que o DRIVE diz: "Consultando o Drive" (ainda perguntando), "No Drive" (já tem o arquivo lá), "Sem arquivo no
#   Drive" (a pasta ainda não tem) e "Drive sem resposta" (não deu para consultar). Depois que a pessoa escolhe um arquivo, o
#   estado é o da auditoria dele: "Válido", "Com avisos", "Com erros" ou "Não consegui ler" (nem abriu como planilha). Por fim,
#   "Em breve" é o arquivo do catálogo que ainda não tem auditoria (desde 15/10/2026 todos os 6 têm, então hoje nenhum cartão
#   aparece assim; o estado fica pronto para um arquivo novo).
# * [DECISÃO, 15/10/2026] → O resultado da auditoria (e do envio) vive só na resposta da tela: não há banco. Quem guarda a "verdade"
#   do que foi enviado é o próprio Drive, e o cartão pergunta a ele (nunca a um registro nosso, que poderia ficar desatualizado):
#   ao abrir ou recarregar a página (F5), cada cartão mostra "No Drive" (selo e área verdes, com nome, tamanho e data) ou
#   "Sem arquivo no Drive" — assim recarregar não "apaga" a informação de que o arquivo já foi enviado.
# * [EXPLICAÇÃO] → Depois de um envio bem-sucedido o cartão ganha `envio` (o que o Drive guardou) e passa a mostrar
#   "Enviado ao Drive"; escolher outro arquivo volta ao fluxo normal (conferir → enviar).

from .catalogo_arquivos import arquivos_por_grupo
from .relatorio_auditoria import STATUS_COM_AVISOS, STATUS_COM_ERROS, STATUS_ILEGIVEL, STATUS_VALIDO, formatar_tamanho

ESTADO_CONSULTANDO = 'consultando'
ESTADO_NO_DRIVE = 'no_drive'
ESTADO_SEM_ARQUIVO = 'sem_arquivo'
ESTADO_DRIVE_ERRO = 'drive_erro'
ESTADO_EM_BREVE = 'em_breve'

# estado -> (rótulo, ícone COMPLETO do Font Awesome 6: família + nome; o logo do Drive é "fab", os demais "fas")
ESTADOS = {
    ESTADO_CONSULTANDO: ('Consultando o Drive', 'fas fa-spinner fa-spin'),
    ESTADO_NO_DRIVE: ('No Drive', 'fab fa-google-drive'),
    ESTADO_SEM_ARQUIVO: ('Sem arquivo no Drive', 'fas fa-circle-minus'),
    ESTADO_DRIVE_ERRO: ('Drive sem resposta', 'fas fa-triangle-exclamation'),
    STATUS_VALIDO: ('Válido', 'fas fa-circle-check'),
    STATUS_COM_AVISOS: ('Com avisos', 'fas fa-triangle-exclamation'),
    STATUS_COM_ERROS: ('Com erros', 'fas fa-circle-xmark'),
    STATUS_ILEGIVEL: ('Não consegui ler', 'fas fa-file-circle-exclamation'),
    ESTADO_EM_BREVE: ('Em breve', 'fas fa-hourglass-half'),
}

# Estado da linha "No Drive agora" -> estado do cartão (quando ainda não há arquivo conferido).
ESTADO_DO_CARTAO_PELA_LINHA = {
    'carregando': ESTADO_CONSULTANDO,
    'existe': ESTADO_NO_DRIVE,
    'vazio': ESTADO_SEM_ARQUIVO,
    'erro': ESTADO_DRIVE_ERRO,
}


# Função Objetivo: Os dados da linha "No Drive agora" de 1 cartão. 4 jeitos de aparecer:
#   "carregando" (a tela ainda vai perguntar ao Drive), "existe" (tem o arquivo: tamanho, data, cópias), "vazio" (a pasta
#   ainda não tem o arquivo) e "erro" (não deu para consultar: texto + atalho para a Gestão de APIs quando for login).
# `situacao` é o dict de consultar_no_drive. `enviado_agora` marca o resultado de um envio que acabou de dar certo.
# `sem_arquivo_local` = o cartão ainda não tem arquivo conferido: nesse caso a resposta do Drive também atualiza o selo e a
# área do cartão (ver view_situacao_no_drive); com arquivo conferido, o cartão mostra o arquivo conferido e só a linha muda.
def montar_linha_do_drive(
    id_do_arquivo, situacao=None, erro=None, link=None, enviado_agora=False, erro_completo=None, sem_arquivo_local=False,
):
    linha = {
        'arquivo_id': id_do_arquivo, 'enviado_agora': enviado_agora, 'sem_arquivo_local': sem_arquivo_local, 'estado': 'carregando',
    }
    if erro:
        # `erro` é o texto curto (cabe na linha); `erro_completo` aparece ao passar o mouse.
        linha.update(estado='erro', erro=erro, erro_completo=erro_completo or erro, link=link)
    elif situacao is not None and not situacao['existe']:
        linha.update(estado='vazio', caminho=situacao['caminho'])
    elif situacao is not None:
        tamanho = situacao['tamanho_em_bytes']
        linha.update(
            estado='existe', caminho=situacao['caminho'], copias=situacao['copias'], modificado_em=situacao['modificado_em'],
            tamanho_texto=formatar_tamanho(tamanho) if tamanho is not None else '',
        )
    return linha


# Função Objetivo: Dados de 1 cartão. `relatorio` (RelatorioDeAuditoria) e `quando` (datetime) só existem depois
# de a pessoa escolher um arquivo; `envio` (dict devolvido por enviar_para_o_drive) só depois de enviá-lo ao Drive.
# `linha_drive` (de montar_linha_do_drive) já vem pronta quando a própria resposta do Drive está montando o cartão.
def montar_cartao(arquivo, relatorio=None, quando=None, envio=None, linha_drive=None):
    # Logo depois de enviar, a linha do Drive já mostra o que o Drive guardou (sem perguntar de novo); antes disso, ela se
    # preenche sozinha na tela, perguntando ao Drive (hx-get ao carregar).
    if linha_drive is None:
        situacao_do_envio = None
        if envio is not None:
            situacao_do_envio = {
                'existe': True, 'copias': 1 + envio['copias_que_ficaram'], 'tamanho_em_bytes': envio['tamanho_em_bytes'],
                'modificado_em': envio['modificado_em'], 'caminho': envio['caminho'],
            }
        linha_drive = montar_linha_do_drive(
            arquivo.id, situacao_do_envio, enviado_agora=envio is not None,
            sem_arquivo_local=relatorio is None and arquivo.auditoria_pronta,
        )

    if not arquivo.auditoria_pronta:
        estado = ESTADO_EM_BREVE
    elif relatorio is None:
        estado = ESTADO_DO_CARTAO_PELA_LINHA[linha_drive['estado']]
    else:
        estado = relatorio.status
    rotulo, icone = ESTADOS[estado]

    return {
        'id': arquivo.id,
        'nome': arquivo.nome,
        'icone': arquivo.icone,
        'nome_no_drive': arquivo.nome_no_drive,
        'pasta_no_drive': arquivo.pasta_no_drive,
        'para_que_serve': arquivo.para_que_serve,
        'formato_esperado': arquivo.formato_esperado,
        'upload_habilitado': arquivo.auditoria_pronta,
        'estado': estado,
        'estado_rotulo': rotulo,
        'estado_icone': icone,
        'relatorio': relatorio,
        'quando': quando,
        'envio': envio,
        'linha_drive': linha_drive,
    }


# Função Objetivo: Os grupos da tela, na ordem, cada um com seus cartões ainda sem arquivo.
def montar_grupos():
    return [
        {'id': id_do_grupo, 'titulo': titulo, 'subtitulo': subtitulo, 'cartoes': [montar_cartao(a) for a in arquivos]}
        for id_do_grupo, titulo, subtitulo, arquivos in arquivos_por_grupo()
    ]
