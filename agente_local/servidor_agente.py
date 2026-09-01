# agente_local/servidor_agente.py

# Função Objetivo: O agente de verdade — recebe o aviso do navegador (via
# rota local /executar/<id>), busca os itens na API do Django, e processa
# cada 1 (baixar -> postar -> avisar resultado), com F8/F9 e blindagem de
# foco. Roda escondido na bandeja do sistema (pystray), sem terminal.

import ctypes
import datetime
import os
import shutil
import sys
import tempfile
import threading
import time


# Função Objetivo: Duplica toda saída (print) pro terminal E pra um arquivo
# de log — garante que os logs sobrevivem mesmo se a janela do terminal
# fechar sozinha (crash, ou qualquer outro motivo ainda não diagnosticado).
class _DuplicadorSaida:
    def __init__(self, saida_original, arquivo_log):
        self.saida_original = saida_original
        self.arquivo_log = arquivo_log

    def write(self, texto):
        # * [EXPLICAÇÃO] → Em build --noconsole (sem terminal anexado), o
        #                  Windows deixa sys.stdout/sys.stderr como None —
        #                  só grava no arquivo de log nesse caso, sem
        #                  quebrar. Rodando com console de verdade (dev,
        #                  python servidor_agente.py direto), continua
        #                  duplicando pros 2 lugares como antes.
        if self.saida_original is not None:
            self.saida_original.write(texto)
        self.arquivo_log.write(texto)
        self.arquivo_log.flush()

    def flush(self):
        if self.saida_original is not None:
            self.saida_original.flush()
        self.arquivo_log.flush()

# * [EXPLICAÇÃO] → Corrigido (30/07) — SEM isso, um .exe gerado pelo
#                  PyInstaller não avisa ao Windows que sabe lidar com
#                  telas de alta resolução/escala — o Windows então aplica
#                  uma escala "por trás", sem avisar, fazendo qualquer
#                  coordenada de tela (como mover o mouse pra cima de um
#                  botão) ficar deslocada de forma fixa e repetida. Isso
#                  precisa rodar ANTES de qualquer janela/automação ser
#                  tocada — por isso é a primeira coisa do arquivo. Seguro
#                  de rodar em qualquer situação (import, teste, produção):
#                  já é protegido por try/except e não escreve nada em disco.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()  # fallback pra versões mais antigas do Windows
    except Exception:
        pass


def _pasta_do_executavel_para_log():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _capturar_excecao_nao_tratada(tipo, valor, traceback_obj):
    # * [EXPLICAÇÃO] → Captura QUALQUER exceção não tratada, em qualquer
    #                  lugar do programa, antes dela conseguir fechar o
    #                  processo silenciosamente. Requisito do usuário: o
    #                  agente só fecha quando ELE decide fechar (menu
    #                  "Sair"), nunca sozinho. Só é conectada de verdade
    #                  (sys.excepthook =) dentro do `if __name__ ==
    #                  '__main__':`, no fim do arquivo — nunca ao importar.
    import traceback
    print('[AGENTE] ERRO NÃO TRATADO — isso NÃO deveria ter fechado o programa:')
    traceback.print_exception(tipo, valor, traceback_obj)


import pystray
from PIL import Image, ImageDraw
from flask import Flask, jsonify, request
from flask_cors import CORS

from agente_local.aviso_execucao import AvisoExecucao
from agente_local.controle_teclado import ControleTeclado
from agente_local.postagem_ml import postar_video_no_ml
from agente_local.replicacao_ml import replicar_video_no_ml
from agente_local.verificacao_ml import ler_estado_aprovacao
from agente_local import cliente_api

PORTA_LOCAL = 5678

# * [EXPLICAÇÃO] → Duplicado aqui de propósito (nunca importado de
#                  core.empresa) — o agente local precisa continuar 100%
#                  autossuficiente, sem NENHUMA dependência de Django,
#                  mesmo que isso signifique manter esta lista em 2
#                  lugares. Usada só para validar o parâmetro `empresa`
#                  que chega na rota Flask, antes de repassar pra API.
EMPRESAS_VALIDAS_AGENTE = ('MAGAZINE', 'SAMVALE')

