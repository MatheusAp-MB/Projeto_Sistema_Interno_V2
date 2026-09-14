#!/usr/bin/env python3
# dividir_views_impostos.py
#
# Roda a partir da RAIZ do repo (Projeto_Sistema_Interno_V2), onde este
# script foi salvo.
#
# Passo 3 da reorganização entrada/saida do app `impostos` (Passo 1 foi
# models.py, Passo 2 foi funcoes_auxiliares/ -- ver vault, Decisao "App
# impostos Sera Reorganizado em Entrada e Saida..."). Escopo revisado
# depois de conferir a convenção do resto do repo (13/09/2026): só
# `views.py` vira pacote -- `templates/impostos/` e `static/impostos/`
# ficam exatamente como estão, porque já seguem o padrão do repo (plano,
# nome de arquivo autoexplicativo, sem subpasta por domínio -- nenhum app
# do projeto, nem o precificacao, faz isso).
#
# Faz `impostos/views.py` (arquivo único, 8 funções) virar um pacote
# `impostos/views/` PLANO -- sem subpasta, mesmo padrão de
# `precificacao/views/` (o único outro pacote de views do projeto):
#   impostos/views/entrada.py   (2 funções)
#   impostos/views/saida.py     (6 funções)
#   impostos/views/__init__.py  (reexporta as 8)
#
# `impostos/urls.py` só faz `from . import views` + `views.view_X` (nunca
# importa uma view por caminho de submódulo) -- confirmado por grep antes
# de escrever este script. Por isso, igual ao Passo 1 (models.py), NENHUM
# import externo muda: o `__init__.py` reexportando é suficiente. Não tem
# o risco do Passo 2 (que exigia reescrever import em todo o repo).
#
# Cada import do topo do arquivo original é atribuído ao(s) domínio(s)
# cujas funções realmente usam o nome importado (checado por busca de
# palavra inteira no corpo de cada função, comentários ignorados) -- ex:
# `render` é usado pelas 8 funções, então entra em entrada.py E saida.py;
# `Paginator`/`HttpResponse` só aparecem em funções de entrada, então só
# entram em entrada.py. Nenhuma lista de "isso vai pra entrada, isso vai
# pra saida" é hardcoded pra imports -- só pras 8 funções em si (única
# classificação que precisa de julgamento humano).
#
# Por segurança: valida ANTES de escrever que (a) as 8 funções encontradas
# em views.py batem exatamente com a classificação esperada, (b) nenhum
# import do arquivo original ficou sem uso identificado em nenhum dos 2
# domínios (sinal de que a extração de corpo/nome falhou), e (c) nenhum
# arquivo do repo já importa `impostos.views.<algo>` por caminho de
# submódulo (o que não deveria existir ainda, já que views.py era um
# arquivo só até agora). Se achar qualquer coisa inesperada, o script para
# e NADA é escrito. Roda em DRY-RUN por padrão. Passe --apply pra
# executar de verdade.
#
# Uso:
#   python dividir_views_impostos.py            (dry-run)
#   python dividir_views_impostos.py --apply     (executa)
#
# Depois de rodar com --apply:
#   git add -A && git status                          (conferir o que mudou)
#   python manage.py check                             (Django ainda sobe)
#   python manage.py makemigrations --check --dry-run  (tem que dar "No changes detected" -- views.py não mexe em model, isso é só confirmação de que nada mais quebrou)
#   python -m pytest impostos/tests/ -q                (os testes de impostos/ -- mais garantia de que nenhum import de view ficou quebrado)
#
# Teste manual extra (views não tem cobertura de teste automatizado hoje,
# então vale conferir na mão que as 8 páginas ainda respondem, com o
# servidor local rodando):
#   /impostos/                                     (resumo entrada)
#   /impostos/auditoria-fiscal/                    (auditoria fiscal)
#   /impostos/icms-por-ncm/                        (tabela ICMS por NCM)
#   /impostos/pis-cofins-por-ncm-cst/              (tabela PIS/COFINS por NCM+CST)

import ast
import re
import sys
from pathlib import Path

RAIZ = Path('.')
CAMINHO_VIEWS_ANTIGO = Path('impostos/views.py')
PASTA_VIEWS_NOVA = Path('impostos/views')

