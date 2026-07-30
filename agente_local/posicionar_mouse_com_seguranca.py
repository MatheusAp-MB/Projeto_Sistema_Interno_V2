# agente_local/posicionar_mouse_com_seguranca.py

# Função Objetivo: Move o mouse até o centro de 1 elemento da tela (SEM
# clicar) — sempre revalidando a posição NO MOMENTO do movimento (nunca uma
# posição capturada antes, que pode estar desatualizada se a página rolou
# ou o layout mudou), e sempre conferindo se a posição faz sentido dentro
# da ÁREA VIRTUAL de tela (todos os monitores, via SM_XVIRTUALSCREEN etc. —
# GetSystemMetrics(0)/(1) sozinhos só cobririam o monitor principal).
# Fonte única — antes duplicada entre postagem_ml.py e replicacao_ml.py.

import time
import win32api


def posicionar_mouse_com_seguranca(elemento, log_func):
    from pywinauto import mouse

    try:
        elemento.set_focus()
    except Exception:
        pass  # * setar foco pode falhar silenciosamente em alguns controles — não é fatal
    time.sleep(0.5)

    retangulo = elemento.rectangle()
    centro_x = (retangulo.left + retangulo.right) // 2
    centro_y = (retangulo.top + retangulo.bottom) // 2

    origem_x = win32api.GetSystemMetrics(76)
    origem_y = win32api.GetSystemMetrics(77)
    largura_virtual = win32api.GetSystemMetrics(78)
    altura_virtual = win32api.GetSystemMetrics(79)

    dentro_da_tela = (
        origem_x <= centro_x <= origem_x + largura_virtual
        and origem_y <= centro_y <= origem_y + altura_virtual
    )

    if not dentro_da_tela:
        log_func(f'[DIAGNÓSTICO] Posição do elemento parece inválida: ({centro_x}, {centro_y}) — não vou mover o mouse.')
        return False

    mouse.move(coords=(centro_x, centro_y))
    return True