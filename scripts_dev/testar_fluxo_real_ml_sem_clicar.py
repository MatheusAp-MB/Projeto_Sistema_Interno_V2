# scripts_dev/testar_fluxo_real_ml_sem_clicar.py

# Função Objetivo: Valida o fluxo real de postagem — Drive real (só leitura)
# + automação real no navegador — SEM clicar no botão final de verdade
# (postar_video_no_ml já para antes disso, por decisão anterior do usuário).
# Rodar manualmente (nunca dentro do pytest): precisa do navegador aberto e
# focado no Mercado Livre na hora certa. Sucesso é confirmado visualmente
# (mouse posicionado sobre o botão), não por assert.

import os
import sys


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

import shutil
import tempfile
import time

import win32gui

from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.postagem_automatica.orquestrador import (
    obter_mlb_do_produto, resolver_arquivo_da_ocorrencia,
)
from agenda_videos.funcoes_auxiliares.drive.arquivador import ArquivadorDrive, montar_caminho_local_organizado
from agente_local.postagem_ml import postar_video_no_ml

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EAN_PRODUTO_TESTE = '0789888395162'  # QUIMIVIDA — troque se precisar
# ========================================

produto = Produto.objects.filter(ean=EAN_PRODUTO_TESTE).first()
if produto is None:
    raise RuntimeError(f'Produto {EAN_PRODUTO_TESTE} não encontrado no banco.')

ciclo = produto.ciclos_video.first()
if ciclo is None:
    raise RuntimeError(f'Produto {EAN_PRODUTO_TESTE} não tem nenhum CicloVideo.')

mlb = obter_mlb_do_produto(produto)
if mlb is None:
    raise RuntimeError(f'Produto {EAN_PRODUTO_TESTE} não tem MLB vinculado (VariacaoAnuncioMercadoLivre).')

print(f'Produto: {produto.titulo} (EAN {produto.ean})')
print(f'Ciclo atual: {ciclo.fase} #{ciclo.numero_ocorrencia} — etapa {ciclo.etapa_atual()}')
print(f'MLB: {mlb}\n')

print('=== Passo 1: localizando o vídeo no Drive real ===')
arquivo_alvo, pasta_videos_id, motivo = resolver_arquivo_da_ocorrencia(produto, ciclo)
if arquivo_alvo is None:
    raise RuntimeError(f'Vídeo não encontrado: {motivo}')
print(f'Arquivo encontrado: {arquivo_alvo.nome_arquivo} (id={arquivo_alvo.drive_file_id})\n')

print('=== Passo 2: baixando o vídeo de verdade (só leitura, nada é movido no Drive) ===')
pasta_temporaria = tempfile.mkdtemp(prefix='teste_ml_dry_run_')
caminho_local = montar_caminho_local_organizado(pasta_temporaria, produto.ean, arquivo_alvo.nome_arquivo)
arquivador = ArquivadorDrive()
arquivador.baixar_arquivo(arquivo_alvo.drive_file_id, caminho_local)
print(f'Baixado em: {caminho_local}\n')

try:
    print('=== Passo 3: automação no navegador (SEM clicar de verdade) ===')
    input('Deixe o Chrome/Edge focado no Mercado Livre e pressione ENTER pra continuar...')
    print('Você tem 5 segundos pra confirmar o foco na janela certa...')
    time.sleep(5)
    janela_handle = win32gui.GetForegroundWindow()
    print(f'Janela capturada: "{win32gui.GetWindowText(janela_handle)}" (handle={janela_handle})\n')

    sucesso, mensagem_erro = postar_video_no_ml(mlb, caminho_local, janela_handle)

    print('\n=== Resultado ===')
    print(f'sucesso={sucesso}')
    print(f'mensagem={mensagem_erro}')
    if sucesso:
        print('\nO mouse deve estar posicionado sobre o botão de enviar/anunciar.')
        print('CONFIRME NA TELA — e NÃO clique, a menos que queira publicar de verdade.')
finally:
    shutil.rmtree(pasta_temporaria, ignore_errors=True)