# * [DECISÃO, 31/08] Lote de 90 vídeos seguidos — pausa entre uma
#   postagem real e outra, pra não parecer atividade de bot pro
#   Mercado Livre. Só entra a partir do 2º vídeo (ver
#   houve_postagem_anterior em _processar_execucao).
DELAY_ENTRE_POSTAGENS_SEGUNDOS = 30

# * [DECISÃO, 01/09] Verificação de Aprovação (Fase 1) — mesmo raciocínio
#   anti-bot da Postagem, mas mais curto: ler a tela é uma interação bem
#   mais leve que postar (menos cliques autônomos), então 10s já cobre.
#   Só entra a partir da 2ª leitura (ver houve_leitura_anterior em
#   _processar_verificacao_aprovacao).
DELAY_ENTRE_LEITURAS_VERIFICACAO_SEGUNDOS = 10


def _obter_pasta_do_executavel():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def carregar_configuracao():
    caminho_config = os.path.join(_obter_pasta_do_executavel(), 'agente_config.env')
    if not os.path.exists(caminho_config):
        raise RuntimeError(
            f'Arquivo de configuração não encontrado: {caminho_config}\n'
            f'Crie esse arquivo, na mesma pasta do programa, com:\n'
            f'SERVIDOR=http://endereco:porta\nTOKEN=seu_token_aqui'
        )
    configuracao = {}
    with open(caminho_config, 'r', encoding='utf-8') as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if '=' in linha:
                chave, valor = linha.split('=', 1)
                configuracao[chave.strip()] = valor.strip()
    if 'SERVIDOR' not in configuracao or 'TOKEN' not in configuracao:
        raise RuntimeError(f'{caminho_config} precisa ter as linhas SERVIDOR=... e TOKEN=...')
    return configuracao['SERVIDOR'], configuracao['TOKEN']


# * [EXPLICAÇÃO] → Corrigido (25/08) — antes, a leitura da config real
#                  (linha abaixo) e todo o "start de verdade" (log em
#                  arquivo, servidor Flask na porta 5678, ícone da bandeja)
#                  ficavam soltos no nível do módulo, SEM guard de
#                  `if __name__ == '__main__':`. Isso significa que só
#                  IMPORTAR este arquivo (ex: pra testar as rotas Flask)
#                  já disparava tudo de verdade: lia agente_config.env do
#                  disco (levantando erro se não achasse), escrevia um
#                  arquivo de log real, e travava pra sempre no loop do
#                  ícone da bandeja — tornando o módulo impossível de
#                  testar. Agora só o app Flask + as rotas (que não
#                  dependem de config nenhuma pra SEREM DEFINIDAS) ficam no
#                  nível do módulo — sempre seguro de importar. O "start de
#                  verdade" (bloco `if __name__ == '__main__':`, no fim do
#                  arquivo) continua idêntico ao que já era, só reorganizado.
app_flask = Flask(__name__)

icone_referencia = {'obj': None}
execucao_em_andamento = {'ativo': False}


def _criar_imagem(cor):
    imagem = Image.new('RGB', (64, 64), 'white')
    desenho = ImageDraw.Draw(imagem)
    desenho.ellipse((8, 8, 56, 56), fill=cor)
    return imagem


def _voltar_ao_repouso():
    execucao_em_andamento['ativo'] = False
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('green')
        icone_referencia['obj'].title = f'Agente rodando — conectado a {SERVIDOR_DJANGO}'


# * [EXPLICAÇÃO] → Generalizada (30/07) — recebe QUAL função de heartbeat
#                  chamar (Postagem ou Replicação), em vez de duplicar essa
#                  mesma thread pros 2 fluxos.
def _enviar_heartbeat_em_loop(funcao_heartbeat, execucao_id, empresa, evento_parar):
    import time
    while not evento_parar.is_set():
        try:
            funcao_heartbeat(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, empresa)
        except Exception as erro:
            print(f'[AGENTE] Falha ao enviar heartbeat: {erro}')
        evento_parar.wait(10)  # * a cada 10s — bem dentro do limite de 30s do Django


