# arquivos_referencia/funcoes_auxiliares/auditoria_frete_ml.py

# Função Objetivo: Audita a planilha da tabela de frete do Mercado Livre (peso × preço × regime). Espelha
# core/management/commands/popular_banco_suporte/importar_tabela_frete_ml.py.
#
# * [EXPLICAÇÃO] → Como o importador lê (e a auditoria reproduz):
#   - linha 1 = cabeçalho; as colunas F..M (8) têm o TEXTO da faixa de preço ("R$ 19 a R$ 48,99"): o importador tira
#     os números do texto. Cabeçalho sem número vira "a partir de R$ 0" EM SILÊNCIO — por isso é erro aqui;
#   - linha de dado = qualquer linha com "Peso mín." (coluna B) preenchido; sem isso a linha é IGNORADA (é assim que as
#     notas de rodapé são puladas) — então uma linha de dado sem peso mínimo some sem aviso. Aqui vira erro;
#   - são 2 linhas por faixa de peso, uma por Regime (coluna D, texto exato "Sem Frete Grátis Rápido" ou "Com Frete
#     Grátis Rápido"); Regime com qualquer outro texto (até um espaço a mais) é pulado pelo importador;
#   - peso máximo: número, ou texto "sem limite" na última faixa. QUALQUER texto ali é lido como "sem limite" — um
#     "0,5" digitado como texto viraria uma faixa sem teto. Aqui só "sem limite" passa;
#   - a chave de cada valor é (peso mínimo, preço mínimo, regime): linha repetida sobrescreve a anterior em silêncio.
# * [IMPORTANTE] → Os textos válidos do Regime vêm do próprio model (FreteML.Regime), via o importador — nunca
#   escritos de novo aqui.

import re

from openpyxl.utils import get_column_letter

from .auditor_base import AuditorDeTabela, celula, sem_acentos
from .regras_de_faixas import (
    FOLGA_DO_PESO_DO_ML, FOLGA_DO_PRECO_EM_REAIS, Faixa, Ponto, verificar_sequencia_de_faixas,
    verificar_valores_nao_decrescentes,
)
from .relatorio_auditoria import (
    descrever_local, formatar_dinheiro, formatar_numero, formatar_peso, limpar_texto, montar_previa,
)
from .valores_de_celula import LeitorDeNumeros, ler_numero

QUANTIDADE_DE_FAIXAS_DE_PRECO = 8
PADRAO_DE_NUMERO = re.compile(r'\d+(?:[.,]\d+)?')


class FaixaDePreco:

    def __init__(self, coluna, texto, minimo, maximo, tem_numero):
        self.coluna = coluna
        self.texto = texto
        self.minimo = minimo
        self.maximo = maximo
        self.tem_numero = tem_numero


class RegistroDeFreteML:

    def __init__(self, n_linha, rotulo, regime_texto, minimo, maximo, valores):
        self.n_linha = n_linha
        self.rotulo = rotulo
        self.regime_texto = regime_texto
        self.minimo = minimo
        self.maximo = maximo          # None = sem limite
        self.valores = valores        # 8 valores (None = célula vazia)
        self.confiavel = True         # vira False se alguma célula-chave da linha teve problema


