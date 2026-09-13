#!/usr/bin/env python3
# dividir_models_impostos.py
#
# Roda a partir da RAIZ do repo (Projeto_Sistema_Interno_V2), onde este
# script foi salvo.
#
# Faz o que era "impostos/models.py" (arquivo único) virar um pacote
# "impostos/models/" com 1 arquivo por classe, separado em entrada/ e
# saida/ (Passo 1 do plano de reorganização confirmado com o Matheus,
# 13/09/2026) -- sem mudar NADA de comportamento: `from impostos.models
# import X` continua funcionando idêntico em todo o resto do repo, porque
# impostos/models/__init__.py reexporta tudo. Migrations não são afetadas
# (Django rastreia por app_label.NomeDoModel, não por caminho de arquivo).
#
# Por segurança, o script NUNCA sobrescreve nada e roda em modo DRY-RUN
# por padrão -- só mostra o que faria. Passe --apply pra executar de
# verdade.
#
# Uso:
#   python dividir_models_impostos.py            (dry-run, só mostra)
#   python dividir_models_impostos.py --apply     (executa de verdade)
#
# Depois de rodar com --apply:
#   git add -A && git status              (conferir o que mudou)
#   python manage.py check                 (valida que o Django ainda sobe)
#   python manage.py makemigrations --check --dry-run
#       (tem que dar "No changes detected" -- se aparecer migration nova,
#       PARE e me avise antes de continuar, algo saiu diferente do esperado)

import re
import sys
from pathlib import Path

CAMINHO_MODELS_ANTIGO = Path('impostos/models.py')
PASTA_MODELS_NOVA = Path('impostos/models')

# Classificação confirmada por inspeção manual do arquivo real, 13/09/2026
# -- se o arquivo tiver uma classe que não está em nenhuma das 2 listas
# abaixo, o script PARA sem escrever nada (ver validar_classes_encontradas).
CLASSES_ENTRADA = [
    'ImpostoComAliquota',
    'ImpostosECustosXMLEntradaProduto',
    'IcmsEntradaProduto',
    'IcmsStEntradaProduto',
    'IcmsRetEntradaProduto',
    'IpiEntradaProduto',
    'PisEntradaProduto',
    'CofinsEntradaProduto',
]
CLASSES_SAIDA = [
    'IcmsNcmUf',
    'PisCofinsNcmCst',
    'IcmsNcmRejeitado',
    'PisCofinsNcmCstRejeitado',
    'IcmsSaidaMediaPorNcmCstOrigem',
]

# Bloco de import compartilhado -- prepend em TODO arquivo novo, mesmo
# quando a classe não precisa de 1 ou outro (import não usado é warning de
# lint, nunca erro; rodar ruff/flake8 depois é polimento opcional, não
# bloqueia nada). Escolhido assim de propósito: extrair só o necessário
# por classe exigiria entender cada campo, e o risco de esquecer 1 import
# necessário é pior que ter 1 import sobrando.
IMPORTS_COMPARTILHADOS = (
    "from __future__ import annotations\n"
    "\n"
    "from django.core.serializers.json import DjangoJSONEncoder\n"
    "from django.db import models\n"
    "\n"
    "from produtos.models import Produto\n"
)

CABECALHO_INIT_ENTRADA = '''# impostos/models/entrada/__init__.py

# Reexporta as tabelas de impostos de ENTRADA (1 produto, vindas do
# XML/Cadastro da nota fiscal via Sysemp) -- 1 arquivo por classe dentro
# desta pasta. `from impostos.models import X` continua funcionando
# idêntico em todo o resto do repo.

'''

CABECALHO_INIT_SAIDA = '''# impostos/models/saida/__init__.py

# Reexporta as tabelas de impostos de SAÍDA (ICMS por NCM+CST+Origem,
# PIS/COFINS por NCM+CST, tabelas de rejeitado e a média ponderada
# persistida) -- 1 arquivo por classe dentro desta pasta. `from
# impostos.models import X` continua funcionando idêntico em todo o resto
# do repo.

'''

CABECALHO_INIT_RAIZ = '''# impostos/models/__init__.py

# Reexporta tudo de entrada/ e saida/ num namespace só -- ninguém fora
# daqui precisa saber que a divisão existe. Separação decidida em
# 13/09/2026 (ver Decisão no vault): entrada e saída de impostos são
# domínios distintos (fontes de dado diferentes, times diferentes,
# nenhuma classe usada dos 2 lados) -- só moravam juntas por história, não
# por design.

'''


