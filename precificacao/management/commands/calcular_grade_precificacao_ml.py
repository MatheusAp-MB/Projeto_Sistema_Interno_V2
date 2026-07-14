# * [RESUMO] → Comando standalone (roda só, sem popular_banco ainda) —
#              calcula a Grade de Precificação ML pra TODOS os
#              produtos: 4 margens × 4 combinações-base (FULL/Coleta ×
#              Catálogo/Não) para o Clássico via Goal Seek de verdade;
#              Premium é DERIVADO do Clássico (markup de preço, nunca
#              busca margem própria — regra documentada em
#              acrescimo_preco). Sem signal, sem recálculo automático —
#              só roda quando você mandar.

import time
from decimal import Decimal
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Calcula a Grade de Precificação ML pra todos os produtos (Goal Seek)'

    def handle(self, *args, **options):
        from produtos.models import Produto
        from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML
        from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_margem
        from precificacao.funcoes_auxiliares.mercado_livre.montar_parametros_ml import (
            calcular_preco_grade_ml, preparar_fixo_e_faixas,
        )
        from precificacao.funcoes_auxiliares.goal_seek import arredondar_para_90
        from precificacao.models import GradePrecificacaoML

        TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
        TipoLogistico = TipoDeAnuncioMercadoLivre.TipoLogistico
        Margem = GradePrecificacaoML.MargemAlvo

        self.stdout.write('[GRADE DE PRECIFICAÇÃO ML] Calculando...')

        inicio_total = time.perf_counter()

        inicio_carga = time.perf_counter()
        produtos = list(Produto.objects.all())
        self.stdout.write(f'    {len(produtos)} produto(s) encontrados')

        configs = {
            (c.tipo_anuncio, c.tipo_logistico, c.catalogo): c
            for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()
        }

        combinacoes_base = [
            (logistico, catalogo)
            for logistico in [TipoLogistico.FULL, TipoLogistico.COLETA]
            for catalogo in [True, False]
        ]

        existentes = {
            (r.produto_id, r.tipo_anuncio_id, r.margem_alvo): r
            for r in GradePrecificacaoML.objects.all()
        }

        # * [EXPLICAÇÃO] → FreteML é pequena (~232 linhas) — carrega
        #                  TUDO em memória 1 vez pro comando inteiro,
        #                  em vez de 1 query por produto (ou pior, 1
        #                  por combinação). Elimina milhares de queries
        #                  pequenas repetidas.
        frete_todas = list(FreteML.objects.all())

        tempo_carga = time.perf_counter() - inicio_carga
        self.stdout.write(f'  ⏱ Carregar produtos/config/existentes/frete: {tempo_carga:.1f}s')

        para_criar = []
        para_atualizar = []
        erros = []
        sem_calculo = 0

        inicio_calculo = time.perf_counter()
        tempo_goal_seek_classico = 0.0
        tempo_derivar_premium = 0.0
        qtd_calculos_classico = 0
        total_produtos = len(produtos)

        for indice_produto, produto in enumerate(produtos, start=1):
            if indice_produto % 200 == 0 or indice_produto == total_produtos:
                decorrido = time.perf_counter() - inicio_calculo
                self.stdout.write(f'    ... {indice_produto}/{total_produtos} produtos processados ({decorrido:.1f}s)')

            # * [EXPLICAÇÃO] → FIXO e faixas de frete NÃO mudam entre
            #                  as 14 combinações desse produto —
            #                  calculado 1 vez só, aqui fora do loop de
            #                  combinações/margens.
            fixo_produto, faixas_produto = preparar_fixo_e_faixas(produto, frete_todas)

            # * [EXPLICAÇÃO] → (taxa, margem) que já deu um resultado
            #                  nesse produto não precisa rodar o Goal
            #                  Seek de novo — resultado é o mesmo,
            #                  distribuído pra todas as combinações que
            #                  compartilham o mesmo par. Cache reiniciado
            #                  a cada produto (taxa muda por produto,
            #                  via ICMS/PIS individuais).
            cache_goal_seek = {}

            for logistico, catalogo in combinacoes_base:
                config_classico = configs.get((TipoAnuncio.CLASSICO, logistico, catalogo))
                config_premium = configs.get((TipoAnuncio.PREMIUM, logistico, catalogo))
                if not config_classico or not config_premium:
                    continue

                margens = [
                    (Margem.MINIMA, config_classico.margem_minima),
                    (Margem.PADRAO, config_classico.margem_padrao),
                    (Margem.MAXIMA, config_classico.margem_maxima),
                ]
                if catalogo:
                    margens.append((Margem.COMPETICAO, config_classico.margem_competicao))

                for margem_chave, margem_valor in margens:
                    try:
                        taxa_percentual = (
                            (config_classico.comissao / 100)
                            + (produto.icms_saida_media or Decimal('0')) / 100
                            + (produto.pis_cofins or Decimal('0')) / 100
                        )
                        chave_cache = (taxa_percentual, margem_valor)

                        t0 = time.perf_counter()
                        if chave_cache in cache_goal_seek:
                            resultado_classico = cache_goal_seek[chave_cache]
                        else:
                            resultado_classico = calcular_preco_grade_ml(
                                produto, config_classico, margem_valor, fixo_produto, faixas_produto
                            )
                            cache_goal_seek[chave_cache] = resultado_classico
                        tempo_goal_seek_classico += time.perf_counter() - t0
                        qtd_calculos_classico += 1

                        if resultado_classico is None:
                            sem_calculo += 1
                            continue

                        preco_classico = resultado_classico['preco_calculado']
                        margem_classico_obtida = resultado_classico['margem_percentual_obtida']

                        # * [EXPLICAÇÃO] → Premium NUNCA roda Goal Seek
                        #                  próprio — é sempre markup em
                        #                  cima do preço do Clássico já
                        #                  calculado, arredondado pra 90
                        #                  de novo, e a margem só é
                        #                  RECALCULADA pra frente (não é
                        #                  uma meta, é o resultado real).
                        t0 = time.perf_counter()
                        preco_premium_exato = preco_classico * (1 + config_premium.acrescimo_preco / 100)
                        preco_premium = arredondar_para_90(preco_premium_exato)

                        margem_premium_resultado = calcular_margem(
                            produto, preco_premium, config_tipo=config_premium,
                            fixo=fixo_produto, faixas_frete=faixas_produto,
                        )
                        margem_premium_obtida = (
                            margem_premium_resultado['margem_percentual'] if margem_premium_resultado else None
                        )
                        tempo_derivar_premium += time.perf_counter() - t0

                        linhas_a_salvar = [
                            (config_classico, preco_classico, margem_classico_obtida),
                            (config_premium, preco_premium, margem_premium_obtida),
                        ]

                        for config_tipo, preco, margem_obtida in linhas_a_salvar:
                            if margem_obtida is None:
                                sem_calculo += 1
                                continue

                            chave = (produto.id, config_tipo.id, margem_chave)
                            dados = dict(preco_calculado=preco, margem_percentual_obtida=margem_obtida)
                            existente = existentes.get(chave)
                            if existente:
                                for campo, valor in dados.items():
                                    setattr(existente, campo, valor)
                                para_atualizar.append(existente)
                            else:
                                nova = GradePrecificacaoML(
                                    produto=produto, tipo_anuncio=config_tipo,
                                    margem_alvo=margem_chave, **dados,
                                )
                                para_criar.append(nova)
                                existentes[chave] = nova

                    except AssertionError as e:
                        erros.append(f'{produto} | {margem_chave} | {e}')

        tempo_calculo_total = time.perf_counter() - inicio_calculo
        self.stdout.write(f'  ⏱ Loop de cálculo (Clássico + Premium), total: {tempo_calculo_total:.1f}s')
        self.stdout.write(f'      ↳ Goal Seek Clássico: {tempo_goal_seek_classico:.1f}s ({qtd_calculos_classico} cálculo(s))')
        self.stdout.write(f'      ↳ Derivar Premium: {tempo_derivar_premium:.1f}s')

        inicio_salvar = time.perf_counter()
        campos = ['preco_calculado', 'margem_percentual_obtida']

        if para_criar:
            GradePrecificacaoML.objects.bulk_create(para_criar, batch_size=1000)
        if para_atualizar:
            GradePrecificacaoML.objects.bulk_update(para_atualizar, campos, batch_size=1000)
        tempo_salvar = time.perf_counter() - inicio_salvar
        self.stdout.write(f'  ⏱ Salvar no banco (bulk_create/bulk_update): {tempo_salvar:.1f}s')

        tempo_total = time.perf_counter() - inicio_total

        self.stdout.write(self.style.SUCCESS(
            f'[GRADE DE PRECIFICAÇÃO ML] Concluído em {tempo_total:.1f}s!\n'
            f'    Linhas criadas: {len(para_criar)}\n'
            f'    Linhas atualizadas: {len(para_atualizar)}\n'
            f'    Sem cálculo possível (sem frete/config): {sem_calculo}\n'
            f'    Erros de assert (margem abaixo da meta): {len(erros)}'
        ))

        if erros:
            self.stdout.write(self.style.ERROR('    ATENÇÃO — erros de assert encontrados:'))
            for erro in erros[:20]:
                self.stdout.write(self.style.ERROR(f'      {erro}'))
            if len(erros) > 20:
                self.stdout.write(self.style.ERROR(f'      ... e mais {len(erros) - 20} erro(s)'))