class AuditorFreteML(AuditorDeTabela):

    NOME_DA_TABELA = 'Frete — Mercado Livre'

    # Função Objetivo: Busca no importador as posições das colunas e o leitor do cabeçalho (fonte única).
    def carregar_layout(self):
        from core.management.commands.popular_banco_suporte import importar_tabela_frete_ml as importador
        self.coluna_peso_min = importador.COLUNA_PESO_MIN
        self.coluna_peso_max = importador.COLUNA_PESO_MAX
        self.coluna_regime = importador.COLUNA_REGIME
        self.coluna_inicial_dos_precos = importador.COLUNA_INICIO_PRECOS
        self.regimes_validos = list(importador.REGIME_POR_TEXTO_PLANILHA.keys())
        # O texto do cabeçalho é lido pelo MESMO código do importador (não por uma cópia).
        self._importador_para_ler_faixa = importador.ImportadorFreteML(None, None)

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

        # O cabeçalho do ML é conferido pelas colunas fixas e pelas 8 faixas de preço.
        colunas_fixas_ok = self.conferir_cabecalho(aba, linhas[0], [
            (self.coluna_peso_min, 'Peso mín. (kg)', ['peso', 'min']),
            (self.coluna_peso_max, 'Peso máx. (kg)', ['peso', 'max']),
            (self.coluna_regime, 'Regime', ['regime']),
        ])
        faixas_de_preco = self._ler_faixas_de_preco(aba, linhas[0])
        if not colunas_fixas_ok or faixas_de_preco is None:
            return

        self._faixas_de_preco_lidas = faixas_de_preco
        registros = self._ler_linhas(aba, linhas, faixas_de_preco)
        self._conferir_faixas_de_peso(aba, registros)
        self._conferir_regimes_e_valores(aba, registros)
        self._resumir(registros, faixas_de_preco)
        self._montar_previa(aba, registros, faixas_de_preco)

    # Função Objetivo: Lê as 8 faixas de preço do cabeçalho e confere ordem, números e buracos.
    # Devolve a lista de FaixaDePreco, ou None se o cabeçalho de preço está quebrado (aí nada mais faz sentido conferir).
    def _ler_faixas_de_preco(self, aba, cabecalho):
        faixas, quebrou = [], False
        for deslocamento in range(QUANTIDADE_DE_FAIXAS_DE_PRECO):
            coluna = self.coluna_inicial_dos_precos + deslocamento
            bruto = celula(cabecalho, coluna)
            texto = limpar_texto(bruto) if bruto is not None else ''
            if not texto or not PADRAO_DE_NUMERO.search(texto):
                quebrou = True
                visto = f'“{texto}”' if texto else 'uma célula vazia'
                self.relatorio.erro(
                    descrever_local(aba, 1, coluna),
                    f'O cabeçalho desta coluna deveria ser uma faixa de preço (ex.: “R$ 19 a R$ 48,99”), mas tem {visto}.',
                    f'O sistema lê {QUANTIDADE_DE_FAIXAS_DE_PRECO} faixas de preço, nas colunas F a M. Sem número no '
                    'cabeçalho ele leria “a partir de R$ 0”.',
                )
                continue
            minimo, maximo = self._importador_para_ler_faixa._parsear_faixa_preco(texto)
            faixas.append(FaixaDePreco(coluna, texto, float(minimo), None if maximo is None else float(maximo), True))
        if quebrou:
            return None

        # As 8 faixas estão lado a lado na linha 1: em Faixa.linha vai o ÍNDICE DA COLUNA (a posição da faixa).
        verificar_sequencia_de_faixas(
            self.relatorio, [Faixa(f.coluna, f.minimo, f.maximo) for f in faixas],
            descrever_local=lambda coluna: self.local(aba, 1, coluna),
            posicao=lambda coluna: f'coluna {get_column_letter(coluna + 1)}',
            formatar=formatar_dinheiro, nome='preço',
            consequencia='anúncios com preço nesse intervalo ficariam sem frete.',
            folga_entre_faixas=FOLGA_DO_PRECO_EM_REAIS, ultima_deve_ser_aberta=True,
            grupo='faixas de preço do cabeçalho',
        )
        return faixas

    # Função Objetivo: Lê as linhas de dado do mesmo jeito do importador e registra os erros de célula.
    def _ler_linhas(self, aba, linhas, faixas_de_preco):
        leitor = LeitorDeNumeros(self.relatorio, aba)
        registros = []

        for n_linha, linha in enumerate(linhas[1:], start=2):
            peso_minimo_bruto = celula(linha, self.coluna_peso_min)
            if peso_minimo_bruto is None:
                # O importador ignora a linha. Se ela tem DADO (não é nota de rodapé), isso é uma perda silenciosa.
                if any(celula(linha, c) is not None for c in range(self.coluna_peso_max, self.coluna_inicial_dos_precos + QUANTIDADE_DE_FAIXAS_DE_PRECO)):
                    self.relatorio.erro(
                        self.local(aba, n_linha, self.coluna_peso_min),
                        'A linha tem dados mas o peso mínimo está vazio — o sistema ignora esta linha inteira.',
                        'Preencha o peso mínimo ou apague a linha.',
                    )
                continue

            minimo, ok_minimo = leitor.ler(n_linha, self.coluna_peso_min, peso_minimo_bruto,
                                           self.titulos_das_colunas.get(self.coluna_peso_min))
            maximo, ok_maximo = self._ler_peso_maximo(aba, n_linha, celula(linha, self.coluna_peso_max))
            regime_texto, ok_regime = self._ler_regime(aba, n_linha, celula(linha, self.coluna_regime))

            valores = []
            for faixa in faixas_de_preco:
                bruto = celula(linha, faixa.coluna)
                if bruto is None:
                    self.relatorio.aviso(
                        self.local(aba, n_linha, faixa.coluna),
                        'Esta faixa de preço está sem valor de frete — o sistema não grava esta combinação.',
                        'Preencha o valor, se ele existe.',
                    )
                    valores.append(None)
                    continue
                valor, ok = leitor.ler(n_linha, faixa.coluna, bruto, self.titulos_das_colunas.get(faixa.coluna))
                if ok and valor == 0:
                    self.relatorio.aviso(
                        self.local(aba, n_linha, faixa.coluna), 'O frete está em R$ 0,00.',
                        'Confira se é isso mesmo ou se faltou digitar o valor.',
                    )
                valores.append(valor if ok else None)

            confiavel = ok_minimo and ok_maximo and ok_regime
            registro = RegistroDeFreteML(n_linha, celula(linha, 0), regime_texto, minimo, maximo, valores)
            registro.confiavel = confiavel
            registros.append(registro)
        return registros

    # Função Objetivo: Peso máximo: número, vazio ou "sem limite". Qualquer outro texto é erro (o importador leria como "sem limite").
    def _ler_peso_maximo(self, aba, n_linha, bruto):
        if bruto is None:
            return None, True
        if isinstance(bruto, str):
            if sem_acentos(limpar_texto(bruto)) == 'sem limite':
                return None, True
            self.relatorio.erro(
                self.local(aba, n_linha, self.coluna_peso_max),
                f'O peso máximo tem o texto “{limpar_texto(bruto)}”. O sistema leria qualquer texto aqui como “sem limite”.',
                'Digite o peso como NÚMERO (ex.: 0,5). Só a última faixa usa o texto “sem limite”.',
            )
            return None, False
        valor, problema = ler_numero(bruto)
        if problema is not None:
            leitor = LeitorDeNumeros(self.relatorio, aba)
            leitor.ler(n_linha, self.coluna_peso_max, bruto, self.titulos_das_colunas.get(self.coluna_peso_max), obrigatorio=False)
            return None, False
        if valor < 0:
            self.relatorio.erro(self.local(aba, n_linha, self.coluna_peso_max), f'O valor {valor} é negativo.',
                                'Confira o sinal: pesos não são negativos.')
            return None, False
        # Número gigante é o jeito antigo de dizer "sem limite" (o importador também reconhece).
        return (None if valor >= 999999999 else valor), True

    # Função Objetivo: Regime precisa ser EXATAMENTE um dos 2 textos do model.
    def _ler_regime(self, aba, n_linha, bruto):
        if bruto in self.regimes_validos:
            return bruto, True
        validos = ' ou '.join(f'“{t}”' for t in self.regimes_validos)
        if bruto is None:
            o_que = 'O regime está vazio — o sistema pula esta linha.'
        else:
            dica = ''
            if isinstance(bruto, str) and limpar_texto(bruto) in self.regimes_validos:
                dica = ' (o texto tem espaços sobrando)'
            o_que = f'O regime “{bruto}” não é um dos válidos{dica} — o sistema pula esta linha.'
        self.relatorio.erro(
            self.local(aba, n_linha, self.coluna_regime), o_que,
            f'Use exatamente {validos}, sem espaço sobrando no começo ou no fim.',
        )
        return bruto, False

    # Função Objetivo: Para cada regime separadamente: faixas de peso repetidas, buracos e teto.
    def _conferir_faixas_de_peso(self, aba, registros):
        tudo_lido = all(r.confiavel for r in registros)
        if not tudo_lido:
            self.relatorio.resumir('Buracos e faixas faltando', 'não conferidos até corrigir os erros')
        for regime in self.regimes_validos:
            do_regime = [r for r in registros if r.confiavel and r.regime_texto == regime]
            verificar_sequencia_de_faixas(
                self.relatorio, [Faixa(r.n_linha, r.minimo, r.maximo) for r in do_regime],
                descrever_local=lambda linha: self.local(aba, linha, self.coluna_peso_min),
                formatar=formatar_peso, nome='peso',
                consequencia='produtos com peso nesse intervalo ficariam sem frete.',
                folga_entre_faixas=FOLGA_DO_PESO_DO_ML, ultima_deve_ser_aberta=True,
                grupo=f'regime “{regime}”', conferir_continuidade=tudo_lido,
            )

    # Função Objetivo: Os 2 regimes têm as mesmas faixas de peso? E o frete só sobe com o peso e com o preço?
    def _conferir_regimes_e_valores(self, aba, registros):
        por_regime = {}
        for r in registros:
            if r.confiavel:
                por_regime.setdefault(r.regime_texto, {}).setdefault(round(r.minimo, 6), r)

        todos_os_pesos = sorted({peso for faixas in por_regime.values() for peso in faixas})
        for regime, faixas in (por_regime.items() if all(r.confiavel for r in registros) else []):
            for peso in todos_os_pesos:
                if peso not in faixas:
                    self.relatorio.aviso(
                        self.local(aba),
                        f'Falta a faixa que começa em {formatar_peso(peso)} no regime “{regime}” (o outro regime tem).',
                        'Cada faixa de peso deve ter as 2 linhas: “Sem” e “Com Frete Grátis Rápido”.',
                    )

        for regime, faixas in por_regime.items():
            ordenados = [faixas[peso] for peso in sorted(faixas)]
            # frete sobe com o peso (cada faixa de preço, de cima para baixo)
            for posicao, faixa_de_preco in enumerate(self._faixas_de_preco_lidas):
                pontos = [Ponto(r.n_linha, faixa_de_preco.coluna, r.valores[posicao]) for r in ordenados if r.valores[posicao] is not None]
                verificar_valores_nao_decrescentes(
                    self.relatorio, pontos,
                    descrever_local=lambda linha, coluna: self.local(aba, linha, coluna),
                    formatar_valor=formatar_dinheiro,
                    quando=f'ao passar para a faixa de peso seguinte ({regime})',
                )
            # frete sobe com o preço (cada linha, da esquerda para a direita)
            for r in ordenados:
                pontos = [Ponto(r.n_linha, f.coluna, v) for f, v in zip(self._faixas_de_preco_lidas, r.valores) if v is not None]
                verificar_valores_nao_decrescentes(
                    self.relatorio, pontos,
                    descrever_local=lambda linha, coluna: self.local(aba, linha, coluna),
                    formatar_valor=formatar_dinheiro,
                    quando='ao passar para a faixa de preço seguinte (mais cara)',
                )

    def _resumir(self, registros, faixas_de_preco):
        confiaveis = [r for r in registros if r.confiavel]
        pesos = {round(r.minimo, 6) for r in confiaveis}
        valores = sum(1 for r in confiaveis for v in r.valores if v is not None)
        self.relatorio.resumir('Faixas de peso', len(pesos))
        self.relatorio.resumir('Regimes', len({r.regime_texto for r in confiaveis}))
        self.relatorio.resumir('Faixas de preço', len(faixas_de_preco))
        self.relatorio.resumir('Valores de frete lidos', valores)

    def _montar_previa(self, aba, registros, faixas_de_preco):
        colunas = ['Linha', 'Peso mín. (kg)', 'Peso máx. (kg)', 'Regime'] + [f.texto for f in faixas_de_preco]
        linhas = []
        for r in registros:
            linhas.append(
                [r.n_linha, formatar_numero(r.minimo), formatar_numero(r.maximo) if r.maximo is not None else 'sem limite',
                 r.regime_texto if r.regime_texto is not None else '—']
                + [formatar_dinheiro(v) if v is not None else '—' for v in r.valores]
            )
        self.relatorio.adicionar_previa(montar_previa(f'Frete lido da aba “{aba}”', colunas, linhas))