def para_snake_case(nome_classe):
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', nome_classe)
    s2 = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1)
    return s2.lower()


def encontrar_segmentos(linhas):
    # Âncora = linha que começa literalmente com "class " na coluna 0
    # (top-level, nunca indentada).
    regex_classe = re.compile(r'^class\s+(\w+)')
    indices_ancora = [i for i, linha in enumerate(linhas) if regex_classe.match(linha)]

    if not indices_ancora:
        raise RuntimeError('Nenhuma "class" encontrada em impostos/models.py -- arquivo inesperado, abortando.')

    def inicio_do_preambulo(indice_ancora):
        i = indice_ancora
        while i > 0:
            anterior = linhas[i - 1]
            if anterior.strip() == '' or anterior.lstrip().startswith('#'):
                i -= 1
            else:
                break
        return i

    limites = [inicio_do_preambulo(a) for a in indices_ancora]

    segmentos = []
    for pos, limite in enumerate(limites):
        fim = limites[pos + 1] if pos + 1 < len(limites) else len(linhas)
        nome = regex_classe.match(linhas[indices_ancora[pos]]).group(1)
        corpo = linhas[limite:fim]
        # Tira linhas em branco do INÍCIO do segmento (podem ter sobrado
        # do jeito que o próximo segmento "puxou" o preâmbulo pra trás) --
        # puramente cosmético, não muda o conteúdo real da classe.
        while corpo and corpo[0].strip() == '':
            corpo = corpo[1:]
        segmentos.append((nome, corpo))

    return segmentos


def validar_classes_encontradas(nomes_encontrados):
    esperado = set(CLASSES_ENTRADA) | set(CLASSES_SAIDA)
    encontrado = set(nomes_encontrados)

    faltando = esperado - encontrado
    sobrando = encontrado - esperado

    if faltando or sobrando:
        print('ERRO: o arquivo real não bate com a classificação esperada. Nada foi escrito.')
        if faltando:
            print(f'  Esperava e não achei: {sorted(faltando)}')
        if sobrando:
            print(f'  Achei e não esperava (classe nova desde a última conferência): {sorted(sobrando)}')
        print('Me avise com o conteúdo atual de impostos/models.py antes de tentar de novo.')
        sys.exit(1)


TODAS_AS_CLASSES = CLASSES_ENTRADA + CLASSES_SAIDA


def remover_comentarios(corpo_linhas):
    # Tira tudo a partir do 1º "#" de cada linha -- os comentários deste
    # arquivo (todo em português, sem "#" dentro de string) costumam
    # CITAR outras classes só como explicação (ex: "mesma convenção de
    # PisCofinsNcmCst.cst"), o que não é uma dependência de código de
    # verdade e não pode virar import.
    return '\n'.join(linha.split('#', 1)[0] for linha in corpo_linhas)


def encontrar_referencias_locais(corpo_linhas, nome_classe):
    # Varre o corpo INTEIRO da classe (não só a linha "class X(Base):") --
    # cobre tanto herança (class IcmsEntradaProduto(ImpostoComAliquota))
    # quanto referência de campo (models.OneToOneField(ImpostosECustos...))
    # ou qualquer outro uso de outra classe deste mesmo split em qualquer
    # lugar do corpo DE CÓDIGO (comentários já removidos). \b garante
    # palavra inteira (não casa 1 nome que é substring de outro).
    texto = remover_comentarios(corpo_linhas)
    encontradas = []
    for outra_classe in TODAS_AS_CLASSES:
        if outra_classe == nome_classe:
            continue
        if re.search(rf'\b{re.escape(outra_classe)}\b', texto):
            encontradas.append(outra_classe)
    return encontradas


def dominio_da_classe(nome_classe):
    if nome_classe in CLASSES_ENTRADA:
        return 'entrada'
    if nome_classe in CLASSES_SAIDA:
        return 'saida'
    raise RuntimeError(f'Classe {nome_classe} não está classificada em nenhum domínio.')


