# impostos/funcoes_auxiliares/importacao_icms_ncm.py

# Função Objetivo: Lê a planilha Busca Legal, agrupa por NCM e valida
# consistência entre os EANs de cada NCM — produz o dado já "tratado",
# pronto pra gravar em IcmsNcmUf (decisão no vault: import tratado, nunca
# direto). Não grava no banco — isso fica pra outro módulo, na camada
# seguinte.
#
# Regra de validação (decidida no vault): todos os EANs de 1 mesmo NCM
# precisam concordar em cada 1 das 27 UFs — mesmo valor preenchido, ou
# todos em branco. Qualquer divergência (inclusive preenchido vs em
# branco) rejeita o NCM INTEIRO, não só a UF que divergiu — e para na
# primeira UF divergente encontrada, não avalia as outras.

from decimal import Decimal

from core.empresa import obter_empresa_ativa
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA,
    COLUNA_EAN,
    ler_linhas_planilha_impostos_saida,
)
from impostos.models import IcmsNcmUf

COLUNA_NCM = 'NCM'

UFS_ORDENADAS = [
    'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT',
    'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO',
]

DUAS_CASAS_DECIMAIS = Decimal('0.01')


# Função Objetivo: Normaliza um código textual (NCM, EAN) lido da célula.
# Explicação em detalhe: mesma lógica de _normalizar_ean em
# preenchimento_impostos_saida.py — se o Excel converteu o código pra
# número (perde o formato texto), remove o ".0" residual do float. Nunca
# faz padding de zero à esquerda: melhor não casar/exibir errado do que
# inventar um zero que não estava lá.
def _normalizar_codigo_celula(valor):
    if valor is None:
        return None
    if isinstance(valor, float):
        texto = str(int(valor)) if valor.is_integer() else str(valor)
    else:
        texto = str(valor)
    texto = texto.strip()
    return texto or None


# Função Objetivo: Representa 1 linha (EAN) já reduzida a NCM + as 27 UFs.
class LinhaIcmsNcm:

    def __init__(self, linha_bruta, conversor):
        self.linha_bruta = linha_bruta
        self.conversor = conversor

        self.ean = None
        self.ncm = None
        self.valores_por_uf = {}

    # Função Objetivo: Converte fração (ex: 0,18) pra percentual (ex: 18.00), preservando em branco.
    # Explicação em detalhe: diferente de _fracao_para_percentual em
    # preenchimento_impostos_saida.py — aquela usa padrao=0 (os 4 campos
    # do Produto nunca são None). Aqui em branco continua em branco
    # (None) — é dado real (produto sem aquele imposto), nunca vira 0%
    # por acidente.
    def _fracao_para_percentual_ou_none(self, valor_coluna):
        fracao = self.conversor.para_decimal(valor_coluna)
        if fracao is None:
            return None
        return (fracao * 100).quantize(DUAS_CASAS_DECIMAIS)

    def extrair_campos(self):
        self.ean = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_EAN))
        self.ncm = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_NCM))
        self.valores_por_uf = {
            uf: self._fracao_para_percentual_ou_none(self.linha_bruta.get(uf))
            for uf in UFS_ORDENADAS
        }
        return self

    def esta_valida(self):
        return bool(self.ncm)


# Função Objetivo: Registra a rejeição de 1 NCM — qual UF divergiu e entre quais EANs.
class NcmRejeitado:

    MAXIMO_EXEMPLOS_POR_GRUPO = 3

    def __init__(self, ncm, uf, valores_conflitantes):
        self.ncm = ncm
        self.uf = uf
        self.valores_conflitantes = valores_conflitantes  # lista de (ean, valor)

    # Função Objetivo: Agrupa os EANs conflitantes por valor, do mais pro menos frequente.
    # Explicação em detalhe: o valor mais comum normalmente é o "certo" e os
    # poucos que destoam são o problema real de verdade — separar isso é o
    # que deixa o relatório legível, em vez de despejar todos os EANs numa
    # linha só (o que virava ilegível com NCMs de 20+ produtos).
    def _grupos_por_valor(self):
        grupos = {}
        for ean, valor in self.valores_conflitantes:
            grupos.setdefault(valor, []).append(ean)
        return sorted(grupos.items(), key=lambda item: -len(item[1]))

    def __str__(self):
        grupos = self._grupos_por_valor()
        total = len(self.valores_conflitantes)

        linhas = [f'NCM {self.ncm} — UF {self.uf} diverge entre {total} EANs:']
        for valor, eans in grupos:
            valor_exibido = str(valor) if valor is not None else 'em branco'
            if len(eans) <= self.MAXIMO_EXEMPLOS_POR_GRUPO:
                exemplos = ', '.join(eans)
                linhas.append(f'    {valor_exibido}: {len(eans)} EAN(s) — {exemplos}')
            else:
                exemplos = ', '.join(eans[:self.MAXIMO_EXEMPLOS_POR_GRUPO])
                linhas.append(f'    {valor_exibido}: {len(eans)} EANs — ex: {exemplos}, ...')
        return '\n'.join(linhas)


