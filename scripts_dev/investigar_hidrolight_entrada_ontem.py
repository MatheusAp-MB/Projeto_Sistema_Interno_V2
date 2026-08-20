# scripts_dev/investigar_hidrolight_entrada_ontem.py

# Função Objetivo: script ISOLADO de investigação (não faz parte do
# pipeline real de sincronização/orquestração) — lê direto o JSON bruto
# já salvo em disco pela última sincronização e isola os produtos cuja
# nota de entrada MAIS RECENTE é de ontem (19/08/2026), candidatos ao
# problema real: marca HIDROLIGHT, empresa MAGAZINE, onde os dados de
# imposto de 1 produto ficaram split entre 2 notas fiscais distintas
# (1 com ICMS correto, outra com PIS/COFINS correto).
#
# Não usa Django, não usa ORM, não chama a API — só lê o arquivo json
# que já está no disco (o mesmo que o orquestrador real usa, via
# arquivos_retorno_api.NOME_ARQUIVO_BRUTO). Pensado pra "pensar isolado
# do sistema real", conforme pedido, antes de decidir qualquer mudança
# na lógica de seleção/merge de verdade.
#
# Uso (a partir da raiz do projeto):
#   poetry run python scripts_dev/investigar_hidrolight_entrada_ontem.py
#   poetry run python scripts_dev/investigar_hidrolight_entrada_ontem.py --empresa=magazine --data=2026-08-19
#   poetry run python scripts_dev/investigar_hidrolight_entrada_ontem.py --caminho=/caminho/manual/XML_Manifesto_NF_Bruto.json

import argparse
import json
import os

CAMPOS_FISCAIS = (
    'CST PIS', 'Base Calculo PIS', 'Aliquota PIS', 'Valor PIS',
    'CST ICMS', 'Base Calculo ICMS', 'Aliquota ICMS', 'Valor ICMS',
    'CST ICMS Cadastro', 'Base Calculo ICMS ST', 'Valor ICMS ST',
    'CST COFINS', 'Base Calculo COFINS', 'Aliquota COFINS', 'Valor COFINS',
    'CST IPI', 'Base Calculo IPI', 'Aliquota IPI', 'Valor IPI',
)


def montar_caminho_padrao(empresa: str) -> str:
    # Mesma estrutura de pasta usada por
    # integracao_sysemp/servicos/arquivos_retorno_api.py — reproduzida
    # aqui de propósito, sem importar o módulo real, pra manter este
    # script isolado (sem depender de Django/settings pra rodar).
    return os.path.join(
        'integracao_sysemp', 'retorno_api', 'dados_impostos_xml_entrada',
        empresa.lower(), 'XML_Manifesto_NF_Bruto.json',
    )


def carregar_notas(caminho: str) -> list:
    with open(caminho, encoding='utf-8') as arquivo:
        dados = json.load(arquivo)
    return dados['retorno'] if isinstance(dados, dict) and 'retorno' in dados else dados


def campo_tem_valor_relevante(nota: dict, campo: str) -> bool:
    valor = nota.get(campo)
    if valor in (None, ''):
        return False
    try:
        return float(valor) != 0.0
    except (TypeError, ValueError):
        return True  # campo não numérico (ex: CST) presente e não vazio


def resumo_fiscal_da_nota(nota: dict) -> str:
    partes = []
    for grupo, campos in (
        ('PIS', ('CST PIS', 'Valor PIS')),
        ('ICMS', ('CST ICMS', 'Valor ICMS')),
        ('ICMS ST', ('Valor ICMS ST',)),
        ('COFINS', ('CST COFINS', 'Valor COFINS')),
        ('IPI', ('CST IPI', 'Valor IPI')),
    ):
        tem_algo = any(campo_tem_valor_relevante(nota, campo) for campo in campos)
        marcador = '✓ preenchido' if tem_algo else '— zerado/vazio'
        valores = ' '.join(f'{campo}={nota.get(campo)!r}' for campo in campos)
        partes.append(f'    {grupo}: {marcador} ({valores})')
    return '\n'.join(partes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--empresa', default='magazine')
    parser.add_argument('--data', default='2026-08-19', help='formato AAAA-MM-DD')
    parser.add_argument('--caminho', default=None, help='caminho manual pro json bruto, se quiser pular o padrão')
    args = parser.parse_args()

    caminho = args.caminho or montar_caminho_padrao(args.empresa)
    if not os.path.exists(caminho):
        print(f'Arquivo não encontrado: {caminho}')
        print('Rode a sincronização real antes (sincronizar_impostos_entrada --empresa=... [--forcar]), '
              'ou passe --caminho apontando pro json bruto certo.')
        return

    notas = carregar_notas(caminho)
    print(f'Total de notas no bruto ({caminho}): {len(notas)}')

    # Filtro direto por nota — só entra quem tem Entrada NF exatamente
    # igual à data pedida. Nada de olhar histórico do produto aqui;
    # isso é outro passo, separado.
    notas_do_dia = [nota for nota in notas if (nota.get('Entrada NF') or '') == args.data]
    print(f'Notas com Entrada NF = {args.data}: {len(notas_do_dia)}')

    por_produto = {}
    for nota in notas_do_dia:
        ean = nota.get('Código Barras')
        por_produto.setdefault(ean, []).append(nota)

    print(f'Produtos distintos entre essas notas: {len(por_produto)}')
    print()

    for ean, notas_do_produto in por_produto.items():
        notas_ordenadas = sorted(notas_do_produto, key=lambda n: (n.get('NR NF') or ''))
        fornecedores = {n.get('Fornecedor') for n in notas_do_produto}
        produto_nome = notas_do_produto[0].get('Produto')
        print(f'=== EAN {ean} — {produto_nome} ===')
        print(f'    Fornecedor(es): {", ".join(str(f) for f in fornecedores)}')
        print(f'    Notas com entrada em {args.data}: {len(notas_ordenadas)}')
        for nota in notas_ordenadas:
            print(
                f"  -- NF {nota.get('NR NF')} | Item {nota.get('Item')} | "
                f"Entrada NF {nota.get('Entrada NF')} | Emissão {nota.get('Emissão')} | "
                f"CFOP Cadastro {nota.get('CFOP Cadastro')} | CFOP XML {nota.get('CFOP XML')}"
            )
            print(resumo_fiscal_da_nota(nota))
        print()


if __name__ == '__main__':
    main()