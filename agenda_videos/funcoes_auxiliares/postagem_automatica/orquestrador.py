# agenda_videos/funcoes_auxiliares/postagem_automatica/orquestrador.py

# Função Objetivo: O loop principal da Postagem Automática — busca produtos
# elegíveis, processa 1 produto por vez (baixar → postar → atualizar Agenda
# → arquivar → apagar pasta local daquele produto), sempre checando o
# controle de teclado (pausa/cancela/blindagem de foco) antes da ação
# arriscada. Roda dentro de 1 thread em segundo plano, disparada pela view —
# nunca chamado direto numa requisição HTTP (travaria a resposta por minutos).

import os
import shutil
import tempfile

from django.db import close_old_connections
from django.utils import timezone
from agenda_videos.models import (
    ExecucaoPostagemAutomatica, StatusExecucao, ItemExecucaoPostagem, StatusItemExecucao,
)
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import listar_a_fazer_hoje
from agenda_videos.funcoes_auxiliares.postagem_ciclica import marcar_ciclo_atual_aguardando_aprovacao, ja_postou_hoje
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_indicadores_agenda_produto
from agenda_videos.funcoes_auxiliares.drive.localizador import LocalizadorArquivosProduto
from agenda_videos.funcoes_auxiliares.drive.arquivador import ArquivadorDrive, montar_caminho_local_organizado
from agenda_videos.funcoes_auxiliares.drive.parser import parsear_arquivos_produto
from agente_local.aviso_execucao import AvisoExecucao
from .controle_teclado import ControleTeclado
from agente_local.postagem_ml import postar_video_no_ml


# Função Objetivo: Quem entra na fila — Ativo, pendente de postar hoje, SEM
# Reestruturação Manual (esses a equipe finaliza manualmente; postar de novo
# duplicaria conteúdo já publicado pelo processo antigo), já na ordem de
# prioridade certa — mesma regra que já vale pro resto da Agenda, nenhum
# filtro novo escrito aqui.
def listar_produtos_elegiveis():
    return listar_a_fazer_hoje(filtros={'pendente_agora': ['postar']})


# * [EXPLICAÇÃO] → Não é mais privada (29/07) — a API (api/postagem_automatica/
#                  views.py) reaproveita esta função, em vez de duplicá-la.
def obter_mlb_do_produto(produto):
    from mercado_livre.models import VariacaoAnuncioMercadoLivre
    variacao = VariacaoAnuncioMercadoLivre.objects.filter(produto=produto).select_related('anuncio').first()
    return variacao.anuncio.mlb if variacao else None


# Função Objetivo: Acha o vídeo EXATO da ocorrência atual (CicloVideo já diz
# exatamente qual arquivo baixar, sem precisar de cache local à parte).
# * [PENDENTE] → Assume que a pasta do Drive continua organizada por fase,
#                com arquivos numerados dentro dela — ainda não confirmado se
#                isso muda no modelo novo (Base/Completo por OCORRÊNCIA, não
#                mais por fase inteira). Revisitar quando a estrutura do
#                Drive for discutida à parte.
def resolver_arquivo_da_ocorrencia(produto, ciclo):
    localizador = LocalizadorArquivosProduto()
    encontrado, arquivos_brutos, motivo, pasta_videos_id = localizador.localizar_arquivos(produto.marca, produto.ean)
    if not encontrado:
        return None, None, motivo

    estrutura = parsear_arquivos_produto(produto.marca, produto.ean, arquivos_brutos)
    fase = ciclo.fase
    numero_esperado = ciclo.numero_ocorrencia
    completos_da_fase = estrutura.fases[fase].completos
    todos_os_numerados = completos_da_fase.arquivos_validos + completos_da_fase.arquivos_fora_de_sequencia
    arquivo_alvo = next((a for a in todos_os_numerados if a.numero == numero_esperado), None)

    if arquivo_alvo is None:
        return None, pasta_videos_id, f'Vídeo da ocorrência {numero_esperado} não encontrado em Videos/.'

    return arquivo_alvo, pasta_videos_id, None


