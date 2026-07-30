import threading
import pystray
from PIL import Image, ImageDraw
from flask import Flask, jsonify
from flask_cors import CORS

app_flask = Flask(__name__)
CORS(app_flask)  # * [EXPLICAÇÃO] → Libera qualquer página (Django, AWS, ou
                  #   arquivo aberto direto no navegador) chamar este
                  #   servidor local — sem isso, o navegador bloqueia
                  #   sozinho por segurança (CORS).

icone_referencia = {'obj': None}


def _criar_imagem(cor):
    imagem = Image.new('RGB', (64, 64), 'white')
    desenho = ImageDraw.Draw(imagem)
    desenho.ellipse((8, 8, 56, 56), fill=cor)
    return imagem


@app_flask.route('/notificar', methods=['POST'])
def notificar():
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('blue')
        icone_referencia['obj'].title = 'Recebi o clique do navegador!'
    return jsonify({'status': 'ok'})


def _rodar_servidor_flask():
    app_flask.run(host='127.0.0.1', port=5678)


def _sair(icone, item):
    icone.stop()


# * [EXPLICAÇÃO] → Flask roda numa thread separada (daemon=True — morre
#                  sozinha quando o programa principal fecha) porque tanto
#                  Flask quanto pystray "bloqueiam" o loop principal — os 2
#                  não podem disputar o mesmo lugar.
thread_servidor = threading.Thread(target=_rodar_servidor_flask, daemon=True)
thread_servidor.start()

icone = pystray.Icon(
    'agente_teste',
    _criar_imagem('green'),
    'Agente rodando — tudo OK, use o navegador normalmente',
    menu=pystray.Menu(pystray.MenuItem('Sair', _sair)),
)
icone_referencia['obj'] = icone
icone.run()