# scripts_dev/importar_retroativo_replicacoes_txt.py

# Função Objetivo: Script de USO ÚNICO — lê replicacoes_realizadas.txt
# (gerado pelo agente antes de mlbs_replicados/mlbs_nao_encontrados
# existirem no banco) e preenche esses campos retroativamente nas
# Postagens correspondentes. Depois de rodado com sucesso, pode ser
# descartado — não faz parte do fluxo normal do sistema.

import ast
import datetime
import os
import re
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

from django.utils import timezone
from produtos.models import Produto
from agenda_videos.models import Postagem, StatusPostagem

# ==== CONFIGURA AQUI ANTES DE RODAR ====
# Copie o replicacoes_realizadas.txt da máquina do agente pra perto deste
# script (ou ajuste o caminho abaixo pro lugar real).
CAMINHO_ARQUIVO_LOG = 'replicacoes_realizadas.txt'
TOLERANCIA_SEGUNDOS = 3600  # diferença máxima aceita entre o timestamp do log e Postagem.replicado_em
# ========================================


def _parsear_linha(linha):
    partes = [p.strip() for p in linha.strip().split('|')]
    if len(partes) < 5:
        return None

    timestamp_str = partes[0]
    ean = partes[1].replace('EAN', '', 1).strip()
    titulo = partes[2]
    mlb_origem = partes[3].replace('MLB origem', '', 1).strip()

    lista_str = partes[4]
    if lista_str.lower().startswith('replicado para:'):
        lista_str = lista_str.split(':', 1)[1]
    mlbs_replicados = [m.strip() for m in lista_str.split(',') if m.strip()]

    mlbs_nao_encontrados = []
    if len(partes) >= 6:
        match = re.search(r"não encontrados:\s*(\[.*?\])", partes[5])
        if match:
            try:
                mlbs_nao_encontrados = ast.literal_eval(match.group(1))
            except (ValueError, SyntaxError):
                mlbs_nao_encontrados = []

    try:
        timestamp = timezone.make_aware(datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S'))
    except ValueError:
        timestamp = None

    return {
        'timestamp': timestamp, 'ean': ean, 'titulo': titulo, 'mlb_origem': mlb_origem,
        'mlbs_replicados': mlbs_replicados, 'mlbs_nao_encontrados': mlbs_nao_encontrados,
    }


if not os.path.exists(CAMINHO_ARQUIVO_LOG):
    print(f'Arquivo não encontrado: {CAMINHO_ARQUIVO_LOG}')
    print('Copie o replicacoes_realizadas.txt da máquina do agente pra perto deste script, ou ajuste o caminho no topo do arquivo.')
    sys.exit(1)

with open(CAMINHO_ARQUIVO_LOG, 'r', encoding='utf-8') as arquivo:
    linhas = [l for l in arquivo.readlines() if l.strip()]

print(f'{len(linhas)} linha(s) encontrada(s) em {CAMINHO_ARQUIVO_LOG}.\n')

pendentes = []

for numero, linha in enumerate(linhas, start=1):
    dados = _parsear_linha(linha)
    if dados is None or dados['timestamp'] is None:
        print(f'[linha {numero}] Não consegui interpretar — pulando: {linha.strip()}')
        continue

    produto = Produto.objects.filter(ean=dados['ean']).first()
    if produto is None:
        print(f'[linha {numero}] EAN {dados["ean"]} não encontrado no banco — pulando.')
        continue

    candidatos = list(Postagem.objects.filter(produto=produto, status=StatusPostagem.REPLICADO))
    if not candidatos:
        print(f'[linha {numero}] EAN {dados["ean"]} não tem nenhuma Postagem "replicado" — pulando.')
        continue

    melhor = min(candidatos, key=lambda p: abs((p.replicado_em - dados['timestamp']).total_seconds()))
    diferenca = abs((melhor.replicado_em - dados['timestamp']).total_seconds())

    if diferenca > TOLERANCIA_SEGUNDOS:
        print(
            f'[linha {numero}] EAN {dados["ean"]} — Postagem mais próxima está a '
            f'{diferenca:.0f}s do timestamp do log (> {TOLERANCIA_SEGUNDOS}s de tolerância) — pulando, não é confiável.'
        )
        continue

    if melhor.mlbs_replicados:
        print(f'[linha {numero}] Postagem #{melhor.id} (EAN {dados["ean"]}) já tem mlbs_replicados preenchido — pulando (não sobrescrevo).')
        continue

    pendentes.append((numero, dados, melhor))
    print(
        f'[linha {numero}] EAN {dados["ean"]} ({dados["titulo"]}) → Postagem #{melhor.id} '
        f'({melhor.get_fase_display()} #{melhor.numero_ocorrencia}) — '
        f'{len(dados["mlbs_replicados"])} MLB(s) replicado(s), {len(dados["mlbs_nao_encontrados"])} não encontrado(s).'
    )

if not pendentes:
    print('\nNada pra importar.')
    sys.exit(0)

print(f'\n{len(pendentes)} Postagem(ns) serão atualizadas. Digite SIM pra confirmar: ', end='')
confirmacao = input().strip()
if confirmacao != 'SIM':
    print('Cancelado — nada foi alterado.')
    sys.exit(0)

for numero, dados, postagem in pendentes:
    postagem.mlbs_replicados = dados['mlbs_replicados']
    postagem.mlbs_nao_encontrados = dados['mlbs_nao_encontrados']
    postagem.save(update_fields=['mlbs_replicados', 'mlbs_nao_encontrados'])
    print(f'[linha {numero}] Postagem #{postagem.id} atualizada.')

print('\nConcluído.')