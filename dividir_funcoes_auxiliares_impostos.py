#!/usr/bin/env python3
# dividir_funcoes_auxiliares_impostos.py
#
# Roda a partir da RAIZ do repo (Projeto_Sistema_Interno_V2), onde este
# script foi salvo.
#
# Passo 2 da reorganização entrada/saida do app `impostos` (Passo 1 foi o
# models.py -- ver vault, Decisao "App impostos Sera Reorganizado em
# Entrada e Saida..."). Faz `impostos/funcoes_auxiliares/` (14 arquivos
# soltos) virar `impostos/funcoes_auxiliares/entrada/` (6 arquivos) +
# `impostos/funcoes_auxiliares/saida/` (8 arquivos), SEM renomear nenhum
# arquivo -- só move.
#
# Diferente do Passo 1 (models.py): aqui o resto do repo importa por
# CAMINHO DE SUBMÓDULO (`from impostos.funcoes_auxiliares.X import Y`), não
# só pelo pacote -- então mover o arquivo por si só quebraria todo mundo
# que importa assim. Por isso este script faz 2 coisas, nesta ordem:
#   1) reescreve toda linha `from impostos.funcoes_auxiliares.X import`
#      pra `from impostos.funcoes_auxiliares.<entrada|saida>.X import`,
#      em TODO arquivo .py do repo (isso inclui os 8 imports internos
#      entre os próprios arquivos de funcoes_auxiliares/, e os ~26 pontos
#      espalhados pelo resto do repo -- levantamento feito por grep antes
#      de escrever este script, nenhum é cross-domain: todo import interno
#      é entrada->entrada ou saida->saida, nunca cruzado);
#   2) só DEPOIS move fisicamente os 14 arquivos (com o conteúdo já
#      corrigido) pra dentro de entrada/ ou saida/.
#
# Por segurança: valida ANTES de escrever que (a) os 14 arquivos encontrados
# em funcoes_auxiliares/ batem exatamente com a classificação esperada, e
# (b) todo `from impostos.funcoes_auxiliares.<algo>` achado no repo
# referencia um desses 14 nomes conhecidos -- se achar qualquer coisa
# inesperada dos 2 lados, o script para e NADA é escrito. Roda em
# DRY-RUN por padrão. Passe --apply pra executar de verdade.
#
# Uso:
#   python dividir_funcoes_auxiliares_impostos.py            (dry-run)
#   python dividir_funcoes_auxiliares_impostos.py --apply     (executa)
#
# Depois de rodar com --apply:
#   git add -A && git status                        (conferir o que mudou)
#   python manage.py check                            (Django ainda sobe)
#   python manage.py makemigrations --check --dry-run (tem que dar "No changes detected" -- nenhum model mudou)
#   python -m pytest impostos/tests/ precificacao/tests/ -q
#       (os 2 testes de impostos/ e os 6 de precificacao/ importam direto
#       de funcoes_auxiliares/ -- são o teste mais forte de que nenhum
#       import ficou quebrado)

import re
import sys
from pathlib import Path

RAIZ = Path('.')
PASTA_FUNCOES_AUXILIARES = Path('impostos/funcoes_auxiliares')

# Classificação confirmada por inspeção manual de cada arquivo (cabeçalho
# "Função Objetivo:") e por grep de quem os importa, 13/09/2026 -- se a
# pasta real tiver um arquivo que não está em nenhuma das 2 listas abaixo,
# o script PARA sem escrever nada (ver validar_modulos_encontrados).
MODULOS_ENTRADA = [
    'conversao_valores_impostos',
    'creditos_fiscais_para_precificacao',
    'exibicao_impostos_entrada',
    'exportacao_resumo_entrada',
    'resumo_entrada',
    'sincronizacao_impostos_entrada',
]
MODULOS_SAIDA = [
    'exibicao_auditoria_fiscal',
    'exibicao_icms_por_ncm',
    'exibicao_pis_cofins_por_ncm_cst',
    'importacao_icms_ncm',
    'importacao_pis_cofins_ncm_cst',
    'motivo_impostos_saida',
    'preenchimento_cst_produtos',
    'preenchimento_impostos_saida',
]

