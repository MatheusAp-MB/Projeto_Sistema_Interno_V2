# aviso_execucao.py

# Função Objetivo: Janela de aviso fixa, sempre visível, que NUNCA rouba o foco da
# janela que o script está automatizando.
# Explicação em detalhe: roda numa thread separada porque o tkinter precisa do próprio
# loop de eventos rodando o tempo todo, em paralelo com o resto do script fazendo a
# automação de verdade. A troca de texto/cor é feita via fila (Queue) — thread-safe,
# evita mexer direto num widget tkinter de outra thread.

import threading
import queue
import tkinter as tk

import win32gui
import win32con


class AvisoExecucao:

    def __init__(self):
        self._fila = queue.Queue()
        self._pronto = threading.Event()
        self._thread = threading.Thread(target=self._rodar, daemon=True)
        self._thread.start()
        self._pronto.wait()

    def _rodar(self):
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.geometry("500x60+20+20")

        self._label = tk.Label(
            self._root, text="", font=("Segoe UI", 13, "bold"),
            fg="white", bg="#c0392b", wraplength=480, justify="center",
        )
        self._label.pack(fill="both", expand=True)

        # * [EXPLICAÇÃO] → WS_EX_NOACTIVATE impede que esta janela roube o foco
        #                  ao aparecer/atualizar — crítico, senão ela mesma
        #                  atrapalha a automação que está controlando outra janela.
        hwnd = self._root.winfo_id()
        estilo_atual = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(
            hwnd, win32con.GWL_EXSTYLE,
            estilo_atual | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOPMOST,
        )

        self.atualizar("SCRIPT EM EXECUÇÃO — NÃO MEXA NO MOUSE/TECLADO", "#c0392b")
        self._pronto.set()
        self._processar_fila()
        self._root.mainloop()

    def _processar_fila(self):
        try:
            while True:
                texto, cor = self._fila.get_nowait()
                if texto == "__FECHAR__":
                    self._root.destroy()
                    return  # não reagenda mais — janela já foi fechada
                self._label.config(text=texto, bg=cor)
                self._root.configure(bg=cor)
        except queue.Empty:
            pass
        self._root.after(100, self._processar_fila)

    def atualizar(self, texto, cor="#c0392b"):
        self._fila.put((texto, cor))

    def fechar(self):
        # * [EXPLICAÇÃO] → Nunca chamar destroy() direto daqui — isso rodaria
        #                  numa thread diferente da que criou a janela, e o
        #                  Tkinter trava/quebra quando isso acontece. Por isso
        #                  o fechamento também passa pela fila.
        self._fila.put(("__FECHAR__", None))