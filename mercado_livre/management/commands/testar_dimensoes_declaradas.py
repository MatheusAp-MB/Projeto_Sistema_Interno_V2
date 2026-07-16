# * [RESUMO] → COMANDO DE TESTE, ISOLADO — não faz parte do
#              popular_banco ainda. Lê o mesmo detalhes_mlbs.json já
#              usado pelas outras etapas, extrai as dimensões/peso
#              DECLARADOS pelo vendedor no ML (atributos
#              SELLER_PACKAGE_*, ~85,6% de preenchimento — fallback
#              pro atributo legado WEIGHT quando ausente), calcula o
#              peso volumétrico (mesma fórmula do peso_cubado do ERP:
#              altura×largura×comprimento÷6000, só que por MLB REAL,
#              não por produto), pega o maior entre físico e
#              volumétrico, busca a faixa de frete certa (peso + preço
#              atual real da variação) e grava em frete_real. No
#              final, monta uma tabela comparando o frete REAL (por
#              MLB, dimensão declarada) com o frete esperado a partir
#              do PRODUTO (dimensão do ERP) — pra comparação manual
#              com o Mercado Livre.

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from django.core.management.base import BaseCommand
from django.utils import timezone
from tabulate import tabulate

CAMINHO_DETALHES_MLBS = Path('Arquivos_API/detalhes_mlbs.json')


def _parsear_numero(texto):
    """'19 cm' -> Decimal('19'), '550 g' -> Decimal('550'). None se
    vazio/inválido — nunca derruba o comando por 1 registro ruim."""
    if not texto:
        return None
    try:
        primeira_parte = str(texto).strip().split()[0]
        return Decimal(primeira_parte.replace(',', '.'))
    except (InvalidOperation, IndexError, ValueError):
        return None


def _buscar_frete_por_peso_e_preco(peso, preco, frete_todas):
    for faixa in frete_todas:
        peso_ok = faixa.peso_min <= peso and (faixa.peso_max is None or faixa.peso_max >= peso)
        preco_ok = faixa.preco_min <= preco and (faixa.preco_max is None or faixa.preco_max >= preco)
        if peso_ok and preco_ok:
            return faixa.valor
    return None


