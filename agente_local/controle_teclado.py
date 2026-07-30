# agente_local/controle_teclado.py

# Função Objetivo: Máquina de estados por teclado — MESMA lógica da versão
# que já validamos dentro do Django (agenda_videos/.../controle_teclado.py),
# mas 100% local: nenhuma linha toca banco de dados. Estado vive só em
# memória (self.status) — quem precisa saber disso (o orquestrador do
# agente) pergunta direto ao objeto, nunca via consulta externa.

import time
import threading
import keyboard
import win32gui

TECLA_PAUSA_RETOMA = 'F8'
TECLA_CANCELAR = 'F9'

AGUARDANDO_INICIO = 'aguardando_inicio'
RODANDO = 'rodando'
PAUSADO = 'pausado'
CANCELADO = 'cancelado'


class ControleTeclado:

    def __init__(self):
        self.status = AGUARDANDO_INICIO
        self._janela_referencia = None
        self._evento_iniciado = threading.Event()
        self._lock = threading.Lock()
        keyboard.add_hotkey(TECLA_PAUSA_RETOMA, self._ao_pressionar_pausa_retoma)
        keyboard.add_hotkey(TECLA_CANCELAR, self._ao_pressionar_cancelar)

    def _ao_pressionar_pausa_retoma(self):
        import datetime
        agora = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        with self._lock:
            estado_antes = self.status
            if self.status == AGUARDANDO_INICIO:
                self._janela_referencia = win32gui.GetForegroundWindow()
                self.status = RODANDO
                self._evento_iniciado.set()
            elif self.status == RODANDO:
                self.status = PAUSADO
            elif self.status == PAUSADO:
                self.status = RODANDO
            print(f'[TECLADO {agora}] F8 pressionado — estado: {estado_antes} → {self.status}')

    def _ao_pressionar_cancelar(self):
        import datetime
        agora = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        with self._lock:
            estado_antes = self.status
            if self.status in (AGUARDANDO_INICIO, RODANDO, PAUSADO):
                self.status = CANCELADO
                self._evento_iniciado.set()
            print(f'[TECLADO {agora}] F9 pressionado — estado: {estado_antes} → {self.status}')

    def aguardar_inicio(self):
        self._evento_iniciado.wait()

    def foi_cancelado(self):
        return self.status == CANCELADO

    @property
    def janela_referencia(self):
        return self._janela_referencia

    # Função Objetivo: Ponto único de checagem antes de qualquer ação
    # arriscada — bloqueia enquanto pausado, confere cancelamento, e confere
    # a blindagem de foco (janela ainda é a mesma capturada no início?).
    def verificar_e_aguardar(self, aviso=None):
        while True:
            if self.status == CANCELADO:
                return False

            if self.status == RODANDO:
                if self._janela_referencia is not None and win32gui.GetForegroundWindow() != self._janela_referencia:
                    import datetime
                    agora = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    janela_atual = win32gui.GetForegroundWindow()
                    print(
                        f'[BLINDAGEM {agora}] Foco perdido — janela esperada={self._janela_referencia}, '
                        f'janela atual={janela_atual} ("{win32gui.GetWindowText(janela_atual)}") — pausando sozinho.'
                    )
                    self.status = PAUSADO
                    if aviso:
                        aviso.atualizar(
                            'FOCO PERDIDO — confirme a janela certa e pressione F8 pra continuar',
                            '#c0392b',
                        )
                    continue
                if aviso:
                    aviso.atualizar(
                        'RODANDO — NÃO MEXA NO MOUSE/TECLADO  |  F8 pausa  |  F9 cancela',
                        '#c0392b',
                    )
                return True

            if self.status == PAUSADO:
                if aviso:
                    aviso.atualizar('PAUSADO  |  F8 retoma  |  F9 cancela', '#d68910')
                time.sleep(0.3)
                continue

    def encerrar(self):
        keyboard.remove_hotkey(TECLA_PAUSA_RETOMA)
        keyboard.remove_hotkey(TECLA_CANCELAR)