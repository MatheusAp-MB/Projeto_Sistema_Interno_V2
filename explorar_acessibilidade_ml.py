import sys
import time
import threading
import tkinter as tk
from tkinter import messagebox

import keyboard
import win32gui
from pywinauto import Application
from pywinauto.keyboard import send_keys

from aviso_execucao import AvisoExecucao

# ==== CONFIGURA AQUI ANTES DE RODAR ====
TECLA_CAPTURA = "F8"
NOME_BOTAO_UPLOAD = "Subir archivo"

# Lista de teste — MLBs reais da planilha (só pra validar troca de link + carregamento)
MLBS_TESTE = [
    "MLB1633265106",
    "MLB2860739942",
    "MLB1957001787",
]
# ========================================


def montar_url(mlb):
    return (
        f"https://www.mercadolivre.com.br/video/creator/upload"
        f"?item_syi={mlb}&item_id={mlb}&origin=syi"
    )


janela_capturada = {"handle": None}
evento_capturado = threading.Event()


def capturar_janela_em_primeiro_plano():
    janela_capturada["handle"] = win32gui.GetForegroundWindow()
    evento_capturado.set()


keyboard.add_hotkey(TECLA_CAPTURA, capturar_janela_em_primeiro_plano)

root = tk.Tk()
root.title("Aguardando captura")
root.attributes("-topmost", True)
root.geometry("460x140")
tk.Label(
    root, justify="left", padx=15, pady=15,
    text=(
        "1) Clique na aba do Chrome, já logada no Mercado Livre.\n\n"
        f"2) Sem clicar em mais nada, aperte {TECLA_CAPTURA}."
    ),
).pack()


def verificar_captura():
    if evento_capturado.is_set():
        root.destroy()
    else:
        root.after(200, verificar_captura)


root.after(200, verificar_captura)
root.mainloop()
keyboard.remove_hotkey(TECLA_CAPTURA)

if janela_capturada["handle"] is None:
    print("Cancelado.")
    sys.exit(0)

aviso = AvisoExecucao()
aviso.atualizar("SCRIPT EM EXECUÇÃO — NÃO MEXA NO MOUSE/TECLADO", "#c0392b")

app = Application(backend="uia").connect(handle=janela_capturada["handle"])
janela = app.window(handle=janela_capturada["handle"])

for indice, mlb in enumerate(MLBS_TESTE, start=1):
    url = montar_url(mlb)
    aviso.atualizar(f"Produto {indice}/{len(MLBS_TESTE)} — trocando pra {mlb}", "#c0392b")
    print(f"[{indice}/{len(MLBS_TESTE)}] Trocando URL para: {url}")

    janela.set_focus()
    send_keys("^l")  # foca a barra de endereço
    time.sleep(0.3)
    send_keys(url, with_spaces=True)
    send_keys("{ENTER}")

    print("  Esperando a página carregar (até 15s)...")
    carregou = False
    for _ in range(30):
        time.sleep(0.5)
        botao_upload = janela.child_window(title=NOME_BOTAO_UPLOAD, control_type="Button")
        if botao_upload.exists():
            carregou = True
            break

    print(f"  Carregou: {carregou}")
    if not carregou:
        print(f"  [ERRO] Página do MLB {mlb} não carregou a tempo — pulando.")
        continue

    time.sleep(1.5)  # pausa só pra você visualmente confirmar antes do próximo

aviso.atualizar("TESTE CONCLUÍDO", "#2e7d32")
aviso.fechar()
time.sleep(0.3)

root_final = tk.Tk()
root_final.withdraw()
root_final.attributes("-topmost", True)
messagebox.showinfo("Concluído", "Teste de troca de link terminou — confira o terminal.")
root_final.destroy()

keyboard.unhook_all()
sys.exit(0)