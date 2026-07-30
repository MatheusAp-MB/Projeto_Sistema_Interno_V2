import os
import sys
import time
import keyboard
import win32gui
from pywinauto import Application
from pywinauto.keyboard import send_keys


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from mercado_livre.models import VariacaoAnuncioMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
MLB_JA_POSTADO = 'MLB1633265106'  # o MLB que já tem clip publicado, do seu print
# ========================================


# Função Objetivo: Acha o Produto dono desse MLB, depois lista os MLBs de
# TODOS os outros anúncios do mesmo produto (exclui o já postado) — mesma
# consulta que a automação de verdade vai usar.
def _obter_outros_mlbs(mlb_ja_postado):
    variacao_postada = VariacaoAnuncioMercadoLivre.objects.filter(
        anuncio__mlb=mlb_ja_postado,
    ).select_related('produto').first()
    if variacao_postada is None or variacao_postada.produto is None:
        return []
    produto = variacao_postada.produto
    mlbs = VariacaoAnuncioMercadoLivre.objects.filter(
        produto=produto,
    ).exclude(anuncio__mlb=mlb_ja_postado).values_list('anuncio__mlb', flat=True).distinct()
    return list(mlbs)

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

url = f'https://www.mercadolivre.com.br/video/creator/listing?item_id={MLB_JA_POSTADO}'
print(f'Navegando para: {url}')
janela.set_focus()
send_keys('^l')
time.sleep(0.3)
send_keys(url, with_spaces=True)
send_keys('{ENTER}')

print('Aguardando a página carregar (6s)...\n')
time.sleep(6)

print('=== Botões visíveis na página ===')
try:
    for i, botao in enumerate(janela.descendants(control_type='Button')):
        try:
            print(f'  [{i}] texto={botao.window_text()!r} | auto_id={botao.element_info.automation_id!r}')
        except Exception as erro:
            print(f'  [{i}] (erro ao ler: {erro})')
except Exception as erro:
    print(f'ERRO ao listar botões: {erro}')

print('\n=== Clicando no PRIMEIRO "vertical_dots" (deveria ser o vídeo mais recente) ===')
botoes_vertical_dots = [b for b in janela.descendants(control_type='Button') if b.window_text() == 'vertical_dots']
print(f'Total de "vertical_dots" encontrados: {len(botoes_vertical_dots)}')

