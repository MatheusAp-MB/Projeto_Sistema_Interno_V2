# core/funcoes_auxiliares/cabecalhos_ordenaveis.py

# Função Objetivo: Monta os cabeçalhos ordenáveis (link + seta + destaque) de qualquer
# tela com tabela filtrável.
# Explicação em detalhe: promovida de produtos/funcoes_auxiliares/contexto_tela_produtos.py
# (24/07) — já nasceu genérica, promovida pra core no 2º uso real (agenda_videos), seguindo
# a regra de nunca generalizar de 1 caso só. Refatorada nesta promoção: devolve uma
# dataclass em vez de dict cru, alinhando com o padrão de encapsulamento do resto do
# projeto — templates continuam funcionando sem mudança nenhuma.

from dataclasses import dataclass


# Função Objetivo: Representa 1 cabeçalho de coluna ordenável, pronto pro template.
@dataclass
class CabecalhoOrdenavel:
    label: str
    href: str
    icone: str
    ativo: bool


# Função Objetivo: Monta o link/seta de ordenação de cada cabeçalho de coluna de 1 tela.
class ConstrutorCabecalhosOrdenacao:

    def __init__(self, ordenar, querystring_base):
        self.ordenar = ordenar
        self.querystring_base = querystring_base

    # Função Objetivo: Monta 1 cabeçalho (chave, label).
    def _montar_um(self, chave, label):
        ativo = self.ordenar.lstrip('-') == chave
        esta_asc = ativo and not self.ordenar.startswith('-')
        proximo = f'-{chave}' if esta_asc else chave

        if not ativo:
            icone = 'fa-sort'
        elif esta_asc:
            icone = 'fa-sort-up'
        else:
            icone = 'fa-sort-down'

        return CabecalhoOrdenavel(
            label=label, icone=icone, ativo=ativo,
            href=f'?{self.querystring_base}&ordenar={proximo}',
        )

    # Função Objetivo: Monta todos os cabeçalhos, a partir do dicionário de rótulos.
    def montar(self, labels_colunas):
        return {chave: self._montar_um(chave, label) for chave, label in labels_colunas.items()}