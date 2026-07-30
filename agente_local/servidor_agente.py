# agente_local/servidor_agente.py

# Função Objetivo: O agente de verdade — recebe o aviso do navegador (via
# rota local /executar/<id>), busca os itens na API do Django, e processa
# cada 1 (baixar -> postar -> avisar resultado), com F8/F9 e blindagem de
# foco. Roda escondido na bandeja do sistema (pystray), sem terminal.

import ctypes
import datetime
import os
import shutil
import sys
import tempfile
import threading
import time


# Função Objetivo: Duplica toda saída (print) pro terminal E pra um arquivo
# de log — garante que os logs sobrevivem mesmo se a janela do terminal
# fechar sozinha (crash, ou qualquer outro motivo ainda não diagnosticado).
class _DuplicadorSaida:
    def __init__(self, saida_original, arquivo_log):
        self.saida_original = saida_original
        self.arquivo_log = arquivo_log

    def write(self, texto):
        self.saida_original.write(texto)
        self.arquivo_log.write(texto)
        self.arquivo_log.flush()

    def flush(self):
        self.saida_original.flush()
        self.arquivo_log.flush()

# * [EXPLICAÇÃO] → Corrigido (30/07) — SEM isso, um .exe gerado pelo
#                  PyInstaller não avisa ao Windows que sabe lidar com
#                  telas de alta resolução/escala — o Windows então aplica
#                  uma escala "por trás", sem avisar, fazendo qualquer
#                  coordenada de tela (como mover o mouse pra cima de um
#                  botão) ficar deslocada de forma fixa e repetida. Isso
#                  precisa rodar ANTES de qualquer janela/automação ser
#                  tocada — por isso é a primeira coisa do arquivo.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()  # fallback pra versões mais antigas do Windows
    except Exception:
        pass


# * [EXPLICAÇÃO] → Ativa o log em arquivo o mais cedo possível, antes de
#                  qualquer outra coisa poder falhar — assim até um erro
#                  bem no início já fica registrado.
def _pasta_do_executavel_para_log():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_caminho_log = os.path.join(
    _pasta_do_executavel_para_log(), f'agente_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt',
)
_arquivo_log = open(_caminho_log, 'a', encoding='utf-8')
sys.stdout = _DuplicadorSaida(sys.stdout, _arquivo_log)
sys.stderr = _DuplicadorSaida(sys.stderr, _arquivo_log)
print(f'[AGENTE] Log sendo gravado em: {_caminho_log}')


# * [EXPLICAÇÃO] → Captura QUALQUER exceção não tratada, em qualquer lugar
#                  do programa, antes dela conseguir fechar o processo
#                  silenciosamente. Requisito do usuário: o agente só fecha
#                  quando ELE decide fechar (menu "Sair"), nunca sozinho.
#                  Isso não impede 100% dos jeitos de o Windows encerrar um
#                  processo à força, mas cobre qualquer erro de Python — que
#                  é a causa mais provável.
def _capturar_excecao_nao_tratada(tipo, valor, traceback_obj):
    import traceback
    print('[AGENTE] ERRO NÃO TRATADO — isso NÃO deveria ter fechado o programa:')
    traceback.print_exception(tipo, valor, traceback_obj)


sys.excepthook = _capturar_excecao_nao_tratada

import pystray
from PIL import Image, ImageDraw
from flask import Flask, jsonify
from flask_cors import CORS

from agente_local.aviso_execucao import AvisoExecucao
from agente_local.controle_teclado import ControleTeclado
from agente_local.postagem_ml import postar_video_no_ml
from agente_local.replicacao_ml import replicar_video_no_ml
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


# * [EXPLICAÇÃO] → Generalizada (30/07) — recebe QUAL função de heartbeat
#                  chamar (Postagem ou Replicação), em vez de duplicar essa
#                  mesma thread pros 2 fluxos.
def _enviar_heartbeat_em_loop(funcao_heartbeat, execucao_id, evento_parar):
    import time
    while not evento_parar.is_set():
        try:
            funcao_heartbeat(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id)
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
        target=_enviar_heartbeat_em_loop,
        args=(cliente_api.enviar_heartbeat, execucao_id, evento_parar_heartbeat), daemon=True,
    )
    thread_heartbeat.start()

    if controle.foi_cancelado():
        controle.encerrar()
        aviso.fechar()
        try:
            cliente_api.finalizar_execucao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, cancelada=True)
        except Exception as erro:
            print(f'[AGENTE] Erro ao avisar cancelamento: {erro}')
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
                SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, item['produto_ean'], pasta_temporaria_raiz,
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

    foi_cancelado = controle.foi_cancelado()
    evento_parar_heartbeat.set()

    shutil.rmtree(pasta_temporaria_raiz, ignore_errors=True)
    controle.encerrar()
    aviso.fechar()

    try:
        cliente_api.finalizar_execucao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, cancelada=foi_cancelado)
    except Exception as erro:
        print(f'[AGENTE] Erro ao avisar que a execução terminou: {erro}')

    _voltar_ao_repouso()


