# core/management/commands/popular_banco_suporte/sincronizar_roadmap_agenda.py

from produtos.models import Produto
from agenda_videos.models import RoadmapAgenda, EstagioAgenda, ProgressoProducaoVideo
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_chave_atual, montar_preparacoes_por_fase
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import (
    colapsar_chave_em_estagio, _verificar_video_reprovado,
)
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO


# Função Objetivo: Garante que TODO Produto tenha um ProgressoProducaoVideo — sem
# isso, marcar Simples/Base quebraria pros produtos "Não Agendado" de verdade.
def _garantir_progresso_producao_video(produtos):
    ids_com_progresso = set(
        ProgressoProducaoVideo.objects.filter(produto__in=produtos).values_list('produto_id', flat=True)
    )
    faltando = [p for p in produtos if p.id not in ids_com_progresso]
    if faltando:
        ProgressoProducaoVideo.objects.bulk_create(
            [ProgressoProducaoVideo(produto=p) for p in faltando], batch_size=BATCH_SIZE_PADRAO,
        )
    return len(faltando)


def sincronizar_roadmap_agenda(stdout, style):
    stdout.write('[ROADMAP AGENDA] Sincronizando...')

    produtos = list(Produto.objects.select_related(
        'progresso_producao_video', 'andamento_agenda', 'andamento_agenda__fase_atual',
    ).prefetch_related('preparacoes_video').all())

    qtd_progresso_criado = _garantir_progresso_producao_video(produtos)
    if qtd_progresso_criado:
        stdout.write(f'    ProgressoProducaoVideo criado pra {qtd_progresso_criado} produto(s).')
        produtos = list(Produto.objects.select_related(
            'progresso_producao_video', 'andamento_agenda', 'andamento_agenda__fase_atual',
        ).prefetch_related('preparacoes_video').all())

    total = len(produtos)
    existentes = {r.produto_id: r for r in RoadmapAgenda.objects.all()}
    para_criar = []
    para_atualizar = []
    contagem_por_estagio = {estagio.value: 0 for estagio in EstagioAgenda}

    for indice, produto in enumerate(produtos, start=1):
        if indice % 500 == 0 or indice == total:
            stdout.write(f'    ... {indice}/{total} produtos processados')

        preparacoes_por_fase = montar_preparacoes_por_fase(produto)
        chave_atual = calcular_chave_atual(
            getattr(produto, 'progresso_producao_video', None),
            preparacoes_por_fase,
            getattr(produto, 'andamento_agenda', None),
        )
        estagio = colapsar_chave_em_estagio(chave_atual)
        contagem_por_estagio[estagio] += 1
        tem_video_reprovado = _verificar_video_reprovado(produto)

        existente = existentes.get(produto.id)
        if existente is None:
            para_criar.append(RoadmapAgenda(
                produto=produto, estagio_atual=estagio, tem_video_reprovado=tem_video_reprovado,
            ))
        elif existente.estagio_atual != estagio or existente.tem_video_reprovado != tem_video_reprovado:
            existente.estagio_atual = estagio
            existente.tem_video_reprovado = tem_video_reprovado
            para_atualizar.append(existente)

    if para_criar:
        RoadmapAgenda.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)
    if para_atualizar:
        RoadmapAgenda.objects.bulk_update(
            para_atualizar, ['estagio_atual', 'tem_video_reprovado'], batch_size=BATCH_SIZE_PADRAO,
        )

    linhas_resumo = '\n'.join(f'    {EstagioAgenda(k).label}: {v}' for k, v in contagem_por_estagio.items())
    stdout.write(style.SUCCESS(
        f'[ROADMAP AGENDA] Concluído!\n    Criados: {len(para_criar)}\n    Atualizados: {len(para_atualizar)}\n{linhas_resumo}'
    ))