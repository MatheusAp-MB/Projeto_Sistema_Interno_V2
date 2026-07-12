# * [RESUMO] → Calcula em lote a recomendação de precificação (os 3
#              comportamentos) pra TODAS as variações, salvando em
#              RecomendacaoPrecificacao. Roda dentro do popular_banco,
#              por ÚLTIMO — depende de Promoções, Qualidade, Competição
#              e Configuração de Tipo de Anúncio já estarem no banco.
#              Nunca calculado ao vivo por nenhuma tela depois disso.

from mercado_livre.models import VariacaoAnuncioMercadoLivre, RecomendacaoPrecificacao
from mercado_livre.funcoes_auxiliares.montar_linhas_precificacao import montar_linhas_candidatas
from mercado_livre.funcoes_auxiliares.recomendacao_precificacao import recomendar_precificacao, COMPORTAMENTOS


def calcular_recomendacoes_precificacao(stdout, style):
    stdout.write('[RECOMENDAÇÃO PRECIFICAÇÃO] Calculando os 3 comportamentos por variação...')

    variacoes = (
        VariacaoAnuncioMercadoLivre.objects
        .exclude(produto__isnull=True)
        .exclude(anuncio__tipo_de_anuncio__isnull=True)
        .exclude(anuncio__eh_fossil_migracao=True)
        .select_related('anuncio__tipo_de_anuncio', 'anuncio__competicao', 'produto')
        .prefetch_related('promocoes')
    )

    total_variacoes = variacoes.count()
    stdout.write(f'    {total_variacoes} variação(ões) elegível(is)')

    existentes = {
        (r.variacao_id, r.comportamento): r
        for r in RecomendacaoPrecificacao.objects.all()
    }

    para_criar = []
    para_atualizar = []
    sem_calculo = 0

    for variacao in variacoes:
        linhas, eh_catalogo, margem_minima, margem_atual, config_tipo = montar_linhas_candidatas(variacao)

        if margem_minima is None:
            sem_calculo += 1
            continue

        for comportamento in COMPORTAMENTOS:
            resultado = recomendar_precificacao(
                linhas, margem_minima, comportamento=comportamento, exigir_ganha_catalogo=eh_catalogo,
            )
            escolhida = resultado['escolhida']

            dados = dict(
                tem_escolha=escolhida is not None,
                cenario_nome=escolhida['nome'] if escolhida else None,
                cenario_tipo=escolhida['tipo'] if escolhida else None,
                preco_recomendado=escolhida['preco_promocional'] if escolhida else None,
                margem_recomendada=escolhida['margem_real']['margem_percentual'] if escolhida else None,
                bucket_nome=resultado['bucket_nome'],
                exige_aprovacao=resultado['exige_aprovacao'],
            )

            chave = (variacao.id, comportamento)
            existente = existentes.get(chave)
            if existente:
                for campo, valor in dados.items():
                    setattr(existente, campo, valor)
                para_atualizar.append(existente)
            else:
                nova = RecomendacaoPrecificacao(variacao=variacao, comportamento=comportamento, **dados)
                para_criar.append(nova)
                existentes[chave] = nova

    campos = [
        'tem_escolha', 'cenario_nome', 'cenario_tipo',
        'preco_recomendado', 'margem_recomendada', 'bucket_nome', 'exige_aprovacao',
    ]

    if para_criar:
        RecomendacaoPrecificacao.objects.bulk_create(para_criar, batch_size=1000)
    if para_atualizar:
        RecomendacaoPrecificacao.objects.bulk_update(para_atualizar, campos, batch_size=1000)

    stdout.write(style.SUCCESS(
        f'[RECOMENDAÇÃO PRECIFICAÇÃO] Concluído!\n'
        f'    Recomendações criadas: {len(para_criar)}\n'
        f'    Recomendações atualizadas: {len(para_atualizar)}\n'
        f'    Sem cálculo possível (sem produto/config): {sem_calculo}'
    ))