# Classificação confirmada por inspeção manual do arquivo real, 13/09/2026
# (mesma classificação já registrada na Decisão do vault: 2 entrada, 6
# saída) -- se o arquivo real tiver uma função "view_..." que não está em
# nenhuma das 2 listas abaixo, o script PARA sem escrever nada (ver
# validar_funcoes_encontradas). A ordem aqui é a mesma ordem em que as
# funções aparecem no arquivo original (as 2 de entrada vêm primeiro, as 6
# de saída depois -- coincidência conveniente, não é regra).
FUNCOES_ENTRADA = [
    'view_resumo_impostos_entrada',
    'view_exportar_resumo_impostos_entrada',
]
FUNCOES_SAIDA = [
    'view_auditoria_fiscal',
    'view_tabela_icms_por_ncm',
    'view_calcular_icms_por_ncm',
    'view_tabela_pis_cofins_por_ncm_cst',
    'view_csts_disponiveis_pis_cofins_ncm_cst',
    'view_calcular_pis_cofins_por_ncm_cst',
]
TODAS_AS_FUNCOES = FUNCOES_ENTRADA + FUNCOES_SAIDA
DOMINIO_POR_FUNCAO = {f: 'entrada' for f in FUNCOES_ENTRADA}
DOMINIO_POR_FUNCAO.update({f: 'saida' for f in FUNCOES_SAIDA})

# Pastas nunca escaneadas -- controle de versão, venvs, cache.
PASTAS_IGNORADAS = {'.git', 'venv', 'env', '.venv', '__pycache__', 'node_modules', '.pytest_cache'}

CABECALHO_INIT_RAIZ = '''# impostos/views/__init__.py

# Reexporta as 8 views (2 de entrada, 6 de saída) num namespace só --
# impostos/urls.py continua fazendo `from . import views` e
# `views.view_xxx`, sem precisar saber que virou um pacote (mesmo padrão
# de precificacao/views/__init__.py, o único outro pacote de views do
# projeto). Separação decidida em 13/09/2026 (Passo 3 do plano no vault,
# escopo revisado pra não incluir templates/static -- ver Decisão) --
# mesma divisão entrada/saida que impostos/models/ e
# impostos/funcoes_auxiliares/ já têm.

'''

CABECALHO_ENTRADA = '# impostos/views/entrada.py\n\n'
CABECALHO_SAIDA = '# impostos/views/saida.py\n\n'


def listar_arquivos_py():
    for caminho in RAIZ.rglob('*.py'):
        if any(parte in PASTAS_IGNORADAS for parte in caminho.parts):
            continue
        yield caminho


REGEX_IMPORT_SUBMODULO_VIEWS = re.compile(r'^(\s*)from impostos\.views\.(\w+)\b')


def validar_nenhum_import_de_submodulo_de_views():
    """views.py hoje é um arquivo só -- ninguém no repo pode legitimamente
    importar `impostos.views.<algo>` por caminho de submódulo ainda,
    porque esse submódulo não existe. Se isso aparecer, algo mudou desde
    a última conferência e o script para."""
    achados = []
    for caminho in listar_arquivos_py():
        if caminho == CAMINHO_VIEWS_ANTIGO:
            continue
        texto = caminho.read_text(encoding='utf-8')
        for numero, linha in enumerate(texto.splitlines(), start=1):
            if REGEX_IMPORT_SUBMODULO_VIEWS.match(linha):
                achados.append((caminho, numero, linha.strip()))
    if achados:
        print('ERRO: encontrei import de "impostos.views.<algo>" por caminho de submódulo -- isso não deveria existir ainda. Nada foi escrito.')
        for caminho, numero, linha in achados:
            print(f'  {caminho}:{numero} -- {linha}')
        print('Me avise com esse trecho antes de tentar de novo -- pode ser um import novo desde a última conferência.')
        sys.exit(1)