def montar_conteudo_arquivo(nome_classe, corpo_linhas, dominio):
    nome_arquivo = para_snake_case(nome_classe)
    cabecalho = f'# impostos/models/{dominio}/{nome_arquivo}.py\n\n'
    corpo = ''.join(corpo_linhas).rstrip('\n') + '\n'

    imports_locais = ''
    for referencia in encontrar_referencias_locais(corpo_linhas, nome_classe):
        dominio_referencia = dominio_da_classe(referencia)
        if dominio_referencia == dominio:
            caminho_modulo = f'.{para_snake_case(referencia)}'
        else:
            caminho_modulo = f'..{dominio_referencia}.{para_snake_case(referencia)}'
        imports_locais += f'from {caminho_modulo} import {referencia}\n'
    if imports_locais:
        imports_locais = imports_locais + '\n'

    return cabecalho + IMPORTS_COMPARTILHADOS + '\n' + imports_locais + '\n' + corpo


def montar_init(classes, cabecalho):
    linhas_import = []
    for nome_classe in classes:
        nome_arquivo = para_snake_case(nome_classe)
        linhas_import.append(f'from .{nome_arquivo} import {nome_classe}')
    return cabecalho + '\n'.join(linhas_import) + '\n'


def montar_init_raiz():
    def bloco(classes):
        nomes = ',\n    '.join(classes)
        return f'    {nomes},\n'

    return (
        CABECALHO_INIT_RAIZ
        + 'from .entrada import (\n'
        + bloco(CLASSES_ENTRADA)
        + ')\n'
        + 'from .saida import (\n'
        + bloco(CLASSES_SAIDA)
        + ')\n'
    )


def main():
    aplicar = '--apply' in sys.argv

    if not CAMINHO_MODELS_ANTIGO.exists():
        print(f'ERRO: não encontrei {CAMINHO_MODELS_ANTIGO} -- rode este script na raiz do repo.')
        sys.exit(1)

    if PASTA_MODELS_NOVA.exists():
        print(f'ERRO: {PASTA_MODELS_NOVA} já existe -- apague ou renomeie antes de rodar de novo.')
        sys.exit(1)

    linhas = CAMINHO_MODELS_ANTIGO.read_text(encoding='utf-8').splitlines(keepends=True)
    segmentos = encontrar_segmentos(linhas)
    validar_classes_encontradas([nome for nome, _ in segmentos])

    segmentos_por_nome = dict(segmentos)

    plano = []  # (caminho_relativo, conteudo)
    for nome_classe in CLASSES_ENTRADA:
        conteudo = montar_conteudo_arquivo(nome_classe, segmentos_por_nome[nome_classe], 'entrada')
        plano.append((PASTA_MODELS_NOVA / 'entrada' / f'{para_snake_case(nome_classe)}.py', conteudo))
    for nome_classe in CLASSES_SAIDA:
        conteudo = montar_conteudo_arquivo(nome_classe, segmentos_por_nome[nome_classe], 'saida')
        plano.append((PASTA_MODELS_NOVA / 'saida' / f'{para_snake_case(nome_classe)}.py', conteudo))

    plano.append((PASTA_MODELS_NOVA / 'entrada' / '__init__.py', montar_init(CLASSES_ENTRADA, CABECALHO_INIT_ENTRADA)))
    plano.append((PASTA_MODELS_NOVA / 'saida' / '__init__.py', montar_init(CLASSES_SAIDA, CABECALHO_INIT_SAIDA)))
    plano.append((PASTA_MODELS_NOVA / '__init__.py', montar_init_raiz()))

    print(f'{"APLICANDO" if aplicar else "DRY-RUN (nada será escrito -- rode com --apply pra executar)"}')
    print(f'{len(segmentos)} classes encontradas em {CAMINHO_MODELS_ANTIGO}: {[n for n, _ in segmentos]}')
    print()
    for caminho, conteudo in plano:
        print(f'  criaria {caminho}  ({len(conteudo.splitlines())} linhas)')
    print(f'  removeria {CAMINHO_MODELS_ANTIGO}')

    if not aplicar:
        return

    for caminho, conteudo in plano:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo, encoding='utf-8')

    CAMINHO_MODELS_ANTIGO.unlink()

    print()
    print('Feito. Próximos passos:')
    print('  git add -A && git status')
    print('  python manage.py check')
    print('  python manage.py makemigrations --check --dry-run   (tem que dar "No changes detected")')


if __name__ == '__main__':
    main()