# agente_local/replicacao_ml.py

# Função Objetivo: Automação real de Replicação no Mercado Livre — abre a
# tela de "Meus Clips" filtrada pelo MLB já postado, acha o clip mais
# recente, clica "Mostrar em outros anúncios", e busca e marca cada MLB irmão
# (por MLB exato, nunca por texto/SKU — garante 100% de acerto e
# rastreabilidade, decisão já validada em sessão anterior).
# * [FLAG TEMPORÁRIA, 06/08] → a decisão de 30/07 era clicar de verdade em
#   "Escolher anúncios" (diferente da Postagem, que sempre parava antes).
#   Suspensa enquanto a Replicação Automática ainda está em fase de teste —
#   agora tem o MESMO comportamento seguro da Postagem por padrão
#   (confirmar_de_verdade=False, nunca clica), via a mesma função
#   compartilhada posicionar_mouse_com_seguranca(). O fluxo automático real
#   (servidor_agente.py) passa confirmar_de_verdade=True explícito, pra não
#   mudar o comportamento em produção — a flag existe só pra permitir os
#   testes manuais de dry-run sem tocar no fluxo real.

import time
import win32gui
from pywinauto import Application
from pywinauto.keyboard import send_keys
from agente_local.posicionar_mouse_com_seguranca import posicionar_mouse_com_seguranca


def _log(mensagem):
    import datetime
    agora = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f'[REPLICACAO_ML {agora}] {mensagem}')


def _montar_url_clips(mlb):
    return f'https://www.mercadolivre.com.br/video/creator/listing?item_id={mlb}'


