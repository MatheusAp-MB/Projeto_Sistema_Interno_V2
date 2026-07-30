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

# * [RESUMO] → Script de USO ÚNICO (por rodada de teste) — zera por completo
# o estado da Agenda de Vídeos (Postagem, PreparacaoVideoFase, AndamentoAgenda,
# ProgressoProducaoVideo, RoadmapAgenda, SnapshotArquivosDrive) de TODO
# produto, real ou de teste, e apaga os produtos de teste (EAN "TESTE-AGENDA-...")
# por inteiro. ConfiguracaoFase NÃO é tocada — fica com os períodos reais.
#
# Reaplica automaticamente reestruturacao_manual nos 73 produtos legados no
# final — sem isso, essa tag se perderia junto com o resto de RoadmapAgenda.

from produtos.models import Produto
from mercado_livre.models import AnuncioMercadoLivre
from agenda_videos.models import (
    Postagem, PreparacaoVideoFase, RoadmapAgenda, AndamentoAgenda,
    ProgressoProducaoVideo, SnapshotArquivosDrive,
)
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto

PREFIXO_TESTE = 'TESTE-AGENDA-'

EANS_LEGADO = [
    '0070341902806', '0789888395957', '7891117006961', '7891117051985',
    '7891117101307', '7891117102687', '7891117103936', '7891117108009',
    '7891988003199', '7891988006480', '7891988006671', '7891988010432',
    '7891988038306', '7891988044178', '7891988052159', '7891988054306',
    '7891988055341', '7891988063780', '7891988071518', '7895293437342',
    '7895293546662', '7895293684708', '7895293684715', '7895293695636',
    '7895293790454', '7895293908057', '7895572102275', '7896660874258',
    '7896660874272', '7896692148310', '7896821500279', '7897154291377',
    '7898026080587', '7898026082116', '7898026083229', '7898026083359',
    '7898026086237', '7898632330663', '7898632332155', '7898632332162',
    '7898632332223', '7898632339543', '7898635051602', '7898635052319',
    '7898635052326', '7899009119775', '7899296599199', '7899612724472',
    '7908050719121', '7908050719534', '7908050734483', '7908276603655',
    '7908276605376', '7908276607578', '7908276608605', '7908276608612',
    '7908276622236', '7908276625664', '7908276643316', '7908276645501',
    '7908276645556', '7908276653209', '7908276656156', '7908276656163',
    '7908276656248', '7908276662348', '7908276665974', '7908276665981',
    '7908276682759', '7908276684319', '7909436939669', '7909439011089',
    '7909439011096',
]


def zerar_estado_da_agenda():
    qtd_postagem, _ = Postagem.objects.all().delete()
    qtd_preparacao, _ = PreparacaoVideoFase.objects.all().delete()
    qtd_snapshot, _ = SnapshotArquivosDrive.objects.all().delete()
    qtd_roadmap, _ = RoadmapAgenda.objects.all().delete()
    qtd_andamento, _ = AndamentoAgenda.objects.all().delete()
    qtd_progresso, _ = ProgressoProducaoVideo.objects.all().delete()

    print(
        f'Estado da Agenda zerado — Postagem: {qtd_postagem}, PreparacaoVideoFase: {qtd_preparacao}, '
        f'SnapshotArquivosDrive: {qtd_snapshot}, RoadmapAgenda: {qtd_roadmap}, '
        f'AndamentoAgenda: {qtd_andamento}, ProgressoProducaoVideo: {qtd_progresso}.'
    )


def apagar_produtos_de_teste():
    qtd_anuncios, _ = AnuncioMercadoLivre.objects.filter(mlb__startswith=PREFIXO_TESTE).delete()
    qtd_produtos, _ = Produto.objects.filter(ean__startswith=PREFIXO_TESTE).delete()
    print(f'Produtos de teste apagados: {qtd_produtos} (+ {qtd_anuncios} registro(s) ligado(s) em mercado_livre).')


def ressincronizar_produtos_reais():
    produtos_restantes = Produto.objects.all()
    for produto in produtos_restantes:
        sincronizar_roadmap_agenda_produto(produto)
    print(f'{produtos_restantes.count()} produto(s) real(is) ressincronizado(s) — todos voltam como "Não Agendado".')


def reaplicar_reestruturacao_manual():
    marcados = 0
    nao_encontrados = []
    for ean in EANS_LEGADO:
        produto = Produto.objects.filter(ean=ean).first()
        if produto is None:
            nao_encontrados.append(ean)
            continue
        roadmap_agenda, _ = RoadmapAgenda.objects.get_or_create(produto=produto)
        roadmap_agenda.reestruturacao_manual = True
        roadmap_agenda.save()
        marcados += 1

    print(f'Reestruturação Manual reaplicada em {marcados} produto(s) legado(s).')
    if nao_encontrados:
        print(f'  {len(nao_encontrados)} EAN(s) da lista legada não encontrados no banco: {nao_encontrados}')


if __name__ == '__main__':
    resposta = input(
        'Isso vai APAGAR todo o estado da Agenda (Postagem/Preparação/Andamento/Progresso/'
        'Roadmap/Snapshot) de TODO produto, e apagar os produtos de teste por completo. '
        'A tag Reestruturação Manual será reaplicada automaticamente no final. Confirma? (digite SIM): '
    )
    if resposta.strip().upper() != 'SIM':
        print('Cancelado — nada foi apagado.')
    else:
        zerar_estado_da_agenda()
        apagar_produtos_de_teste()
        ressincronizar_produtos_reais()
        reaplicar_reestruturacao_manual()
        print('\nConcluído. Banco pronto pra você subir os dados reais do zero.')