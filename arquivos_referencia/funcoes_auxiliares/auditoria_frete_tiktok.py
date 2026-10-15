# arquivos_referencia/funcoes_auxiliares/auditoria_frete_tiktok.py

# Função Objetivo: Audita a planilha da tabela de frete do TikTok Shop (só peso × valor médio). Espelha
# core/management/commands/popular_banco_suporte/importar_tabela_frete_tiktok.py.
#
# * [EXPLICAÇÃO] → Colunas (posições vêm do importador): A rótulo (não usada) · B valor médio (R$) · C peso mínimo ·
#   D peso máximo (vazio só na última faixa). Sem regra própria: vale tudo que as tabelas "por peso" têm em comum.

from .auditor_tabela_por_peso import AuditorDeTabelaPorPeso


class AuditorFreteTiktok(AuditorDeTabelaPorPeso):

    NOME_DA_TABELA = 'Frete — TikTok Shop'
    QUANTAS_COLUNAS_DEFINEM_LINHA_VAZIA = 2   # igual ao importador: `row[:2]`

    def carregar_layout(self):
        from core.management.commands.popular_banco_suporte import importar_tabela_frete_tiktok as importador
        self.coluna_valor = importador.COL_VALOR
        self.coluna_peso_min = importador.COL_PESO_MIN
        self.coluna_peso_max = importador.COL_PESO_MAX
        self.colunas_de_valor = [(self.coluna_valor, 'Valor médio (R$)')]

    def cabecalho_esperado(self):
        return [
            (self.coluna_valor, 'Valor médio (R$)', ['valor']),
            (self.coluna_peso_min, 'Peso mínimo', ['minimo']),
            (self.coluna_peso_max, 'Peso máximo', ['maximo']),
        ]
