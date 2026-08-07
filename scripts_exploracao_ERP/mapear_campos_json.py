# scripts_exploracao_ERP/mapear_campos_json.py

# Função Objetivo: Lê o JSON mais recente salvo em saidas/ e gera um mapa
# de campos — caminho completo (respeitando hierarquia, incluindo listas)
# e o(s) tipo(s) de valor visto em cada um — sem nenhum dado real. Existe
# pra poder compartilhar a FORMA da resposta do Sysemp sem expor dado
# fiscal sensível. Quando um campo mora dentro de uma lista, mostra também
# em quantos itens da lista ele apareceu (campo pode ser opcional).

import glob
import json
import os

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')


def _arquivo_json_mais_recente():
    arquivos = glob.glob(os.path.join(PASTA_SAIDAS, '*.json'))
    if not arquivos:
        raise RuntimeError(f'Nenhum .json encontrado em {PASTA_SAIDAS} — rode um script de exploração antes.')
    return max(arquivos, key=os.path.getmtime)


def _lista_pai(caminho):
    # Função Objetivo: Acha o caminho da lista mais próxima que envolve
    # este campo (ex: 'retorno[].emitente.cnpj' -> 'retorno[]') — usado só
    # pra calcular em quantos itens da lista o campo apareceu.
    indice = caminho.rfind('[]')
    if indice == -1:
        return None
    return caminho[:indice + 2]


def coletar_estrutura(dado, caminho, campos, contagem_listas):
    # Função Objetivo: Percorre o dado recursivamente e acumula, por
    # caminho de campo, o conjunto de tipos vistos e quantas vezes cada um
    # apareceu — nunca guarda o valor em si, só a forma.
    if isinstance(dado, dict):
        for chave, valor in dado.items():
            novo_caminho = f'{caminho}.{chave}' if caminho else chave
            coletar_estrutura(valor, novo_caminho, campos, contagem_listas)
    elif isinstance(dado, list):
        caminho_lista = f'{caminho}[]'
        contagem_listas[caminho_lista] = contagem_listas.get(caminho_lista, 0) + len(dado)
        for item in dado:
            coletar_estrutura(item, caminho_lista, campos, contagem_listas)
    else:
        entrada = campos.setdefault(caminho, {'tipos': set(), 'ocorrencias': 0})
        entrada['tipos'].add(type(dado).__name__)
        entrada['ocorrencias'] += 1


def formatar_mapa(campos, contagem_listas):
    # Função Objetivo: Transforma os dados coletados numa lista de linhas
    # de texto, ordenada por caminho, com tipo(s) e presença (quando o
    # campo mora dentro de alguma lista).
    linhas = []
    for caminho in sorted(campos.keys()):
        entrada = campos[caminho]
        tipos = ' | '.join(sorted(entrada['tipos']))
        lista_pai = _lista_pai(caminho)
        if lista_pai and contagem_listas.get(lista_pai):
            total = contagem_listas[lista_pai]
            presenca = f' (presente em {entrada["ocorrencias"]}/{total} itens)'
        else:
            presenca = ''
        linhas.append(f'{caminho}: {tipos}{presenca}')
    return linhas


caminho_json = _arquivo_json_mais_recente()
with open(caminho_json, encoding='utf-8') as arquivo:
    dado_bruto = json.load(arquivo)

campos = {}
contagem_listas = {}
coletar_estrutura(dado_bruto, '', campos, contagem_listas)
linhas_do_mapa = formatar_mapa(campos, contagem_listas)

print(f'Lendo: {caminho_json}')
print(f'{len(linhas_do_mapa)} campo(s) encontrado(s):\n')
for linha in linhas_do_mapa:
    print(linha)

caminho_saida = caminho_json.replace('.json', '_mapa_campos.txt')
with open(caminho_saida, 'w', encoding='utf-8') as arquivo:
    arquivo.write('\n'.join(linhas_do_mapa))
print(f'\nMapa salvo em: {caminho_saida}')