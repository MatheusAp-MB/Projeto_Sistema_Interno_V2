# * [RESUMO] → Calcula em lote a recomendação de precificação (os 3
#              comportamentos) pra TODAS as variações, salvando em
#              RecomendacaoPrecificacao. Roda dentro do popular_banco,
#              por ÚLTIMO — depende de Promoções, Qualidade, Competição
#              e Configuração de Tipo de Anúncio já estarem no banco.
#              Nunca calculado ao vivo por nenhuma tela depois disso.
#
#              Auditoria de otimização (15/07): 2 achados corrigidos —
#              (1) contagem de consultas trocada de
#              len(connection.queries_log) (capado em 9.000 pelo
#              Django — CONFIRMADO batendo exatamente nesse teto em 2
#              rodadas diferentes, escondendo o número real) pra
#              contar_consultas() (sem teto); (2) recomendar_precificacao
#              recebe os buckets JÁ CLASSIFICADOS, calculados 1 vez por
#              variação — antes eram recalculados do zero 3x (1 por
#              comportamento), com linhas/margem_minima/eh_catalogo
#              idênticos nas 3 chamadas (2 de cada 3 eram desperdício).

import time
from decimal import Decimal
from mercado_livre.models import VariacaoAnuncioMercadoLivre, RecomendacaoPrecificacao, FreteML


LIMITE_PERCENTUAL = Decimal('9999.99')


def _percentual_seguro(valor, contexto, avisos):
    """Protege contra margem calculada absurda (achado real: produto
    com preço muito baixo + frete real/embalagem desproporcional pode
    gerar margem% que estoura o campo, ex: -50000%). Nunca deixa 1
    caso extremo quebrar o bulk_create inteiro — vira None (sem dado
    confiável) e é LISTADO pro usuário investigar, mesmo princípio já
    usado com peso_cubado/dimensão de embalagem."""
    if valor is None:
        return None
    if abs(valor) > LIMITE_PERCENTUAL:
        avisos.append(f'{contexto}: margem calculada ({valor:.2f}%) fora da faixa aceitável — ignorada.')
        return None
    return valor
from mercado_livre.funcoes_auxiliares.montar_linhas_precificacao import montar_linhas_candidatas
from mercado_livre.funcoes_auxiliares.recomendacao_precificacao import (
    recomendar_precificacao, classificar_buckets, COMPORTAMENTOS, TIPOS_SEM_PROMOCAO,
)
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.funcoes_auxiliares.contador_consultas import contar_consultas


