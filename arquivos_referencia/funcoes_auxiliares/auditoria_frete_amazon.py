# arquivos_referencia/funcoes_auxiliares/auditoria_frete_amazon.py

# Função Objetivo: Audita a planilha da tabela de frete da Amazon (DBA + FBA, peso × preço). Espelha
# core/management/commands/popular_banco_suporte/importar_tabela_frete_amazon.py.
#
# * [EXPLICAÇÃO] → Como o importador lê (e a auditoria reproduz):
#   - 2 abas com NOME EXATO ("Frete Amazon_DBA" e "Frete Amazon_FBA"): o tipo vem do nome da aba, não de uma coluna;
#   - formato "longo": 1 linha = 1 combinação de faixa de peso × faixa de preço, colunas A..E (peso mín., peso máx.,
#     preço mín., preço máx., valor); a linha 1 é o cabeçalho;
#   - as primeiras faixas de PREÇO baixo (até R$ 78,99) não dependem de peso: nelas peso mínimo e máximo ficam vazios;
#   - preço mínimo é obrigatório (vazio = erro no importador); preço máximo vazio = "sem teto";
#   - a chave de cada valor é (tipo, peso mínimo, preço mínimo): linha repetida gravaria 2 vezes a mesma célula da matriz.
# * [DECISÃO, 15/10/2026] → Além das faixas de cada eixo, a auditoria confere a MATRIZ: toda faixa de peso tem que ter
#   todas as faixas de preço (se faltar 1 combinação, produtos naquele peso e preço ficam sem frete).

from .auditor_base import AuditorDeTabela, celula
from .regras_de_faixas import (
    FOLGA_DO_PESO_EM_KG, FOLGA_DO_PRECO_EM_REAIS, TOLERANCIA, Faixa, Ponto, verificar_sequencia_de_faixas,
    verificar_valores_nao_decrescentes,
)
from .relatorio_auditoria import formatar_dinheiro, formatar_numero, formatar_peso, montar_previa
from .valores_de_celula import LeitorDeNumeros


class LinhaAmazon:

    def __init__(self, n_linha, peso_min, peso_max, preco_min, preco_max, valor, confiavel):
        self.n_linha = n_linha
        self.peso_min = peso_min
        self.peso_max = peso_max
        self.preco_min = preco_min
        self.preco_max = preco_max
        self.valor = valor
        self.confiavel = confiavel

    @property
    def depende_do_peso(self):
        return self.peso_min is not None