# * [EXPLICAÇÃO] → Espera visível (contagem regressiva na janela de aviso)
#                  entre uma postagem e outra. Confere cancelamento (F9) a
#                  cada segundo — não trava os 20s inteiros se o usuário já
#                  quis parar no meio da espera.
def _aguardar_entre_postagens(segundos, aviso, controle):
    for restante in range(segundos, 0, -1):
        if controle.foi_cancelado():
            return False
        aviso.atualizar(f'Aguardando {restante}s antes do próximo vídeo (pausa anti-bot)...', '#2980b9')
        time.sleep(1)
    return True


def _processar_execucao(execucao_id, empresa):
    aviso = AvisoExecucao()
    aviso.atualizar('AGUARDANDO — foque a janela certa e pressione F8 pra iniciar  |  F9 cancela', '#d68910')

    controle = ControleTeclado()
    controle.aguardar_inicio()

    evento_parar_heartbeat = threading.Event()
    thread_heartbeat = threading.Thread(
        target=_enviar_heartbeat_em_loop,
        args=(cliente_api.enviar_heartbeat, execucao_id, empresa, evento_parar_heartbeat), daemon=True,
    )
    thread_heartbeat.start()

    if controle.foi_cancelado():
        controle.encerrar()
        aviso.fechar()
        try:
            cliente_api.finalizar_execucao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, empresa, cancelada=True)
        except Exception as erro:
            print(f'[AGENTE] Erro ao avisar cancelamento: {erro}')
        _voltar_ao_repouso()
        return

    try:
        itens = cliente_api.listar_itens(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, empresa)
    except Exception as erro:
        print(f'[AGENTE] Erro ao buscar itens da execução #{execucao_id}: {erro}')
        controle.encerrar()
        aviso.fechar()
        _voltar_ao_repouso()
        return

    pasta_temporaria_raiz = tempfile.mkdtemp(prefix='agente_postagem_')
    houve_postagem_anterior = False

    for item in itens:
        if controle.foi_cancelado():
            break
        if item['ja_postado_hoje']:
            print(f'[AGENTE] Item #{item["item_id"]} já postado hoje — pulando.')
            continue

        item_id = item['item_id']

        try:
            caminho_local, drive_file_id, pasta_videos_id = cliente_api.baixar_video(
                SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, item['produto_ean'], pasta_temporaria_raiz, empresa,
            )
        except Exception as erro:
            print(f'[AGENTE] Erro ao baixar vídeo do item #{item_id}: {erro}')
            try:
                cliente_api.marcar_falhou(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, f'Erro ao baixar: {erro}', empresa)
            except Exception:
                pass
            continue

        if houve_postagem_anterior:
            if not _aguardar_entre_postagens(DELAY_ENTRE_POSTAGENS_SEGUNDOS, aviso, controle):
                break

        if not controle.verificar_e_aguardar(aviso):
            break

        houve_postagem_anterior = True

        try:
            sucesso, mensagem_erro = postar_video_no_ml(
                item['mlb'], caminho_local, controle.janela_referencia,
                # * [DECISÃO, 31/08] Validação real concluída (botão certo
                #   encontrado na tela do ML, trava de dry-run funcionando
                #   como esperado) — usuário autorizou reverter pra
                #   produção real.
                confirmar_de_verdade=True,
            )
        except Exception as erro:
            sucesso, mensagem_erro = False, f'Erro inesperado na automação: {erro}'

        if not sucesso:
            cliente_api.marcar_falhou(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, mensagem_erro or 'Falha ao postar.', empresa)
            continue

        try:
            cliente_api.marcar_concluido(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, drive_file_id, pasta_videos_id, empresa)
            print(f'[AGENTE] Item #{item_id} concluído.')
        except Exception as erro:
            print(f'[AGENTE] Postado, mas erro ao avisar o servidor: {erro}')

    foi_cancelado = controle.foi_cancelado()
    evento_parar_heartbeat.set()

    shutil.rmtree(pasta_temporaria_raiz, ignore_errors=True)
    controle.encerrar()
    aviso.fechar()

    try:
        cliente_api.finalizar_execucao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, empresa, cancelada=foi_cancelado)
    except Exception as erro:
        print(f'[AGENTE] Erro ao avisar que a execução terminou: {erro}')

    _voltar_ao_repouso()


