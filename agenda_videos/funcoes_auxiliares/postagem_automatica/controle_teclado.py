# agenda_videos/funcoes_auxiliares/postagem_automatica/controle_teclado.py

# Função Objetivo: Máquina de estados controlada por teclado, pra 1
# ExecucaoPostagemAutomatica — reaproveita a MESMA biblioteca (keyboard) e o
# MESMO padrão (win32gui.GetForegroundWindow, via hotkey) já validados no
# protótipo antigo (simular_dia_agenda.py).
#
# F8: 1º aperto = inicia de verdade (captura a janela em foco como
#     referência pra blindagem); apertos seguintes = alterna Rodando <-> Pausado.
# F9: cancela (a partir de Aguardando Início, Rodando, ou Pausado) — vira
#     estado final, sem volta.
#
# Todo estado é persistido em ExecucaoPostagemAutomatica.status — é essa
# mesma coluna que a tela de progresso lê via polling, nunca acesso direto
# a esta classe/thread.

import time
import threading
import keyboard
import win32gui
from agenda_videos.models import ExecucaoPostagemAutomatica, StatusExecucao

TECLA_PAUSA_RETOMA = 'F8'
TECLA_CANCELAR = 'F9'


class ControleTeclado:

    def __init__(self, execucao_id):
        self.execucao_id = execucao_id
        self._janela_referencia = None
        self._evento_iniciado = threading.Event()
        self._lock = threading.Lock()
        keyboard.add_hotkey(TECLA_PAUSA_RETOMA, self._ao_pressionar_pausa_retoma)
        keyboard.add_hotkey(TECLA_CANCELAR, self._ao_pressionar_cancelar)

    def _obter_execucao(self):
        return ExecucaoPostagemAutomatica.objects.get(id=self.execucao_id)

    def _ao_pressionar_pausa_retoma(self):
        with self._lock:
            execucao = self._obter_execucao()
            if execucao.status == StatusExecucao.AGUARDANDO_INICIO:
                self._janela_referencia = win32gui.GetForegroundWindow()
                execucao.status = StatusExecucao.RODANDO
                execucao.save(update_fields=['status'])
                self._evento_iniciado.set()
            elif execucao.status == StatusExecucao.RODANDO:
                execucao.status = StatusExecucao.PAUSADO
                execucao.save(update_fields=['status'])
            elif execucao.status == StatusExecucao.PAUSADO:
                execucao.status = StatusExecucao.RODANDO
                execucao.save(update_fields=['status'])

    def _ao_pressionar_cancelar(self):
        with self._lock:
            execucao = self._obter_execucao()
            if execucao.status in (
                StatusExecucao.AGUARDANDO_INICIO, StatusExecucao.RODANDO, StatusExecucao.PAUSADO,
            ):
                execucao.status = StatusExecucao.CANCELADO
                execucao.save(update_fields=['status'])
                self._evento_iniciado.set()  # libera quem estivesse esperando o início

    def aguardar_inicio(self):
        self._evento_iniciado.wait()

    @property
    def janela_referencia(self):
        return self._janela_referencia

    def foi_cancelado(self):
        return self._obter_execucao().status == StatusExecucao.CANCELADO

    # Função Objetivo: Ponto ÚNICO de checagem antes de qualquer ação
    # "arriscada" (a futura postagem de verdade) — bloqueia enquanto pausado,
    # confere cancelamento, e confere a BLINDAGEM de foco (a janela em foco
    # agora ainda é a mesma capturada no início?). Devolve False quando o
    # chamador deve parar (foi cancelado).
    def verificar_e_aguardar(self, aviso=None):
        while True:
            execucao = self._obter_execucao()

            if execucao.status == StatusExecucao.CANCELADO:
                return False

            if execucao.status == StatusExecucao.RODANDO:
                if self._janela_referencia is not None and win32gui.GetForegroundWindow() != self._janela_referencia:
                    execucao.status = StatusExecucao.PAUSADO
                    execucao.save(update_fields=['status'])
                    if aviso:
                        aviso.atualizar(
                            'FOCO PERDIDO — confirme a janela do Mercado Livre e pressione F8 pra continuar',
                            '#c0392b',
                        )
                    continue
                if aviso:
                    aviso.atualizar(
                        'RODANDO — NÃO MEXA NO MOUSE/TECLADO  |  F8 pausa  |  F9 cancela',
                        '#c0392b',
                    )
                return True

            if execucao.status == StatusExecucao.PAUSADO:
                if aviso:
                    aviso.atualizar('PAUSADO  |  F8 retoma  |  F9 cancela', '#d68910')
                time.sleep(0.3)
                continue

    def encerrar(self):
        keyboard.remove_hotkey(TECLA_PAUSA_RETOMA)
        keyboard.remove_hotkey(TECLA_CANCELAR)