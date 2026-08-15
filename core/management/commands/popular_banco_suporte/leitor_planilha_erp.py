# core/management/commands/popular_banco_suporte/leitor_planilha_erp.py

# * [RESUMO] → Lê uma planilha do ERP linha por linha, devolvendo cada linha
#              como um dicionário {nome_da_coluna: valor}. Existe porque a
#              exportação do ERP tem colunas com nome duplicado (Marca, Grupo,
#              Subgrupo — cada uma aparece 2 vezes: uma como nome legível,
#              outra como ID numérico interno do ERP). A distinção é feita
#              pelo TIPO do valor (texto = nome real, número puro = ID
#              descartável), NUNCA pela posição da coluna — a ordem pode
#              mudar numa exportação futura do ERP, e confiar na posição
#              quebraria silenciosamente nesse caso.
#
#              Só resolve ambiguidade pras colunas duplicadas que alguém
#              realmente usa (hoje, só Marca — ver
#              LinhaProdutoERP.extrair_campos_basicos). Grupo/Subgrupo também
#              duplicam, mas ninguém lê esses campos ainda — resolvê-los
#              também faria a importação falhar por causa de uma coluna
#              irrelevante (achado real, 15/08: linha com Grupo=[None, None]
#              travava a importação inteira à toa). Se um dia alguém precisar
#              de Grupo/Subgrupo, é só adicionar o nome em
#              COLUNAS_DUPLICADAS_RESOLVIDAS.

import openpyxl
from collections import defaultdict

# * [EXPLICAÇÃO] → Só as colunas duplicadas que algum importador de fato lê.
COLUNAS_DUPLICADAS_RESOLVIDAS = {'Marca'}


# Função Objetivo: Diz se um valor de célula é um número puro (int/float).
def _eh_numero_puro(valor):
    if valor is None:
        return False
    if isinstance(valor, (int, float)):
        return True
    try:
        float(str(valor).strip().replace(',', '.'))
        return True
    except (TypeError, ValueError):
        return False


# Função Objetivo: Escolhe, entre os valores de uma coluna duplicada, qual é o texto real.
# Explicação em detalhe: linha sem NENHUM valor nas 2 ocorrências (ou só com
# valor numérico, sem nenhum texto) não é ambiguidade — é ausência real do
# dado (produto sem marca cadastrada no ERP), devolve None. A ambiguidade de
# verdade só existe quando sobra mais de 1 valor de TEXTO — aí sim não dá
# pra saber qual dos dois é o nome certo, e paramos com erro.
def _resolver_valor_duplicado(nome_coluna, valores):
    valores_presentes = [v for v in valores if v is not None]
    if not valores_presentes:
        return None

    textuais = [v for v in valores_presentes if not _eh_numero_puro(v)]
    if len(textuais) == 1:
        return textuais[0]
    if not textuais:
        # * [EXPLICAÇÃO] → Só sobrou ID numérico, sem nome — o nome real
        #                  está vazio nesta linha, tratado como ausente.
        return None

    raise ValueError(
        f"Coluna '{nome_coluna}' duplicada de forma ambígua — mais de 1 valor "
        f"de texto encontrado, não dá pra saber qual é o nome real: {valores!r}. "
        f"Verificar a planilha do ERP na fonte."
    )


# Função Objetivo: Lê a planilha inteira, devolvendo 1 dicionário por linha.
# Explicação em detalhe: linha 100% vazia é pulada (sobra comum no fim do
# arquivo exportado pelo ERP). Coluna sem duplicata é lida direto. Coluna
# duplicada só é resolvida se estiver em COLUNAS_DUPLICADAS_RESOLVIDAS —
# as demais (ex: Grupo, Subgrupo) são ignoradas de propósito, nunca entram
# no dicionário da linha.
def ler_linhas_planilha_erp(caminho, colunas_duplicadas_resolvidas=COLUNAS_DUPLICADAS_RESOLVIDAS):
    workbook = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    planilha = workbook.active

    linhas = planilha.iter_rows(values_only=True)
    cabecalho = next(linhas)

    posicoes_por_nome = defaultdict(list)
    for indice, nome in enumerate(cabecalho):
        posicoes_por_nome[nome].append(indice)

    linhas_como_dicionario = []
    for linha_bruta in linhas:
        if all(valor is None for valor in linha_bruta):
            continue

        linha_dicionario = {}
        for nome, posicoes in posicoes_por_nome.items():
            if len(posicoes) == 1:
                linha_dicionario[nome] = linha_bruta[posicoes[0]]
                continue

            if nome not in colunas_duplicadas_resolvidas:
                continue

            valores = [linha_bruta[i] for i in posicoes]
            linha_dicionario[nome] = _resolver_valor_duplicado(nome, valores)

        linhas_como_dicionario.append(linha_dicionario)

    workbook.close()
    return linhas_como_dicionario