# * [EXPLICAÇÃO] → Log simples em .txt (30/07, provisório) — só pra
#                  conferir manualmente se a Replicação real está indo pros
#                  MLBs certos, enquanto não existe tela de histórico no
#                  sistema (fica pra depois, ainda como Django). 1 linha
#                  por replicação concluída, sempre em append — nunca
#                  sobrescreve. Vive na pasta do agente (mesma de
#                  agente_config.env), não no servidor.
def _registrar_log_replicacao(ean, titulo, mlb_origem, marcados, observacao=None):
    caminho_log = os.path.join(_obter_pasta_do_executavel(), 'replicacoes_realizadas.txt')
    agora = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    linha = f'{agora} | EAN {ean} | {titulo} | MLB origem {mlb_origem} | replicado para: {", ".join(marcados)}'
    if observacao:
        linha += f' | obs: {observacao}'
    with open(caminho_log, 'a', encoding='utf-8') as arquivo:
        arquivo.write(linha + '\n')


def _processar_execucao_replicacao(execucao_id, empresa):
    aviso = AvisoExecucao()
    aviso.atualizar('AGUARDANDO — foque a janela certa e pressione F8 pra iniciar  |  F9 cancela', '#d68910')

    controle = ControleTeclado()
    controle.aguardar_inicio()

    evento_parar_heartbeat = threading.Event()
    thread_heartbeat = threading.Thread(
        target=_enviar_heartbeat_em_loop,
        args=(cliente_api.enviar_heartbeat_replicacao, execucao_id, empresa, evento_parar_heartbeat), daemon=True,
    )
    thread_heartbeat.start()

    if controle.foi_cancelado():
        controle.encerrar()
        aviso.fechar()
        try:
            cliente_api.finalizar_execucao_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, empresa, cancelada=True)
        except Exception as erro:
            print(f'[AGENTE] Erro ao avisar cancelamento (replicação): {erro}')
        _voltar_ao_repouso()
        return

    try:
        itens = cliente_api.listar_itens_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, empresa)
    except Exception as erro:
        print(f'[AGENTE] Erro ao buscar itens da execução de replicação #{execucao_id}: {erro}')
        controle.encerrar()
        aviso.fechar()
        _voltar_ao_repouso()
        return

    for item in itens:
        if controle.foi_cancelado():
            break

        item_id = item['item_id']

        if not controle.verificar_e_aguardar(aviso):
            break

        try:
            sucesso, mensagem_erro, marcados, nao_encontrados = replicar_video_no_ml(
                item['mlb'], item['outros_mlbs'], controle.janela_referencia,
                confirmar_de_verdade=False,  # * [TEMPORÁRIO — TESTE 13/08, reafirmado 25/08] estava True
                                              #   (produção real). REVERTER pra True só depois da validação
                                              #   completa (empresa correta ponta a ponta) ser confirmada
                                              #   pelo usuário.
            )
        except Exception as erro:
            sucesso, mensagem_erro, marcados, nao_encontrados = False, f'Erro inesperado na automação: {erro}', [], []

        if not sucesso:
            try:
                cliente_api.marcar_falhou_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, mensagem_erro or 'Falha ao replicar.', empresa)
            except Exception:
                pass
            continue

        if marcados:
            try:
                _registrar_log_replicacao(item['produto_ean'], item['produto_titulo'], item['mlb'], marcados, mensagem_erro)
            except Exception as erro:
                print(f'[AGENTE] Erro ao gravar log de replicação (não impede o fluxo): {erro}')

        try:
            cliente_api.marcar_concluido_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, item_id, empresa, marcados, nao_encontrados)
            print(f'[AGENTE] Item de replicação #{item_id} concluído.')
        except Exception as erro:
            print(f'[AGENTE] Replicado, mas erro ao avisar o servidor: {erro}')

    foi_cancelado = controle.foi_cancelado()
    evento_parar_heartbeat.set()
    controle.encerrar()
    aviso.fechar()

    try:
        cliente_api.finalizar_execucao_replicacao(SERVIDOR_DJANGO, TOKEN_AGENTE, execucao_id, empresa, cancelada=foi_cancelado)
    except Exception as erro:
        print(f'[AGENTE] Erro ao avisar que a execução de replicação terminou: {erro}')

    _voltar_ao_repouso()


