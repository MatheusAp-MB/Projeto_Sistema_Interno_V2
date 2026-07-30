# agente_local/servidor_agente.py

# Função Objetivo: O agente de verdade — recebe o aviso do navegador (via
# rota local /executar/<id>), busca os itens na API do Django, e processa
# cada 1 (baixar -> postar -> avisar resultado), com F8/F9 e blindagem de
# foco. Roda escondido na bandeja do sistema (pystray), sem terminal.

import os
import shutil
import sys
import tempfile
import threading

import pystray
from PIL import Image, ImageDraw
from flask import Flask, jsonify
from flask_cors import CORS

from agente_local.aviso_execucao import AvisoExecucao
from agente_local.controle_teclado import ControleTeclado
from agente_local.postagem_ml import postar_video_no_ml
from agente_local import cliente_api

PORTA_LOCAL = 5678


def _obter_pasta_do_executavel():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def carregar_configuracao():
    caminho_config = os.path.join(_obter_pasta_do_executavel(), 'agente_config.env')
    if not os.path.exists(caminho_config):
        raise RuntimeError(
            f'Arquivo de configuração não encontrado: {caminho_config}\n'
            f'Crie esse arquivo, na mesma pasta do programa, com:\n'
            f'SERVIDOR=http://endereco:porta\nTOKEN=seu_token_aqui'
        )
    configuracao = {}
    with open(caminho_config, 'r', encoding='utf-8') as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if '=' in linha:
                chave, valor = linha.split('=', 1)
                configuracao[chave.strip()] = valor.strip()
    if 'SERVIDOR' not in configuracao or 'TOKEN' not in configuracao:
        raise RuntimeError(f'{caminho_config} precisa ter as linhas SERVIDOR=... e TOKEN=...')
    return configuracao['SERVIDOR'], configuracao['TOKEN']


SERVIDOR_DJANGO, TOKEN_AGENTE = carregar_configuracao()

app_flask = Flask(__name__)
CORS(app_flask, origins=[SERVIDOR_DJANGO])

icone_referencia = {'obj': None}
execucao_em_andamento = {'ativo': False}


def _criar_imagem(cor):
    imagem = Image.new('RGB', (64, 64), 'white')
    desenho = ImageDraw.Draw(imagem)
    desenho.ellipse((8, 8, 56, 56), fill=cor)
    return imagem


def _voltar_ao_repouso():
    execucao_em_andamento['ativo'] = False
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('green')
        icone_referencia['obj'].title = f'Agente rodando — conectado a {SERVIDOR_DJANGO}'


def _enviar_heartbeat_em_loop(execucao_id, evento_parar):
    import time
    while not evento_parar.is_set():
        try:
            cliente_api.enviar_heartbeat(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id)
        except Exception as erro:
            print(f'[AGENTE] Falha ao enviar heartbeat: {erro}')
        evento_parar.wait(10)  # * a cada 10s — bem dentro do limite de 30s do Django


def _processar_execucao(execucao_id):
    aviso = AvisoExecucao()
    aviso.atualizar('AGUARDANDO — foque a janela certa e pressione F8 pra iniciar  |  F9 cancela', '#d68910')

    controle = ControleTeclado()
    controle.aguardar_inicio()

    evento_parar_heartbeat = threading.Event()
    thread_heartbeat = threading.Thread(
        target=_enviar_heartbeat_em_loop, args=(execucao_id, evento_parar_heartbeat), daemon=True,
    )
    thread_heartbeat.start()

    if controle.foi_cancelado():
        controle.encerrar()
        aviso.fechar()
        _voltar_ao_repouso()
        return

    try:
        itens = cliente_api.listar_itens(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id)
    except Exception as erro:
        print(f'[AGENTE] Erro ao buscar itens da execução #{execucao_id}: {erro}')
        controle.encerrar()
        aviso.fechar()
        _voltar_ao_repouso()
        return

    pasta_temporaria_raiz = tempfile.mkdtemp(prefix='agente_postagem_')

    for item in itens:
        if controle.foi_cancelado():
            break
        if item['ja_postado_hoje']:
            print(f'[AGENTE] Item #{item["item_id"]} já postado hoje — pulando.')
            continue

        item_id = item['item_id']

        try:
            caminho_local, drive_file_id, pasta_videos_id = cliente_api.baixar_video(
                SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, pasta_temporaria_raiz,
            )
        except Exception as erro:
            print(f'[AGENTE] Erro ao baixar vídeo do item #{item_id}: {erro}')
            try:
                cliente_api.marcar_falhou(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, f'Erro ao baixar: {erro}')
            except Exception:
                pass
            continue

        if not controle.verificar_e_aguardar(aviso):
            break

        try:
            sucesso, mensagem_erro = postar_video_no_ml(item['mlb'], caminho_local, controle.janela_referencia)
        except Exception as erro:
            sucesso, mensagem_erro = False, f'Erro inesperado na automação: {erro}'

        if not sucesso:
            cliente_api.marcar_falhou(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, mensagem_erro or 'Falha ao postar.')
            continue

        try:
            cliente_api.marcar_concluido(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, drive_file_id, pasta_videos_id)
            print(f'[AGENTE] Item #{item_id} concluído.')
        except Exception as erro:
            print(f'[AGENTE] Postado, mas erro ao avisar o servidor: {erro}')

    evento_parar_heartbeat.set()
    shutil.rmtree(pasta_temporaria_raiz, ignore_errors=True)
    controle.encerrar()
    aviso.fechar()
    _voltar_ao_repouso()


@app_flask.route('/executar/<int:execucao_id>', methods=['POST'])
def executar(execucao_id):
    # * [EXPLICAÇÃO] → Recusa uma 2ª execução enquanto a 1ª ainda roda NESTE
    #                  agente — mesma lição já aprendida (2 execuções
    #                  concorrentes derrubam Tkinter/hotkey).
    if execucao_em_andamento['ativo']:
        return jsonify({'status': 'ocupado', 'mensagem': 'Já existe uma execução rodando neste agente.'}), 409

    execucao_em_andamento['ativo'] = True
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('blue')
        icone_referencia['obj'].title = f'Execução #{execucao_id} — aguardando F8'

    thread = threading.Thread(target=_processar_execucao, args=(execucao_id,), daemon=True)
    thread.start()

    return jsonify({'status': 'iniciado', 'execucao_id': execucao_id})


def _rodar_servidor_flask():
    app_flask.run(host='127.0.0.1', port=PORTA_LOCAL)


def _sair(icone, item):
    icone.stop()


thread_servidor = threading.Thread(target=_rodar_servidor_flask, daemon=True)
thread_servidor.start()

icone = pystray.Icon(
    'agente_postagem',
    _criar_imagem('green'),
    f'Agente rodando — conectado a {SERVIDOR_DJANGO}',
    menu=pystray.Menu(pystray.MenuItem('Sair', _sair)),
)
icone_referencia['obj'] = icone
icone.run()