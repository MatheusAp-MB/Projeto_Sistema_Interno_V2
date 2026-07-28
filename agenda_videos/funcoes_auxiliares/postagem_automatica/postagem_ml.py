# agenda_videos/funcoes_auxiliares/postagem_automatica/postagem_ml.py

# Função Objetivo: Automação real no Mercado Livre — abre a URL certa, faz
# upload do vídeo, confirma que processou (3 checkpoints) — e PARA antes do
# clique final ("Enviar clip"/"Anunciar"), de propósito, por decisão do
# usuário. Adaptado do protótipo já validado (simular_dia_agenda.py).
#
# * [EXPLICAÇÃO] → A interface do Mercado Livre já apareceu em português
#                  ("Arraste um vídeo...", "Enviar clip") E em espanhol
#                  ("Subir archivo", "Anunciar") em testes reais — não dá
#                  pra confiar em 1 nome fixo. NOMES_BOTAO_* guarda TODAS as
#                  variantes conhecidas; _buscar_por_qualquer_nome() é o
#                  ÚNICO lugar que tenta cada uma — nunca duplicar essa
#                  tentativa em mais de 1 ponto do arquivo.

import os
import time
import win32gui
from pywinauto import Application
from pywinauto.keyboard import send_keys

NOMES_BOTAO_UPLOAD = ['Arraste um vídeo ou busque-o nos seus arquivos', 'Subir archivo']
NOMES_BOTAO_ENVIAR = ['Enviar clip', 'Anunciar']


def _montar_url(mlb):
    return f'https://www.mercadolivre.com.br/video/creator/upload?item_syi={mlb}&item_id={mlb}&origin=syi'


def _listar_janelas_abertas():
    handles = []
    win32gui.EnumWindows(lambda h, resultado: resultado.append(h), handles)
    return set(h for h in handles if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h))


# Função Objetivo: Tenta achar 1 elemento por QUALQUER 1 dos nomes possíveis
# — devolve o elemento assim que achar o 1º que existir de verdade, ou None
# se nenhum bater. Único lugar do arquivo que faz essa tentativa.
def _buscar_por_qualquer_nome(janela, nomes_possiveis, control_type='Button'):
    for nome in nomes_possiveis:
        elemento = janela.child_window(title=nome, control_type=control_type)
        if elemento.exists():
            return elemento
    return None


def postar_video_no_ml(mlb, caminho_video_local, janela_handle):
    app = Application(backend='uia').connect(handle=janela_handle)
    janela_ml = app.window(handle=janela_handle)

    url = _montar_url(mlb)
    janela_ml.set_focus()
    send_keys('^l')
    time.sleep(0.3)
    send_keys(url, with_spaces=True)
    send_keys('{ENTER}')

    # * [EXPLICAÇÃO] → CHECKPOINT 1: página carregou de verdade (debounce de
    #                  2 checagens seguidas — evita confirmar a página
    #                  ANTERIOR ainda de pé, no instante da troca).
    time.sleep(1.5)
    carregou = False
    checagens_seguidas = 0
    for _ in range(30):
        time.sleep(0.5)
        existe_agora = _buscar_por_qualquer_nome(janela_ml, NOMES_BOTAO_UPLOAD) is not None
        checagens_seguidas = checagens_seguidas + 1 if existe_agora else 0
        if checagens_seguidas >= 2:
            carregou = True
            break
    if not carregou:
        try:
            todos_os_botoes = [b.window_text() for b in janela_ml.descendants(control_type='Button')]
        except Exception as erro_diagnostico:
            todos_os_botoes = [f'ERRO AO LISTAR: {erro_diagnostico}']
        print(f'[DIAGNÓSTICO] Botões visíveis na tela (Checkpoint 1 falhou): {todos_os_botoes}')
        return False, 'Página do Mercado Livre não carregou a tempo (Checkpoint 1).'

    botao_enviar = _buscar_por_qualquer_nome(janela_ml, NOMES_BOTAO_ENVIAR)
    botao_upload = _buscar_por_qualquer_nome(janela_ml, NOMES_BOTAO_UPLOAD)

    janelas_antes = _listar_janelas_abertas()
    botao_upload.click_input()

    handle_dialogo = None
    for _ in range(25):
        time.sleep(0.2)
        novas = _listar_janelas_abertas() - janelas_antes
        if novas:
            handle_dialogo = novas.pop()
            break
    if handle_dialogo is None:
        return False, 'Janela "Abrir arquivo" não apareceu.'

    app_dialogo = Application(backend='uia').connect(handle=handle_dialogo)
    janela_dialogo = app_dialogo.window(handle=handle_dialogo)
    janela_dialogo.child_window(auto_id='1148', control_type='Edit').set_text(caminho_video_local)
    janela_dialogo.child_window(auto_id='1', control_type='SplitButton').click_input()

    # * [EXPLICAÇÃO] → CHECKPOINT 2: confirma que o ARQUIVO CERTO foi
    #                  escolhido — já é independente de idioma (procura pelo
    #                  nome do ARQUIVO, não por um rótulo fixo).
    nome_arquivo = os.path.basename(caminho_video_local)
    arquivo_confirmado = False
    for _ in range(20):
        time.sleep(0.5)
        elementos = janela_ml.descendants(control_type='Button')
        if any(nome_arquivo in (elem.window_text() or '') for elem in elementos):
            arquivo_confirmado = True
            break
    if not arquivo_confirmado:
        return False, f'Arquivo "{nome_arquivo}" não foi confirmado na tela após o upload (Checkpoint 2).'

    # * [EXPLICAÇÃO] → CHECKPOINT 3: vídeo processado, pronto pra enviar.
    habilitou = False
    for _ in range(30):
        time.sleep(0.5)
        if botao_enviar.is_enabled():
            habilitou = True
            break
    if not habilitou:
        return False, 'Vídeo não processou a tempo — botão de enviar não habilitou (Checkpoint 3).'

    # * [EXPLICAÇÃO] → PARA AQUI DE PROPÓSITO — nunca clica no botão de
    #                  enviar. O vídeo fica processado e pronto na tela,
    #                  aguardando confirmação humana. Decisão do usuário,
    #                  não limitação técnica.
    return True, None