# * [EXPLICAÇÃO] → Mesmo padrão de _aguardar_entre_postagens — espera
#                  visível (contagem regressiva na janela de aviso) entre
#                  uma leitura e outra. Confere cancelamento (F9) a cada
#                  segundo.
def _aguardar_entre_leituras_verificacao(segundos, aviso, controle):
    for restante in range(segundos, 0, -1):
        if controle.foi_cancelado():
            return False
        aviso.atualizar(f'Aguardando {restante}s antes da próxima leitura (pausa anti-bot)...', '#2980b9')
        time.sleep(1)
    return True


# * [EXPLICAÇÃO] → Fase 1 (27/08) da Verificação de Aprovação — LEITURA,
#                  reaproveitando a MESMA blindagem de F8/F9/foco perdido
#                  já validada em Postagem/Replicação (AvisoExecucao +
#                  ControleTeclado). Fase 2 (01/09) — depois de cada
#                  leitura, avisa o Django (marcar_estado_verificacao); só
#                  aplica mudança de status quando o estado lido tem
#                  mapeamento certo (ver MAPEAMENTO_ESTADO_PARA_STATUS em
#                  agenda_videos/funcoes_auxiliares/verificacao_aprovacao.py)
#                  — EM REVISÃO/PAUSADO/None não mexem em nada.
def _processar_verificacao_aprovacao(mlbs, empresa):
    aviso = AvisoExecucao()
    aviso.atualizar('AGUARDANDO — foque a janela certa e pressione F8 pra iniciar  |  F9 cancela', '#d68910')

    controle = ControleTeclado()
    controle.aguardar_inicio()

    if controle.foi_cancelado():
        controle.encerrar()
        aviso.fechar()
        _voltar_ao_repouso()
        return

    print(f'[AGENTE] Verificação de Aprovação — {len(mlbs)} produto(s) na fila (empresa={empresa}).')

    houve_leitura_anterior = False

    for mlb in mlbs:
        if controle.foi_cancelado():
            break

        if houve_leitura_anterior:
            if not _aguardar_entre_leituras_verificacao(DELAY_ENTRE_LEITURAS_VERIFICACAO_SEGUNDOS, aviso, controle):
                break

        if not controle.verificar_e_aguardar(aviso):
            break

        houve_leitura_anterior = True

        try:
            estado = ler_estado_aprovacao(mlb, controle.janela_referencia)
        except Exception as erro:
            print(f'[AGENTE] {mlb} — ERRO ao verificar: {erro}')
            continue

        print(f'[AGENTE] {mlb} — estado lido: {estado}')

        try:
            resultado = cliente_api.marcar_estado_verificacao(SERVIDOR_DJANGO, TOKEN_AGENTE, mlb, estado, empresa)
            print(f'[AGENTE] {mlb} — {resultado["status"]}')
        except Exception as erro:
            print(f'[AGENTE] {mlb} — lido, mas erro ao avisar o servidor: {erro}')

    controle.encerrar()
    aviso.fechar()
    _voltar_ao_repouso()


