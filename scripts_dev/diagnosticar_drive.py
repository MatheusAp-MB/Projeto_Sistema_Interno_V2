# scripts_dev/diagnosticar_drive.py

# Função Objetivo: confirmar, nesta máquina, que o ambiente do Google
# Drive está configurado corretamente ANTES de continuar o Portal do
# Drive — sem tocar em nenhuma pasta real de produção. Checa, em ordem:
# (1) as 3 credenciais apontam pra arquivo real no disco; (2) a LEITURA
# (Service Account) alcança as 4 pastas configuradas (2 reais + 2 de
# teste); (3) a ESCRITA (OAuth) funciona de verdade — testada só dentro
# das 2 pastas de TESTE, criando e apagando 1 arquivo vazio em cada uma.

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__ + '/..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from django.conf import settings

from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive, obter_servico_drive_escrita

PASTAS_PARA_CHECAR = (
    ('Magazine Estruturada (real)', 'GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE'),
    ('Samvale Estruturada (real)', 'GOOGLE_DRIVE_PASTA_RAIZ_SAMVALE'),
    ('Teste Magazine', 'GOOGLE_DRIVE_PASTA_TESTE_MAGAZINE'),
    ('Teste Samvale', 'GOOGLE_DRIVE_PASTA_TESTE_SAMVALE'),
)

NOME_ARQUIVO_TESTE_ESCRITA = '_diagnostico_escrita.txt'


def _checar_variaveis_de_ambiente():
    print('--- 1. Variáveis de ambiente ---')
    tudo_ok = True

    for nome_variavel in ('GOOGLE_DRIVE_CREDENCIAIS_JSON', 'GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_JSON', 'GOOGLE_DRIVE_OAUTH_TOKEN_JSON'):
        caminho = getattr(settings, nome_variavel, None)
        if not caminho:
            print(f'  [FALTA] {nome_variavel} não está definida no .env.')
            tudo_ok = False
        elif not os.path.exists(caminho):
            print(f'  [FALTA] {nome_variavel} aponta pra "{caminho}", mas o arquivo não existe nesta máquina.')
            tudo_ok = False
        else:
            print(f'  [OK] {nome_variavel} -> {caminho}')

    for rotulo, nome_variavel in PASTAS_PARA_CHECAR:
        valor = getattr(settings, nome_variavel, None)
        if not valor:
            print(f'  [FALTA] {nome_variavel} ({rotulo}) não está definida no .env.')
            tudo_ok = False
        else:
            print(f'  [OK] {nome_variavel} ({rotulo}) -> {valor}')

    return tudo_ok


def _checar_leitura():
    print('\n--- 2. Leitura (Service Account) ---')
    try:
        servico = obter_servico_drive()
    except Exception as erro:
        print(f'  [ERRO] Não consegui autenticar a leitura: {erro}')
        return

    for rotulo, nome_variavel in PASTAS_PARA_CHECAR:
        pasta_id = getattr(settings, nome_variavel, None)
        if not pasta_id:
            print(f'  [PULADO] {rotulo} — variável não configurada, ver seção 1.')
            continue
        try:
            metadado = servico.files().get(
                fileId=pasta_id, fields='id, name, mimeType', supportsAllDrives=True,
            ).execute()
            print(f'  [OK] {rotulo} -> encontrada: "{metadado["name"]}" (id {metadado["id"]})')
        except Exception as erro:
            print(f'  [ERRO] {rotulo} (id {pasta_id}) -> {erro}')


def _checar_escrita():
    print('\n--- 3. Escrita (OAuth) — só nas pastas de TESTE ---')
    try:
        servico = obter_servico_drive_escrita()
    except Exception as erro:
        print(f'  [ERRO] Não consegui autenticar a escrita: {erro}')
        return

    for rotulo, nome_variavel in (
        ('Teste Magazine', 'GOOGLE_DRIVE_PASTA_TESTE_MAGAZINE'),
        ('Teste Samvale', 'GOOGLE_DRIVE_PASTA_TESTE_SAMVALE'),
    ):
        pasta_id = getattr(settings, nome_variavel, None)
        if not pasta_id:
            print(f'  [PULADO] {rotulo} — variável não configurada, ver seção 1.')
            continue
        try:
            arquivo_criado = servico.files().create(
                body={'name': NOME_ARQUIVO_TESTE_ESCRITA, 'parents': [pasta_id]},
                fields='id', supportsAllDrives=True,
            ).execute()
            servico.files().delete(fileId=arquivo_criado['id'], supportsAllDrives=True).execute()
            print(f'  [OK] {rotulo} -> criou e apagou "{NOME_ARQUIVO_TESTE_ESCRITA}" com sucesso (cota de escrita confirmada).')
        except Exception as erro:
            print(f'  [ERRO] {rotulo} -> {erro}')


if __name__ == '__main__':
    variaveis_ok = _checar_variaveis_de_ambiente()
    if not variaveis_ok:
        print('\nCorrija as variáveis marcadas [FALTA] no .env antes de continuar — leitura/escrita nem vão ser testadas.')
        sys.exit(1)
    _checar_leitura()
    _checar_escrita()
    print('\nDiagnóstico concluído.')