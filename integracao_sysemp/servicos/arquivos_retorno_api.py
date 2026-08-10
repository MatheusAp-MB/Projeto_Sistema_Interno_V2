# integracao_sysemp/servicos/arquivos_retorno_api.py

# Função Objetivo: Ponto único de leitura/gravação dos 4 arquivos json
# fixos do retorno da API Sysemp (bruto, filtrado, notas mais recentes por
# produto, erros). Sempre sobrescreve — sem histórico por execução, mesma
# filosofia do guarda-chuva de impostos. Dado de API é caro, guardamos pra
# não precisar rechamar. Nenhuma função de negócio (filtro, seleção,
# orquestrador) sabe de disco por conta própria — só este módulo.

import json
import os

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_RETORNO_API = os.path.join(
    os.path.dirname(_PASTA_ATUAL), 'retorno_api', 'dados_impostos_xml_entrada',
)

NOME_ARQUIVO_BRUTO = 'XML_Manifesto_NF_Bruto.json'
NOME_ARQUIVO_FILTRADO = 'XML_Manifesto_NF_Filtrado.json'
NOME_ARQUIVO_NOTAS_MAIS_RECENTES = 'XML_Manifesto_NF_notas_mais_recentes_por_produto.json'
NOME_ARQUIVO_ERROS = 'XML_Manifesto_NF_Erros.json'


def salvar_json(dados, nome_arquivo: str) -> None:
    os.makedirs(PASTA_RETORNO_API, exist_ok=True)
    caminho = os.path.join(PASTA_RETORNO_API, nome_arquivo)
    with open(caminho, 'w', encoding='utf-8') as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


def ler_json(nome_arquivo: str, padrao=None):
    caminho = os.path.join(PASTA_RETORNO_API, nome_arquivo)
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, encoding='utf-8') as arquivo:
        return json.load(arquivo)