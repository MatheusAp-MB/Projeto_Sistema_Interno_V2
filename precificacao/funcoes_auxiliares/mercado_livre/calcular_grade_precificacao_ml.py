# * [RESUMO] → Calcula a Grade de Precificação ML pra TODOS os
#              produtos: 4 margens × 2 tipos de anúncio (Clássico e
#              Premium) — os DOIS rodam Goal Seek de verdade agora,
#              cada um com sua própria comissão. Simplificado em
#              27/07: confirmado com o usuário/superior que logística
#              (FULL/Coleta) e catálogo NÃO afetam mais comissão/
#              margem — só Clássico/Premium importa. Premium deixou
#              de ser derivado do Clássico por markup fixo (regra
#              antiga de acrescimo_preco, removida — o markup fixo
#              podia gerar margem abaixo da meta, achado real
#              confirmado com o superior). Sem signal, sem recálculo
#              automático — só roda quando popular_banco (ou o
#              comando standalone) mandar.

import time


def calcular_grade_precificacao_ml(stdout, style):
    from produtos.models import Produto
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML
    from precificacao.funcoes_auxiliares.mercado_livre.montar_parametros_ml import (
        calcular_preco_grade_ml, preparar_fixo_e_faixas,
    )
    from precificacao.models import GradePrecificacaoML

    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
    Margem = GradePrecificacaoML.MargemAlvo

    stdout.write('[GRADE DE PRECIFICAÇÃO ML] Calculando...')

    inicio_total = time.perf_counter()

    inicio_carga = time.perf_counter()
    produtos = list(Produto.objects.all())
    stdout.write(f'    {len(produtos)} produto(s) encontrados')

    configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}

    existentes = {
        (r.produto_id, r.tipo_anuncio_id, r.margem_alvo): r
        for r in GradePrecificacaoML.objects.all()
    }

    frete_todas = list(FreteML.objects.all())

    tempo_carga = time.perf_counter() - inicio_carga
    stdout.write(f'  ⏱ Carregar produtos/config/existentes/frete: {tempo_carga:.1f}s')

    para_criar = []
    para_atualizar = []
    erros = []
    sem_calculo = 0

    inicio_calculo = time.perf_counter()
    tempo_goal_seek = 0.0
    qtd_calculos = 0
    total_produtos = len(produtos)

    for indice_produto, produto in enumerate(produtos, start=1):
        if indice_produto % 200 == 0 or indice_produto == total_produtos:
            decorrido = time.perf_counter() - inicio_calculo
            stdout.write(f'    ... {indice_produto}/{total_produtos} produtos processados ({decorrido:.1f}s)')

        fixo_produto, faixas_produto = preparar_fixo_e_faixas(produto, frete_todas)

        # * [EXPLICAÇÃO] → (taxa, margem) que já deu resultado nesse
        #                  produto não roda de novo — mas agora
        #                  Clássico e Premium têm comissões diferentes,
        #                  então quase nunca compartilham o mesmo par
        #                  (taxa muda com a comissão). Ainda vale manter
        #                  o cache: dentro do MESMO tipo, as 4 margens
        #                  têm taxas idênticas entre si só na parte do
        #                  ICMS/PIS, mas margem sempre muda a chave.
        cache_goal_seek = {}

        for tipo in (TipoAnuncio.CLASSICO, TipoAnuncio.PREMIUM):
            config = configs.get(tipo)
            if not config:
                continue

            margens = [
                (Margem.MINIMA, config.margem_minima),
                (Margem.PADRAO, config.margem_padrao),
                (Margem.MAXIMA, config.margem_maxima),
                (Margem.COMPETICAO, config.margem_competicao),
            ]

            for margem_chave, margem_valor in margens:
                try:
                    chave_cache = (tipo, margem_valor)

                    t0 = time.perf_counter()
                    if chave_cache in cache_goal_seek:
                        resultado = cache_goal_seek[chave_cache]
                    else:
                        resultado = calcular_preco_grade_ml(
                            produto, config, margem_valor, fixo_produto, faixas_produto
                        )
                        cache_goal_seek[chave_cache] = resultado
                    tempo_goal_seek += time.perf_counter() - t0
                    qtd_calculos += 1

                    if resultado is None:
                        sem_calculo += 1
                        continue

                    preco = resultado['preco_calculado']
                    margem_obtida = resultado['margem_percentual_obtida']

                    chave = (produto.id, config.id, margem_chave)
                    dados = dict(preco_calculado=preco, margem_percentual_obtida=margem_obtida)
                    existente = existentes.get(chave)
                    if existente:
                        for campo, valor in dados.items():
                            setattr(existente, campo, valor)
                        para_atualizar.append(existente)
                    else:
                        nova = GradePrecificacaoML(
                            produto=produto, tipo_anuncio=config,
                            margem_alvo=margem_chave, **dados,
                        )
                        para_criar.append(nova)
                        existentes[chave] = nova

                except AssertionError as e:
                    erros.append(f'{produto} | {tipo} | {margem_chave} | {e}')

    tempo_calculo_total = time.perf_counter() - inicio_calculo
    stdout.write(f'  ⏱ Loop de cálculo (Goal Seek Clássico + Premium), total: {tempo_calculo_total:.1f}s')
    stdout.write(f'      ↳ Goal Seek: {tempo_goal_seek:.1f}s ({qtd_calculos} cálculo(s))')

    inicio_salvar = time.perf_counter()
    campos = ['preco_calculado', 'margem_percentual_obtida']

    if para_criar:
        GradePrecificacaoML.objects.bulk_create(para_criar, batch_size=1000)
    if para_atualizar:
        GradePrecificacaoML.objects.bulk_update(para_atualizar, campos, batch_size=1000)
    tempo_salvar = time.perf_counter() - inicio_salvar
    stdout.write(f'  ⏱ Salvar no banco (bulk_create/bulk_update): {tempo_salvar:.1f}s')

    tempo_total = time.perf_counter() - inicio_total

    stdout.write(style.SUCCESS(
        f'[GRADE DE PRECIFICAÇÃO ML] Concluído em {tempo_total:.1f}s!\n'
        f'    Linhas criadas: {len(para_criar)}\n'
        f'    Linhas atualizadas: {len(para_atualizar)}\n'
        f'    Sem cálculo possível (sem frete/config): {sem_calculo}\n'
        f'    Erros de assert (margem abaixo da meta): {len(erros)}'
    ))

    if erros:
        stdout.write(style.ERROR('    ATENÇÃO — erros de assert encontrados:'))
        for erro in erros[:20]:
            stdout.write(style.ERROR(f'      {erro}'))
        if len(erros) > 20:
            stdout.write(style.ERROR(f'      ... e mais {len(erros) - 20} erro(s)'))