def calcular_recomendacoes_precificacao(stdout, style):
    stdout.write('[RECOMENDAÇÃO PRECIFICAÇÃO] Calculando os 3 comportamentos por variação...')

    with contar_consultas() as contador:
        inicio_total = time.perf_counter()

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

        # * [EXPLICAÇÃO] → FreteML é pequena (~232 linhas) — carrega TUDO
        #                  em memória 1 vez pro comando inteiro, mesma
        #                  otimização já aplicada na Grade de Precificação.
        #                  Elimina dezenas de milhares de queries repetidas
        #                  (1 por linha candidata × variação).
        from mercado_livre.models import (
            ConfiguracaoMercadoLivre, FaixaArmazenagemMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre,
        )

        frete_todas = list(FreteML.objects.all())
        config_geral = ConfiguracaoMercadoLivre.obter()
        faixas_armazenagem = list(FaixaArmazenagemMercadoLivre.objects.filter(ativo=True).order_by('ordem'))
        configs_por_tipo = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}

        existentes = {
            (r.variacao_id, r.comportamento): r
            for r in RecomendacaoPrecificacao.objects.all()
        }

        para_criar = []
        para_atualizar = []
        para_atualizar_variacoes = []
        sem_calculo = 0
        avisos_margem = []

        inicio_loop = time.perf_counter()
        for indice, variacao in enumerate(variacoes, start=1):
            if indice % 500 == 0 or indice == total_variacoes:
                decorrido = time.perf_counter() - inicio_loop
                stdout.write(f'    ... {indice}/{total_variacoes} variações processadas ({decorrido:.1f}s)')

            linhas, eh_catalogo, margem_minima, margem_atual, config_tipo, margem_original = montar_linhas_candidatas(
                variacao, frete_todas=frete_todas, config_geral=config_geral,
                faixas_armazenagem=faixas_armazenagem, configs_por_tipo=configs_por_tipo,
            )
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
                variacao.margem_atual_vs_original_pp = _percentual_seguro(
                    round(margem_atual['margem_percentual'] - margem_original['margem_percentual'], 2),
                    f'{variacao.anuncio.mlb} (atual vs original)', avisos_margem,
                )
            para_atualizar_variacoes.append(variacao)

            # * [EXPLICAÇÃO] → linhas/margem_minima/eh_catalogo são os
            #                  MESMOS pros 3 comportamentos desta
            #                  variação — classifica os buckets 1 VEZ
            #                  aqui, reaproveita nas 3 chamadas abaixo
            #                  (antes era recalculado do zero 3x).
            buckets = classificar_buckets(linhas, margem_minima, eh_catalogo)

            for comportamento in COMPORTAMENTOS:
                resultado = recomendar_precificacao(
                    linhas, margem_minima, comportamento=comportamento,
                    exigir_ganha_catalogo=eh_catalogo, buckets_precalculados=buckets,
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
                        categoria_estado = Categoria.SUGESTAO_RISCO if risco else Categoria.SEM_OPORTUNIDADE
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
                    margem_recomendada=_percentual_seguro(
                        escolhida['margem_real']['margem_percentual'] if escolhida else None,
                        f'{variacao.anuncio.mlb} ({comportamento})', avisos_margem,
                    ),
                    bucket_nome=resultado['bucket_nome'],
                    exige_aprovacao=resultado['exige_aprovacao'],
                    categoria_estado=categoria_estado,
                    variacao_margem_pp=_percentual_seguro(
                        escolhida['diferenca'] if escolhida else None,
                        f'{variacao.anuncio.mlb} ({comportamento})', avisos_margem,
                    ),
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

        tempo_loop = time.perf_counter() - inicio_loop
        stdout.write(f'  ⏱ Loop de cálculo (todas as variações): {tempo_loop:.1f}s')

        campos = [
            'tem_escolha', 'cenario_nome', 'cenario_tipo',
            'preco_recomendado', 'margem_recomendada', 'bucket_nome', 'exige_aprovacao',
            'categoria_estado', 'variacao_margem_pp',
        ]

        inicio_salvar = time.perf_counter()
        if para_criar:
            RecomendacaoPrecificacao.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)
        if para_atualizar:
            RecomendacaoPrecificacao.objects.bulk_update(para_atualizar, campos, batch_size=BATCH_SIZE_PADRAO)
        if para_atualizar_variacoes:
            VariacaoAnuncioMercadoLivre.objects.bulk_update(
                para_atualizar_variacoes, ['margem_atual_vs_original_pp'], batch_size=BATCH_SIZE_PADRAO
            )
        tempo_salvar = time.perf_counter() - inicio_salvar
        stdout.write(f'  ⏱ Salvar no banco (bulk_create/bulk_update): {tempo_salvar:.1f}s')

        tempo_total = time.perf_counter() - inicio_total

    stdout.write(f'  📊 Consultas ao banco (SQL) no total: {contador["total"]}')

    stdout.write(style.SUCCESS(
        f'[RECOMENDAÇÃO PRECIFICAÇÃO] Concluído em {tempo_total:.1f}s!\n'
        f'    Recomendações criadas: {len(para_criar)}\n'
        f'    Recomendações atualizadas: {len(para_atualizar)}\n'
        f'    Sem cálculo possível (sem produto/config): {sem_calculo}\n'
        f'    Margens fora da faixa aceitável (ignoradas): {len(avisos_margem)}'
    ))

    if avisos_margem:
        stdout.write(style.WARNING('\n[MARGENS CALCULADAS ABSURDAS — VERIFICAR PREÇO/FRETE]'))
        for aviso in avisos_margem[:30]:
            stdout.write(style.WARNING(f'    {aviso}'))
        if len(avisos_margem) > 30:
            stdout.write(style.WARNING(f'    ... e mais {len(avisos_margem) - 30} caso(s).'))