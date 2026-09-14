#!/usr/bin/env python3
# dividir_tests_impostos.py
#
# Roda a partir da RAIZ do repo (Projeto_Sistema_Interno_V2), onde este
# script foi salvo.
#
# Passo 4 (último) da reorganização entrada/saida do app `impostos` (Passo
# 1 = models.py, Passo 2 = funcoes_auxiliares/, Passo 3 = views.py -- ver
# vault, Decisao "App impostos Sera Reorganizado em Entrada e Saida...").
#
# Faz `impostos/tests/` (2 arquivos soltos, os 2 100% entrada) virar
# `impostos/tests/entrada/` -- só move os 2 arquivos e atualiza o
# comentário de caminho na 1ª linha de cada um (mesma convenção de
# cabeçalho já usada no resto do repo). NÃO cria `tests/saida/` --  não
# existe teste de impostos de saída hoje, então essa pasta nasce só
# quando o primeiro for escrito (mesma regra já usada no vault: pasta só
# existe quando tem o 1º item real dentro).
#
# Por que isso é o mais simples dos 4 passos: ninguém no repo importa
# `impostos.tests.<algo>` como módulo (confirmado por grep -- só existe 1
# comentário em `integracao_sysemp/servicos/tests/test_nivel_3__orquestrador.py`
# citando a pasta como texto, não como import, então não quebra). E o
# jeito de RODAR os testes também não muda: `pyproject.toml` não restringe
# `testpaths`, só define `python_files = ["tests.py", "test_*.py"]` --
# pytest descobre recursivamente por padrão, então `pytest impostos/tests/`
# continua achando os 2 arquivos de dentro de `entrada/` sem precisar de
# nenhuma outra configuração.
#
# Por segurança: valida ANTES de escrever que os 2 arquivos reais batem
# com o esperado, e que a 1ª linha de cada um é exatamente o comentário de
# caminho esperado (senão aborta em vez de reescrever às cegas). Roda em
# DRY-RUN por padrão. Passe --apply pra executar de verdade.
#
# Uso:
#   python dividir_tests_impostos.py            (dry-run)
#   python dividir_tests_impostos.py --apply     (executa)
#
# Depois de rodar com --apply:
#   git add -A && git status
#   python manage.py check
#   python manage.py makemigrations --check --dry-run   (não deveria existir migration aqui, mas mantém o hábito de conferir)
#   python -m pytest impostos/tests/ -q   (tem que continuar dando 20 passed, 2 xfailed -- os mesmos números de antes do Passo 4)

import sys
from pathlib import Path

PASTA_TESTS_ANTIGA = Path('impostos/tests')
PASTA_TESTS_ENTRADA = PASTA_TESTS_ANTIGA / 'entrada'

# Classificação confirmada por inspeção manual, 14/09/2026 -- se a pasta
# real tiver um arquivo de teste que não está nesta lista, o script PARA
# sem escrever nada (ver validar_arquivos_encontrados).
ARQUIVOS_ENTRADA = [
    'test_nivel_3__creditos_fiscais_para_precificacao.py',
    'test_nivel_3__impostos_e_custos_xml_entrada_produto.py',
]

CABECALHO_INIT_ENTRADA = '''# impostos/tests/entrada/__init__.py

# Testes de impostos de ENTRADA (Nível 3, banco real). Não existe pasta
# saida/ ainda -- ela nasce só quando o primeiro teste de impostos de
# saída for escrito (Passo 4 da reorganização entrada/saida do app
# impostos, ver Decisão no vault).

'''


def validar_arquivos_encontrados():
    reais = sorted(
        p.name for p in PASTA_TESTS_ANTIGA.glob('*.py') if p.name != '__init__.py'
    )
    esperado = set(ARQUIVOS_ENTRADA)
    encontrado = set(reais)
    faltando = esperado - encontrado
    sobrando = encontrado - esperado
    if faltando or sobrando:
        print('ERRO: impostos/tests/ real não bate com o esperado. Nada foi escrito.')
        if faltando:
            print(f'  Esperava e não achei: {sorted(faltando)}')
        if sobrando:
            print(f'  Achei e não esperava (arquivo novo desde a última conferência): {sorted(sobrando)}')
        print('Me avise com o conteúdo atual da pasta antes de tentar de novo.')
        sys.exit(1)


def atualizar_cabecalho(texto, nome_arquivo):
    """Só a 1ª linha do arquivo (comentário de caminho) muda. Confirma que
    a linha é EXATAMENTE o texto esperado antes de trocar -- se não for,
    aborta em vez de reescrever um arquivo que não é o que eu pensava."""
    linha_esperada = f'# impostos/tests/{nome_arquivo}\n'
    linhas = texto.splitlines(keepends=True)
    primeira = linhas[0] if linhas else None
    if primeira != linha_esperada:
        raise RuntimeError(
            f'{nome_arquivo}: 1ª linha não é o comentário de caminho esperado '
            f'({linha_esperada!r}) -- achei {primeira!r}. Abortando, nada foi escrito.'
        )
    linhas[0] = f'# impostos/tests/entrada/{nome_arquivo}\n'
    return ''.join(linhas)


def main():
    aplicar = '--apply' in sys.argv

    if not PASTA_TESTS_ANTIGA.exists():
        print(f'ERRO: não encontrei {PASTA_TESTS_ANTIGA} -- rode este script na raiz do repo.')
        sys.exit(1)

    if PASTA_TESTS_ENTRADA.exists():
        print(f'ERRO: {PASTA_TESTS_ENTRADA} já existe -- apague ou renomeie antes de rodar de novo.')
        sys.exit(1)

    validar_arquivos_encontrados()

    conteudo_por_arquivo = {}
    for nome in ARQUIVOS_ENTRADA:
        texto_original = (PASTA_TESTS_ANTIGA / nome).read_text(encoding='utf-8')
        conteudo_por_arquivo[nome] = atualizar_cabecalho(texto_original, nome)

    print(f'{"APLICANDO" if aplicar else "DRY-RUN (nada será escrito -- rode com --apply pra executar de verdade)"}')
    print(f'{len(ARQUIVOS_ENTRADA)} arquivo(s) em {PASTA_TESTS_ANTIGA}, todos entrada (nenhum de saída hoje)')
    print()
    print(f'  criaria {PASTA_TESTS_ENTRADA}/__init__.py  (vazio + comentário)')
    for nome in ARQUIVOS_ENTRADA:
        print(f'  moveria {PASTA_TESTS_ANTIGA}/{nome}  ->  {PASTA_TESTS_ENTRADA}/{nome}  (cabeçalho de caminho atualizado)')

    if not aplicar:
        return

    PASTA_TESTS_ENTRADA.mkdir(parents=True, exist_ok=True)
    (PASTA_TESTS_ENTRADA / '__init__.py').write_text(CABECALHO_INIT_ENTRADA, encoding='utf-8')

    for nome in ARQUIVOS_ENTRADA:
        (PASTA_TESTS_ENTRADA / nome).write_text(conteudo_por_arquivo[nome], encoding='utf-8')
        (PASTA_TESTS_ANTIGA / nome).unlink()

    print()
    print('Feito. Próximos passos:')
    print('  git add -A && git status')
    print('  python manage.py check')
    print('  python manage.py makemigrations --check --dry-run')
    print('  python -m pytest impostos/tests/ -q   (tem que continuar dando 20 passed, 2 xfailed)')


if __name__ == '__main__':
    main()