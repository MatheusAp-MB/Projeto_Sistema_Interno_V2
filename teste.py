import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

# * [RESUMO] → Script de USO ÚNICO — zera por completo o estado da Agenda de
# Vídeos (Postagem, PreparacaoVideoFase, RoadmapAgenda, AndamentoAgenda,
# ProgressoProducaoVideo) de TODO produto, real ou de teste, e apaga os 23
# produtos de teste (EAN "TESTE-AGENDA-...") por inteiro, incluindo os
# registros ligados no app mercado_livre (Anúncio/Variação/Qualidade) criados
# pelo cenário "Sem Vídeo". ConfiguracaoFase (Diária/Semanal/Mensal) NÃO é
# tocada — fica com os períodos reais já validados.
#
# Depois de rodar isso, o próximo passo é reimportar os dados reais do zero:
#   python manage.py importar_agenda_legada "caminho/MAGAZINE.xlsx"

from produtos.models import Produto
from mercado_livre.models import AnuncioMercadoLivre
from agenda_videos.models import (
    Postagem, PreparacaoVideoFase, RoadmapAgenda, AndamentoAgenda, ProgressoProducaoVideo,
)
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto

PREFIXO_TESTE = 'TESTE-AGENDA-'


def zerar_estado_da_agenda():
    # * [EXPLICAÇÃO] → Ordem importa: AndamentoAgenda.fase_atual é
    #                  on_delete=PROTECT pra ConfiguracaoFase — mas como
    #                  ConfiguracaoFase não está sendo apagada aqui, essa
    #                  ordem específica não trava nada. Mantida mesmo assim,
    #                  pela clareza (postagem/preparo antes de andamento).
    qtd_postagem, _ = Postagem.objects.all().delete()
    qtd_preparacao, _ = PreparacaoVideoFase.objects.all().delete()
    qtd_roadmap, _ = RoadmapAgenda.objects.all().delete()
    qtd_andamento, _ = AndamentoAgenda.objects.all().delete()
    qtd_progresso, _ = ProgressoProducaoVideo.objects.all().delete()

    print(
        f'Estado da Agenda zerado — Postagem: {qtd_postagem}, PreparacaoVideoFase: {qtd_preparacao}, '
        f'RoadmapAgenda: {qtd_roadmap}, AndamentoAgenda: {qtd_andamento}, '
        f'ProgressoProducaoVideo: {qtd_progresso}.'
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


if __name__ == '__main__':
    resposta = input(
        'Isso vai APAGAR todo o estado da Agenda (Postagem/Preparação/Andamento/Progresso/Roadmap) '
        'de TODO produto, e apagar os 23 produtos de teste por completo. Confirma? (digite SIM): '
    )
    if resposta.strip().upper() != 'SIM':
        print('Cancelado — nada foi apagado.')
    else:
        zerar_estado_da_agenda()
        apagar_produtos_de_teste()
        ressincronizar_produtos_reais()
        print('\nConcluído. Próximo passo: rodar importar_agenda_legada com o MAGAZINE.xlsx real.')