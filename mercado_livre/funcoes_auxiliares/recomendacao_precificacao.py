# * [RESUMO] → Lógica de recomendação de precificação para Catálogo —
#              decide qual preço/promoção usar, seguindo 1 de 3
#              comportamentos possíveis. Sempre parte da mesma pergunta:
#              "qual a melhor forma de ganhar o catálogo com segurança?"
#              Separado da view de propósito — é lógica de negócio pura,
#              testável sozinha, sem nenhuma dependência de HTTP/Django.

from mercado_livre.funcoes_auxiliares.calculo_margem import MARGEM_MINIMA_PADRAO

COMPORTAMENTOS = {
    'padrao': 'Padrão (equilíbrio)',
    'busca_lucro': 'Busca-Lucro (maior margem)',
    'disputa': 'Disputa (ganha catálogo a qualquer custo seguro)',
}


def melhor_margem(lista):
    """Escolhe, dentro de uma lista de linhas candidatas, a de maior margem."""
    if not lista:
        return None
    return max(lista, key=lambda l: l['margem_real']['margem_percentual'])


def _classificar_buckets(linhas, margem_minima):
    """Separa as linhas que GANHAM catálogo em 4 grupos, cruzando margem
    (dentro/abaixo do mínimo) com origem (promoção real / Preço Direto).
    Linhas que perdem catálogo não entram aqui — essa função alimenta só
    a recomendação, não a visão geral por categoria (que continua tendo
    suas próprias 4 categorias, incluindo as que perdem catálogo)."""
    ganham = [l for l in linhas if l['ganha_catalogo']]

    dentro = [l for l in ganham if l['margem_real']['margem_percentual'] >= margem_minima]
    abaixo = [l for l in ganham if l['margem_real']['margem_percentual'] < margem_minima]

    return {
        'com_promocao_dentro': [l for l in dentro if l['tipo'] != 'PRECO_DIRETO'],
        'sem_promocao_dentro': [l for l in dentro if l['tipo'] == 'PRECO_DIRETO'],
        'com_promocao_abaixo': [l for l in abaixo if l['tipo'] != 'PRECO_DIRETO'],
        'sem_promocao_abaixo': [l for l in abaixo if l['tipo'] == 'PRECO_DIRETO'],
    }


def recomendar_precificacao(linhas, comportamento='padrao', margem_minima=None):
    """Aplica 1 dos 3 comportamentos sobre as linhas já calculadas
    (promoções + Preço Direto). Retorna a linha escolhida (ou None),
    o nome do bucket de onde veio, e se essa escolha exige aprovação
    manual (fica abaixo da margem mínima)."""
    margem_minima = margem_minima if margem_minima is not None else MARGEM_MINIMA_PADRAO
    buckets = _classificar_buckets(linhas, margem_minima)

    # * [EXPLICAÇÃO] → Busca-Lucro: só considera as 2 opções seguras
    #                  (dentro da margem mínima), com ou sem promoção, e
    #                  pega a de maior margem entre as duas — nunca cai
    #                  pra abaixo do mínimo, mesmo que nada seja achado.
    if comportamento == 'busca_lucro':
        candidatos = buckets['com_promocao_dentro'] + buckets['sem_promocao_dentro']
        escolhida = melhor_margem(candidatos)
        return {
            'escolhida': escolhida,
            'bucket_nome': 'Maior margem possível (dentro do mínimo)' if escolhida else None,
            'exige_aprovacao': False,
        }

    # * [EXPLICAÇÃO] → Padrão e Disputa seguem a MESMA hierarquia hoje —
    #                  a diferença entre os dois só existirá quando
    #                  houver automação de verdade (Disputa teria
    #                  permissão de executar sozinho o que cai abaixo da
    #                  margem; Padrão sempre pediria aprovação manual
    #                  nesse caso). Mantidos como comportamentos
    #                  distintos de propósito, mesmo calculando igual
    #                  hoje, pra já existir esse contrato pronto quando
    #                  a automação chegar.
    ordem = [
        ('com_promocao_dentro', 'Ganha catálogo, dentro da margem, com promoção'),
        ('sem_promocao_dentro', 'Ganha catálogo, dentro da margem, sem promoção'),
        ('com_promocao_abaixo', 'Ganha catálogo, abaixo da margem, com promoção'),
        ('sem_promocao_abaixo', 'Ganha catálogo, abaixo da margem, sem promoção'),
    ]

    for chave, nome in ordem:
        escolhida = melhor_margem(buckets[chave])
        if escolhida:
            return {
                'escolhida': escolhida,
                'bucket_nome': nome,
                'exige_aprovacao': chave in ('com_promocao_abaixo', 'sem_promocao_abaixo'),
            }

    return {'escolhida': None, 'bucket_nome': None, 'exige_aprovacao': False}