@app_flask.route('/executar/<int:execucao_id>', methods=['POST'])
def executar(execucao_id):
    # * [EXPLICAÇÃO] → Recusa uma 2ª execução enquanto a 1ª ainda roda NESTE
    #                  agente — mesma lição já aprendida (2 execuções
    #                  concorrentes derrubam Tkinter/hotkey).
    if execucao_em_andamento['ativo']:
        return jsonify({'status': 'ocupado', 'mensagem': 'Já existe uma execução rodando neste agente.'}), 409

    # * [EXPLICAÇÃO] → "Achado central" (24/08) — o template manda a empresa
    #                  ativa (do navegador, via query string) porque este
    #                  agente NUNCA tem sessão de navegador — sem isso, a
    #                  API não tem como saber se é Magazine ou Samvale.
    #                  Valida aqui, de forma explícita, com a lista LOCAL
    #                  (nunca importada de core.empresa — o agente precisa
    #                  seguir 100% autossuficiente).
    empresa = request.args.get('empresa')
    if empresa not in EMPRESAS_VALIDAS_AGENTE:
        return jsonify({
            'status': 'erro',
            'mensagem': f'Parâmetro empresa ausente ou inválido: {empresa!r}.',
        }), 400

    execucao_em_andamento['ativo'] = True
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('blue')
        icone_referencia['obj'].title = f'Execução #{execucao_id} — aguardando F8'

    thread = threading.Thread(target=_processar_execucao, args=(execucao_id, empresa), daemon=True)
    thread.start()

    return jsonify({'status': 'iniciado', 'execucao_id': execucao_id, 'empresa': empresa})


@app_flask.route('/executar-replicacao/<int:execucao_id>', methods=['POST'])
def executar_replicacao(execucao_id):
    # * [EXPLICAÇÃO] → Mesma trava do /executar (Postagem) — execucao_em_andamento
    #                  é 1 flag SÓ, compartilhado entre os 2 tipos. Isso é
    #                  de propósito: Postagem e Replicação usam a MESMA
    #                  infraestrutura de Tkinter/hotkey nesta máquina — 1
    #                  de cada tipo rodando ao mesmo tempo seria o mesmo
    #                  crash que já corrigimos antes (2 execuções concorrentes).
    if execucao_em_andamento['ativo']:
        return jsonify({'status': 'ocupado', 'mensagem': 'Já existe uma execução rodando neste agente.'}), 409

    # * [EXPLICAÇÃO] → Mesma validação da rota /executar (Postagem) — ver
    #                  comentário lá pro porquê completo.
    empresa = request.args.get('empresa')
    if empresa not in EMPRESAS_VALIDAS_AGENTE:
        return jsonify({
            'status': 'erro',
            'mensagem': f'Parâmetro empresa ausente ou inválido: {empresa!r}.',
        }), 400

    execucao_em_andamento['ativo'] = True
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('blue')
        icone_referencia['obj'].title = f'Execução de Replicação #{execucao_id} — aguardando F8'

    thread = threading.Thread(target=_processar_execucao_replicacao, args=(execucao_id, empresa), daemon=True)
    thread.start()

    return jsonify({'status': 'iniciado', 'execucao_id': execucao_id, 'empresa': empresa})


# * [EXPLICAÇÃO] → Mesma trava/validação de empresa das rotas de Postagem/
#                  Replicação — ver comentário lá pro porquê completo.
#                  Diferença de propósito: esta rota NUNCA fala com o
#                  Django (fase 1, só leitura/console) — por isso não cria
#                  execucao_id nenhum, só recebe a lista de itens direto no
#                  corpo da requisição.
@app_flask.route('/verificar-aprovacao', methods=['POST'])
def verificar_aprovacao():
    if execucao_em_andamento['ativo']:
        return jsonify({'status': 'ocupado', 'mensagem': 'Já existe uma execução rodando neste agente.'}), 409

    empresa = request.args.get('empresa')
    if empresa not in EMPRESAS_VALIDAS_AGENTE:
        return jsonify({
            'status': 'erro',
            'mensagem': f'Parâmetro empresa ausente ou inválido: {empresa!r}.',
        }), 400

    # * [EXPLICAÇÃO] → MLBs vêm na query string (igual execucao_id de
    #                  Postagem/Replicação), nunca em JSON body — evita a
    #                  checagem prévia (preflight) do navegador.
    mlbs_bruto = request.args.get('mlbs', '')
    mlbs = [mlb for mlb in mlbs_bruto.split(',') if mlb]
    if not mlbs:
        return jsonify({'status': 'erro', 'mensagem': 'Nenhum MLB recebido pra verificar.'}), 400

    execucao_em_andamento['ativo'] = True
    if icone_referencia['obj'] is not None:
        icone_referencia['obj'].icon = _criar_imagem('blue')
        icone_referencia['obj'].title = 'Verificação de Aprovação — aguardando F8'

    thread = threading.Thread(target=_processar_verificacao_aprovacao, args=(mlbs, empresa), daemon=True)
    thread.start()

    return jsonify({'status': 'iniciado', 'total_itens': len(mlbs), 'empresa': empresa})


