# agenda_videos/funcoes_auxiliares/parser_arquivos_drive.py

# Função Objetivo: Transforma a lista crua de arquivos (vinda do Drive — nome
# + ID) nas dataclasses padronizadas — puro, sem chamada de rede, testável
# isolado com qualquer lista de {id, name}. Reconhecimento é insensível a
# maiúscula/minúscula, mas rígido no FORMATO (2 dígitos exatos, prefixo
# certo, extensão certa).
#
# * [EXPLICAÇÃO] → Cada arquivo reconhecido carrega nome E id do Drive
#                  (26/07) — não é só "existe/não existe": uma automação
#                  futura (que vai baixar/usar o arquivo de verdade) precisa
#                  do ID pra buscar o conteúdo direto na API, sem precisar
#                  re-consultar "qual é o arquivo com esse nome" depois.

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ArquivoDrive:
    nome_arquivo: str
    drive_file_id: str
    numero: Optional[int] = None  # só usado pelos "completos" numerados


@dataclass(frozen=True)
class ArquivosCompletos:
    arquivos_validos: list             # list[ArquivoDrive], sequência contígua a partir de 1
    quantidade: int
    arquivos_fora_de_sequencia: list   # list[ArquivoDrive]


@dataclass(frozen=True)
class ArquivosFase:
    fase: str
    roteiros: Optional[ArquivoDrive]
    completos: ArquivosCompletos


@dataclass(frozen=True)
class ArquivosProdutoDrive:
    marca: str
    ean: str
    pasta_encontrada: bool
    motivo_pasta_nao_encontrada: Optional[str]
    simples: Optional[ArquivoDrive]
    base: Optional[ArquivoDrive]
    fases: dict
    arquivos_nao_reconhecidos: list    # list[ArquivoDrive]


PADRAO_SIMPLES = re.compile(r'^simples\.mp4$', re.IGNORECASE)
PADRAO_BASE = re.compile(r'^base\.mp4$', re.IGNORECASE)
PADRAO_ROTEIROS = re.compile(r'^roteiros_(diario|semanal|mensal)\.txt$', re.IGNORECASE)
PADRAO_COMPLETO = re.compile(r'^(diario|semanal|mensal)_(\d{2})\.mp4$', re.IGNORECASE)

MAPA_PREFIXO_PARA_FASE = {'diario': 'diaria', 'semanal': 'semanal', 'mensal': 'mensal'}


# Função Objetivo: Separa os arquivos numerados em "válidos" (sequência
# contígua a partir de 1) e "fora de sequência" (furo antes impede contar) —
# nunca descarta um arquivo, só decide se ele conta pra quantidade ou não.
def _montar_completos(arquivos_numerados):
    ordenados = sorted(arquivos_numerados, key=lambda item: item[0])
    validos = []
    fora_de_sequencia = []
    esperado = 1
    for numero, arquivo in ordenados:
        if numero == esperado:
            validos.append(arquivo)
            esperado += 1
        else:
            fora_de_sequencia.append(arquivo)
    return ArquivosCompletos(
        arquivos_validos=validos, quantidade=len(validos), arquivos_fora_de_sequencia=fora_de_sequencia,
    )


# Função Objetivo: Ponto de entrada — dado a lista crua de {id, name} de 1
# pasta "Videos", devolve a estrutura padronizada e categorizada.
def parsear_arquivos_produto(marca, ean, arquivos_brutos):
    simples = None
    base = None
    roteiros_por_fase = {'diaria': None, 'semanal': None, 'mensal': None}
    numerados_por_fase = {'diaria': [], 'semanal': [], 'mensal': []}
    nao_reconhecidos = []

    for item in arquivos_brutos:
        nome = item['name']
        arquivo = ArquivoDrive(nome_arquivo=nome, drive_file_id=item['id'])

        if PADRAO_SIMPLES.match(nome):
            simples = arquivo
            continue
        if PADRAO_BASE.match(nome):
            base = arquivo
            continue

        match_roteiros = PADRAO_ROTEIROS.match(nome)
        if match_roteiros:
            fase = MAPA_PREFIXO_PARA_FASE[match_roteiros.group(1).lower()]
            roteiros_por_fase[fase] = arquivo
            continue

        match_completo = PADRAO_COMPLETO.match(nome)
        if match_completo:
            fase = MAPA_PREFIXO_PARA_FASE[match_completo.group(1).lower()]
            numero = int(match_completo.group(2))
            arquivo_numerado = ArquivoDrive(nome_arquivo=nome, drive_file_id=item['id'], numero=numero)
            numerados_por_fase[fase].append((numero, arquivo_numerado))
            continue

        nao_reconhecidos.append(arquivo)

    fases = {
        fase: ArquivosFase(
            fase=fase, roteiros=roteiros_por_fase[fase], completos=_montar_completos(numerados_por_fase[fase]),
        )
        for fase in ('diaria', 'semanal', 'mensal')
    }

    return ArquivosProdutoDrive(
        marca=marca, ean=ean, pasta_encontrada=True, motivo_pasta_nao_encontrada=None,
        simples=simples, base=base, fases=fases,
        arquivos_nao_reconhecidos=sorted(nao_reconhecidos, key=lambda a: a.nome_arquivo),
    )


# Função Objetivo: Monta a versão "não encontrada" (pasta ausente em algum
# nível) — mesma dataclass, sem duplicar a estrutura na mão em cada chamador.
def montar_produto_nao_encontrado(marca, ean, motivo):
    fase_vazia = lambda fase: ArquivosFase(
        fase=fase, roteiros=None,
        completos=ArquivosCompletos(arquivos_validos=[], quantidade=0, arquivos_fora_de_sequencia=[]),
    )
    return ArquivosProdutoDrive(
        marca=marca, ean=ean, pasta_encontrada=False, motivo_pasta_nao_encontrada=motivo,
        simples=None, base=None,
        fases={f: fase_vazia(f) for f in ('diaria', 'semanal', 'mensal')},
        arquivos_nao_reconhecidos=[],
    )