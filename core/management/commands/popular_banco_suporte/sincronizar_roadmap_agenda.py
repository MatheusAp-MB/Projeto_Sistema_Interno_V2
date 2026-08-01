# core/management/commands/popular_banco_suporte/sincronizar_roadmap_agenda.py

from produtos.models import Produto
from agenda_videos.models import IndicadoresAgendaProduto
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import calcular_indicadores
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO

CAMPOS_INDICADORES = ['etapa_atual', 'fase_atual', 'ciclo_atual_atrasado', 'tem_video_reprovado', 'status_manual']


def sincronizar_roadmap_agenda(stdout, style):
    stdout.write('[INDICADORES AGENDA] Sincronizando...')

    produtos = list(
        Produto.objects.select_related('participacao_agenda').prefetch_related('ciclos_video').all()
    )
    total = len(produtos)

    existentes = {i.produto_id: i for i in IndicadoresAgendaProduto.objects.all()}
    para_criar = []
    para_atualizar = []
    contagem_por_etapa = {}

    for indice, produto in enumerate(produtos, start=1):
        if indice % 500 == 0 or indice == total:
            stdout.write(f'    ... {indice}/{total} produtos processados')

        ciclos = list(produto.ciclos_video.all())  # já veio do prefetch, sem query nova
        ciclo_mais_recente = ciclos[0] if ciclos else None
        valores = calcular_indicadores(produto, ciclo_mais_recente)
        contagem_por_etapa[valores['etapa_atual']] = contagem_por_etapa.get(valores['etapa_atual'], 0) + 1

        existente = existentes.get(produto.id)
        if existente is None:
            para_criar.append(IndicadoresAgendaProduto(produto=produto, **valores))
        elif any(getattr(existente, campo) != valor for campo, valor in valores.items()):
            for campo, valor in valores.items():
                setattr(existente, campo, valor)
            para_atualizar.append(existente)

    if para_criar:
        IndicadoresAgendaProduto.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)
    if para_atualizar:
        IndicadoresAgendaProduto.objects.bulk_update(para_atualizar, CAMPOS_INDICADORES, batch_size=BATCH_SIZE_PADRAO)

    linhas_resumo = '\n'.join(f'    {chave}: {valor}' for chave, valor in sorted(contagem_por_etapa.items()))
    stdout.write(style.SUCCESS(
        f'[INDICADORES AGENDA] Concluído!\n    Criados: {len(para_criar)}\n    Atualizados: {len(para_atualizar)}\n{linhas_resumo}'
    ))