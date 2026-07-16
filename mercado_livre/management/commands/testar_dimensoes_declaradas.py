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
#              atual real da variação) e grava em frete_real.
#
#              Relatório final: compara, pra TODO o catálogo (não só
#              amostra), o frete "Real" (MLB, dimensão declarada) com
#              o frete "Produto" (ERP) — quantos batem, quantos o ML
#              cobra mais, quantos cobra menos, e as 3 maiores
#              diferenças de cada lado.

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
        'vendedor no ML, e compara com o frete esperado pelas dimensões do '
        'PRODUTO (ERP) — relatório agregado pro catálogo inteiro.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--top', type=int, default=3,
            help='Quantas maiores diferenças mostrar em cada categoria (padrão: 3).'
        )

    def handle(self, *args, **options):
        from mercado_livre.models import AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre, FreteML
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

        # * [EXPLICAÇÃO] → 1 registro por variação com AMBOS os fretes
        #                  calculáveis (real e produto) — usado pro
        #                  relatório agregado do catálogo inteiro.
        comparacoes = []

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

            frete_real = None
            if peso_real is not None and variacao.preco_atual:
                frete_real = _buscar_frete_por_peso_e_preco(peso_real, variacao.preco_atual, frete_todas)

            variacao.frete_real = frete_real
            variacao.frete_real_atualizado_em = timezone.now() if frete_real is not None else None
            variacoes_para_atualizar.append(variacao)

            # * [EXPLICAÇÃO] → Frete "Produto" — mesma regra de sempre
            #                  (maior entre peso físico e peso_cubado
            #                  do PRODUTO, já corrigido pra cm),
            #                  calculado em memória (frete_todas já
            #                  carregado), sem query nova por item.
            produto = variacao.produto
            if produto and frete_real is not None and variacao.preco_atual:
                peso_produto = max(produto.peso or Decimal('0'), produto.peso_cubado or Decimal('0'))
                frete_produto = _buscar_frete_por_peso_e_preco(peso_produto, variacao.preco_atual, frete_todas)
                if frete_produto is not None:
                    comparacoes.append({
                        'mlb': mlb,
                        'sku': produto.sku,
                        'dimensoes_reais': f'{altura}×{largura}×{comprimento} cm, {peso_declarado_kg} kg',
                        'dimensoes_produto': f'{produto.altura}×{produto.largura}×{produto.profundidade} cm, {peso_produto} kg',
                        'frete_real': frete_real,
                        'frete_produto': frete_produto,
                        'diferenca': frete_real - frete_produto,
                    })

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
            f'    Sem variação correspondente: {sem_variacao}\n'
            f'    Comparáveis (frete Real E Produto disponíveis): {len(comparacoes)}'
        ))

        maiores = [c for c in comparacoes if c['diferenca'] > 0]
        iguais = [c for c in comparacoes if c['diferenca'] == 0]
        menores = [c for c in comparacoes if c['diferenca'] < 0]

        top = options['top']
        maiores_ordenados = sorted(maiores, key=lambda c: c['diferenca'], reverse=True)[:top]
        menores_ordenados = sorted(menores, key=lambda c: c['diferenca'])[:top]

        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS(
            f'RELATÓRIO — Frete "Real" (MLB) vs Frete "Produto" (ERP)\n'
            f'    ML cobra MAIS que o esperado:  {len(maiores)}\n'
            f'    Preços IGUAIS:                 {len(iguais)}\n'
            f'    ML cobra MENOS que o esperado: {len(menores)}'
        ))
        self.stdout.write('=' * 70)

        def montar_linhas(lista):
            return [
                [c['mlb'], c['sku'], c['dimensoes_reais'], f"R$ {c['frete_real']:.2f}",
                 c['dimensoes_produto'], f"R$ {c['frete_produto']:.2f}", f"R$ {c['diferenca']:+.2f}"]
                for c in lista
            ]

        colunas = ['MLB', 'SKU', 'Dimensões "Reais"', 'Frete "Real"', 'Dimensões "Produto"', 'Frete "Produto"', 'Diferença']

        self.stdout.write(f'\n--- TOP {top} — ML COBRA MAIS QUE O ESPERADO ---\n')
        if maiores_ordenados:
            self.stdout.write(tabulate(montar_linhas(maiores_ordenados), headers=colunas, tablefmt='grid'))
        else:
            self.stdout.write('(nenhum caso)')

        self.stdout.write(f'\n--- TOP {top} — ML COBRA MENOS QUE O ESPERADO ---\n')
        if menores_ordenados:
            self.stdout.write(tabulate(montar_linhas(menores_ordenados), headers=colunas, tablefmt='grid'))
        else:
            self.stdout.write('(nenhum caso)')