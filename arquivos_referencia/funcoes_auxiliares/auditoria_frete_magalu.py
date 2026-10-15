# arquivos_referencia/funcoes_auxiliares/auditoria_frete_magalu.py

# Função Objetivo: Audita a planilha da tabela de frete do Magalu (peso × reputação do vendedor). Espelha
# core/management/commands/popular_banco_suporte/importar_tabela_frete_magalu.py.
#
# * [EXPLICAÇÃO] → Colunas (posições vêm do importador): A rótulo (não usada) · B reputação <92% (0% de desconto) ·
#   C reputação 92–97% (25%) · D reputação >97% (50%) · E peso mínimo · F peso máximo (vazio só na última faixa).
# * [DECISÃO, 15/10/2026] → Regra própria do Magalu: o desconto por reputação está ESCRITO no cabeçalho
#   ("(25% desconto)"). A auditoria usa esse texto para conferir cada linha (valor da coluna C ≈ B menos 25%, D ≈ B
#   menos 50%). É o que pega um valor digitado errado no meio de 27 linhas, que o olho não vê.

import re

from .auditor_tabela_por_peso import AuditorDeTabelaPorPeso
from .auditor_base import celula
from .relatorio_auditoria import formatar_dinheiro

TOLERANCIA_DO_DESCONTO_EM_REAIS = 0.011    # o Magalu arredonda para o centavo (26,925 vira 26,93)


class AuditorFreteMagalu(AuditorDeTabelaPorPeso):

    NOME_DA_TABELA = 'Frete — Magalu'
    QUANTAS_COLUNAS_DEFINEM_LINHA_VAZIA = 4   # igual ao importador: `row[:4]`

    def carregar_layout(self):
        from core.management.commands.popular_banco_suporte import importar_tabela_frete_magalu as importador
        self.coluna_peso_min = importador.COL_PESO_MIN
        self.coluna_peso_max = importador.COL_PESO_MAX
        self.coluna_baixa = importador.COL_VALOR_BAIXA
        self.coluna_media = importador.COL_VALOR_MEDIA
        self.coluna_alta = importador.COL_VALOR_ALTA
        self.colunas_de_valor = [
            (self.coluna_baixa, 'Reputação <92% (R$)'),
            (self.coluna_media, 'Reputação 92–97% (R$)'),
            (self.coluna_alta, 'Reputação >97% (R$)'),
        ]

    def cabecalho_esperado(self):
        return [
            (self.coluna_baixa, 'frete para reputação abaixo de 92%', ['92']),
            (self.coluna_media, 'frete para reputação entre 92% e 97%', ['92', '97']),
            (self.coluna_alta, 'frete para reputação acima de 97%', ['97']),
            (self.coluna_peso_min, 'Peso mínimo', ['minimo']),
            (self.coluna_peso_max, 'Peso máximo', ['maximo']),
        ]

    # Função Objetivo: Reputação melhor = frete menor; e os descontos escritos no cabeçalho têm que bater com os valores.
    def regras_extras(self, aba, registros):
        percentuais = [self._percentual_do_cabecalho(i) for i in (self.coluna_baixa, self.coluna_media, self.coluna_alta)]
        sabe_os_descontos = all(p is not None for p in percentuais)

        for r in registros:
            if not r.confiavel:
                continue
            baixa, media, alta = r.valores
            if not (baixa >= media >= alta):
                self.relatorio.aviso(
                    self.local(aba, r.n_linha),
                    f'Os fretes não diminuem com a reputação: {formatar_dinheiro(baixa)} (<92%), '
                    f'{formatar_dinheiro(media)} (92–97%), {formatar_dinheiro(alta)} (>97%).',
                    'Quanto melhor a reputação, menor o frete. Confira se algum valor foi digitado errado.',
                )
                continue
            if not sabe_os_descontos or (1 - percentuais[0] / 100) == 0:
                continue
            base = baixa / (1 - percentuais[0] / 100)
            for posicao, coluna in ((1, self.coluna_media), (2, self.coluna_alta)):
                esperado = base * (1 - percentuais[posicao] / 100)
                if abs(r.valores[posicao] - esperado) > TOLERANCIA_DO_DESCONTO_EM_REAIS:
                    self.relatorio.aviso(
                        self.local(aba, r.n_linha, coluna),
                        f'Com {percentuais[posicao]:g}% de desconto sobre {formatar_dinheiro(base)} o valor seria '
                        f'{formatar_dinheiro(esperado)}, mas está {formatar_dinheiro(r.valores[posicao])}.',
                        'Confira qual está certo: o valor desta coluna ou o da coluna sem desconto.',
                    )

    # Função Objetivo: Lê "25%" de "Entre 92% e 97% (25% desconto)".
    def _percentual_do_cabecalho(self, coluna):
        titulo = self.titulos_das_colunas.get(coluna, '')
        achado = re.search(r'(\d+(?:[.,]\d+)?)\s*%\s*desconto', titulo, flags=re.IGNORECASE)
        return float(achado.group(1).replace(',', '.')) if achado else None
