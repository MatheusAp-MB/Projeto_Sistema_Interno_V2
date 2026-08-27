# agente_local/verificacao_ml.py

# Função Objetivo: Lê, na tela "Meus Vídeos" do Mercado Livre, qual o estado
# atual do clip postado pra um MLB — usado pela Verificação de Aprovação
# Autônoma. Lógica validada em scripts_dev/testar_leitura_estado_video_ml.py
# (27/08), com 2 casos reais (1 Recusado, 1 Publicado): a tela filtrada por
# item_id ÀS VEZES mostra uma linha extra (possível MLBU/catálogo — não
# confirmado com certeza), então NUNCA lemos o estado casando pelo texto
# literal do MLB. Em vez disso, olhamos só o 1º estado que aparecer na tela,
# em ordem — mesma lógica já usada em replicacao_ml.py pro "1º vertical_dots
# = vídeo mais recente".

import time
from pywinauto import Application
from pywinauto.keyboard import send_keys

ESTADOS_VALIDOS = ('EM REVISÃO', 'PUBLICADO', 'RECUSADO', 'PAUSADO')


def _montar_url(mlb):
    return f'https://vendedores.mercadolivre.com.br/video/creator/listing?page=1&item_id={mlb}'


# Função Objetivo: Único ponto do sistema que lê o estado de aprovação de 1
# MLB na tela do ML. Devolve o texto do estado (um de ESTADOS_VALIDOS), ou
# None se a tela não mostrou nenhum dos 4 estados conhecidos (ex: MLB sem
# nenhum vídeo postado ainda).
def ler_estado_aprovacao(mlb, janela_handle):
    app = Application(backend='uia').connect(handle=janela_handle)
    janela = app.window(handle=janela_handle)

    url = _montar_url(mlb)
    janela.set_focus()
    send_keys('^l')
    time.sleep(0.3)
    send_keys(url, with_spaces=True)
    send_keys('{ENTER}')

    time.sleep(6)

    for elemento in janela.descendants(control_type='Text'):
        try:
            texto = elemento.window_text().strip()
        except Exception:
            continue
        if texto in ESTADOS_VALIDOS:
            return texto

    return None