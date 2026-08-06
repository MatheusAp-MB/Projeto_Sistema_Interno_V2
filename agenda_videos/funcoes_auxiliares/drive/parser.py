# agenda_videos/funcoes_auxiliares/drive/parser.py

# Função Objetivo: Transforma a lista crua de arquivos (vinda do Drive — nome
# + ID) na estrutura padronizada do modelo novo — Base/Roteiro/Completo por
# OCORRÊNCIA (não mais por fase inteira). Puro, sem chamada de rede, testável
# isolado com qualquer lista de {id, name}. Reconhecimento é insensível a
# maiúscula/minúscula, mas rígido no FORMATO: 2 dígitos exatos pra número,
# prefixo certo, e extensão certa por TIPO (Base/Completo sempre .mp4,
# Roteiro sempre .txt) — um arquivo com nome certo mas extensão errada cai
# em "não reconhecido", nunca é aceito por engano.
#
# * [EXPLICAÇÃO] → Roteiro é só EXISTÊNCIA, nunca conteúdo — a automação
#                  nunca baixa/lê esse arquivo, só precisa saber que ele
#                  existe com o nome certo (decisão do usuário, 05/08). Por
#                  isso o parser nunca confere mimeType, só o nome.

import re
from dataclasses import dataclass
from typing import Optional
from .constantes import FASE_POR_PREFIXO_ARQUIVO_MINUSCULO, PREFIXO_ARQUIVO_POR_FASE


@dataclass(frozen=True)
class ArquivoDrive:
    nome_arquivo: str
    drive_file_id: str


@dataclass(frozen=True)
class ArquivosOcorrencia:
    numero: int
    base: Optional[ArquivoDrive]
    roteiro: Optional[ArquivoDrive]
    completo: Optional[ArquivoDrive]


@dataclass(frozen=True)
class ArquivosFase:
    fase: str
    ocorrencias: list  # list[ArquivosOcorrencia], sempre ordenada por número

    def obter_ocorrencia(self, numero):
        return next((o for o in self.ocorrencias if o.numero == numero), None)


@dataclass(frozen=True)
class ArquivosProdutoDrive:
    marca: str
    ean: str
    pasta_encontrada: bool
    motivo_pasta_nao_encontrada: Optional[str]
    simples: ArquivosFase
    video_mensal: ArquivosFase
    video_trimestral: ArquivosFase
    arquivos_nao_reconhecidos: list  # list[ArquivoDrive]

    def obter_fase(self, chave_fase):
        if chave_fase not in PREFIXO_ARQUIVO_POR_FASE:
            raise ValueError(f'Chave de fase inválida: {chave_fase!r} — esperado uma de {sorted(PREFIXO_ARQUIVO_POR_FASE)}')
        return getattr(self, chave_fase)


EXTENSOES_VALIDAS_POR_TIPO = {'base': 'mp4', 'completo': 'mp4', 'roteiro': 'txt'}

PADRAO_SIMPLES = re.compile(r'^simples_(base|roteiro|completo)\.([a-z0-9]+)$', re.IGNORECASE)
PADRAO_NUMERADO = re.compile(r'^(mensal|trimestral)_(\d{2})_(base|roteiro|completo)\.([a-z0-9]+)$', re.IGNORECASE)


def _extensao_valida(tipo, extensao):
    return EXTENSOES_VALIDAS_POR_TIPO[tipo] == extensao.lower()


def _montar_fase(fase, entradas_por_numero):
    ocorrencias = [
        ArquivosOcorrencia(
            numero=numero, base=valores.get('base'), roteiro=valores.get('roteiro'), completo=valores.get('completo'),
        )
        for numero, valores in sorted(entradas_por_numero.items())
    ]
    return ArquivosFase(fase=fase, ocorrencias=ocorrencias)


# Função Objetivo: Ponto de entrada — dado a lista crua de {id, name} de 1
# pasta "Videos", devolve a estrutura padronizada e categorizada.
def parsear_arquivos_produto(marca, ean, arquivos_brutos):
    entradas_por_fase = {'simples': {}, 'video_mensal': {}, 'video_trimestral': {}}
    nao_reconhecidos = []

    for item in arquivos_brutos:
        nome = item['name']
        arquivo = ArquivoDrive(nome_arquivo=nome, drive_file_id=item['id'])

        match_simples = PADRAO_SIMPLES.match(nome)
        if match_simples:
            tipo, extensao = match_simples.group(1).lower(), match_simples.group(2)
            if _extensao_valida(tipo, extensao):
                entradas_por_fase['simples'].setdefault(1, {})[tipo] = arquivo
            else:
                nao_reconhecidos.append(arquivo)
            continue

        match_numerado = PADRAO_NUMERADO.match(nome)
        if match_numerado:
            prefixo, numero_str, tipo, extensao = match_numerado.groups()
            prefixo, tipo = prefixo.lower(), tipo.lower()
            if _extensao_valida(tipo, extensao):
                fase = FASE_POR_PREFIXO_ARQUIVO_MINUSCULO[prefixo]
                entradas_por_fase[fase].setdefault(int(numero_str), {})[tipo] = arquivo
            else:
                nao_reconhecidos.append(arquivo)
            continue

        nao_reconhecidos.append(arquivo)

    return ArquivosProdutoDrive(
        marca=marca, ean=ean, pasta_encontrada=True, motivo_pasta_nao_encontrada=None,
        simples=_montar_fase('simples', entradas_por_fase['simples']),
        video_mensal=_montar_fase('video_mensal', entradas_por_fase['video_mensal']),
        video_trimestral=_montar_fase('video_trimestral', entradas_por_fase['video_trimestral']),
        arquivos_nao_reconhecidos=sorted(nao_reconhecidos, key=lambda a: a.nome_arquivo),
    )


# Função Objetivo: Monta a versão "não encontrada" (pasta ausente em algum
# nível) — mesma dataclass, sem duplicar a estrutura na mão em cada chamador.
def montar_produto_nao_encontrado(marca, ean, motivo):
    fase_vazia = lambda fase: ArquivosFase(fase=fase, ocorrencias=[])
    return ArquivosProdutoDrive(
        marca=marca, ean=ean, pasta_encontrada=False, motivo_pasta_nao_encontrada=motivo,
        simples=fase_vazia('simples'), video_mensal=fase_vazia('video_mensal'),
        video_trimestral=fase_vazia('video_trimestral'), arquivos_nao_reconhecidos=[],
    )