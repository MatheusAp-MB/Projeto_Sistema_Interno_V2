import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from django.conf import settings
from agenda_videos.funcoes_auxiliares.google_drive_cliente import obter_servico_drive

servico = obter_servico_drive()
resultado = servico.files().list(
    q=f"'{settings.GOOGLE_DRIVE_PASTA_RAIZ_ID}' in parents",
    fields="files(id, name, mimeType)",
).execute()

arquivos = resultado.get('files', [])
print(f"{len(arquivos)} item(ns) encontrado(s) na pasta raiz:")
for arquivo in arquivos:
    tipo = "PASTA" if arquivo['mimeType'] == 'application/vnd.google-apps.folder' else "arquivo"
    print(f"  [{tipo}] {arquivo['name']} (id: {arquivo['id']})")