# Função Objetivo: Agrupa as linhas por NCM e aplica a regra de consistência.
class AgrupadorIcmsPorNcm:

    def __init__(self):
        self.linhas_por_ncm = {}  # ncm -> lista de LinhaIcmsNcm
        self.sem_ncm_na_planilha = 0

        self.aceitos = {}  # ncm -> {uf: Decimal}, só UFs preenchidas
        self.rejeitados = []  # lista de NcmRejeitado

    def adicionar_linha(self, linha):
        if not linha.esta_valida():
            self.sem_ncm_na_planilha += 1
            return
        self.linhas_por_ncm.setdefault(linha.ncm, []).append(linha)

    # Função Objetivo: Decide se 1 NCM é aceito (e com quais valores) ou rejeitado (e por quê).
    # Explicação em detalhe: usa um set() dos valores encontrados por UF —
    # None entra no set igual a qualquer Decimal, então "1 EAN preenchido +
    # 1 EAN em branco" vira set de tamanho 2 (diverge) exatamente igual a
    # "2 EANs com valores numéricos diferentes". Para na 1ª UF divergente.
    def _validar_ncm(self, ncm, linhas):
        if len(linhas) == 1:
            return linhas[0].valores_por_uf, None

        for uf in UFS_ORDENADAS:
            valores_encontrados = {linha.valores_por_uf[uf] for linha in linhas}
            if len(valores_encontrados) > 1:
                conflitantes = [(linha.ean, linha.valores_por_uf[uf]) for linha in linhas]
                return None, NcmRejeitado(ncm, uf, conflitantes)

        return linhas[0].valores_por_uf, None

    def processar(self):
        for ncm, linhas in self.linhas_por_ncm.items():
            valores, rejeicao = self._validar_ncm(ncm, linhas)
            if rejeicao:
                self.rejeitados.append(rejeicao)
            else:
                self.aceitos[ncm] = {uf: valor for uf, valor in valores.items() if valor is not None}

    def relatorio_resumo(self):
        return (
            f'[ICMS POR NCM] NCMs distintos encontrados: {len(self.linhas_por_ncm)}\n'
            f'    Aceitos:    {len(self.aceitos)}\n'
            f'    Rejeitados: {len(self.rejeitados)}\n'
            f'    Linhas sem NCM na planilha (ignoradas): {self.sem_ncm_na_planilha}'
        )


# Função Objetivo: Ponto de entrada — lê a planilha inteira e devolve o agrupador já processado.
def agrupar_icms_por_ncm(caminho_planilha):
    conversor = ConversorCelulaExcel(origem='openpyxl')
    agrupador = AgrupadorIcmsPorNcm()

    for linha_bruta in ler_linhas_planilha_impostos_saida(caminho_planilha):
        linha = LinhaIcmsNcm(linha_bruta, conversor).extrair_campos()
        agrupador.adicionar_linha(linha)

    agrupador.processar()
    return agrupador


# Função Objetivo: Grava em IcmsNcmUf os NCMs aceitos por AgrupadorIcmsPorNcm.
# Explicação em detalhe: nunca compara valor novo com o que já está
# gravado — o dado que chegou e passou na validação é sempre a verdade,
# sobrescreve sem comparar (decisão do Matheus). NCM/UF que não vieram
# nessa rodada continuam como estavam — a planilha só atualiza/cria o que
# ela possui, nunca apaga o que já existe.
class PersistidorIcmsNcm:

    def __init__(self):
        self.existentes = {}  # (ncm, uf) -> IcmsNcmUf
        self.para_criar = []
        self.para_atualizar = []

    def carregar_existentes(self):
        self.existentes = {(r.ncm, r.uf): r for r in IcmsNcmUf.objects.all()}

    def processar(self, aceitos):
        for ncm, valores_por_uf in aceitos.items():
            for uf, aliquota in valores_por_uf.items():
                chave = (ncm, uf)
                existente = self.existentes.get(chave)
                if existente:
                    existente.aliquota = aliquota
                    self.para_atualizar.append(existente)
                else:
                    novo = IcmsNcmUf(ncm=ncm, uf=uf, aliquota=aliquota)
                    self.para_criar.append(novo)
                    self.existentes[chave] = novo

    def salvar(self):
        if self.para_criar:
            IcmsNcmUf.objects.bulk_create(self.para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.para_atualizar:
            IcmsNcmUf.objects.bulk_update(self.para_atualizar, ['aliquota'], batch_size=BATCH_SIZE_PADRAO)

    def relatorio_resumo(self):
        return (
            f'[ICMS POR NCM] Gravação concluída!\n'
            f'    Criados (NCM+UF novos):            {len(self.para_criar)}\n'
            f'    Atualizados (NCM+UF já existiam):  {len(self.para_atualizar)}'
        )


# Função Objetivo: Ponto de entrada do comando — lê, agrupa, valida e grava, do arquivo ao banco.
def importar_icms_por_ncm(stdout, style, caminho_planilha=None):
    if caminho_planilha is None:
        empresa = obter_empresa_ativa()
        if empresa is None:
            raise RuntimeError(
                'Nenhuma empresa ativa — rode este comando com --empresa=MAGAZINE '
                'ou --empresa=SAMVALE.'
            )
        caminho_planilha = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]

    stdout.write('[ICMS POR NCM] Lendo planilha Busca Legal...')

    agrupador = agrupar_icms_por_ncm(caminho_planilha)

    stdout.write('')
    stdout.write(style.SUCCESS(agrupador.relatorio_resumo()))

    if agrupador.rejeitados:
        stdout.write('')
        stdout.write(style.WARNING('[NCMs REJEITADOS — DIVERGÊNCIA ENTRE EANs, NADA GRAVADO DESTES]'))
        for rejeitado in agrupador.rejeitados:
            stdout.write('')
            stdout.write(style.WARNING(str(rejeitado)))

    persistidor = PersistidorIcmsNcm()
    persistidor.carregar_existentes()
    persistidor.processar(agrupador.aceitos)
    persistidor.salvar()

    stdout.write('')
    stdout.write(style.SUCCESS(persistidor.relatorio_resumo()))