def encontrar_segmentos(linhas):
    """Retorna (indice_inicio_do_cabecalho_de_imports, lista_de_segmentos),
    onde cada segmento é (nome_da_funcao, linhas_do_corpo). Âncora = linha
    que começa literalmente com "def view_" na coluna 0 (top-level, nunca
    indentada -- não existe função aninhada em views.py)."""
    regex_funcao = re.compile(r'^def\s+(view_\w+)\s*\(')
    indices_ancora = [i for i, linha in enumerate(linhas) if regex_funcao.match(linha)]

    if not indices_ancora:
        raise RuntimeError('Nenhuma "def view_..." encontrada em impostos/views.py -- arquivo inesperado, abortando.')

    def inicio_do_preambulo(indice_ancora):
        i = indice_ancora
        while i > 0 and linhas[i - 1].strip() == '':
            i -= 1
        return i

    limites = [inicio_do_preambulo(a) for a in indices_ancora]

    segmentos = []
    for pos, limite in enumerate(limites):
        fim = limites[pos + 1] if pos + 1 < len(limites) else len(linhas)
        nome = regex_funcao.match(linhas[indices_ancora[pos]]).group(1)
        corpo = linhas[limite:fim]
        while corpo and corpo[0].strip() == '':
            corpo = corpo[1:]
        while corpo and corpo[-1].strip() == '':
            corpo = corpo[:-1]
        segmentos.append((nome, corpo))

    return limites[0], segmentos


def validar_funcoes_encontradas(nomes_encontrados):
    esperado = set(TODAS_AS_FUNCOES)
    encontrado = set(nomes_encontrados)
    faltando = esperado - encontrado
    sobrando = encontrado - esperado
    if faltando or sobrando:
        print('ERRO: as funções reais de impostos/views.py não batem com a classificação esperada. Nada foi escrito.')
        if faltando:
            print(f'  Esperava e não achei: {sorted(faltando)}')
        if sobrando:
            print(f'  Achei e não esperava (função nova desde a última conferência): {sorted(sobrando)}')
        print('Me avise com o conteúdo atual de impostos/views.py antes de tentar de novo.')
        sys.exit(1)


def remover_comentarios(corpo_linhas):
    # Mesma guarda dos scripts anteriores: comentários deste arquivo (em
    # português, sem "#" dentro de string) podem citar um nome importado só
    # como explicação -- isso não conta como uso de verdade.
    return '\n'.join(linha.split('#', 1)[0] for linha in corpo_linhas)


def extrair_imports_do_cabecalho(linhas_cabecalho):
    """Usa o módulo ast só pra achar onde cada import começa e termina
    (node.lineno / node.end_lineno) -- o TEXTO de cada import é copiado
    verbatim das linhas originais (nunca regenerado a partir da árvore),
    então formatação, quebra de linha com parênteses etc. ficam idênticas
    ao arquivo original. Retorna lista de (nomes_importados, texto_original)."""
    texto_cabecalho = ''.join(linhas_cabecalho)
    arvore = ast.parse(texto_cabecalho)
    imports = []
    for node in arvore.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            inicio = node.lineno - 1
            fim = node.end_lineno
            texto = ''.join(linhas_cabecalho[inicio:fim])
            nomes = [alias.asname or alias.name for alias in node.names]
            imports.append((nomes, texto))
    return imports


def dominios_que_usam(nomes, corpo_texto_por_dominio):
    usados_em = []
    for dominio, texto in corpo_texto_por_dominio.items():
        if any(re.search(rf'\b{re.escape(nome)}\b', texto) for nome in nomes):
            usados_em.append(dominio)
    return usados_em


def montar_conteudo_dominio(cabecalho, imports_do_dominio, funcoes_do_dominio, corpo_por_funcao):
    bloco_imports = ''.join(imports_do_dominio)
    # Cada corpo já termina em "\n" (última linha da função, com quebra
    # preservada) -- separador de "\n\n" entre eles produz exatamente 2
    # linhas em branco entre uma função e a próxima (padrão do resto do
    # arquivo original), sem duplicar a quebra de linha final.
    corpo_funcoes = '\n\n'.join(
        ''.join(corpo_por_funcao[f]) for f in funcoes_do_dominio
    )
    return cabecalho + bloco_imports + '\n\n' + corpo_funcoes


def montar_init_raiz():
    def bloco(funcoes):
        nomes = ',\n    '.join(funcoes)
        return f'    {nomes},\n'

    return (
        CABECALHO_INIT_RAIZ
        + 'from impostos.views.entrada import (\n'
        + bloco(FUNCOES_ENTRADA)
        + ')\n'
        + 'from impostos.views.saida import (\n'
        + bloco(FUNCOES_SAIDA)
        + ')\n'
    )