TODOS_OS_MODULOS = MODULOS_ENTRADA + MODULOS_SAIDA
DOMINIO_POR_MODULO = {m: 'entrada' for m in MODULOS_ENTRADA}
DOMINIO_POR_MODULO.update({m: 'saida' for m in MODULOS_SAIDA})

# Pastas nunca escaneadas/reescritas -- controle de versão, venvs, cache.
PASTAS_IGNORADAS = {'.git', 'venv', 'env', '.venv', '__pycache__', 'node_modules', '.pytest_cache'}

# Só casa "from impostos.funcoes_auxiliares.<modulo>" no INÍCIO de uma
# linha lógica (só espaço em branco antes) -- exclui menção dentro de
# comentário (ex: "# ... gravado por importacao_icms_ncm.py ...", que nem
# começa com "from" mesmo, mas a guarda fica explícita e documentada).
REGEX_IMPORT = re.compile(r'^(\s*)from impostos\.funcoes_auxiliares\.(\w+)\b')


def listar_arquivos_py():
    for caminho in RAIZ.rglob('*.py'):
        if any(parte in PASTAS_IGNORADAS for parte in caminho.parts):
            continue
        yield caminho


def validar_modulos_encontrados():
    arquivos_reais = sorted(
        p.stem for p in PASTA_FUNCOES_AUXILIARES.glob('*.py') if p.name != '__init__.py'
    )
    esperado = set(TODOS_OS_MODULOS)
    encontrado = set(arquivos_reais)
    faltando = esperado - encontrado
    sobrando = encontrado - esperado
    if faltando or sobrando:
        print('ERRO: impostos/funcoes_auxiliares/ real não bate com a classificação esperada. Nada foi escrito.')
        if faltando:
            print(f'  Esperava e não achei: {sorted(faltando)}')
        if sobrando:
            print(f'  Achei e não esperava (arquivo novo desde a última conferência): {sorted(sobrando)}')
        print('Me avise com o conteúdo atual da pasta antes de tentar de novo.')
        sys.exit(1)


def encontrar_todas_as_ocorrencias():
    """Retorna lista de (caminho, numero_da_linha, modulo) para TODO import
    encontrado em TODO arquivo .py do repo (inclusive dentro da própria
    funcoes_auxiliares/, que também precisa da correção)."""
    ocorrencias = []
    for caminho in listar_arquivos_py():
        texto = caminho.read_text(encoding='utf-8')
        for numero, linha in enumerate(texto.splitlines(), start=1):
            m = REGEX_IMPORT.match(linha)
            if m:
                ocorrencias.append((caminho, numero, m.group(2)))
    return ocorrencias


def validar_ocorrencias(ocorrencias):
    desconhecidos = [(c, n, mod) for c, n, mod in ocorrencias if mod not in DOMINIO_POR_MODULO]
    if desconhecidos:
        print('ERRO: encontrei import de impostos.funcoes_auxiliares pra módulo que não conheço. Nada foi escrito.')
        for caminho, numero, mod in desconhecidos:
            print(f'  {caminho}:{numero} -- módulo desconhecido: {mod}')
        print('Me avise com esse(s) trecho(s) antes de tentar de novo -- pode ser um arquivo criado depois da última conferência.')
        sys.exit(1)


def reescrever_arquivo(caminho, aplicar):
    texto_original = caminho.read_text(encoding='utf-8')
    linhas = texto_original.splitlines(keepends=True)
    mudou = False
    novas_linhas = []
    for linha in linhas:
        m = REGEX_IMPORT.match(linha)
        if m:
            espacos, modulo = m.group(1), m.group(2)
            dominio = DOMINIO_POR_MODULO[modulo]
            resto_da_linha = linha[m.end():]  # tudo depois do nome do módulo (ex: " import (\n")
            nova_linha = f'{espacos}from impostos.funcoes_auxiliares.{dominio}.{modulo}{resto_da_linha}'
            novas_linhas.append(nova_linha)
            mudou = True
        else:
            novas_linhas.append(linha)
    if mudou and aplicar:
        caminho.write_text(''.join(novas_linhas), encoding='utf-8')
    return mudou


