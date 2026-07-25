import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from datetime import date, timedelta
from produtos.models import Produto
from agenda_videos.models import (
    ConfiguracaoFase, Fase, AndamentoAgenda, StatusManualAgenda,
    ProgressoProducaoVideo, StatusVideo, Postagem, StatusPostagem,
)
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_fase

# ==== CONFIGURA AQUI ANTES DE RODAR ====
QTD_PRODUTOS_EXEMPLO = 6
# ========================================

config_diaria, criada = ConfiguracaoFase.objects.get_or_create(
    fase=Fase.DIARIA,
    defaults={'quantidade_postagens': 1, 'periodo': 10},
)
print(f"ConfiguracaoFase Diária: {'criada agora' if criada else 'já existia'} — periodo={config_diaria.periodo}")

produtos = list(Produto.objects.filter(andamento_agenda__isnull=True)[:QTD_PRODUTOS_EXEMPLO])
print(f"{len(produtos)} produto(s) sem Agenda encontrados (de {QTD_PRODUTOS_EXEMPLO} pedidos).")

if len(produtos) < QTD_PRODUTOS_EXEMPLO:
    print("AVISO: menos produtos disponíveis que o pedido — alguns cenários abaixo podem faltar.")

hoje = date.today()
janela_fase = calcular_janela_fase(Fase.DIARIA, hoje, config_diaria.periodo)

# * [EXPLICAÇÃO] → 6 cenários ilustrativos, cobrindo os casos que a gente desenhou:
#                  urgente, pausado, descontinuado, sem vídeo nenhum, quase terminando
#                  com postagem recusada, e tudo pronto com postagem replicada.
CENARIOS = [
    {
        'ocorrencia_atual': 2, 'status_manual': StatusManualAgenda.ATIVO, 'urgente': True,
        'video_simples': StatusVideo.GERADO, 'video_base': StatusVideo.GERADO,
        'roteiros_gerados': True, 'completos_produzidos': False, 'quantidade_roteiros': 6,
        'postagem': None,
    },
    {
        'ocorrencia_atual': 5, 'status_manual': StatusManualAgenda.ATIVO, 'urgente': False,
        'video_simples': StatusVideo.GERADO, 'video_base': StatusVideo.GERADO,
        'roteiros_gerados': True, 'completos_produzidos': True, 'quantidade_roteiros': 10,
        'postagem': StatusPostagem.AGUARDANDO_APROVACAO,
    },
    {
        'ocorrencia_atual': 1, 'status_manual': StatusManualAgenda.PAUSADO, 'urgente': False,
        'video_simples': StatusVideo.NAO_GERADO, 'video_base': StatusVideo.NAO_GERADO,
        'roteiros_gerados': False, 'completos_produzidos': False, 'quantidade_roteiros': 0,
        'postagem': None,
    },
    {
        'ocorrencia_atual': 8, 'status_manual': StatusManualAgenda.ATIVO, 'urgente': True,
        'video_simples': StatusVideo.GERADO, 'video_base': StatusVideo.GERADO,
        'roteiros_gerados': True, 'completos_produzidos': True, 'quantidade_roteiros': 10,
        'postagem': StatusPostagem.RECUSADO,
    },
    {
        'ocorrencia_atual': 10, 'status_manual': StatusManualAgenda.ATIVO, 'urgente': False,
        'video_simples': StatusVideo.GERADO, 'video_base': StatusVideo.GERADO,
        'roteiros_gerados': True, 'completos_produzidos': True, 'quantidade_roteiros': 10,
        'postagem': StatusPostagem.REPLICADO,
    },
    {
        'ocorrencia_atual': 3, 'status_manual': StatusManualAgenda.DESCONTINUADO, 'urgente': False,
        'video_simples': StatusVideo.GERADO, 'video_base': StatusVideo.NAO_GERADO,
        'roteiros_gerados': False, 'completos_produzidos': False, 'quantidade_roteiros': 2,
        'postagem': None,
    },
]

for produto, cenario in zip(produtos, CENARIOS):
    andamento = AndamentoAgenda.objects.create(
        produto=produto,
        fase_atual=config_diaria,
        ocorrencia_atual=cenario['ocorrencia_atual'],
        inicio_fase=janela_fase.inicio,
        fim_fase=janela_fase.fim,
        status_manual=cenario['status_manual'],
        urgente=cenario['urgente'],
    )

    progresso = ProgressoProducaoVideo.objects.create(
        produto=produto,
        video_simples_status=cenario['video_simples'],
        video_base_status=cenario['video_base'],
        roteiros_gerados=cenario['roteiros_gerados'],
        completos_produzidos=cenario['completos_produzidos'],
        quantidade_roteiros=cenario['quantidade_roteiros'],
    )  # roteiros_insuficientes é calculado sozinho no save()

    if cenario['postagem']:
        Postagem.objects.create(
            produto=produto,
            fase=Fase.DIARIA,
            numero_ocorrencia=cenario['ocorrencia_atual'],
            inicio_ocorrencia=hoje,
            fim_ocorrencia=hoje,
            status=cenario['postagem'],
        )

    print(
        f"[OK] {produto.sku or produto.ean} — {produto.titulo[:40]} | "
        f"dia {cenario['ocorrencia_atual']}/{config_diaria.periodo} | "
        f"{cenario['status_manual']} | urgente={cenario['urgente']} | "
        f"roteiros={cenario['quantidade_roteiros']} (insuficiente={progresso.roteiros_insuficientes}) | "
        f"postagem={cenario['postagem'] or 'nenhuma'}"
    )

print("\nPronto — acessa a tela 'Diários' pra ver os produtos de exemplo.")