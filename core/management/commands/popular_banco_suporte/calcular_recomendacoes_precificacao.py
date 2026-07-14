# * [RESUMO] → Calcula em lote a recomendação de precificação (os 3
#              comportamentos) pra TODAS as variações, salvando em
#              RecomendacaoPrecificacao. Roda dentro do popular_banco,
#              por ÚLTIMO — depende de Promoções, Qualidade, Competição
#              e Configuração de Tipo de Anúncio já estarem no banco.
#              Nunca calculado ao vivo por nenhuma tela depois disso.

from mercado_livre.models import VariacaoAnuncioMercadoLivre, RecomendacaoPrecificacao
from mercado_livre.funcoes_auxiliares.montar_linhas_precificacao import montar_linhas_candidatas
from mercado_livre.funcoes_auxiliares.recomendacao_precificacao import recomendar_precificacao, COMPORTAMENTOS, TIPOS_SEM_PROMOCAO

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
    para_atualizar_variacoes = []
    sem_calculo = 0

    for indice, variacao in enumerate(variacoes, start=1):
        if indice % 500 == 0 or indice == total_variacoes:
            stdout.write(f'    ... {indice}/{total_variacoes} variações processadas')

        linhas, eh_catalogo, margem_minima, margem_atual, config_tipo, margem_original = montar_linhas_candidatas(variacao)
        if margem_minima is None:
            sem_calculo += 1
            continue

        promocoes_ativas = [p for p in variacao.promocoes.all() if p.status == 'started']

        # * [EXPLICAÇÃO] → margem_original agora vem PRONTA de
        #                  montar_linhas_candidatas (escopo ORIGINAL,
        #                  nunca com rebate) — não recalcula mais aqui,
        #                  elimina a duplicação que existia antes.
        variacao.margem_atual_vs_original_pp = None
        if margem_atual and margem_original:
            variacao.margem_atual_vs_original_pp = round(
                margem_atual['margem_percentual'] - margem_original['margem_percentual'], 2
            )
        para_atualizar_variacoes.append(variacao)

        for comportamento in COMPORTAMENTOS:
            resultado = recomendar_precificacao(
                linhas, margem_minima, comportamento=comportamento, exigir_ganha_catalogo=eh_catalogo,
            )
            escolhida = resultado['escolhida']

            # * [EXPLICAÇÃO] → 'risco' só pode ser True em Catálogo —
            #                  Simples/Base nunca escolhe algo abaixo da
            #                  margem mínima (recomendar_precificacao já
            #                  garante isso). exige_aprovacao aqui é o
            #                  MESMO campo que já persiste no registro,
            #                  não é recalculado — só é reaproveitado
            #                  pra decidir a categoria.
            risco = bool(escolhida) and resultado['exige_aprovacao'] and eh_catalogo

            Categoria = RecomendacaoPrecificacao.CategoriaEstado

            if len(promocoes_ativas) >= 2:
                categoria_estado = Categoria.CONFLITO_MULTIPLAS_ATIVAS
            elif escolhida:
                if len(promocoes_ativas) == 1:
                    ativa_chave = promocoes_ativas[0].chave_externa
                    # * [EXPLICAÇÃO] → "Mesma chave" OU "diferença real
                    #                  não é positiva" (zero ou negativa)
                    #                  = nada de novo vale a pena — trata
                    #                  como OTIMIZADO/OPERANDO_EM_RISCO,
                    #                  mesmo que a chave seja tecnicamente
                    #                  diferente (ex: sugestão = "Preço
                    #                  Original", que é sempre diferente
                    #                  da chave de qualquer promoção real,
                    #                  mas só é MELHOR se a conta bater).
                    diferenca_real = escolhida.get('diferenca')
                    if escolhida['chave_externa'] == ativa_chave or (diferenca_real is not None and diferenca_real <= 0):
                        # * [EXPLICAÇÃO] → Vencedora É a mesma promoção
                        #                  que já está ativa — nada de
                        #                  novo a fazer. Mas se essa
                        #                  ativa já é arriscada (margem
                        #                  abaixo do mínimo), não é
                        #                  "Otimizado" — é um estado que
                        #                  merece atenção contínua, e é
                        #                  recalculado do zero a cada
                        #                  rodada (se surgir opção
                        #                  segura melhor depois, sai
                        #                  daqui automaticamente).
                        categoria_estado = Categoria.OPERANDO_EM_RISCO if risco else Categoria.OTIMIZADO
                    else:
                        categoria_estado = Categoria.SUGESTAO_RISCO if risco else Categoria.OPORTUNIDADE_TROCA
                elif escolhida['tipo'] in TIPOS_SEM_PROMOCAO:
                    categoria_estado = Categoria.SEM_OPORTUNIDADE
                else:
                    categoria_estado = Categoria.SUGESTAO_RISCO if risco else Categoria.CANDIDATO
            else:
                # * [EXPLICAÇÃO] → Nenhum cenário passou nos filtros (ex:
                #                  Simples/Base sem nenhuma opção dentro
                #                  da margem) — isso é informação real,
                #                  não ausência de informação. É o mesmo
                #                  "nada a fazer com segurança" que
                #                  SEM_OPORTUNIDADE já representa.
                categoria_estado = Categoria.SEM_OPORTUNIDADE

            dados = dict(
                tem_escolha=escolhida is not None,
                cenario_nome=escolhida['nome'] if escolhida else None,
                cenario_tipo=escolhida['tipo'] if escolhida else None,
                preco_recomendado=escolhida['preco_promocional'] if escolhida else None,
                margem_recomendada=escolhida['margem_real']['margem_percentual'] if escolhida else None,
                bucket_nome=resultado['bucket_nome'],
                exige_aprovacao=resultado['exige_aprovacao'],
                categoria_estado=categoria_estado,
                variacao_margem_pp=escolhida['diferenca'] if escolhida else None,
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
        'categoria_estado', 'variacao_margem_pp',
    ]

    if para_criar:
        RecomendacaoPrecificacao.objects.bulk_create(para_criar, batch_size=1000)
    if para_atualizar:
        RecomendacaoPrecificacao.objects.bulk_update(para_atualizar, campos, batch_size=1000)
    if para_atualizar_variacoes:
        VariacaoAnuncioMercadoLivre.objects.bulk_update(
            para_atualizar_variacoes, ['margem_atual_vs_original_pp'], batch_size=1000
        )

    stdout.write(style.SUCCESS(
        f'[RECOMENDAÇÃO PRECIFICAÇÃO] Concluído!\n'
        f'    Recomendações criadas: {len(para_criar)}\n'
        f'    Recomendações atualizadas: {len(para_atualizar)}\n'
        f'    Sem cálculo possível (sem produto/config): {sem_calculo}'
    ))