def main():
    aplicar = '--apply' in sys.argv

    if not CAMINHO_VIEWS_ANTIGO.exists():
        print(f'ERRO: não encontrei {CAMINHO_VIEWS_ANTIGO} -- rode este script na raiz do repo.')
        sys.exit(1)

    if PASTA_VIEWS_NOVA.exists():
        print(f'ERRO: {PASTA_VIEWS_NOVA} já existe -- apague ou renomeie antes de rodar de novo.')
        sys.exit(1)

    validar_nenhum_import_de_submodulo_de_views()

    linhas = CAMINHO_VIEWS_ANTIGO.read_text(encoding='utf-8').splitlines(keepends=True)
    inicio_primeira_funcao, segmentos = encontrar_segmentos(linhas)
    validar_funcoes_encontradas([nome for nome, _ in segmentos])

    corpo_por_funcao = dict(segmentos)
    linhas_cabecalho = linhas[:inicio_primeira_funcao]
    imports = extrair_imports_do_cabecalho(linhas_cabecalho)

    corpo_texto_por_dominio = {
        'entrada': remover_comentarios([l for f in FUNCOES_ENTRADA for l in corpo_por_funcao[f]]),
        'saida': remover_comentarios([l for f in FUNCOES_SAIDA for l in corpo_por_funcao[f]]),
    }

    imports_por_dominio = {'entrada': [], 'saida': []}
    imports_sem_uso_identificado = []
    for nomes, texto in imports:
        dominios = dominios_que_usam(nomes, corpo_texto_por_dominio)
        if not dominios:
            imports_sem_uso_identificado.append((nomes, texto))
            continue
        for dominio in dominios:
            imports_por_dominio[dominio].append(texto)

    if imports_sem_uso_identificado:
        print('ERRO: encontrei import em views.py cujo nome não aparece em nenhuma das 8 funções. Nada foi escrito.')
        for nomes, texto in imports_sem_uso_identificado:
            print(f'  {texto.strip()}  (nomes: {nomes})')
        print('Me avise com esse trecho -- pode ser um import não usado no arquivo original, ou a busca por nome falhou por algum motivo.')
        sys.exit(1)

    conteudo_entrada = montar_conteudo_dominio(
        CABECALHO_ENTRADA, imports_por_dominio['entrada'], FUNCOES_ENTRADA, corpo_por_funcao,
    )
    conteudo_saida = montar_conteudo_dominio(
        CABECALHO_SAIDA, imports_por_dominio['saida'], FUNCOES_SAIDA, corpo_por_funcao,
    )
    conteudo_init = montar_init_raiz()

    plano = [
        (PASTA_VIEWS_NOVA / '__init__.py', conteudo_init),
        (PASTA_VIEWS_NOVA / 'entrada.py', conteudo_entrada),
        (PASTA_VIEWS_NOVA / 'saida.py', conteudo_saida),
    ]

    print(f'{"APLICANDO" if aplicar else "DRY-RUN (nada será escrito -- rode com --apply pra executar de verdade)"}')
    print(f'{len(segmentos)} funções encontradas em {CAMINHO_VIEWS_ANTIGO}: {len(FUNCOES_ENTRADA)} entrada, {len(FUNCOES_SAIDA)} saída')
    print()
    for caminho, conteudo in plano:
        print(f'  criaria {caminho}  ({len(conteudo.splitlines())} linhas)')
    print(f'  removeria {CAMINHO_VIEWS_ANTIGO}')
    print()
    print('  templates/impostos/ e static/impostos/ NÃO mudam (escopo revisado, ver Decisão no vault).')

    if not aplicar:
        return

    PASTA_VIEWS_NOVA.mkdir(parents=True, exist_ok=True)
    for caminho, conteudo in plano:
        caminho.write_text(conteudo, encoding='utf-8')

    CAMINHO_VIEWS_ANTIGO.unlink()

    print()
    print('Feito. Próximos passos:')
    print('  git add -A && git status')
    print('  python manage.py check')
    print('  python manage.py makemigrations --check --dry-run   (tem que dar "No changes detected")')
    print('  python -m pytest impostos/tests/ -q')
    print('  conferir na mão que as 8 páginas de /impostos/ ainda respondem (ver lista no cabeçalho do script)')


if __name__ == '__main__':
    main()