# * [EXPLICAÇÃO] → Log simples em .txt (30/07, provisório) — só pra
#                  conferir manualmente se a Replicação real está indo pros
#                  MLBs certos, enquanto não existe tela de histórico no
#                  sistema (fica pra depois, ainda como Django). 1 linha
#                  por replicação concluída, sempre em append — nunca
#                  sobrescreve. Vive na pasta do agente (mesma de
#                  agente_config.env), não no servidor.
def _registrar_log_replicacao(ean, titulo, mlb_origem, marcados, observacao=None):
    caminho_log = os.path.join(_obter_pasta_do_executavel(), 'replicacoes_realizadas.txt')
    agora = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    linha = f'{agora} | EAN {ean} | {titulo} | MLB origem {mlb_origem} | replicado para: {", ".join(marcados)}'
    if observacao:
        linha += f' | obs: {observacao}'
    with open(caminho_log, 'a', encoding='utf-8') as arquivo:
        arquivo.write(linha + '\n')


def _processar_execucao_replicacao(execucao_id):
    aviso = AvisoExecucao()
    aviso.atualizar('AGUARDANDO — foque a janela certa e pressione F8 pra iniciar  |  F9 cancela', '#d68910')

    controle = ControleTeclado()
    controle.aguardar_inicio()

    evento_parar_heartbeat = threading.Event()
    thread_heartbeat = threading.Thread(
        target=_enviar_heartbeat_em_loop,
        args=(cliente_api.enviar_heartbeat_replicacao, execucao_id, evento_parar_heartbeat), daemon=True,
    )
    thread_heartbeat.start()

    if controle.foi_cancelado():
        controle.encerrar()
        aviso.fechar()
        try:
            cliente_api.finalizar_execucao_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, cancelada=True)
        except Exception as erro:
            print(f'[AGENTE] Erro ao avisar cancelamento (replicação): {erro}')
        _voltar_ao_repouso()
        return

    try:
        itens = cliente_api.listar_itens_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id)
    except Exception as erro:
        print(f'[AGENTE] Erro ao buscar itens da execução de replicação #{execucao_id}: {erro}')
        controle.encerrar()
        aviso.fechar()
        _voltar_ao_repouso()
        return

    for item in itens:
        if controle.foi_cancelado():
            break

        item_id = item['item_id']

        if not controle.verificar_e_aguardar(aviso):
            break

        try:
            sucesso, mensagem_erro, marcados, nao_encontrados = replicar_video_no_ml(
                item['mlb'], item['outros_mlbs'], controle.janela_referencia,
            )
        except Exception as erro:
            sucesso, mensagem_erro, marcados, nao_encontrados = False, f'Erro inesperado na automação: {erro}', [], []

        if not sucesso:
            try:
                cliente_api.marcar_falhou_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, mensagem_erro or 'Falha ao replicar.')
            except Exception:
                pass
            continue

        if marcados:
            try:
                _registrar_log_replicacao(item['produto_ean'], item['produto_titulo'], item['mlb'], marcados, mensagem_erro)
            except Exception as erro:
                print(f'[AGENTE] Erro ao gravar log de replicação (não impede o fluxo): {erro}')

        try:
            cliente_api.marcar_concluido_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, marcados, nao_encontrados)
            print(f'[AGENTE] Item de replicação #{item_id} concluído.')
        except Exception as erro:
            print(f'[AGENTE] Replicado, mas erro ao avisar o servidor: {erro}')

    foi_cancelado = controle.foi_cancelado()
    evento_parar_heartbeat.set()
    controle.encerrar()
    aviso.fechar()

    try:
        cliente_api.finalizar_execucao_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, cancelada=foi_cancelado)
    except Exception as erro:
        print(f'[AGENTE] Erro ao avisar que a execução de replicação terminou: {erro}')

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


@app_flask.route('/executar-replicacao/<int:execucao_id>', methods=['POST'])
def executar_replicacao(execucao_id):
    # * [EXPLICAÇÃO] → Mesma trava do /executar (Postagem) — execucao_em_andamento
    #                  é 1 flag SÓ, compartilhado entre os 2 tipos. Isso é
    #                  de propósito: Postagem e Replicação usam a MESMA
    #                  infraestrutura de Tkinter/hotkey nesta máquina — 1
    #                  de cada tipo rodando ao mesmo tempo seria o mesmo
    #                  crash que já corrigimos antes (2 execuções concorrentes).
    if execucao_em_andamento['ativo']:
        return jsonify({'status': 'ocupado', 'mensagem': 'Já existe uma execução rodando neste agente.'}), 409

    execucao_em_andamento['ativo'] = True
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('blue')
        icone_referencia['obj'].title = f'Execução de Replicação #{execucao_id} — aguardando F8'

    thread = threading.Thread(target=_processar_execucao_replicacao, args=(execucao_id,), daemon=True)
    thread.start()

    return jsonify({'status': 'iniciado', 'execucao_id': execucao_id})


def _rodar_servidor_flask():
    try:
        app_flask.run(host='127.0.0.1', port=PORTA_LOCAL)
    except Exception as erro:
        print(f'[AGENTE] ERRO — o servidor local (Flask) parou de responder: {erro}')
        import traceback
        traceback.print_exc()


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

try:
    icone.run()
except Exception as erro:
    print(f'[AGENTE] ERRO — o ícone da bandeja parou de funcionar: {erro}')
    import traceback
    traceback.print_exc()
    print('[AGENTE] Aguardando você fechar esta janela manualmente (Ctrl+C ou fechar a janela).')
    # * [EXPLICAÇÃO] → Se o loop do ícone quebrar mesmo assim (não deveria,
    #                  com o try/except acima), mantém o PROCESSO vivo de
    #                  propósito — nunca fecha sozinho, mesmo sem o ícone
    #                  funcionando mais. Só sai quando o usuário decidir.
    while True:
        time.sleep(3600)