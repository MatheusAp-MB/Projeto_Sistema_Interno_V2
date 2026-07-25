# core/management/commands/popular_banco_suporte/sincronizar_roadmap_agenda.py

# Função Objetivo: Garante que TODO Produto tenha um RoadmapAgenda — cria "Não
# Agendado" pra quem ainda não tem, recalcula quem já tem.
# Explicação em detalhe: substitui a ideia de signal (que não dispara em bulk_create,
# usado pela importação do ERP) — esta etapa varre tudo, sempre, a cada rodada do
# popular_banco. Idempotente — seguro rodar quantas vezes for preciso.

from produtos.models import Produto
from agenda_videos.models import RoadmapAgenda, EstagioAgenda
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_chave_atual
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import colapsar_chave_em_estagio
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO


def sincronizar_roadmap_agenda(stdout, style):
    stdout.write('[ROADMAP AGENDA] Sincronizando...')

    produtos = list(Produto.objects.select_related(
        'progresso_producao_video', 'andamento_agenda', 'andamento_agenda__fase_atual',
    ).all())
    total = len(produtos)

    existentes = {r.produto_id: r for r in RoadmapAgenda.objects.all()}
    para_criar = []
    para_atualizar = []
    contagem_por_estagio = {estagio.value: 0 for estagio in EstagioAgenda}

    for indice, produto in enumerate(produtos, start=1):
        if indice % 500 == 0 or indice == total:
            stdout.write(f'    ... {indice}/{total} produtos processados')

        chave_atual = calcular_chave_atual(
            getattr(produto, 'progresso_producao_video', None),
            getattr(produto, 'andamento_agenda', None),
        )
        estagio = colapsar_chave_em_estagio(chave_atual)
        contagem_por_estagio[estagio] += 1

        existente = existentes.get(produto.id)
        if existente is None:
            para_criar.append(RoadmapAgenda(produto=produto, estagio_atual=estagio))
        elif existente.estagio_atual != estagio:
            existente.estagio_atual = estagio
            para_atualizar.append(existente)

    if para_criar:
        RoadmapAgenda.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)
    if para_atualizar:
        RoadmapAgenda.objects.bulk_update(para_atualizar, ['estagio_atual'], batch_size=BATCH_SIZE_PADRAO)

    linhas_resumo = '\n'.join(f'    {EstagioAgenda(k).label}: {v}' for k, v in contagem_por_estagio.items())
    stdout.write(style.SUCCESS(
        f'[ROADMAP AGENDA] Concluído!\n'
        f'    Criados: {len(para_criar)}\n'
        f'    Atualizados: {len(para_atualizar)}\n'
        f'{linhas_resumo}'
    ))