class Command(BaseCommand):
    help = (
        'TESTE — calcula frete_real a partir das dimensões declaradas pelo '
        'vendedor no ML (atributos SELLER_PACKAGE_*), e compara com o frete '
        'esperado pelas dimensões do PRODUTO (ERP). Isolado, não roda dentro '
        'do popular_banco ainda.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--exemplos', type=int, default=15,
            help='Quantos MLBs mostrar na tabela final, pra comparação manual (padrão: 15).'
        )

    def handle(self, *args, **options):
        from mercado_livre.models import AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre, FreteML
        from mercado_livre.funcoes_auxiliares.calculo_margem import buscar_frete
        from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO

        if not CAMINHO_DETALHES_MLBS.exists():
            self.stdout.write(self.style.WARNING(f'Arquivo {CAMINHO_DETALHES_MLBS} não encontrado.'))
            return

        self.stdout.write(f'Lendo {CAMINHO_DETALHES_MLBS}...')
        with open(CAMINHO_DETALHES_MLBS, encoding='utf-8') as f:
            dados = json.load(f)

        registros = dados.get('registros', [])
        self.stdout.write(f'    {len(registros)} registros no JSON')

        anuncios_por_mlb = {
            a.mlb: a for a in AnuncioMercadoLivre.objects.prefetch_related('variacoes__produto').all()
        }
        frete_todas = list(FreteML.objects.all())

        variacoes_para_atualizar = []
        sem_anuncio = 0
        sem_variacao = 0
        sem_dimensao = 0
        com_dimensao_completa = 0
        com_so_peso_legado = 0
        linhas_tabela = []
        limite_exemplos = options['exemplos']

        for reg in registros:
            mlb = reg.get('mlb')
            anuncio = anuncios_por_mlb.get(mlb)
            if not anuncio:
                sem_anuncio += 1
                continue

            variacao_id = str(reg.get('variacao_id') or mlb)
            variacao = next((v for v in anuncio.variacoes.all() if v.variacao_id == variacao_id), None)
            if not variacao:
                sem_variacao += 1
                continue

            altura = _parsear_numero(reg.get('attr_seller_package_height'))
            largura = _parsear_numero(reg.get('attr_seller_package_width'))
            comprimento = _parsear_numero(reg.get('attr_seller_package_length'))
            peso_g = _parsear_numero(reg.get('attr_seller_package_weight'))
            peso_declarado_kg = (peso_g / 1000) if peso_g is not None else None

            if altura is None and largura is None and comprimento is None and peso_declarado_kg is None:
                # * fallback pro campo legado — só peso, sem dimensão
                peso_legado_g = _parsear_numero(reg.get('attr_weight'))
                if peso_legado_g is not None:
                    peso_declarado_kg = peso_legado_g / 1000
                    com_so_peso_legado += 1
                else:
                    sem_dimensao += 1
                    continue
            else:
                com_dimensao_completa += 1

            variacao.altura_declarada_cm = altura
            variacao.largura_declarada_cm = largura
            variacao.comprimento_declarado_cm = comprimento
            variacao.peso_declarado_kg = peso_declarado_kg

            peso_volumetrico = None
            if altura is not None and largura is not None and comprimento is not None:
                peso_volumetrico = (altura * largura * comprimento) / Decimal('6000')

            candidatos_peso = [p for p in (peso_declarado_kg, peso_volumetrico) if p is not None]
            peso_real = max(candidatos_peso) if candidatos_peso else None

            frete_calculado = None
            if peso_real is not None and variacao.preco_atual:
                frete_calculado = _buscar_frete_por_peso_e_preco(peso_real, variacao.preco_atual, frete_todas)

            variacao.frete_real = frete_calculado
            variacao.frete_real_atualizado_em = timezone.now() if frete_calculado is not None else None

            variacoes_para_atualizar.append(variacao)

            if len(linhas_tabela) < limite_exemplos and frete_calculado is not None and variacao.produto:
                produto = variacao.produto
                # * [EXPLICAÇÃO] → buscar_frete já existente — reaproveita
                #                  a mesma regra (maior entre peso/
                #                  peso_cubado do PRODUTO) que a Grade
                #                  de Precificação usa hoje como fallback.
                frete_produto = buscar_frete(produto, variacao.preco_atual)

                dimensoes_reais = f'{altura}×{largura}×{comprimento} cm\n{peso_declarado_kg} kg'
                dimensoes_produto = f'{produto.altura}×{produto.largura}×{produto.profundidade} cm\n{produto.peso} kg (cubado: {produto.peso_cubado})'

                diferenca = None
                if frete_produto is not None:
                    diferenca = frete_calculado - frete_produto

                linhas_tabela.append([
                    mlb,
                    produto.sku,
                    dimensoes_reais,
                    f'R$ {frete_calculado:.2f}',
                    dimensoes_produto,
                    f'R$ {frete_produto:.2f}' if frete_produto is not None else '—',
                    f'R$ {diferenca:+.2f}' if diferenca is not None else '—',
                ])

        if variacoes_para_atualizar:
            VariacaoAnuncioMercadoLivre.objects.bulk_update(
                variacoes_para_atualizar,
                ['altura_declarada_cm', 'largura_declarada_cm', 'comprimento_declarado_cm',
                 'peso_declarado_kg', 'frete_real', 'frete_real_atualizado_em'],
                batch_size=BATCH_SIZE_PADRAO,
            )

        self.stdout.write(self.style.SUCCESS(
            f'Concluído!\n'
            f'    Variações atualizadas: {len(variacoes_para_atualizar)}\n'
            f'    Com dimensão completa (4 campos): {com_dimensao_completa}\n'
            f'    Só peso legado (WEIGHT, sem dimensão): {com_so_peso_legado}\n'
            f'    Sem nenhum dado declarado: {sem_dimensao}\n'
            f'    Sem anúncio correspondente: {sem_anuncio}\n'
            f'    Sem variação correspondente: {sem_variacao}'
        ))

        self.stdout.write('\n--- COMPARAÇÃO: FRETE "REAL" (MLB) vs FRETE "PRODUTO" (ERP) ---\n')
        self.stdout.write(tabulate(
            linhas_tabela,
            headers=['MLB', 'SKU', 'Dimensões "Reais"', 'Frete "Real"', 'Dimensões "Produto"', 'Frete "Produto"', 'Diferença'],
            tablefmt='grid',
        ))