# arquivos_referencia/funcoes_auxiliares/auditor_tabela_por_peso.py

# Função Objetivo: Auditor das tabelas de frete "só por peso" — 1 linha = 1 faixa de peso, com 1 ou mais colunas
# de valor. Hoje: Magalu (3 colunas, uma por reputação) e TikTok Shop (1 coluna). A leitura espelha os importadores
# (importar_tabela_frete_magalu.py e importar_tabela_frete_tiktok.py).
#
# * [EXPLICAÇÃO] → O que os importadores fazem e a auditoria precisa reproduzir:
#   - o cabeçalho é a linha 1 e os dados começam na linha 2;
#   - a linha é IGNORADA se as primeiras colunas (A–D no Magalu, A–B no TikTok) estão todas vazias;
#   - peso mínimo é obrigatório (vazio = erro); peso máximo vazio = "sem teto" (só vale na última faixa);
#   - a coluna A é só um rótulo ("0-0,499") que o sistema não usa — mas serve de conferência: se o rótulo diz
#     "2-4,999" e o peso mínimo da linha é 5, alguém digitou errado.

import re

from .auditor_base import AuditorDeTabela, celula
from .regras_de_faixas import (
    FOLGA_DO_PESO_EM_KG, Faixa, Ponto, verificar_sequencia_de_faixas, verificar_valores_nao_decrescentes,
)
from .relatorio_auditoria import formatar_dinheiro, formatar_numero, formatar_peso, montar_previa
from .valores_de_celula import LeitorDeNumeros

TOLERANCIA_DO_ROTULO = 0.0011   # "0-0,5KG" no rótulo e 0,499 no peso máximo (a tabela real faz isso)


class RegistroDePeso:

    # Função Objetivo: 1 linha de dado já lida (faixa de peso + valores de frete).
    def __init__(self, n_linha, rotulo, minimo, maximo, valores, confiavel=True):
        self.n_linha = n_linha
        self.rotulo = rotulo
        self.minimo = minimo
        self.maximo = maximo
        self.valores = valores     # lista na mesma ordem de colunas_de_valor
        self.confiavel = confiavel  # False se alguma célula da linha teve problema (a linha fica fora das conferências de faixa)


