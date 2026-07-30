# agente_local/postagem_ml.py

# Função Objetivo: Automação real no Mercado Livre — abre a URL certa, faz
# upload do vídeo, confirma que processou (3 checkpoints) — e PARA antes do
# clique final ("Enviar clip"/"Anunciar"), de propósito, por decisão do
# usuário. Fonte única — antes existia uma cópia dentro de agenda_videos/,
# removida (30/07) quando o agente assumiu de vez a execução real.

import os
import time
import win32gui
from pywinauto import Application
from pywinauto.keyboard import send_keys
from agente_local.posicionar_mouse_com_seguranca import posicionar_mouse_com_seguranca

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


def _log(mensagem):
    import datetime
    agora = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f'[POSTAGEM_ML {agora}] {mensagem}')


def postar_video_no_ml(mlb, caminho_video_local, janela_handle):
    _log(f'Iniciando — MLB={mlb}, arquivo={caminho_video_local}')
    app = Application(backend='uia').connect(handle=janela_handle)
    janela_ml = app.window(handle=janela_handle)

    url = _montar_url(mlb)
    janela_ml.set_focus()
    send_keys('^l')
    time.sleep(0.3)
    send_keys(url, with_spaces=True)
    send_keys('{ENTER}')
    _log('URL enviada, aguardando Checkpoint 1...')

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
        _log(f'[DIAGNÓSTICO] Checkpoint 1 falhou. Botões visíveis: {todos_os_botoes}')
        return False, 'Página do Mercado Livre não carregou a tempo (Checkpoint 1).'
    _log('Checkpoint 1 OK — página carregada. Localizando botões...')

    botao_enviar = _buscar_por_qualquer_nome(janela_ml, NOMES_BOTAO_ENVIAR)
    botao_upload = _buscar_por_qualquer_nome(janela_ml, NOMES_BOTAO_UPLOAD)
    _log(f'Botão upload encontrado={botao_upload is not None}, botão enviar encontrado={botao_enviar is not None}')

    janelas_antes = _listar_janelas_abertas()
    _log('Clicando no botão de upload...')
    botao_upload.click_input()

    handle_dialogo = None
    for _ in range(25):
        time.sleep(0.2)
        novas = _listar_janelas_abertas() - janelas_antes
        if novas:
            handle_dialogo = novas.pop()
            break
    if handle_dialogo is None:
        _log('Janela "Abrir arquivo" NÃO apareceu depois do clique.')
        return False, 'Janela "Abrir arquivo" não apareceu.'
    _log(f'Janela "Abrir arquivo" apareceu (handle={handle_dialogo}, título="{win32gui.GetWindowText(handle_dialogo)}").')

    app_dialogo = Application(backend='uia').connect(handle=handle_dialogo)
    janela_dialogo = app_dialogo.window(handle=handle_dialogo)

    # * [EXPLICAÇÃO DIAGNÓSTICO] → Lista TODOS os controles reais dessa
    #                  janela, nessa máquina específica — auto_id pode
    #                  variar entre versões/idiomas do Windows.
    _log('Controles encontrados na janela "Abrir arquivo":')
    for elemento in janela_dialogo.descendants():
        try:
            print(
                f'    control_type={elemento.element_info.control_type!r} | '
                f'auto_id={elemento.element_info.automation_id!r} | '
                f'texto={elemento.window_text()!r}'
            )
        except Exception as erro_diagnostico:
            print(f'    (erro ao ler 1 elemento: {erro_diagnostico})')

    _log('Tentando localizar o campo de texto (Edit) pra digitar o caminho...')
    campo_nome_arquivo = None
    for auto_id_tentativa in ['1148', '1001', '1002']:
        try:
            candidato = janela_dialogo.child_window(auto_id=auto_id_tentativa, control_type='Edit')
            if candidato.exists():
                campo_nome_arquivo = candidato
                _log(f'Campo de texto encontrado com auto_id={auto_id_tentativa!r}.')
                break
        except Exception:
            continue

    if campo_nome_arquivo is None:
        # * [EXPLICAÇÃO] → Fallback — pega o PRIMEIRO Edit que existir,
        #                  não importa o auto_id, já que já sabemos (pelo
        #                  log acima) todos os controles reais disponíveis.
        try:
            campo_nome_arquivo = janela_dialogo.descendants(control_type='Edit')[0]
            _log('Campo de texto encontrado via fallback (1º Edit da janela).')
        except IndexError:
            _log('NENHUM campo de texto (Edit) encontrado na janela — impossível digitar o caminho.')
            return False, 'Campo de texto da janela "Abrir arquivo" não encontrado (ver log de controles acima).'

    campo_nome_arquivo.set_text(caminho_video_local)
    _log(f'Caminho digitado: {caminho_video_local}')

    _log('Tentando localizar o botão "Abrir"...')
    botao_abrir = None
    for auto_id_tentativa, tipo_tentativa in [('1', 'SplitButton'), ('1', 'Button'), ('1', 'ButtonControl')]:
        try:
            candidato = janela_dialogo.child_window(auto_id=auto_id_tentativa, control_type=tipo_tentativa)
            if candidato.exists():
                botao_abrir = candidato
                _log(f'Botão "Abrir" encontrado com auto_id={auto_id_tentativa!r}, control_type={tipo_tentativa!r}.')
                break
        except Exception:
            continue

    if botao_abrir is None:
        _log('Botão "Abrir" NÃO encontrado por nenhuma tentativa — ver log de controles acima pro nome real.')
        return False, 'Botão "Abrir" da janela de arquivo não encontrado (ver log de controles acima).'

    _log('Clicando no botão "Abrir"...')
    botao_abrir.click_input()
    _log('Clique no "Abrir" concluído — prosseguindo pro Checkpoint 2.')

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
        _log(f'Checkpoint 2 falhou — "{nome_arquivo}" nunca apareceu confirmado.')
        return False, f'Arquivo "{nome_arquivo}" não foi confirmado na tela após o upload (Checkpoint 2).'
    _log('Checkpoint 2 OK — arquivo confirmado na tela.')

    # * [EXPLICAÇÃO] → CHECKPOINT 3: vídeo processado, pronto pra enviar.
    habilitou = False
    for _ in range(30):
        time.sleep(0.5)
        if botao_enviar.is_enabled():
            habilitou = True
            break
    if not habilitou:
        _log('Checkpoint 3 falhou — botão de enviar não habilitou a tempo.')
        return False, 'Vídeo não processou a tempo — botão de enviar não habilitou (Checkpoint 3).'
    _log('Checkpoint 3 OK — vídeo processado, botão de enviar habilitado.')

    # * [EXPLICAÇÃO] → PARA AQUI DE PROPÓSITO — nunca clica no botão de
    #                  enviar. O vídeo fica processado e pronto na tela,
    #                  aguardando confirmação humana. Decisão do usuário,
    #                  não limitação técnica. Posiciona o mouse com a mesma
    #                  função compartilhada usada em replicacao_ml.py.
    if not posicionar_mouse_com_seguranca(botao_enviar, _log):
        return True, 'Vídeo processado com sucesso, mas não consegui confirmar a posição do botão na tela.'

    return True, None