def replicar_video_no_ml(mlb, outros_mlbs, janela_handle, confirmar_de_verdade=False):
    _log(f'Iniciando — MLB={mlb}, outros_mlbs={outros_mlbs}')

    if not outros_mlbs:
        _log('Nenhum outro MLB pra replicar — nada a fazer.')
        return True, None, [], []

    app = Application(backend='uia').connect(handle=janela_handle)
    janela_ml = app.window(handle=janela_handle)

    url = _montar_url_clips(mlb)
    janela_ml.set_focus()
    send_keys('^l')
    time.sleep(0.3)
    send_keys(url, with_spaces=True)
    send_keys('{ENTER}')
    _log('URL enviada, aguardando a lista de clips carregar...')

    # * [EXPLICAÇÃO] → CHECKPOINT 1: espera os botões "vertical_dots"
    #                  (menu de cada linha da lista) aparecerem — mesmo
    #                  debounce de 2 checagens seguidas já usado em
    #                  postagem_ml.py, evitando confirmar a página ANTERIOR
    #                  ainda de pé.
    time.sleep(1.5)
    carregou = False
    checagens_seguidas = 0
    for _ in range(30):
        time.sleep(0.5)
        existem_dots = any(
            b.window_text() == 'vertical_dots' for b in janela_ml.descendants(control_type='Button')
        )
        checagens_seguidas = checagens_seguidas + 1 if existem_dots else 0
        if checagens_seguidas >= 2:
            carregou = True
            break
    if not carregou:
        _log('[DIAGNÓSTICO] Checkpoint 1 falhou — lista de clips não carregou a tempo.')
        return False, 'Lista de clips do Mercado Livre não carregou a tempo (Checkpoint 1).', [], []
    _log('Checkpoint 1 OK — lista carregada.')

    botoes_vertical_dots = [
        b for b in janela_ml.descendants(control_type='Button') if b.window_text() == 'vertical_dots'
    ]
    if not botoes_vertical_dots:
        _log('Nenhum "vertical_dots" encontrado, mesmo após Checkpoint 1 confirmar.')
        return False, 'Nenhum clip encontrado na lista.', [], []

    _log(f'{len(botoes_vertical_dots)} clip(s) na lista — clicando no mais recente (1º da lista)...')
    botoes_vertical_dots[0].click_input()
    time.sleep(1)

    botao_mostrar_outros = next(
        (b for b in janela_ml.descendants(control_type='Button')
         if b.window_text() == 'Mostrar em outros anúncios'),
        None,
    )
    if botao_mostrar_outros is None:
        _log('[DIAGNÓSTICO] "Mostrar em outros anúncios" não encontrado no menu.')
        return False, 'Botão "Mostrar em outros anúncios" não encontrado.', [], []

    _log('Clicando em "Mostrar em outros anúncios"...')
    botao_mostrar_outros.click_input()
    time.sleep(2)

    campo_busca = next(
        (e for e in janela_ml.descendants(control_type='Edit') if e.element_info.automation_id != 'view_1012'),
        None,
    )
    if campo_busca is None:
        _log('[DIAGNÓSTICO] Campo de busca não encontrado na tela de "Escolher anúncios".')
        return False, 'Campo de busca não encontrado na tela de escolher anúncios.', [], []

    marcados = []
    nao_encontrados = []

    for mlb_outro in outros_mlbs:
        _log(f'Buscando {mlb_outro}...')
        campo_busca.click_input()
        time.sleep(0.2)
        send_keys('^a{DELETE}')
        time.sleep(0.2)
        send_keys(mlb_outro, with_spaces=True)
        send_keys('{ENTER}')
        time.sleep(1.5)

        auto_id_esperado = f'CHECKBOX_LIST_ITEM_{mlb_outro}'
        checkbox_alvo = next(
            (c for c in janela_ml.descendants(control_type='CheckBox')
             if c.element_info.automation_id == auto_id_esperado),
            None,
        )
        if checkbox_alvo is None:
            _log(f'  {mlb_outro} NÃO encontrado na busca.')
            nao_encontrados.append(mlb_outro)
        else:
            checkbox_alvo.click_input()
            time.sleep(0.5)
            _log(f'  {mlb_outro} marcado.')
            marcados.append(mlb_outro)

    _log(f'Resumo — marcados: {marcados}, não encontrados: {nao_encontrados}')

    if not marcados:
        return False, f'Nenhum dos {len(outros_mlbs)} MLB(s) foi encontrado na busca.', [], nao_encontrados

    # * [EXPLICAÇÃO] → Sempre limpa a busca por completo antes de localizar
    #                  o botão final — se o ÚLTIMO MLB buscado no loop não
    #                  for encontrado, a tela vira "Não há nada aqui" e o
    #                  botão "Escolher anúncios" some junto (faz parte da
    #                  lista, não é elemento separado) — já descoberto e
    #                  corrigido em sessão anterior de investigação.
    _log('Limpando a busca antes de localizar o botão final...')
    campo_busca.click_input()
    time.sleep(0.2)
    send_keys('^a{DELETE}')
    send_keys('{ENTER}')
    time.sleep(1.5)

    botao_escolher = next(
        (b for b in janela_ml.descendants(control_type='Button') if b.window_text() == 'Escolher anúncios'),
        None,
    )
    if botao_escolher is None:
        _log('[DIAGNÓSTICO] "Escolher anúncios" não encontrado, mesmo depois de limpar a busca.')
        return False, 'Botão "Escolher anúncios" não encontrado.', [], nao_encontrados

    # * [EXPLICAÇÃO] → PARA AQUI DE PROPÓSITO por padrão — mesma decisão da
    #                  Postagem: os MLBs já foram marcados (estado real na
    #                  tela), mas a confirmação final fica pra um humano,
    #                  enquanto confirmar_de_verdade não for True explícito.
    if not confirmar_de_verdade:
        if not posicionar_mouse_com_seguranca(botao_escolher, _log):
            return True, 'Anúncios marcados, mas não consegui confirmar a posição do botão na tela.', marcados, nao_encontrados
        _log(f'Parando ANTES do clique final, de propósito (dry-run) — mouse sobre "Escolher anúncios". Marcados: {marcados}')
        return True, None, marcados, nao_encontrados

    # * [EXPLICAÇÃO] → Clique REAL (30/07, decisão explícita do usuário,
    #                  reativada aqui via confirmar_de_verdade=True) —
    #                  click_input() é clique real (isTrusted=True), mesmo
    #                  padrão já usado em todo o resto deste arquivo.
    _log('Clicando em "Escolher anúncios"...')
    botao_escolher.click_input()
    time.sleep(1)
    _log(f'Replicação confirmada de verdade no Mercado Livre — {len(marcados)} MLB(s): {marcados}')

    mensagem = None
    if nao_encontrados:
        mensagem = f'{len(marcados)} de {len(outros_mlbs)} marcado(s) — não encontrados: {nao_encontrados}'
    return True, mensagem, marcados, nao_encontrados