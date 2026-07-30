import os
import sys
import threading
import pystray
import requests
from PIL import Image, ImageDraw
from flask import Flask, jsonify
from flask_cors import CORS

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
CORS(app_flask, origins=[SERVIDOR_DJANGO])  # * [EXPLICAÇÃO] → Só aceita
                                             #   chamada vinda do próprio
                                             #   Django configurado — não
                                             #   qualquer página aberta na
                                             #   máquina.

icone_referencia = {'obj': None}


def _criar_imagem(cor):
    imagem = Image.new('RGB', (64, 64), 'white')
    desenho = ImageDraw.Draw(imagem)
    desenho.ellipse((8, 8, 56, 56), fill=cor)
    return imagem


@app_flask.route('/executar/<int:execucao_id>', methods=['POST'])
def executar(execucao_id):
    # * [EXPLICAÇÃO] → Ainda placeholder — só confirma que o navegador
    #                  conseguiu avisar ESTE agente específico, com o ID
    #                  real da execução que o Django criou. A automação de
    #                  verdade (buscar itens, baixar, postar) entra aqui
    #                  depois, chamando SERVIDOR_DJANGO com TOKEN_AGENTE.
    print(f'Recebi aviso pra executar a Execução #{execucao_id}!')
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('blue')
        icone_referencia['obj'].title = f'Executando #{execucao_id}...'
    return jsonify({'status': 'recebido', 'execucao_id': execucao_id})


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