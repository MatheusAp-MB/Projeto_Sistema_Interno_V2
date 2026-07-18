# precificacao/funcoes_auxiliares/magalu/calcular_grade_precificacao_magalu.py

# Função Objetivo: Calcula a Grade de Precificação do Magalu (Mínima/Padrão/Máxima/Competição).
# Explicação em detalhe: bem mais simples que a do ML — sem variação/anúncio (Magalu ainda
# não tem esse pipeline), sem cache por assinatura de dimensão (cada produto resolve sua
# própria dimensão 1 vez só, direto do ERP — nunca varia por "MLB", já que não existe MLB
# aqui). 4 margens × N produtos, sem mais nada.

import time
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from precificacao.funcoes_auxiliares.magalu.formula_precificacao_magalu import FormulaPrecificacaoMagalu


# Função Objetivo: Devolve as 4 margens fixas (mesmas do ML, mantidas por padrão).
def _margens():
    return [('minima', 10), ('padrao', 15), ('maxima', 20), ('competicao', 5)]


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def calcular_grade_precificacao_magalu(stdout, style):
    from django.db import connection
    from produtos.models import Produto
    from magalu.models import ConfiguracaoMagalu, FreteMagalu
    from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem, GradePrecificacaoMagalu

    stdout.write('[GRADE MAGALU] Calculando...')
    inicio_total = time.perf_counter()

    connection.force_debug_cursor = True
    connection.queries_log.clear()

    inicio_carga = time.perf_counter()
    produtos = list(Produto.objects.all())
    stdout.write(f'    {len(produtos)} produto(s) encontrados')

    config_magalu = ConfiguracaoMagalu.obter()
    config_geral = ConfiguracaoOperacional.obter()
    frete_todas = list(FreteMagalu.objects.all())
    faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

    existentes = {
        (r.produto_id, r.margem): r
        for r in GradePrecificacaoMagalu.objects.all()
    }

    tempo_carga = time.perf_counter() - inicio_carga
    stdout.write(f'  ⏱ Carregar produtos/config/frete: {tempo_carga:.1f}s')

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

        for margem_chave, margem_valor in _margens():
            try:
                formula = FormulaPrecificacaoMagalu(
                    produto=produto, config_magalu=config_magalu, config_geral=config_geral,
                    margem_alvo_percentual=margem_valor, frete_todas=frete_todas,
                    faixas_armazenagem=faixas_armazenagem,
                ).calcular()
            except AssertionError as e:
                erros.append(f'{produto} | {margem_chave} | {e}')
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

            chave = (produto.id, margem_chave)
            existente = existentes.get(chave)
            if existente:
                for campo, valor in dados.items():
                    setattr(existente, campo, valor)
                para_atualizar.append(existente)
            else:
                nova = GradePrecificacaoMagalu(produto=produto, margem=margem_chave, **dados)
                para_criar.append(nova)
                existentes[chave] = nova

    tempo_calculo_total = time.perf_counter() - inicio_calculo
    stdout.write(f'  ⏱ Loop de cálculo, total: {tempo_calculo_total:.1f}s')

    inicio_salvar = time.perf_counter()
    campos_atualizaveis = ['preco', 'margem_percentual_obtida', 'frete_usado', 'detalhamento']

    if para_criar:
        GradePrecificacaoMagalu.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)
    if para_atualizar:
        GradePrecificacaoMagalu.objects.bulk_update(para_atualizar, campos_atualizaveis, batch_size=BATCH_SIZE_PADRAO)

    tempo_salvar = time.perf_counter() - inicio_salvar
    stdout.write(f'  ⏱ Salvar no banco (bulk_create/bulk_update): {tempo_salvar:.1f}s')

    tempo_total = time.perf_counter() - inicio_total

    stdout.write(style.SUCCESS(
        f'[GRADE MAGALU] Concluído em {tempo_total:.1f}s!\n'
        f'    Linhas criadas: {len(para_criar)}\n'
        f'    Linhas atualizadas: {len(para_atualizar)}\n'
        f'    Sem cálculo possível (meta inatingível/sem faixa de frete): {sem_calculo}\n'
        f'    Erros de assert: {len(erros)}'
    ))

    if erros:
        stdout.write(style.ERROR('    ATENÇÃO — erros de assert encontrados:'))
        for erro in erros[:20]:
            stdout.write(style.ERROR(f'      {erro}'))
        if len(erros) > 20:
            stdout.write(style.ERROR(f'      ... e mais {len(erros) - 20} erro(s)'))

    stdout.write(f'  📊 Consultas ao banco (SQL) no total: {len(connection.queries_log)}')