# * [EXPLICAÇÃO] → Fonte única de verdade de "qual status grava em qual
#                  timestamp" — nunca duplicar essa relação em mais de 1 lugar.
CAMPO_TIMESTAMP_POR_STATUS = {
    StatusItemExecucao.BAIXANDO: 'baixando_em',
    StatusItemExecucao.POSTANDO: 'postando_em',
    StatusItemExecucao.ATUALIZANDO_AGENDA: 'atualizando_agenda_em',
    StatusItemExecucao.ARQUIVANDO: 'arquivando_em',
}
ESTADOS_FINAIS = {StatusItemExecucao.CONCLUIDO, StatusItemExecucao.FALHOU, StatusItemExecucao.CANCELADO}


def _marcar_item(item, status, mensagem_erro=None):
    # * [EXPLICAÇÃO] → close_old_connections() ANTES de cada escrita — a
    #                  thread em segundo plano nunca passa pelo ciclo normal
    #                  de conexão por requisição do Django, então força isso
    #                  manualmente, em todo ponto de atualização, não só 1
    #                  vez no início.
    close_old_connections()
    item.status = status
    item.mensagem_erro = mensagem_erro
    campos_atualizados = ['status', 'mensagem_erro', 'atualizado_em']

    campo_timestamp = CAMPO_TIMESTAMP_POR_STATUS.get(status)
    if campo_timestamp:
        setattr(item, campo_timestamp, timezone.now())
        campos_atualizados.append(campo_timestamp)

    if status in ESTADOS_FINAIS:
        item.finalizado_em = timezone.now()
        campos_atualizados.append('finalizado_em')

    item.save(update_fields=campos_atualizados)


def _processar_1_produto(item, controle_teclado, aviso, arquivador, pasta_temporaria_raiz):
    from produtos.models import Produto

    # * [EXPLICAÇÃO] → Busca fresco — mesmo motivo já documentado em views.py
    #                  (cache de relação grudado no objeto, entre uma escrita
    #                  e outra).
    produto = Produto.objects.prefetch_related('ciclos_video').get(id=item.produto_id)
    ciclo = produto.ciclos_video.first()  # já ordenado por -criado_em
    if ciclo is None or ciclo.etapa_atual() != 'postar':
        _marcar_item(item, StatusItemExecucao.FALHOU, 'Produto sem ocorrência pronta pra postar — não deveria acontecer aqui.')
        return

    # * [EXPLICAÇÃO] → Checado ANTES de baixar qualquer coisa — evita gastar
    #                  tempo/chamada de API num produto que já vai ser
    #                  pulado de qualquer jeito. Cobre o caso descrito pelo
    #                  usuário: rodar a Postagem Automática 2x no mesmo dia
    #                  (de propósito ou sem querer), depois de já ter
    #                  aprovado+replicado a 1ª postagem rápido demais.
    if ja_postou_hoje(produto):
        _marcar_item(item, StatusItemExecucao.JA_POSTADO_HOJE)
        return

    mlb = obter_mlb_do_produto(produto)
    if mlb is None:
        _marcar_item(item, StatusItemExecucao.FALHOU, 'Produto sem MLB vinculado (VariacaoAnuncioMercadoLivre).')
        return

    # --- Baixando ---
    _marcar_item(item, StatusItemExecucao.BAIXANDO)
    arquivo_alvo, pasta_videos_id, motivo = resolver_arquivo_da_ocorrencia(produto, ciclo)
    if arquivo_alvo is None:
        _marcar_item(item, StatusItemExecucao.FALHOU, motivo or 'Vídeo não encontrado no Drive.')
        return

    caminho_local = montar_caminho_local_organizado(pasta_temporaria_raiz, produto.ean, arquivo_alvo.nome_arquivo)
    try:
        arquivador.baixar_arquivo(arquivo_alvo.drive_file_id, caminho_local)
    except Exception as erro:
        _marcar_item(item, StatusItemExecucao.FALHOU, f'Erro ao baixar do Drive: {erro}')
        return

    # --- Garantir que o download foi feito corretamente ---
    if not os.path.exists(caminho_local) or os.path.getsize(caminho_local) == 0:
        _marcar_item(item, StatusItemExecucao.FALHOU, 'Download concluiu mas o arquivo local ficou vazio/ausente.')
        return

    # --- Checagem obrigatória antes de qualquer ação arriscada ---
    if not controle_teclado.verificar_e_aguardar(aviso):
        _marcar_item(item, StatusItemExecucao.CANCELADO)
        return

    # --- Postando ---
    _marcar_item(item, StatusItemExecucao.POSTANDO)
    try:
        sucesso, mensagem_erro = postar_video_no_ml(mlb, caminho_local, controle_teclado.janela_referencia)
    except Exception as erro:
        _marcar_item(item, StatusItemExecucao.FALHOU, f'Erro inesperado na automação: {erro}')
        return
    if not sucesso:
        _marcar_item(item, StatusItemExecucao.FALHOU, mensagem_erro or 'Falha desconhecida ao postar no ML.')
        return

    # --- Atualizando Agenda ---
    _marcar_item(item, StatusItemExecucao.ATUALIZANDO_AGENDA)
    marcar_ciclo_atual_aguardando_aprovacao(produto)
    sincronizar_indicadores_agenda_produto(produto)

    # --- Arquivando (mover pra usados/) ---
    _marcar_item(item, StatusItemExecucao.ARQUIVANDO)
    try:
        arquivador.mover_para_usados(arquivo_alvo.drive_file_id, pasta_videos_id)
    except Exception as erro:
        # * [EXPLICAÇÃO] → A postagem JÁ aconteceu e a Agenda JÁ foi
        #                  atualizada — falha aqui não desfaz isso (fingir
        #                  que não postou seria pior). Conta como concluído,
        #                  só registra o aviso.
        _marcar_item(item, StatusItemExecucao.CONCLUIDO, f'Postado, mas falhou ao arquivar no Drive: {erro}')
        return

    # --- Apagando a pasta local deste produto (não espera o lote inteiro) ---
    shutil.rmtree(os.path.dirname(caminho_local), ignore_errors=True)

    _marcar_item(item, StatusItemExecucao.CONCLUIDO)


