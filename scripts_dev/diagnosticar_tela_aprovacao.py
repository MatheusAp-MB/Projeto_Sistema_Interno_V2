# scripts_dev/diagnosticar_tela_aprovacao.py

import time
import keyboard
import win32gui
from pywinauto import Application
from pywinauto.keyboard import send_keys

# ==== CONFIGURA AQUI ANTES DE RODAR ====
# Cada item: (MLB, rótulo do que esperamos ver na coluna "Estado")
MLBS_PARA_DIAGNOSTICAR = [
    ('MLB5130142457', 'RECUSADO'),
    ('MLB7508392688', 'PUBLICADO'),
]
# ========================================

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


# Função Objetivo: Despeja TODOS os controles de 1 tipo, sem filtrar nada —
# não sabemos ainda onde mora o texto "Estado", então lista tudo pra achar.
def _despejar_controles(tipo):
    print(f'--- {tipo} ---')
    try:
        for i, elemento in enumerate(janela.descendants(control_type=tipo)):
            try:
                texto = elemento.window_text()
                if texto.strip():
                    print(f'  [{i}] texto={texto!r} | auto_id={elemento.element_info.automation_id!r}')
            except Exception as erro:
                print(f'  [{i}] (erro ao ler: {erro})')
    except Exception as erro:
        print(f'  ERRO ao listar {tipo}: {erro}')


for mlb, estado_esperado in MLBS_PARA_DIAGNOSTICAR:
    url = f'https://vendedores.mercadolivre.com.br/video/creator/listing?page=1&item_id={mlb}'
    print(f'\n{"=" * 70}')
    print(f'MLB={mlb} — esperado na tela: "{estado_esperado}"')
    print(f'Navegando para: {url}')
    janela.set_focus()
    send_keys('^l')
    time.sleep(0.3)
    send_keys(url, with_spaces=True)
    send_keys('{ENTER}')

    print('Aguardando a página carregar (6s)...\n')
    time.sleep(6)

    # Despeja todo tipo de controle plausível pra achar o texto "Estado" —
    # pode estar em Text, Button (se for algo clicável tipo filtro/badge),
    # ou Group/Custom (comum em componentes web renderizados via UIA).
    for tipo in ('Text', 'Button', 'Group', 'Custom'):
        _despejar_controles(tipo)

print(f'\n{"=" * 70}')
print('Script terminou — procure acima pelo texto "RECUSADO" e "PUBLICADO" pra achar onde fica o Estado.')