class AuditorDeTabelaPorPeso(AuditorDeTabela):

    # Cada tabela define o que ela é (as subclasses preenchem):
    NOME_DA_TABELA = ''
    COLUNA_DO_ROTULO = 0
    QUANTAS_COLUNAS_DEFINEM_LINHA_VAZIA = 2

    # Função Objetivo: Cada subclasse devolve as posições, buscando-as no importador (fonte única).
    def carregar_layout(self):
        raise NotImplementedError

    # Função Objetivo: Cada subclasse devolve a lista de (indice, nome_esperado, palavras) do cabeçalho.
    def cabecalho_esperado(self):
        raise NotImplementedError

    # Função Objetivo: Gancho para regras exclusivas da tabela (ex.: descontos por reputação do Magalu).
    def regras_extras(self, aba, registros):
        pass

    # Função Objetivo: Roda a auditoria inteira e preenche o relatório.
    def auditar(self):
        self.carregar_layout()
        aba = self.leitura.nome_da_aba_ativa
        linhas = self.leitura.linhas(aba)
        self.avisar_abas_extras()

        if not linhas:
            self.relatorio.erro(self.local(aba), 'A aba está vazia.', 'Confira se é o arquivo certo.')
            return

        self.memorizar_titulos(linhas[0])
        self.apontar_formulas_sem_resultado(aba)
        if self.cabecalho_esta_em_outra_linha(aba, linhas, self.cabecalho_esperado()):
            return
        if not self.conferir_cabecalho(aba, linhas[0], self.cabecalho_esperado()):
            return  # colunas fora do lugar: o resto da conferência só geraria ruído

        registros = self._ler_linhas(aba, linhas)
        self._conferir_faixas(aba, registros)
        self.regras_extras(aba, registros)
        self._resumir(registros)
        self._montar_previa(aba, registros)

    # Função Objetivo: Lê as linhas de dado (da 2 em diante) do mesmo jeito do importador e registra erros de célula.
    def _ler_linhas(self, aba, linhas):
        leitor = LeitorDeNumeros(self.relatorio, aba)
        registros = []

        for n_linha, linha in enumerate(linhas[1:], start=2):
            vazia_para_o_importador = all(celula(linha, i) is None for i in range(self.QUANTAS_COLUNAS_DEFINEM_LINHA_VAZIA))
            if vazia_para_o_importador:
                if celula(linha, self.coluna_peso_min) is not None or celula(linha, self.coluna_peso_max) is not None:
                    self.relatorio.erro(
                        self.local(aba, n_linha),
                        'A linha tem peso preenchido mas nenhum valor de frete — o sistema ignora esta linha.',
                        'Preencha os valores de frete ou apague a linha inteira.',
                    )
                continue

            minimo, ok_minimo = leitor.ler(n_linha, self.coluna_peso_min, celula(linha, self.coluna_peso_min),
                                           self.titulos_das_colunas.get(self.coluna_peso_min), obrigatorio=True)
            maximo, ok_maximo = leitor.ler(n_linha, self.coluna_peso_max, celula(linha, self.coluna_peso_max),
                                           self.titulos_das_colunas.get(self.coluna_peso_max), obrigatorio=False)

            valores, tudo_certo = [], ok_minimo and ok_maximo
            for indice, _ in self.colunas_de_valor:
                valor, ok = leitor.ler(n_linha, indice, celula(linha, indice), self.titulos_das_colunas.get(indice),
                                       obrigatorio=True)
                if ok and valor == 0:
                    self.relatorio.aviso(
                        self.local(aba, n_linha, indice),
                        'O frete está em R$ 0,00.',
                        'Confira se é isso mesmo (frete grátis) ou se faltou digitar o valor.',
                    )
                valores.append(valor)
                tudo_certo = tudo_certo and ok

            registro = RegistroDePeso(n_linha, celula(linha, self.COLUNA_DO_ROTULO), minimo, maximo, valores, tudo_certo)
            registros.append(registro)
            if tudo_certo:
                self._conferir_rotulo(aba, registro)
        return registros

    # Função Objetivo: O rótulo da coluna A ("2-4,999") tem que bater com os pesos da própria linha.
    def _conferir_rotulo(self, aba, registro):
        if registro.rotulo is None:
            return
        numeros = [float(n.replace(',', '.')) for n in re.findall(r'\d+(?:[.,]\d+)?', str(registro.rotulo))]
        if not numeros:
            return
        if abs(numeros[0] - registro.minimo) > TOLERANCIA_DO_ROTULO:
            self.relatorio.aviso(
                self.local(aba, registro.n_linha, self.coluna_peso_min),
                f'O nome da faixa (“{registro.rotulo}”) começa em {formatar_numero(numeros[0])}, mas o peso mínimo '
                f'da linha é {formatar_numero(registro.minimo)}.',
                'Confira qual dos dois está certo.',
            )
        if len(numeros) >= 2 and registro.maximo is not None and abs(numeros[1] - registro.maximo) > TOLERANCIA_DO_ROTULO:
            self.relatorio.aviso(
                self.local(aba, registro.n_linha, self.coluna_peso_max),
                f'O nome da faixa (“{registro.rotulo}”) termina em {formatar_numero(numeros[1])}, mas o peso máximo '
                f'da linha é {formatar_numero(registro.maximo)}.',
                'Confira qual dos dois está certo.',
            )

    # Função Objetivo: Faixas repetidas, buracos, teto no lugar errado e frete que cai quando o peso sobe.
    def _conferir_faixas(self, aba, registros):
        confiaveis = [r for r in registros if r.confiavel]
        tudo_lido = len(confiaveis) == len(registros)
        if not tudo_lido:
            self.relatorio.resumir('Buracos entre faixas', 'não conferidos até corrigir os erros')

        verificar_sequencia_de_faixas(
            self.relatorio,
            [Faixa(r.n_linha, r.minimo, r.maximo) for r in confiaveis],
            descrever_local=lambda linha: self.local(aba, linha, self.coluna_peso_min),
            formatar=formatar_peso, nome='peso',
            consequencia='produtos com peso nesse intervalo ficariam sem frete.',
            folga_entre_faixas=FOLGA_DO_PESO_EM_KG, ultima_deve_ser_aberta=True, conferir_continuidade=tudo_lido,
        )

        ordenados = sorted(confiaveis, key=lambda r: (r.minimo, r.n_linha))
        for posicao, (indice, _) in enumerate(self.colunas_de_valor):
            verificar_valores_nao_decrescentes(
                self.relatorio,
                [Ponto(r.n_linha, indice, r.valores[posicao]) for r in ordenados],
                descrever_local=lambda linha, coluna: self.local(aba, linha, coluna),
                formatar_valor=formatar_dinheiro,
                quando='ao passar para a faixa de peso seguinte (mais pesada)',
            )

    def _resumir(self, registros):
        confiaveis = [r for r in registros if r.confiavel]
        self.relatorio.resumir('Faixas de peso lidas', len(registros))
        self.relatorio.resumir('Valores de frete lidos', len(confiaveis) * len(self.colunas_de_valor))
        if confiaveis:
            menor = min(r.minimo for r in confiaveis)
            abertas = [r for r in confiaveis if r.maximo is None]
            maior = max(r.maximo for r in confiaveis if r.maximo is not None) if any(r.maximo is not None for r in confiaveis) else None
            alcance = f'de {formatar_peso(menor)} até ' + ('sem limite' if abertas else formatar_peso(maior))
            self.relatorio.resumir('Pesos cobertos', alcance)

    def _montar_previa(self, aba, registros):
        colunas = ['Linha', 'Faixa (rótulo)', 'Peso mín. (kg)', 'Peso máx. (kg)'] + [t for _, t in self.colunas_de_valor]
        linhas = []
        for r in registros:
            linhas.append(
                [r.n_linha, '' if r.rotulo is None else str(r.rotulo), formatar_numero(r.minimo),
                 formatar_numero(r.maximo) if r.maximo is not None else 'sem limite']
                + [formatar_dinheiro(v) for v in r.valores]
            )
        self.relatorio.adicionar_previa(montar_previa(f'Faixas de peso lidas da aba “{aba}”', colunas, linhas))
