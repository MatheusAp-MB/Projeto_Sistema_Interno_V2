import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from agenda_videos.funcoes_auxiliares.drive_arquivos_produto import LocalizadorArquivosProduto
from agenda_videos.funcoes_auxiliares.parser_arquivos_drive import parsear_arquivos_produto
from agenda_videos.funcoes_auxiliares.drive_download_e_arquivamento import (
    ArquivadorDrive, montar_caminho_local_organizado,
)
from agenda_videos.funcoes_auxiliares.estado_consumo_drive import (
    obter_ultimo_numero_consumido, registrar_numero_consumido, reconstruir_a_partir_do_drive,
)

# ==== CONFIGURA AQUI ANTES DE RODAR ====
MARCA_TESTE = 'TRAMONTINA'
EAN_TESTE = '7891117102687'
PASTA_TEMPORARIA_LOCAL = r'C:\Users\Win10\Desktop\teste_download_drive'
# ========================================

os.makedirs(PASTA_TEMPORARIA_LOCAL, exist_ok=True)

localizador = LocalizadorArquivosProduto()
encontrado, arquivos_brutos, motivo, pasta_videos_id = localizador.localizar_arquivos(MARCA_TESTE, EAN_TESTE)
if not encontrado:
    print(f'Não encontrado: {motivo}')
    exit()

resultado = parsear_arquivos_produto(MARCA_TESTE, EAN_TESTE, arquivos_brutos)
completos_diaria = resultado.fases['diaria'].completos

# * [EXPLICAÇÃO] → Corrigido (26/07) — "menor número em arquivos_validos"
#                  quebrava a partir do 2º dia, porque o vídeo já consumido
#                  SAI da pasta Videos/ (foi pra usados/), então "1" deixa de
#                  existir ali, e a lógica de sequência (pensada pra
#                  verificar POOL completo, não pra achar o PRÓXIMO durante o
#                  consumo) via isso como furo e descartava tudo. Agora: lê
#                  quantos já foram consumidos (estado local), procura
#                  especificamente o número esperado — em QUALQUER lista
#                  (válidos ou fora de sequência, tanto faz, aqui não estamos
#                  perguntando "o pool está completo", só "existe o vídeo N?").
# * [EXPLICAÇÃO] → Se o JSON não tem registro nenhum pra esse EAN/fase ainda
#                  (0 = "nunca vi esse produto", ou dessincronizou por
#                  alguém ter mexido na pasta manualmente), reconstrói
#                  contando de verdade o que já está em Videos/usados/.
ultimo_consumido = obter_ultimo_numero_consumido(EAN_TESTE, 'diaria')
if ultimo_consumido == 0:
    quantidade_real = localizador.contar_ja_usados(pasta_videos_id, 'Diario')
    if quantidade_real > 0:
        print(f'Estado local não tinha registro — reconstruindo a partir do Drive: {quantidade_real} já usado(s).')
        reconstruir_a_partir_do_drive(EAN_TESTE, 'diaria', quantidade_real)
        ultimo_consumido = quantidade_real

numero_esperado = ultimo_consumido + 1

todos_os_completos = completos_diaria.arquivos_validos + completos_diaria.arquivos_fora_de_sequencia
proximo_video = next((a for a in todos_os_completos if a.numero == numero_esperado), None)

if proximo_video is None:
    print(f'Vídeo esperado (número {numero_esperado}) não encontrado em Videos/ — nada disponível ainda.')
    exit()

print(f'Próximo vídeo a usar: {proximo_video.nome_arquivo} (id: {proximo_video.drive_file_id})')

arquivador = ArquivadorDrive()

caminho_local = montar_caminho_local_organizado(PASTA_TEMPORARIA_LOCAL, EAN_TESTE, proximo_video.nome_arquivo)
print(f'Baixando pra: {caminho_local}...')
arquivador.baixar_arquivo(proximo_video.drive_file_id, caminho_local)
print(f'Baixado! Tamanho: {os.path.getsize(caminho_local)} bytes.')

resposta = input('Confirma mover esse arquivo pra "usados/" no Drive? (digite SIM): ')
if resposta.strip().upper() == 'SIM':
    print(f'Movendo {proximo_video.nome_arquivo} para usados/...')
    arquivador.mover_para_usados(proximo_video.drive_file_id, pasta_videos_id)
    registrar_numero_consumido(EAN_TESTE, 'diaria', numero_esperado)
    print('Movido com sucesso! Confira no Drive: deve ter sumido de Videos/ e aparecido em Videos/usados/.')
    print(f'Estado local atualizado: Diária do EAN {EAN_TESTE} já consumiu até o vídeo {numero_esperado}.')
else:
    print('Cancelado — arquivo baixado, mas não movido (estado local não foi atualizado).')