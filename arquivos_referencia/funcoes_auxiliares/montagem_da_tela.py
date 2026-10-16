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
# * [DECISÃO, 15/10/2026] → Cada cartão de arquivo que o sistema importa mostra 2 datas: "Data do envio do arquivo" (a data do arquivo no
#   Drive) e "Última atualização do sistema" (quando o botão "Atualizar o sistema com o Drive" gravou esse arquivo), com o
#   selo "Em dia" ou "Drive tem arquivo mais novo" — assim fica claro se o que está no Drive já foi para o sistema.
# * [DECISÃO, 16/10/2026] → INDEPENDÊNCIA entre as empresas (igual à Gestão de APIs): tudo aqui é montado PARA UMA EMPRESA (a selecionada
#   na tela). Os grupos só trazem os cartões dessa empresa (a planilha Busca Legal da outra nem aparece) e a "Última atualização do
#   sistema" é só a dessa empresa. O arquivo do Drive é o mesmo para as duas, mas a data/selo de cada uma vive no banco dela.

from .atualizacao_do_sistema import (
    EMPRESA_ATUALIZADA, EMPRESA_FALHOU, EMPRESA_RECUSADA, STATUS_ARQUIVO_COM_ERROS, STATUS_ATUALIZADO, STATUS_FALHA_DO_DRIVE,
    STATUS_FALHA_DO_SISTEMA, STATUS_NAO_ATUALIZOU, STATUS_OCUPADO, STATUS_PREVIA, STATUS_PREVIA_INVALIDA, STATUS_SEM_ARQUIVO, o_botao_atualiza,
)
from .catalogo_arquivos import arquivos_por_grupo
from .historico_da_atualizacao import NOMES_CURTOS_DAS_EMPRESAS, situacao_do_sistema
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
# * [EXPLICAÇÃO] → Cartões que o botão "Atualizar o sistema com o Drive" atualiza (`importavel`) ganham, abaixo da linha do Drive, a linha da
#   EMPRESA da tela com "Última atualização do sistema" e se o sistema está em dia (`sistema`, de historico_da_atualizacao.py). O
#   estado "em dia" compara a impressão digital (md5) do arquivo que o Drive tem AGORA com a do último arquivo que o sistema leu.
def montar_linha_do_drive(
    id_do_arquivo, empresa, situacao=None, erro=None, link=None, enviado_agora=False, erro_completo=None, sem_arquivo_local=False,
):
    linha = {
        'arquivo_id': id_do_arquivo, 'empresa': empresa, 'enviado_agora': enviado_agora, 'sem_arquivo_local': sem_arquivo_local,
        'estado': 'carregando', 'importavel': o_botao_atualiza(id_do_arquivo), 'sistema': None,
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
    # Com o Drive sem resposta (erro) ainda dá para mostrar as datas do sistema; só não dá para dizer "em dia" (md5 desconhecido).
    if linha['importavel'] and (erro or situacao is not None):
        linha['sistema'] = situacao_do_sistema(id_do_arquivo, situacao.get('md5') if situacao is not None else None, empresa)
    return linha


# Função Objetivo: Dados de 1 cartão. `relatorio` (RelatorioDeAuditoria) e `quando` (datetime) só existem depois
# de a pessoa escolher um arquivo; `envio` (dict devolvido por enviar_para_o_drive) só depois de enviá-lo ao Drive.
# `linha_drive` (de montar_linha_do_drive) já vem pronta quando a própria resposta do Drive está montando o cartão.
def montar_cartao(arquivo, empresa, relatorio=None, quando=None, envio=None, linha_drive=None):
    # Logo depois de enviar, a linha do Drive já mostra o que o Drive guardou (sem perguntar de novo); antes disso, ela se
    # preenche sozinha na tela, perguntando ao Drive (hx-get ao carregar).
    if linha_drive is None:
        situacao_do_envio = None
        if envio is not None:
            situacao_do_envio = {
                'existe': True, 'copias': 1 + envio['copias_que_ficaram'], 'tamanho_em_bytes': envio['tamanho_em_bytes'],
                'modificado_em': envio['modificado_em'], 'caminho': envio['caminho'], 'md5': envio['md5'],
            }
        linha_drive = montar_linha_do_drive(
            arquivo.id, empresa, situacao_do_envio, enviado_agora=envio is not None,
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
        'empresa': empresa,
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


# ---------- Janela "Atualizar o sistema com o Drive" ----------

# status do arquivo -> (rótulo, ícone completo, sufixo da classe do selo — as mesmas cores dos selos dos cartões)
ESTADOS_DA_ATUALIZACAO = {
    STATUS_ATUALIZADO: ('Atualizado', 'fas fa-circle-check', 'valido'),
    STATUS_NAO_ATUALIZOU: ('Não atualizou', 'fas fa-circle-xmark', 'com_erros'),
    STATUS_ARQUIVO_COM_ERROS: ('Arquivo com erros', 'fas fa-circle-xmark', 'com_erros'),
    STATUS_SEM_ARQUIVO: ('Sem arquivo no Drive', 'fas fa-circle-minus', 'sem_arquivo'),
    STATUS_FALHA_DO_DRIVE: ('Drive sem resposta', 'fas fa-triangle-exclamation', 'drive_erro'),
    STATUS_OCUPADO: ('Já em andamento', 'fas fa-hourglass-half', 'em_breve'),
    STATUS_FALHA_DO_SISTEMA: ('Erro do sistema', 'fas fa-circle-xmark', 'com_erros'),
    STATUS_PREVIA: ('Prévia (nada gravado)', 'fas fa-eye', 'em_breve'),
    STATUS_PREVIA_INVALIDA: ('Nada gravado', 'fas fa-circle-xmark', 'com_erros'),
}

# status de 1 empresa -> (rótulo, ícone completo, classe de cor do texto)
ESTADOS_DA_EMPRESA = {
    EMPRESA_ATUALIZADA: ('Gravada', 'fas fa-circle-check', 'valido'),
    EMPRESA_RECUSADA: ('Não gravou', 'fas fa-circle-xmark', 'erro'),
    EMPRESA_FALHOU: ('Falhou', 'fas fa-circle-xmark', 'erro'),
}


# Função Objetivo: Junta ao resultado de atualizar_arquivo o que a tela precisa para desenhar (rótulo, ícone e cor de cada estado).
# Tabela que já estava igual ao Drive aparece como "Já estava em dia" (também é um resultado bom). `nada_mudou` vem de quem gravou: no frete é
# "nenhuma linha nova, mudada ou removida"; no Busca Legal também conta os produtos cujo imposto mudou e o que o Substituir apagou.
def montar_item_da_atualizacao(resultado, link=None):
    rotulo, icone, cor = ESTADOS_DA_ATUALIZACAO[resultado['status']]
    empresas = resultado['empresas']
    if resultado['status'] == STATUS_ATUALIZADO and all(e['nada_mudou'] for e in empresas):
        rotulo = 'Já estava em dia'
    empresas_prontas = []
    for empresa in empresas:
        rotulo_da_empresa, icone_da_empresa, cor_da_empresa = ESTADOS_DA_EMPRESA[empresa['status']]
        empresas_prontas.append({**empresa, 'rotulo': rotulo_da_empresa, 'icone': icone_da_empresa, 'cor': cor_da_empresa})
    return {
        **resultado, 'rotulo': rotulo, 'icone_do_estado': icone, 'cor': cor, 'empresas': empresas_prontas, 'link': link,
        'empresas_com_remocao': [e for e in empresas_prontas if e['status'] == EMPRESA_ATUALIZADA and e['removidas']],
        # Busca Legal: o resultado traz os passos em vez da tabela "Novas / Mudaram / Iguais / Removidas" (que fica só para o frete e para as falhas).
        'com_etapas': any(e['status'] == EMPRESA_ATUALIZADA and e['etapas'] for e in empresas_prontas),
    }


# Função Objetivo: Os grupos da tela PARA A EMPRESA, na ordem, cada um com seus cartões ainda sem arquivo.
# Grupo que ficou sem nenhum cartão para a empresa não entra (a tela não mostra título vazio).
def montar_grupos(empresa):
    return [
        {'id': id_do_grupo, 'titulo': titulo, 'subtitulo': subtitulo, 'cartoes': [montar_cartao(a, empresa) for a in arquivos]}
        for id_do_grupo, titulo, subtitulo, arquivos in arquivos_por_grupo(empresa)
        if arquivos
    ]


# Função Objetivo: O nome curto da empresa para os textos da tela ("Magazine" / "Samvale").
def nome_curto_da_empresa(empresa):
    return NOMES_CURTOS_DAS_EMPRESAS.get(empresa, empresa.title())
