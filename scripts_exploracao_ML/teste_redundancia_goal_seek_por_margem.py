# scripts_exploracao_ML/teste_redundancia_goal_seek_por_margem.py

# Função Objetivo: Valida se os passos 1-7 de FormulaPrecificacao.calcular() (créditos
# fiscais, custo final, coleta, armazenagem, fixo, taxa%, faixas candidatas) são realmente
# idênticos entre as 4 margens (mínima/padrão/máxima/competição) de um mesmo MLB, e entre
# TODOS os MLBs de um mesmo produto (créditos fiscais + custo final, que são só do produto).
# NUNCA chama resolver_preco() (passo 8) — não faz nenhuma chamada de API, só CPU/banco.
#
# Uso:
#   python scripts_exploracao_ML/teste_redundancia_goal_seek_por_margem.py --empresa magazine

import os
import sys
import django
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from core.empresa import definir_empresa_ativa, EMPRESA_POR_ALIAS_BANCO
from produtos.models import Produto
from mercado_livre.models import (
    ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre,
    FreteML, VariacaoAnuncioMercadoLivre,
)
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from precificacao.funcoes_auxiliares.mercado_livre.formula_precificacao import FormulaPrecificacao

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio


def margens_do_tipo(config):
    return [
        ('minima', config.margem_minima),
        ('padrao', config.margem_padrao),
        ('maxima', config.margem_maxima),
        ('competicao', config.margem_competicao),
    ]


def rodar_ate_faixas(produto, dim, config, config_geral, frete_todas, faixas_armazenagem,
                      margem_valor, variacao):
    f = FormulaPrecificacao(
        produto=produto, dimensoes_efetivas=dim, config_tipo=config,
        config_geral=config_geral, margem_alvo_percentual=margem_valor,
        frete_todas=frete_todas, faixas_armazenagem=faixas_armazenagem,
        variacao=variacao,
    )
    f.obter_creditos_fiscais()
    if f._creditos is None:
        return None
    f.calcular_custo_final()
    f.calcular_coleta()
    f.calcular_armazenagem()
    f.calcular_fixo()
    f.montar_taxa_e_denominador()
    f.filtrar_faixas_frete()
    return {
        'creditos': (f._creditos.icms, f._creditos.ipi, f._creditos.pis, f._creditos.cofins),
        'custo_final': f._custo_final,
        'coleta': f._coleta,
        'armazenagem': f._armazenagem,
        'fixo': f._fixo,
        'taxa_percentual': f._taxa_percentual,
        'faixas': tuple((fx.preco_min, fx.preco_max) for fx in f._faixas_candidatas),
    }


def main():
    parser = argparse.ArgumentParser(
        description='Testa se os passos 1-7 do goal-seek são redundantes entre margens/MLBs.'
    )
    parser.add_argument('--empresa', required=True, choices=list(EMPRESA_POR_ALIAS_BANCO.keys()))
    args = parser.parse_args()

    definir_empresa_ativa(EMPRESA_POR_ALIAS_BANCO[args.empresa])

    configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}
    frete_todas = list(FreteML.objects.all())
    config_geral = ConfiguracaoOperacional.obter()
    faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

    contagem = defaultdict(list)
    produtos_por_chave = {}
    for v in VariacaoAnuncioMercadoLivre.objects.filter(
        produto__isnull=False, anuncio__tipo_de_anuncio__isnull=False
    ).select_related('anuncio__tipo_de_anuncio', 'produto', 'categoria'):
        chave = v.produto.pk
        contagem[chave].append(v)
        produtos_por_chave[chave] = v.produto

    if not contagem:
        print('Nenhum produto com variação/MLB publicado encontrado.')
        return

    chave_produto, variacoes = max(contagem.items(), key=lambda kv: len(kv[1]))
    produto = produtos_por_chave[chave_produto]
    print(f'Produto escolhido: {produto} (pk={chave_produto}) — {len(variacoes)} variação(ões)/MLB(s)')

    grupos = defaultdict(list)
    for v in variacoes:
        grupos[v.anuncio.tipo_de_anuncio.tipo_anuncio].append(v)

    for tipo, vs in grupos.items():
        config = configs.get(tipo)
        if not config:
            continue
        print(f'\n--- Tipo: {tipo} ({len(vs)} MLB(s)) ---')

        for v in vs:
            dim = resolver_dimensoes_efetivas(produto, variacao=v)
            if dim is None:
                print(f'  MLB {v.anuncio.mlb}: sem dimensão, pulando')
                continue

            resultados_por_margem = {}
            for margem_chave, margem_valor in margens_do_tipo(config):
                resultados_por_margem[margem_chave] = rodar_ate_faixas(
                    produto, dim, config, config_geral, frete_todas, faixas_armazenagem,
                    margem_valor, v,
                )

            valores = list(resultados_por_margem.values())
            iguais = all(r == valores[0] for r in valores)
            print(f'  MLB {v.anuncio.mlb}: passos 1-7 iguais nas 4 margens? '
                  f'{"SIM" if iguais else "NAO"}')
            if not iguais:
                for chave, r in resultados_por_margem.items():
                    print(f'    {chave}: {r}')

        creditos_por_mlb = {}
        for v in vs:
            dim = resolver_dimensoes_efetivas(produto, variacao=v)
            if dim is None:
                continue
            r = rodar_ate_faixas(
                produto, dim, config, config_geral, frete_todas, faixas_armazenagem,
                config.margem_padrao, v,
            )
            if r:
                creditos_por_mlb[v.anuncio.mlb] = (r['creditos'], r['custo_final'])

        valores_unicos = set(creditos_por_mlb.values())
        if len(valores_unicos) <= 1:
            print('  Créditos+custo_final iguais entre TODOS os MLBs desse tipo? SIM')
        else:
            print(f'  Créditos+custo_final iguais entre TODOS os MLBs desse tipo? '
                  f'NAO ({len(valores_unicos)} variações diferentes)')


if __name__ == '__main__':
    main()