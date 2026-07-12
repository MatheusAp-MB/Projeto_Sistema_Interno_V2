# * [RESUMO] → Lógica de recomendação de precificação — decide qual
#              preço/promoção usar, seguindo 1 de 3 comportamentos.
#              Funciona pra Catálogo (eixo extra: ganha/perde catálogo)
#              e pra Simples/Base (só margem × com-ou-sem promoção) —
#              mesma lógica generalizada, não duas implementações
#              separadas. margem_minima vem sempre de fora agora (da
#              configuração real do tipo de anúncio, não mais de uma
#              constante fixa).

COMPORTAMENTOS = {
    'padrao': 'Padrão (equilíbrio)',
    'busca_lucro': 'Busca-Lucro (maior margem)',
    'disputa': 'Disputa (ganha catálogo a qualquer custo seguro)',
}

# * [EXPLICAÇÃO] → Marca quem é "linha de base" (preço sem nenhuma
#                  promoção envolvida) — Preço Direto pra Ganhar
#                  (Catálogo) ou Preço Atual (Simples/Base). Qualquer
#                  outro "tipo" veio de uma promoção real da API.
TIPOS_SEM_PROMOCAO = ('PRECO_DIRETO', 'PRECO_ATUAL')


def melhor_margem(lista):
    """Escolhe, dentro de uma lista de linhas candidatas, a de maior margem."""
    if not lista:
        return None
    return max(lista, key=lambda l: l['margem_real']['margem_percentual'])


def _classificar_buckets(linhas, margem_minima, exigir_ganha_catalogo):
    """Separa as linhas em 4 grupos, cruzando margem (dentro/abaixo do
    mínimo) com origem (promoção real / sem promoção)."""
    candidatas = [l for l in linhas if l['ganha_catalogo']] if exigir_ganha_catalogo else linhas

    dentro = [l for l in candidatas if l['margem_real']['margem_percentual'] >= margem_minima]
    abaixo = [l for l in candidatas if l['margem_real']['margem_percentual'] < margem_minima]

    eh_sem_promocao = lambda l: l['tipo'] in TIPOS_SEM_PROMOCAO

    return {
        'com_promocao_dentro': [l for l in dentro if not eh_sem_promocao(l)],
        'sem_promocao_dentro': [l for l in dentro if eh_sem_promocao(l)],
        'com_promocao_abaixo': [l for l in abaixo if not eh_sem_promocao(l)],
        'sem_promocao_abaixo': [l for l in abaixo if eh_sem_promocao(l)],
    }


def recomendar_precificacao(linhas, margem_minima, comportamento='padrao', exigir_ganha_catalogo=True):
    """Aplica 1 dos 3 comportamentos sobre as linhas já calculadas.
    margem_minima é sempre passada pelo chamador — vem da configuração
    real do tipo de anúncio (ConfiguracaoTipoAnuncioMercadoLivre),
    nunca mais uma constante fixa."""
    buckets = _classificar_buckets(linhas, margem_minima, exigir_ganha_catalogo)

    if comportamento == 'busca_lucro':
        candidatos = buckets['com_promocao_dentro'] + buckets['sem_promocao_dentro']
        escolhida = melhor_margem(candidatos)
        return {
            'escolhida': escolhida,
            'bucket_nome': 'Maior margem possível (dentro do mínimo)' if escolhida else None,
            'exige_aprovacao': False,
        }

    if exigir_ganha_catalogo:
        ordem = [
            ('com_promocao_dentro', 'Ganha catálogo, dentro da margem, com promoção'),
            ('sem_promocao_dentro', 'Ganha catálogo, dentro da margem, sem promoção'),
            ('com_promocao_abaixo', 'Ganha catálogo, abaixo da margem, com promoção'),
            ('sem_promocao_abaixo', 'Ganha catálogo, abaixo da margem, sem promoção'),
        ]
    else:
        ordem = [
            ('com_promocao_dentro', 'Dentro da margem, com promoção'),
            ('sem_promocao_dentro', 'Dentro da margem, sem promoção'),
            ('com_promocao_abaixo', 'Abaixo da margem, com promoção'),
            ('sem_promocao_abaixo', 'Abaixo da margem, sem promoção'),
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