if botoes_vertical_dots:
    botoes_vertical_dots[0].click_input()
    time.sleep(1)

    print('\n=== O que apareceu DEPOIS do clique (Button) ===')
    for i, botao in enumerate(janela.descendants(control_type='Button')):
        try:
            print(f'  [{i}] texto={botao.window_text()!r} | auto_id={botao.element_info.automation_id!r}')
        except Exception as erro:
            print(f'  [{i}] (erro ao ler: {erro})')

    print('\n=== O que apareceu DEPOIS do clique (MenuItem) ===')
    for i, item in enumerate(janela.descendants(control_type='MenuItem')):
        try:
            print(f'  [{i}] texto={item.window_text()!r}')
        except Exception as erro:
            print(f'  [{i}] (erro ao ler: {erro})')

    print('\n=== O que apareceu DEPOIS do clique (Text/Link, caso o menu seja feito de texto simples) ===')
    for i, item in enumerate(janela.descendants(control_type='Text')):
        try:
            texto = item.window_text()
            if texto.strip():
                print(f'  [{i}] texto={texto!r}')
        except Exception:
            pass

    print('\n=== Clicando em "Mostrar em outros anúncios" ===')
    botao_mostrar = next(
        (b for b in janela.descendants(control_type='Button') if b.window_text() == 'Mostrar em outros anúncios'),
        None,
    )
    if botao_mostrar is None:
        print('Não encontrei o botão "Mostrar em outros anúncios" — parando aqui.')
    else:
        botao_mostrar.click_input()
        time.sleep(3)

        print('\n=== Botões visíveis na NOVA tela ===')
        for i, botao in enumerate(janela.descendants(control_type='Button')):
            try:
                print(f'  [{i}] texto={botao.window_text()!r} | auto_id={botao.element_info.automation_id!r}')
            except Exception as erro:
                print(f'  [{i}] (erro ao ler: {erro})')

        print('\n=== Campos de texto/busca (Edit) visíveis na NOVA tela ===')
        for i, campo in enumerate(janela.descendants(control_type='Edit')):
            try:
                print(f'  [{i}] auto_id={campo.element_info.automation_id!r} | valor_atual={campo.get_value()!r}')
            except Exception as erro:
                print(f'  [{i}] (erro ao ler: {erro})')

        print('\n=== Checkboxes visíveis na NOVA tela ===')
        for i, chk in enumerate(janela.descendants(control_type='CheckBox')):
            try:
                print(f'  [{i}] texto={chk.window_text()!r} | auto_id={chk.element_info.automation_id!r}')
            except Exception as erro:
                print(f'  [{i}] (erro ao ler: {erro})')

        outros_mlbs = _obter_outros_mlbs(MLB_JA_POSTADO)
        print(f'\n=== MLBs reais do banco (outros anúncios do mesmo produto): {outros_mlbs} ===')

        campo_busca = next(
            (e for e in janela.descendants(control_type='Edit') if e.element_info.automation_id != 'view_1012'),
            None,
        )
        if campo_busca is None:
            print('Não encontrei o campo de busca (Edit diferente da barra de endereço).')
        elif not outros_mlbs:
            print('Nenhum outro MLB encontrado no banco pra esse produto — nada a marcar.')
        else:
            marcados = []
            nao_encontrados = []

            for mlb in outros_mlbs:
                print(f'\n--- Buscando {mlb} ---')
                campo_busca.click_input()
                time.sleep(0.2)
                # * [EXPLICAÇÃO] → Limpa o campo antes de digitar o próximo —
                #                  sem isso, o texto do MLB anterior ficaria
                #                  colado, buscando os 2 juntos.
                send_keys('^a{DELETE}')
                time.sleep(0.2)
                send_keys(mlb, with_spaces=True)
                send_keys('{ENTER}')
                time.sleep(1.5)

                auto_id_esperado = f'CHECKBOX_LIST_ITEM_{mlb}'
                checkbox_alvo = next(
                    (c for c in janela.descendants(control_type='CheckBox')
                     if c.element_info.automation_id == auto_id_esperado),
                    None,
                )
                if checkbox_alvo is None:
                    print(f'  NÃO encontrado na tela.')
                    nao_encontrados.append(mlb)
                else:
                    checkbox_alvo.click_input()
                    time.sleep(0.5)
                    print(f'  Marcado.')
                    marcados.append(mlb)

            print(f'\n=== Resumo ===')
            print(f'Marcados ({len(marcados)}): {marcados}')
            print(f'Não encontrados ({len(nao_encontrados)}): {nao_encontrados}')

            # * [EXPLICAÇÃO] → Corrigido — se o ÚLTIMO MLB buscado no loop não
            #                  for encontrado, a tela inteira vira "Não há
            #                  nada aqui" e o botão "Escolher anúncios" some
            #                  junto (ele faz parte da lista, não é um
            #                  elemento separado). Sempre limpa a busca por
            #                  completo depois do loop, voltando pra lista
            #                  cheia — só aí o botão está garantido de existir.
            print('\n=== Limpando a busca (volta pra lista cheia) antes de localizar o botão ===')
            campo_busca.click_input()
            time.sleep(0.2)
            send_keys('^a{DELETE}')
            send_keys('{ENTER}')
            time.sleep(1.5)

        print('\n=== Localizando "Escolher anúncios" — SÓ POSICIONA O MOUSE, NUNCA CLICA ===')
        botao_escolher = next(
            (b for b in janela.descendants(control_type='Button') if b.window_text() == 'Escolher anúncios'),
            None,
        )
        if botao_escolher is None:
            print('Não encontrei o botão "Escolher anúncios".')
        else:
            from pywinauto import mouse
            retangulo = botao_escolher.rectangle()
            centro_x = (retangulo.left + retangulo.right) // 2
            centro_y = (retangulo.top + retangulo.bottom) // 2
            print(f'Botão encontrado em ({centro_x}, {centro_y}). Movendo o mouse até lá — SEM CLICAR.')
            mouse.move(coords=(centro_x, centro_y))
            print('Mouse posicionado. Nenhum clique foi disparado — confirma visualmente que o cursor está sobre o botão.')
else:
    print('Nenhum botão "vertical_dots" encontrado — não deu pra clicar em nada.')

print('\nScript terminou.')