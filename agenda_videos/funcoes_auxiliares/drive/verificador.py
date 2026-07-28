# agenda_videos/funcoes_auxiliares/drive/verificador.py

# Função Objetivo: Verifica os arquivos de preparação no Drive e avança o
# roadmap automaticamente — reaproveita calcular_chave_atual (a MESMA função
# que decide qual ponto é o atual pro clique manual), em loop: pergunta qual
# é o ponto atual, confere se o Drive tem o arquivo dele, marca como pronto,
# pergunta de novo, repete até faltar arquivo ou chegar num ponto que não
# depende de arquivo (cíclico/Agendamento/Otimizado).
#
# 2 modos de entrada, MESMO loop de avanço por baixo (_avancar_pontos_com_estrutura):
#   - verificar_produto_no_drive(produto_id) — 1 produto, busca o Drive AO VIVO.
#   - verificar_todos_no_drive() — todo o catálogo, reaproveita snapshot que
#     a varredura completa (escaneador.py) ACABOU de salvar.

from dataclasses import dataclass
from django.utils import timezone
from agenda_videos.models import (
    StatusVideo, ProgressoProducaoVideo, PreparacaoVideoFase, SnapshotArquivosDrive,
)
from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    calcular_chave_atual, montar_preparacoes_por_fase, obter_mapa_periodos_por_fase,
    FASE_DA_CHAVE_PREPARACAO,
)
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto
from .constantes import PREFIXO_ARQUIVO_POR_FASE
from .localizador import LocalizadorArquivosProduto
from .parser import parsear_arquivos_produto, montar_produto_nao_encontrado

CHAVES_QUE_DEPENDEM_DE_ARQUIVO = {
    'simples', 'base',
    'roteiros_diaria', 'completos_diaria',
    'roteiros_semanal', 'completos_semanal',
    'roteiros_mensal', 'completos_mensal',
}


@dataclass(frozen=True)
class DiagnosticoBloqueio:
    ponto: str
    mensagem: str


# Função Objetivo: Avalia se o Drive (já navegado/parseado em
# ArquivosProdutoDrive) satisfaz o ponto de preparação `chave` — devolve
# (satisfeito, diagnostico). Pura, sem chamada de rede nem escrita no banco —
# reutilizada tanto pela verificação que ESCREVE (este arquivo) quanto pelo
# diagnóstico que só LÊ (diagnostico.py).
def avaliar_ponto_preparacao(chave, estrutura_drive):
    if chave == 'simples':
        if estrutura_drive.simples is None:
            return False, DiagnosticoBloqueio('simples', 'Aguardando Vídeo Simples — "Simples.mp4" não encontrado.')
        return True, None

    if chave == 'base':
        if estrutura_drive.base is None:
            return False, DiagnosticoBloqueio('base', 'Aguardando Vídeo Base — "Base.mp4" não encontrado.')
        return True, None

    if chave in ('roteiros_diaria', 'roteiros_semanal', 'roteiros_mensal'):
        fase = FASE_DA_CHAVE_PREPARACAO[chave]
        if estrutura_drive.fases[fase].roteiros is None:
            nome_esperado = f'Roteiros_{PREFIXO_ARQUIVO_POR_FASE[fase]}.txt'
            return False, DiagnosticoBloqueio(
                chave, f'Aguardando Roteiros ({fase}) — "{nome_esperado}" não encontrado.',
            )
        return True, None

    if chave in ('completos_diaria', 'completos_semanal', 'completos_mensal'):
        fase = FASE_DA_CHAVE_PREPARACAO[chave]
        periodo_atual = obter_mapa_periodos_por_fase().get(fase)
        quantidade_no_drive = estrutura_drive.fases[fase].completos.quantidade
        if periodo_atual is None or quantidade_no_drive < periodo_atual:
            faltam = (periodo_atual - quantidade_no_drive) if periodo_atual else '?'
            return False, DiagnosticoBloqueio(
                chave,
                f'Completos ({fase}): {quantidade_no_drive} de {periodo_atual} vídeo(s) encontrado(s) — faltam {faltam}.',
            )
        return True, None

    return True, None  # ponto que não depende de arquivo — nunca bloqueado por isso