def _finalizar_execucao(execucao, status):
    execucao.status = status
    execucao.finalizado_em = timezone.now()
    execucao.save(update_fields=['status', 'finalizado_em'])


def executar_postagem_automatica(execucao_id):
    # * [EXPLICAÇÃO] → CoInitialize — o pywinauto (backend UIA) precisa disso
    #                  na thread que vai chamar ele. Acontece sozinho quando
    #                  se roda um script direto no terminal; NÃO acontece
    #                  numa thread própria dentro de outro processo (como
    #                  esta, dentro do Django) — sem isso, checagens do UIA
    #                  podem se comportar de forma errática.
    import pythoncom
    pythoncom.CoInitialize()

    close_old_connections()

    execucao = ExecucaoPostagemAutomatica.objects.get(id=execucao_id)
    aviso = AvisoExecucao()
    aviso.atualizar(
        'AGUARDANDO — foque o Mercado Livre e pressione F8 pra iniciar  |  F9 cancela',
        '#d68910',
    )

    controle_teclado = ControleTeclado(execucao_id)
    controle_teclado.aguardar_inicio()

    if controle_teclado.foi_cancelado():
        execucao.itens.filter(status=StatusItemExecucao.AGUARDANDO).update(status=StatusItemExecucao.CANCELADO)
        _finalizar_execucao(execucao, StatusExecucao.CANCELADO)
        controle_teclado.encerrar()
        aviso.fechar()
        return

    pasta_temporaria_raiz = tempfile.mkdtemp(prefix='postagem_automatica_')
    arquivador = ArquivadorDrive()

    try:
        for item in execucao.itens.order_by('ordem'):
            if controle_teclado.foi_cancelado():
                _marcar_item(item, StatusItemExecucao.CANCELADO)
                continue
            _processar_1_produto(item, controle_teclado, aviso, arquivador, pasta_temporaria_raiz)
    finally:
        shutil.rmtree(pasta_temporaria_raiz, ignore_errors=True)
        controle_teclado.encerrar()
        aviso.fechar()

        status_final = StatusExecucao.CANCELADO if controle_teclado.foi_cancelado() else StatusExecucao.CONCLUIDO
        _finalizar_execucao(execucao, status_final)
        pythoncom.CoUninitialize()