def main():
    aplicar = '--apply' in sys.argv

    if not PASTA_FUNCOES_AUXILIARES.exists():
        print(f'ERRO: não encontrei {PASTA_FUNCOES_AUXILIARES} -- rode este script na raiz do repo.')
        sys.exit(1)

    pasta_entrada = PASTA_FUNCOES_AUXILIARES / 'entrada'
    pasta_saida = PASTA_FUNCOES_AUXILIARES / 'saida'
    if pasta_entrada.exists() or pasta_saida.exists():
        print(f'ERRO: {pasta_entrada} ou {pasta_saida} já existe -- apague ou renomeie antes de rodar de novo.')
        sys.exit(1)

    validar_modulos_encontrados()

    ocorrencias = encontrar_todas_as_ocorrencias()
    validar_ocorrencias(ocorrencias)

    arquivos_com_import_a_corrigir = sorted({str(c) for c, _, _ in ocorrencias})

    print(f'{"APLICANDO" if aplicar else "DRY-RUN (nada será escrito -- rode com --apply pra executar de verdade)"}')
    print(f'{len(TODOS_OS_MODULOS)} módulos em funcoes_auxiliares/: {len(MODULOS_ENTRADA)} entrada, {len(MODULOS_SAIDA)} saída')
    print(f'{len(ocorrencias)} linha(s) de import a corrigir em {len(arquivos_com_import_a_corrigir)} arquivo(s):')
    for caminho in arquivos_com_import_a_corrigir:
        n = sum(1 for c, _, _ in ocorrencias if str(c) == caminho)
        print(f'  corrigiria {caminho}  ({n} linha{"s" if n != 1 else ""})')
    print()
    print(f'  criaria {pasta_entrada}/__init__.py  (vazio, mesmo padrão do __init__.py atual do pacote)')
    print(f'  criaria {pasta_saida}/__init__.py  (vazio, mesmo padrão do __init__.py atual do pacote)')
    for modulo in MODULOS_ENTRADA:
        print(f'  moveria {PASTA_FUNCOES_AUXILIARES}/{modulo}.py  ->  {pasta_entrada}/{modulo}.py')
    for modulo in MODULOS_SAIDA:
        print(f'  moveria {PASTA_FUNCOES_AUXILIARES}/{modulo}.py  ->  {pasta_saida}/{modulo}.py')

    if not aplicar:
        return

    # 1) corrige todo import ANTES de mover qualquer arquivo -- os 14
    # arquivos que vão ser movidos também precisam da correção (imports
    # internos entre eles), e é mais simples corrigir todo mundo primeiro,
    # com o arquivo ainda no caminho antigo, do que depois de mover.
    for caminho in arquivos_com_import_a_corrigir:
        reescrever_arquivo(Path(caminho), aplicar=True)

    # 2) cria as 2 subpastas com __init__.py vazio (mesmo padrão do
    # __init__.py atual, que já é vazio -- nada aqui é reexportado hoje,
    # ninguém importa `from impostos.funcoes_auxiliares import X`).
    pasta_entrada.mkdir(parents=True, exist_ok=True)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    (pasta_entrada / '__init__.py').write_text('', encoding='utf-8')
    (pasta_saida / '__init__.py').write_text('', encoding='utf-8')

    # 3) move os 14 arquivos, já com o conteúdo corrigido.
    for modulo in MODULOS_ENTRADA:
        (PASTA_FUNCOES_AUXILIARES / f'{modulo}.py').rename(pasta_entrada / f'{modulo}.py')
    for modulo in MODULOS_SAIDA:
        (PASTA_FUNCOES_AUXILIARES / f'{modulo}.py').rename(pasta_saida / f'{modulo}.py')

    print()
    print('Feito. Próximos passos:')
    print('  git add -A && git status')
    print('  python manage.py check')
    print('  python manage.py makemigrations --check --dry-run   (tem que dar "No changes detected")')
    print('  python -m pytest impostos/tests/ precificacao/tests/ -q')


if __name__ == '__main__':
    main()