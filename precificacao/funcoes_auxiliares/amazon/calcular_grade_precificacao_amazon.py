import time
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from precificacao.funcoes_auxiliares.amazon.formula_precificacao_amazon import FormulaPrecificacaoAmazon


def _margens():
    return [('minima', 10), ('padrao', 15), ('maxima', 20), ('competicao', 5)]


def _tipos():
    return ['dba', 'fba']


def calcular_grade_precificacao_amazon(stdout, style):
    from django.db import connection
    from produtos.models import Produto
    from amazon.models import ConfiguracaoAmazon
    from precificacao.models import (
        ConfiguracaoOperacional, FaixaArmazenagem, FreteAmazon, TaxaKgAdicionalAmazon,
        GradePrecificacaoAmazon,
    )

    stdout.write('[GRADE AMAZON] Calculando...')
    inicio_total = time.perf_counter()

    connection.force_debug_cursor = True
    connection.queries_log.clear()

    produtos = list(Produto.objects.all())
    stdout.write(f'    {len(produtos)} produto(s) encontrados')

    config_amazon = ConfiguracaoAmazon.obter()
    config_geral = ConfiguracaoOperacional.obter()
    faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))
    fretes_amazon = list(FreteAmazon.objects.all())
    taxas_kg_adicional = list(TaxaKgAdicionalAmazon.objects.all())

    existentes = {(r.produto_id, r.tipo, r.margem): r for r in GradePrecificacaoAmazon.objects.all()}

    para_criar = []
    para_atualizar = []
    erros = []
    sem_calculo = 0

    inicio_calculo = time.perf_counter()
    total_produtos = len(produtos)

    for indice, produto in enumerate(produtos, start=1):
        if indice % 200 == 0 or indice == total_produtos:
            decorrido = time.perf_counter() - inicio_calculo
            stdout.write(f'    ... {indice}/{total_produtos} produtos processados ({decorrido:.1f}s)')

        for tipo in _tipos():
            for margem_chave, margem_valor in _margens():
                try:
                    formula = FormulaPrecificacaoAmazon(
                        produto=produto, config_amazon=config_amazon, config_geral=config_geral,
                        margem_alvo_percentual=margem_valor, tipo=tipo,
                        fretes_amazon=fretes_amazon, taxas_kg_adicional=taxas_kg_adicional,
                        faixas_armazenagem=faixas_armazenagem,
                    ).calcular()
                except AssertionError as e:
                    erros.append(f'{produto} | {tipo} | {margem_chave} | {e}')
                    continue

                if not formula.resolvida:
                    sem_calculo += 1
                    continue

                dados = dict(
                    preco=formula.saida.preco_final,
                    margem_percentual_obtida=formula.saida.margem_percentual_obtida,
                    frete_usado=formula.saida.frete_usado,
                    detalhamento=formula.para_dict_auditoria(),
                )

                chave = (produto.id, tipo, margem_chave)
                existente = existentes.get(chave)
                if existente:
                    for campo, valor in dados.items():
                        setattr(existente, campo, valor)
                    para_atualizar.append(existente)
                else:
                    nova = GradePrecificacaoAmazon(produto=produto, tipo=tipo, margem=margem_chave, **dados)
                    para_criar.append(nova)
                    existentes[chave] = nova

    tempo_calculo_total = time.perf_counter() - inicio_calculo
    stdout.write(f'  ⏱ Loop de cálculo, total: {tempo_calculo_total:.1f}s')

    if para_criar:
        GradePrecificacaoAmazon.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)
    if para_atualizar:
        GradePrecificacaoAmazon.objects.bulk_update(
            para_atualizar, ['preco', 'margem_percentual_obtida', 'frete_usado', 'detalhamento'],
            batch_size=BATCH_SIZE_PADRAO,
        )

    tempo_total = time.perf_counter() - inicio_total

    stdout.write(style.SUCCESS(
        f'[GRADE AMAZON] Concluído em {tempo_total:.1f}s!\n'
        f'    Linhas criadas: {len(para_criar)}\n'
        f'    Linhas atualizadas: {len(para_atualizar)}\n'
        f'    Sem cálculo possível: {sem_calculo}\n'
        f'    Erros de assert: {len(erros)}'
    ))

    if erros:
        stdout.write(style.ERROR('    ATENÇÃO — erros de assert encontrados:'))
        for erro in erros[:20]:
            stdout.write(style.ERROR(f'      {erro}'))

    stdout.write(f'  📊 Consultas ao banco (SQL) no total: {len(connection.queries_log)}')