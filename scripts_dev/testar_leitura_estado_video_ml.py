# scripts_dev/testar_leitura_estado_video_ml.py

# Função Objetivo: testar a lógica REAL de leitura do Estado de um vídeo
# (EM REVISÃO/PUBLICADO/RECUSADO/PAUSADO) na tela filtrada do Mercado Livre
# — só terminal, nada escrito no banco/Agenda ainda. Mesma lógica da
# Replicação: pega o PRIMEIRO estado que aparece na lista (é sempre o mais
# recente), nunca casa pelo número do MLB — confirmado com o usuário que
# a "Anúncio" da 1ª linha pode ser um MLBU/catálogo, não o MLB buscado.

import time
import keyboard
import win32gui
from pywinauto import Application
from pywinauto.keyboard import send_keys

# ==== CONFIGURA AQUI ANTES DE RODAR ====
# Cada item: (MLB pra buscar, estado que a gente espera ver — só pra
# conferência visual no terminal, não é usado pela lógica de leitura)
MLBS_PARA_TESTAR = [
    ('MLB5130142457', 'RECUSADO'),
    ('MLB7508392688', 'PUBLICADO'),
]
# ========================================

ESTADOS_VALIDOS = {'EM REVISÃO', 'PUBLICADO', 'RECUSADO', 'PAUSADO'}

TECLA_CAPTURA = 'F8'
janela_capturada = {'handle': None}


def _capturar_janela():
    janela_capturada['handle'] = win32gui.GetForegroundWindow()


keyboard.add_hotkey(TECLA_CAPTURA, _capturar_janela)
print(f'Foque a janela do Chrome (já logado no ML) e pressione {TECLA_CAPTURA}...')
while janela_capturada['handle'] is None:
    time.sleep(0.2)
keyboard.remove_hotkey(TECLA_CAPTURA)
print(f'Janela capturada: "{win32gui.GetWindowText(janela_capturada["handle"])}"\n')

handle = janela_capturada['handle']
app = Application(backend='uia').connect(handle=handle)
janela = app.window(handle=handle)


# Função Objetivo: percorre os Text da tela NA ORDEM e devolve o primeiro
# que bater com 1 dos 4 estados conhecidos — é sempre a linha mais recente,
# não importa qual "Anúncio" (#MLB) apareça acima dele.
def _ler_primeiro_estado_e_anuncio(janela):
    anuncio_atual = None
    for elemento in janela.descendants(control_type='Text'):
        try:
            texto = elemento.window_text().strip()
        except Exception:
            continue
        if not texto:
            continue
        if texto.startswith('#'):
            anuncio_atual = texto
        if texto in ESTADOS_VALIDOS:
            return texto, anuncio_atual
    return None, None


for mlb, estado_esperado in MLBS_PARA_TESTAR:
    url = f'https://vendedores.mercadolivre.com.br/video/creator/listing?page=1&item_id={mlb}'
    print(f'\n{"=" * 70}')
    print(f'MLB buscado: {mlb}  (esperado: {estado_esperado})')
    print(f'Navegando para: {url}')
    janela.set_focus()
    send_keys('^l')
    time.sleep(0.3)
    send_keys(url, with_spaces=True)
    send_keys('{ENTER}')

    print('Aguardando a página carregar (6s)...')
    time.sleep(6)

    estado_lido, anuncio_lido = _ler_primeiro_estado_e_anuncio(janela)

    if estado_lido is None:
        print('  RESULTADO: nenhum estado encontrado na tela (lista vazia ou página não carregou).')
        continue

    marcador = 'OK' if estado_lido == estado_esperado else 'DIVERGENTE'
    print(f'  Anúncio da 1ª linha (informativo, não usado pra decidir nada): {anuncio_lido}')
    print(f'  Estado lido: {estado_lido}  |  Estado esperado: {estado_esperado}  |  {marcador}')

print(f'\n{"=" * 70}')
print('Script terminou.')