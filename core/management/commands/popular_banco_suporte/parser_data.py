# core/management/commands/popular_banco_suporte/parser_data.py

# Função Objetivo: Converte texto de data em datetime, com 2 formatos possíveis.
# Explicação em detalhe: reaproveitado por Anúncios ML, Promoções ML, Qualidade
# (formato ISO da API) e Produtos ERP (formato Excel brasileiro, dd/mm/aaaa).
# Antes duplicado em 4 lugares (3 cópias idênticas do ISO + 1 diferente do
# Excel) — unificado aqui numa classe só, com match/case interno (só 2
# variações, pouco provável crescer uma 3ª forma de data no projeto — se
# crescer, aí sim vale separar em subclasses).

import pandas as pd
from datetime import datetime
from django.utils import timezone


# Função Objetivo: Converte texto de data pro formato certo, por origem.
class ParserData:

    # Função Objetivo: Recebe qual formato de origem essa instância vai tratar.
    def __init__(self, origem):
        self.origem = origem  # 'iso' ou 'excel_br'

    # Função Objetivo: Roda o parsing certo, de acordo com a origem escolhida.
    def parsear(self, valor):
        match self.origem:
            case 'iso':
                return self._parsear_iso(valor)
            case 'excel_br':
                return self._parsear_excel_br(valor)
            case _:
                raise ValueError(f'Origem de data desconhecida: {self.origem}')

    # Função Objetivo: Converte texto ISO da API (2026-07-16T09:14:04Z).
    # Explicação em detalhe: quando vem só data, sem hora nem offset (ex:
    # "2026-07-05"), fromisoformat devolve datetime NAIVE — corrigido aqui
    # com o mesmo tratamento que _parsear_excel_br já tinha.
    def _parsear_iso(self, valor):
        if not valor:
            return None
        try:
            resultado = datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
        except Exception:
            return None
        if timezone.is_naive(resultado):
            resultado = timezone.make_aware(resultado)
        return resultado

    # Função Objetivo: Converte data do Excel, formato brasileiro (dd/mm/aaaa).
    # Explicação em detalhe: algumas linhas do ERP têm data "suja" (ex:
    # "01-07-2026 ( 0002 )", com número de pedido colado) — errors='coerce'
    # vira "sem data" em vez de travar a importação inteira.
    def _parsear_excel_br(self, valor):
        if pd.isna(valor):
            return None
        resultado = pd.to_datetime(valor, dayfirst=True, errors='coerce')
        if pd.isna(resultado):
            return None
        resultado = resultado.to_pydatetime()
        if timezone.is_naive(resultado):
            resultado = timezone.make_aware(resultado)
        return resultado