# Função Objetivo: O LOOP de avanço em si — reaproveitado tanto pela
# verificação individual quanto pela em massa. Recebe a estrutura do Drive JÁ
# PRONTA (nenhuma chamada de rede aqui dentro).
def _avancar_pontos_com_estrutura(produto_id, estrutura_drive):
    from produtos.models import Produto

    pontos_marcados = []
    diagnostico = None

    while True:
        # * [EXPLICAÇÃO] → Sempre busca fresco — Django guarda em cache a 1ª
        #                  versão de progresso_producao_video/andamento_agenda
        #                  que acessar; salvar um objeto separado
        #                  (get_or_create) não atualiza esse cache.
        produto = Produto.objects.get(id=produto_id)
        progresso = getattr(produto, 'progresso_producao_video', None)
        andamento = getattr(produto, 'andamento_agenda', None)
        preparacoes_por_fase = montar_preparacoes_por_fase(produto)
        chave_atual = calcular_chave_atual(progresso, preparacoes_por_fase, andamento, produto=produto)

        if chave_atual not in CHAVES_QUE_DEPENDEM_DE_ARQUIVO:
            break

        satisfeito, diagnostico_local = avaliar_ponto_preparacao(chave_atual, estrutura_drive)
        if not satisfeito:
            diagnostico = diagnostico_local
            break

        if chave_atual == 'simples':
            progresso, _ = ProgressoProducaoVideo.objects.get_or_create(produto=produto)
            progresso.video_simples_status = StatusVideo.GERADO
            progresso.video_simples_marcado_em = timezone.now()
            progresso.save()
            pontos_marcados.append('Vídeo Simples')

        elif chave_atual == 'base':
            progresso, _ = ProgressoProducaoVideo.objects.get_or_create(produto=produto)
            progresso.video_base_status = StatusVideo.GERADO
            progresso.video_base_marcado_em = timezone.now()
            progresso.save()
            pontos_marcados.append('Vídeo Base')

        elif chave_atual in ('roteiros_diaria', 'roteiros_semanal', 'roteiros_mensal'):
            fase = FASE_DA_CHAVE_PREPARACAO[chave_atual]
            periodo_atual = obter_mapa_periodos_por_fase().get(fase)
            preparacao, _ = PreparacaoVideoFase.objects.get_or_create(produto=produto, fase=fase)
            preparacao.roteiros_gerados = True
            preparacao.roteiros_quantidade_no_clique = periodo_atual
            preparacao.roteiros_marcado_em = timezone.now()
            preparacao.save()
            pontos_marcados.append(f'Roteiros ({fase})')

        elif chave_atual in ('completos_diaria', 'completos_semanal', 'completos_mensal'):
            fase = FASE_DA_CHAVE_PREPARACAO[chave_atual]
            periodo_atual = obter_mapa_periodos_por_fase().get(fase)
            preparacao, _ = PreparacaoVideoFase.objects.get_or_create(produto=produto, fase=fase)
            preparacao.completos_produzidos = True
            preparacao.completos_quantidade_no_clique = periodo_atual
            preparacao.completos_marcado_em = timezone.now()
            preparacao.save()
            pontos_marcados.append(f'Completos ({fase})')

    if pontos_marcados:
        produto = Produto.objects.get(id=produto_id)
        sincronizar_roadmap_agenda_produto(produto)

    return pontos_marcados, diagnostico


def _obter_estrutura_drive_ao_vivo(produto):
    localizador = LocalizadorArquivosProduto()
    encontrado, arquivos_brutos, motivo, pasta_videos_id = localizador.localizar_arquivos(produto.marca, produto.ean)

    if not encontrado:
        SnapshotArquivosDrive.objects.update_or_create(
            produto=produto,
            defaults={
                'pasta_encontrada': False, 'motivo_nao_encontrado': motivo,
                'arquivos_videos': [], 'arquivos_usados': [],
            },
        )
        return montar_produto_nao_encontrado(produto.marca, produto.ean, motivo)

    arquivos_usados = localizador.listar_arquivos_usados(pasta_videos_id)

    SnapshotArquivosDrive.objects.update_or_create(
        produto=produto,
        defaults={
            'pasta_encontrada': True, 'motivo_nao_encontrado': None,
            'arquivos_videos': arquivos_brutos, 'arquivos_usados': arquivos_usados,
        },
    )

    return parsear_arquivos_produto(produto.marca, produto.ean, arquivos_brutos + arquivos_usados)


# Função Objetivo: Verifica 1 produto — busca o Drive AO VIVO (navegação
# individual, 3-4 chamadas), grava o snapshot, avança quantos pontos os
# arquivos permitirem numa passada só.
def verificar_produto_no_drive(produto_id):
    from produtos.models import Produto

    produto_inicial = Produto.objects.get(id=produto_id)
    estrutura_drive = _obter_estrutura_drive_ao_vivo(produto_inicial)

    if not estrutura_drive.pasta_encontrada:
        return [], estrutura_drive.motivo_pasta_nao_encontrada, None

    pontos_marcados, diagnostico = _avancar_pontos_com_estrutura(produto_id, estrutura_drive)
    return pontos_marcados, None, diagnostico


# Função Objetivo: Verifica TODO o catálogo — reaproveita a varredura
# completa (1 sweep no Drive inteiro, escaneador.py), depois roda o loop de
# avanço em cada produto encontrado, usando o snapshot recém-salvo — zero
# chamada nova ao Drive além do sweep.
def verificar_todos_no_drive():
    from produtos.models import Produto
    from .escaneador import sincronizar_snapshots_drive

    _, sem_produto_no_banco, produto_ids_atualizados = sincronizar_snapshots_drive()

    resumo_por_produto = []
    for produto_id in produto_ids_atualizados:
        produto = Produto.objects.select_related('snapshot_drive').get(id=produto_id)
        snapshot = produto.snapshot_drive
        estrutura_drive = parsear_arquivos_produto(
            produto.marca, produto.ean, snapshot.arquivos_videos + snapshot.arquivos_usados,
        )
        pontos_marcados, _ = _avancar_pontos_com_estrutura(produto_id, estrutura_drive)
        if pontos_marcados:
            resumo_por_produto.append((produto, pontos_marcados))

    return resumo_por_produto, sem_produto_no_banco