class AuditorFreteAmazon(AuditorDeTabela):

    NOME_DA_TABELA = 'Frete — Amazon'

    # Função Objetivo: Busca no importador as posições das colunas e os nomes das abas (fonte única).
    def carregar_layout(self):
        from core.management.commands.popular_banco_suporte import importar_tabela_frete_amazon as importador
        self.coluna_peso_min = importador.COL_PESO_MIN
        self.coluna_peso_max = importador.COL_PESO_MAX
        self.coluna_preco_min = importador.COL_PRECO_MIN
        self.coluna_preco_max = importador.COL_PRECO_MAX
        self.coluna_valor = importador.COL_VALOR
        self.abas_por_tipo = dict(importador.ABAS_POR_TIPO)

    # Função Objetivo: Roda a auditoria inteira e preenche o relatório.
    def auditar(self):
        self.carregar_layout()
        nomes = self.leitura.nomes_das_abas

        for tipo, nome_da_aba in self.abas_por_tipo.items():
            if nome_da_aba not in nomes:
                self.relatorio.erro(
                    self.local(None),
                    f'Falta a aba “{nome_da_aba}”. O sistema só acha a tabela {tipo.upper()} por esse nome.',
                    'Renomeie ou crie a aba com exatamente esse nome (maiúsculas e sublinhado incluídos).',
                )
                continue
            self._auditar_aba(tipo, nome_da_aba)

        extras = [n for n in nomes if n not in self.abas_por_tipo.values()]
        if extras:
            self.relatorio.aviso(
                self.local(None),
                f'O arquivo tem abas que o sistema ignora: {", ".join(extras)}.',
                'Sem problema se for de propósito (anotações, por exemplo).',
            )

    def _auditar_aba(self, tipo, aba):
        linhas = self.leitura.linhas(aba)
        if not linhas:
            self.relatorio.erro(self.local(aba), 'A aba está vazia.', 'Confira se é o arquivo certo.')
            return

        self.memorizar_titulos(linhas[0])
        self.apontar_formulas_sem_resultado(aba)
        esperadas = [
            (self.coluna_peso_min, 'Peso mínimo', ['peso', 'min']),
            (self.coluna_peso_max, 'Peso máximo', ['peso', 'max']),
            (self.coluna_preco_min, 'Preço mínimo', ['preco', 'min']),
            (self.coluna_preco_max, 'Preço máximo', ['preco', 'max']),
            (self.coluna_valor, 'Valor', ['valor']),
        ]
        if self.cabecalho_esta_em_outra_linha(aba, linhas, esperadas):
            return
        cabecalho_ok = self.conferir_cabecalho(aba, linhas[0], esperadas)
        if not cabecalho_ok:
            return

        registros = self._ler_linhas(aba, linhas)
        confiaveis = [r for r in registros if r.confiavel]
        tudo_lido = len(confiaveis) == len(registros)
        if not tudo_lido:
            self.relatorio.resumir(f'{tipo.upper()} — buracos e faixas faltando', 'não conferidos até corrigir os erros')
        self._conferir_pesos(aba, confiaveis, tudo_lido)
        self._conferir_precos(aba, confiaveis, tudo_lido)
        if tudo_lido:
            self._conferir_matriz(aba, confiaveis)
        self._conferir_crescimento(aba, confiaveis)
        self._resumir(tipo, registros)
        self._montar_previa(aba, registros)

    # Função Objetivo: Lê as linhas de dado (da 2 em diante) do mesmo jeito do importador.
    def _ler_linhas(self, aba, linhas):
        leitor = LeitorDeNumeros(self.relatorio, aba)
        registros = []
        t = self.titulos_das_colunas

        for n_linha, linha in enumerate(linhas[1:], start=2):
            if all(celula(linha, i) is None for i in range(5)):
                continue   # igual ao importador: `if not any(v is not None for v in row[:5])`

            peso_min, ok1 = leitor.ler(n_linha, self.coluna_peso_min, celula(linha, self.coluna_peso_min), t.get(self.coluna_peso_min), obrigatorio=False)
            peso_max, ok2 = leitor.ler(n_linha, self.coluna_peso_max, celula(linha, self.coluna_peso_max), t.get(self.coluna_peso_max), obrigatorio=False)
            preco_min, ok3 = leitor.ler(n_linha, self.coluna_preco_min, celula(linha, self.coluna_preco_min), t.get(self.coluna_preco_min), obrigatorio=True)
            preco_max, ok4 = leitor.ler(n_linha, self.coluna_preco_max, celula(linha, self.coluna_preco_max), t.get(self.coluna_preco_max), obrigatorio=False)
            valor, ok5 = leitor.ler(n_linha, self.coluna_valor, celula(linha, self.coluna_valor), t.get(self.coluna_valor), obrigatorio=True)

            if ok5 and valor == 0:
                self.relatorio.aviso(self.local(aba, n_linha, self.coluna_valor), 'O frete está em R$ 0,00.',
                                     'Confira se é isso mesmo ou se faltou digitar o valor.')
            if ok1 and ok2 and peso_min is None and peso_max is not None:
                self.relatorio.aviso(
                    self.local(aba, n_linha, self.coluna_peso_max),
                    'Tem peso máximo mas não tem peso mínimo — o sistema trata a linha como “não depende de peso” e ignora o máximo.',
                    'Preencha o peso mínimo (faixa com peso) ou apague o peso máximo (faixa sem peso).',
                )
            registros.append(LinhaAmazon(n_linha, peso_min, peso_max, preco_min, preco_max, valor, ok1 and ok2 and ok3 and ok4 and ok5))
        return registros

    # Função Objetivo: Faixas de peso (uma por peso mínimo): buracos, teto, e a mesma faixa com 2 pesos máximos.
    def _conferir_pesos(self, aba, confiaveis, tudo_lido):
        por_minimo = {}
        for r in confiaveis:
            if r.depende_do_peso:
                por_minimo.setdefault(round(r.peso_min, 6), []).append(r)

        faixas = []
        for minimo, grupo in por_minimo.items():
            maximos = {None if r.peso_max is None else round(r.peso_max, 6) for r in grupo}
            if len(maximos) > 1:
                lista = ', '.join('sem limite' if m is None else formatar_peso(m) for m in sorted(maximos, key=lambda m: (m is None, m or 0)))
                self.relatorio.aviso(
                    self.local(aba, grupo[0].n_linha, self.coluna_peso_max),
                    f'A faixa de peso que começa em {formatar_peso(minimo)} aparece com pesos máximos diferentes: {lista}.',
                    'Todas as linhas da mesma faixa de peso devem ter o mesmo peso máximo.',
                )
            faixas.append(Faixa(grupo[0].n_linha, minimo, grupo[0].peso_max))

        verificar_sequencia_de_faixas(
            self.relatorio, faixas,
            descrever_local=lambda linha: self.local(aba, linha, self.coluna_peso_min),
            formatar=formatar_peso, nome='peso',
            consequencia='produtos com peso nesse intervalo ficariam sem frete.',
            folga_entre_faixas=FOLGA_DO_PESO_EM_KG, ultima_deve_ser_aberta=False, conferir_continuidade=tudo_lido,
        )

    # Função Objetivo: Faixas de preço — as que não dependem de peso, as de cada faixa de peso, e a emenda entre elas.
    def _conferir_precos(self, aba, confiaveis, tudo_lido):
        sem_peso = [r for r in confiaveis if not r.depende_do_peso]
        com_peso = {}
        for r in confiaveis:
            if r.depende_do_peso:
                com_peso.setdefault(round(r.peso_min, 6), []).append(r)

        def checar(linhas, grupo, minimo_esperado, ultima_aberta):
            verificar_sequencia_de_faixas(
                self.relatorio, [Faixa(r.n_linha, r.preco_min, r.preco_max) for r in linhas],
                descrever_local=lambda linha: self.local(aba, linha, self.coluna_preco_min),
                formatar=formatar_dinheiro, nome='preço',
                consequencia='anúncios com preço nesse intervalo ficariam sem frete.',
                folga_entre_faixas=FOLGA_DO_PRECO_EM_REAIS, ultima_deve_ser_aberta=ultima_aberta,
                minimo_esperado_da_primeira=minimo_esperado, grupo=grupo, conferir_continuidade=tudo_lido,
            )

        if sem_peso:
            checar(sem_peso, 'faixas de preço sem peso', 0.0, False)
        for minimo, grupo in sorted(com_peso.items()):
            maximo = next((r.peso_max for r in grupo if r.peso_max is not None), None)
            rotulo = f'peso a partir de {formatar_peso(minimo)}' + (f' até {formatar_peso(maximo)}' if maximo is not None else '')
            checar(grupo, rotulo, None, True)

        # Emenda: onde terminam as faixas "sem peso" tem que começar a primeira faixa "com peso".
        if tudo_lido and sem_peso and com_peso:
            tetos = [r.preco_max for r in sem_peso if r.preco_max is not None]
            primeiro_com_peso = min(r.preco_min for grupo in com_peso.values() for r in grupo)
            if tetos:
                diferenca = primeiro_com_peso - max(tetos)
                if diferenca > FOLGA_DO_PRECO_EM_REAIS + TOLERANCIA or diferenca < -TOLERANCIA:
                    self.relatorio.aviso(
                        self.local(aba),
                        f'As faixas de preço sem peso terminam em {formatar_dinheiro(max(tetos))} e as faixas com peso '
                        f'começam em {formatar_dinheiro(primeiro_com_peso)}.',
                        'Confira se há buraco ou sobreposição entre os dois blocos.',
                    )

    # Função Objetivo: Toda faixa de peso precisa ter todas as faixas de preço (a matriz completa).
    def _conferir_matriz(self, aba, confiaveis):
        por_peso = {}
        for r in confiaveis:
            if r.depende_do_peso:
                por_peso.setdefault(round(r.peso_min, 6), {})[round(r.preco_min, 6)] = r
        todos_os_precos = sorted({preco for faixas in por_peso.values() for preco in faixas})
        for peso in sorted(por_peso):
            for preco in todos_os_precos:
                if preco not in por_peso[peso]:
                    primeira_linha = min(r.n_linha for r in por_peso[peso].values())
                    self.relatorio.aviso(
                        self.local(aba, primeira_linha),
                        f'A faixa de peso a partir de {formatar_peso(peso)} não tem a faixa de preço que começa em '
                        f'{formatar_dinheiro(preco)} (as outras faixas de peso têm).',
                        'Sem essa linha, produtos desse peso e preço ficariam sem frete.',
                    )

    # Função Objetivo: O frete só deve subir (ou ficar igual) com o preço e com o peso.
    def _conferir_crescimento(self, aba, confiaveis):
        def local(linha, coluna):
            return self.local(aba, linha, coluna)

        sem_peso = sorted((r for r in confiaveis if not r.depende_do_peso), key=lambda r: r.preco_min)
        verificar_valores_nao_decrescentes(
            self.relatorio, [Ponto(r.n_linha, self.coluna_valor, r.valor) for r in sem_peso],
            descrever_local=local, formatar_valor=formatar_dinheiro, quando='ao passar para a faixa de preço seguinte',
        )

        por_peso, por_preco = {}, {}
        for r in confiaveis:
            if r.depende_do_peso:
                por_peso.setdefault(round(r.peso_min, 6), []).append(r)
                por_preco.setdefault(round(r.preco_min, 6), []).append(r)

        for peso in sorted(por_peso):
            ordenadas = sorted(por_peso[peso], key=lambda r: r.preco_min)
            verificar_valores_nao_decrescentes(
                self.relatorio, [Ponto(r.n_linha, self.coluna_valor, r.valor) for r in ordenadas],
                descrever_local=local, formatar_valor=formatar_dinheiro,
                quando=f'ao passar para a faixa de preço seguinte (peso a partir de {formatar_peso(peso)})',
            )
        for preco in sorted(por_preco):
            ordenadas = sorted(por_preco[preco], key=lambda r: r.peso_min)
            verificar_valores_nao_decrescentes(
                self.relatorio, [Ponto(r.n_linha, self.coluna_valor, r.valor) for r in ordenadas],
                descrever_local=local, formatar_valor=formatar_dinheiro,
                quando=f'ao passar para a faixa de peso seguinte (preço a partir de {formatar_dinheiro(preco)})',
            )

    def _resumir(self, tipo, registros):
        rotulo = tipo.upper()
        confiaveis = [r for r in registros if r.confiavel]
        self.relatorio.resumir(f'{rotulo} — linhas lidas', len(registros))
        self.relatorio.resumir(f'{rotulo} — faixas de peso', len({round(r.peso_min, 6) for r in confiaveis if r.depende_do_peso}))
        self.relatorio.resumir(f'{rotulo} — faixas de preço', len({round(r.preco_min, 6) for r in confiaveis}))

    def _montar_previa(self, aba, registros):
        colunas = ['Linha', 'Peso mín. (kg)', 'Peso máx. (kg)', 'Preço mín.', 'Preço máx.', 'Valor']
        linhas = []
        for r in registros:
            linhas.append([
                r.n_linha,
                formatar_numero(r.peso_min) if r.peso_min is not None else 'não depende',
                formatar_numero(r.peso_max) if r.peso_max is not None else ('—' if r.peso_min is None else 'sem limite'),
                formatar_dinheiro(r.preco_min),
                formatar_dinheiro(r.preco_max) if r.preco_max is not None else 'sem limite',
                formatar_dinheiro(r.valor),
            ])
        self.relatorio.adicionar_previa(montar_previa(f'Frete lido da aba “{aba}”', colunas, linhas))
