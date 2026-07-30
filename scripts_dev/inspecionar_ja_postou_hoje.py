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

from django.conf import settings
from django.utils import timezone
from produtos.models import Produto
from agenda_videos.models import Postagem
from agenda_videos.funcoes_auxiliares.postagem_ciclica import ja_postou_hoje
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import calcular_pendencias_atuais_produto, listar_a_fazer_hoje
from agenda_videos.funcoes_auxiliares.postagem_automatica import listar_produtos_elegiveis

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EANS_PARA_INSPECIONAR = ['7891117102687', '7891988003199']
# ========================================

print('=== Configuração de fuso horário ===')
print(f'USE_TZ: {settings.USE_TZ}')
print(f'TIME_ZONE: {settings.TIME_ZONE}')
print(f'timezone.now() (bruto):      {timezone.now()}')
print(f'timezone.now() (localizado): {timezone.localtime(timezone.now())}')
print(f'.date() do bruto:      {timezone.now().date()}')
print(f'.date() do localizado: {timezone.localtime(timezone.now()).date()}')
print()

for ean in EANS_PARA_INSPECIONAR:
    print(f'=== {ean} ===')
    produto = Produto.objects.filter(ean=ean).first()
    if produto is None:
        print('  Não encontrado no banco.')
        continue

    andamento = getattr(produto, 'andamento_agenda', None)
    if andamento is None:
        print('  Sem AndamentoAgenda.')
        continue

    print(f'  Fase atual: {andamento.fase_atual.fase} | Ocorrência atual: {andamento.ocorrencia_atual}')
    print(f'  inicio_fase: {andamento.inicio_fase} | fim_ocorrencia_atual: {andamento.fim_ocorrencia_atual}')
    print()

    print('  --- TODAS as Postagens deste produto (qualquer ocorrência) ---')
    postagens = Postagem.objects.filter(produto=produto).order_by('criado_em')
    if not postagens.exists():
        print('    Nenhuma Postagem encontrada.')
    for postagem in postagens:
        print(
            f'    id={postagem.id} | ocorrência={postagem.numero_ocorrencia} | status={postagem.status} | '
            f'aguardando_aprovacao_em={postagem.aguardando_aprovacao_em} '
            f'(date={postagem.aguardando_aprovacao_em.date() if postagem.aguardando_aprovacao_em else None})'
        )

    print()
    print(f'  ja_postou_hoje(produto) = {ja_postou_hoje(produto)}')

    postagem_atual = Postagem.objects.filter(
        produto=produto, fase=andamento.fase_atual.fase, numero_ocorrencia=andamento.ocorrencia_atual,
    ).order_by('-criado_em').first()
    pendencias = calcular_pendencias_atuais_produto(produto, andamento, postagem_atual, hoje=timezone.localtime(timezone.now()).date())
    print(f'  Pendências calculadas AGORA: {pendencias}')
    print(f'  "aguardando_postar" está entre elas? {"aguardando_postar" in pendencias}')
    print()

print('=== Produtos que listar_produtos_elegiveis() (a fonte real da Postagem Automática) retorna agora ===')
elegiveis = listar_produtos_elegiveis()
if not elegiveis:
    print('  Nenhum.')
for produto in elegiveis:
    print(f'  {produto.ean} — {produto.titulo}')