def _rodar_servidor_flask():
    try:
        app_flask.run(host='127.0.0.1', port=PORTA_LOCAL)
    except Exception as erro:
        print(f'[AGENTE] ERRO — o servidor local (Flask) parou de responder: {erro}')
        import traceback
        traceback.print_exc()


def _sair(icone, item):
    icone.stop()


# * [EXPLICAÇÃO] → Corrigido (25/08) — TUDO que é "start de verdade" (nunca
#                  deve rodar só por importar o módulo) vive aqui dentro:
#                  log em arquivo, leitura de agente_config.env, CORS com a
#                  origem real, o servidor Flask na porta 5678, e o ícone
#                  da bandeja. Comportamento idêntico ao que já existia
#                  quando rodado como script/.exe — só reorganizado pra
#                  dentro do guard padrão do Python, pra viabilizar teste
#                  automatizado das rotas (ver
#                  agente_local/tests/test_nivel_4__servidor_agente_rotas.py).
#                  Ressalva consciente: um erro de IMPORT (ex: dependência
#                  faltando no .exe) não fica mais registrado no log em
#                  arquivo, já que o log só é ligado aqui dentro — isso já
#                  era um risco baixo (as dependências são as mesmas
#                  travadas no pyproject.toml) e o ganho de testabilidade
#                  compensa.
if __name__ == '__main__':
    _caminho_log = os.path.join(
        _pasta_do_executavel_para_log(), f'agente_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt',
    )
    _arquivo_log = open(_caminho_log, 'a', encoding='utf-8')
    sys.stdout = _DuplicadorSaida(sys.stdout, _arquivo_log)
    sys.stderr = _DuplicadorSaida(sys.stderr, _arquivo_log)
    print(f'[AGENTE] Log sendo gravado em: {_caminho_log}')

    sys.excepthook = _capturar_excecao_nao_tratada

    SERVIDOR_DJANGO, TOKEN_AGENTE = carregar_configuracao()
    CORS(app_flask, origins=[SERVIDOR_DJANGO])

    thread_servidor = threading.Thread(target=_rodar_servidor_flask, daemon=True)
    thread_servidor.start()

    icone = pystray.Icon(
        'agente_postagem',
        _criar_imagem('green'),
        f'Agente rodando — conectado a {SERVIDOR_DJANGO}',
        menu=pystray.Menu(pystray.MenuItem('Sair', _sair)),
    )
    icone_referencia['obj'] = icone

    try:
        icone.run()
    except Exception as erro:
        print(f'[AGENTE] ERRO — o ícone da bandeja parou de funcionar: {erro}')
        import traceback
        traceback.print_exc()
        print('[AGENTE] Aguardando você fechar esta janela manualmente (Ctrl+C ou fechar a janela).')
        # * [EXPLICAÇÃO] → Se o loop do ícone quebrar mesmo assim (não deveria,
        #                  com o try/except acima), mantém o PROCESSO vivo de
        #                  propósito — nunca fecha sozinho, mesmo sem o ícone
        #                  funcionando mais. Só sai quando o usuário decidir.
        while True:
            time.sleep(3600)