import os
import sys

# * [EXPLICAÇÃO] → Acha a raiz do projeto subindo pastas até encontrar
#                  "manage.py" — assim o script funciona rodando de dentro
#                  de qualquer subpasta, sem precisar saber de antemão
#                  quantos níveis subir.
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

from produtos.models import Produto
from agenda_videos.models import SnapshotArquivosDrive
from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive
from agenda_videos.funcoes_auxiliares.drive.escaneador import (
    _listar_tudo_paginado, montar_arvore_por_ean, MIME_PASTA,
)
from django.conf import settings

servico = obter_servico_drive()
todos_os_itens = _listar_tudo_paginado(servico)

print(f'Total de itens (arquivos + pastas) encontrados na varredura inteira: {len(todos_os_itens)}\n')

raiz_id = settings.GOOGLE_DRIVE_PASTA_RAIZ_ID
filhos_da_raiz = [item for item in todos_os_itens if raiz_id in item.get('parents', [])]

print('=== Filhos diretos da pasta raiz (deveriam ser só pastas de marca) ===')
for item in filhos_da_raiz:
    tipo = 'PASTA' if item['mimeType'] == MIME_PASTA else 'arquivo'
    print(f'  [{tipo}] "{item["name"]}"  (id: {item["id"]})')

print()
print('=== Árvore reconstruída (marca → ean → Videos → arquivos) ===')
arvore_por_ean = montar_arvore_por_ean(todos_os_itens, raiz_id)
print(f'Total de EANs reconhecidos pela árvore: {len(arvore_por_ean)}\n')

for ean, dados in arvore_por_ean.items():
    produto = Produto.objects.filter(ean=ean).first()
    situacao_produto = 'ENCONTRADO no banco' if produto else '❌ NÃO ENCONTRADO no banco'
    snapshot = SnapshotArquivosDrive.objects.filter(produto__ean=ean).first() if produto else None
    situacao_snapshot = f'snapshot atualizado em {snapshot.atualizado_em}' if snapshot else 'sem snapshot salvo ainda'

    print(f'EAN: {ean}  |  Marca: {dados["marca"]}  |  {situacao_produto}  |  {situacao_snapshot}')
    print(f'  Arquivos em Videos/: {[a["name"] for a in dados["arquivos_videos"]]}')
    print(f'  Arquivos em Videos/usados/: {[a["name"] for a in dados["arquivos_usados"]]}')
    print()