# core/management/commands/popular_banco_suporte/conversor_celula_excel.py

# Função Objetivo: Converte célula bruta do Excel em Decimal/texto, com segurança.
# Explicação em detalhe: reaproveitado por Produtos ERP e Planilha Validada —
# os 2 leem via openpyxl direto (não pandas, desde 15/08 — ver
# leitor_planilha_erp.py). Mantido com 2 variações internas (pandas/openpyxl)
# porque representam "célula vazia" de formas diferentes (pandas usa NaN;
# openpyxl usa None ou texto de erro de fórmula, tipo "#N/A"/"#REF!") — se
# algum arquivo novo voltar a usar pandas no futuro, a variação já existe aqui.
#
# NÃO inclui conversão fração→percentual (_pct do arquivo original) — essa
# é uma transformação própria, sem equivalente no outro arquivo, continua
# só onde já está.

import pandas as pd
from decimal import Decimal


# Função Objetivo: Converte célula do Excel pro tipo certo, por origem.
class ConversorCelulaExcel:

    # Função Objetivo: Recebe qual biblioteca de leitura essa instância trata.
    def __init__(self, origem):
        self.origem = origem  # 'pandas' ou 'openpyxl'

    # Função Objetivo: Converte pra Decimal, tratando célula vazia.
    def para_decimal(self, valor, padrao=None, casas_decimais=None):
        match self.origem:
            case 'pandas':
                return self._converter_pandas(valor, padrao)
            case 'openpyxl':
                return self._converter_openpyxl(valor, padrao, casas_decimais)
            case _:
                raise ValueError(f'Origem de célula desconhecida: {self.origem}')

    # Função Objetivo: Converte pra texto, tratando célula vazia.
    # Explicação em detalhe (17/08/2026): checa se ficou vazio DEPOIS do
    # strip, não só se é None — célula com espaço em branco (ou string
    # vazia gravada) passava pela checagem de None e virava '' em vez de
    # cair no padrao. Achado real: 2+ produtos com "Codigo Auxiliar" em
    # branco (mas não None) geravam sku='' pra mais de 1 produto, colidindo
    # na constraint unique do banco (bulk_create).
    def para_texto(self, valor, padrao=None):
        match self.origem:
            case 'pandas':
                texto = str(valor).strip() if pd.notna(valor) else ''
            case 'openpyxl':
                valor_filtrado = self._filtrar_erro_formula(valor)
                texto = str(valor_filtrado).strip() if valor_filtrado is not None else ''
            case _:
                raise ValueError(f'Origem de célula desconhecida: {self.origem}')
        return texto if texto else padrao

    # Função Objetivo: Converte célula do pandas — vazio detectado via NaN.
    def _converter_pandas(self, valor, padrao):
        if pd.isna(valor):
            return Decimal(str(padrao)) if padrao is not None else None
        return Decimal(str(valor))

    # Função Objetivo: Converte célula do openpyxl — vazio via None/erro de fórmula.
    def _converter_openpyxl(self, valor, padrao, casas_decimais):
        valor_filtrado = self._filtrar_erro_formula(valor)
        if valor_filtrado is None:
            return padrao
        if casas_decimais is not None:
            return Decimal(str(round(float(valor_filtrado), casas_decimais)))
        return Decimal(str(valor_filtrado))

    # Função Objetivo: Detecta erro de fórmula do Excel (#N/A, #REF!, etc).
    def _filtrar_erro_formula(self, valor):
        if valor is None:
            return None
        if isinstance(valor, str) and valor.strip().startswith('#'):
            return None
        return valor