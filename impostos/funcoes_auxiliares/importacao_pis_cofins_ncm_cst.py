# impostos/funcoes_auxiliares/importacao_pis_cofins_ncm_cst.py

# Função Objetivo: Lê a planilha Busca Legal, agrupa por NCM + CST e valida
# consistência entre os EANs de cada grupo — produz o dado já "tratado",
# pronto pra gravar em PisCofinsNcmCst (mesmo padrão do ICMS: import
# tratado, nunca direto). Não grava no banco — isso fica pra outro módulo,
# na camada seguinte.
#
# Regra de validação: todos os EANs de 1 mesmo NCM+CST precisam concordar
# em PIS e em COFINS — mesmo valor preenchido, ou os dois em branco.
# Qualquer divergência (inclusive preenchido vs em branco) rejeita o
# GRUPO INTEIRO (o NCM+CST, não o NCM sozinho).
#
# Diferente do ICMS: aqui a chave é NCM + CST, não só NCM (ver Descoberta
# no vault — CST não é função do NCM, então agrupar só por NCM
# "vazaria" 2 taxas diferentes pro mesmo grupo). Além da validação,
# emite um relatório INFORMATIVO (não-bloqueante) de NCMs que aparecem
# com mais de 1 CST — no levantamento real, isso bateu, EAN por EAN, com
# os mesmos itens que já divergiam no ICMS por NCM: provável cadastro de
# CST errado, não variação tributária legítima. Não impede o import.

from decimal import Decimal

from core.empresa import obter_empresa_ativa
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA,
    COLUNA_EAN,
    ler_linhas_planilha_impostos_saida,
)
from impostos.models import PisCofinsNcmCst

COLUNA_NCM = 'NCM'
COLUNA_PIS = 'PIS'
COLUNA_COFINS = 'COFINS'
COLUNA_CST = 'CST'

DUAS_CASAS_DECIMAIS = Decimal('0.01')


# Função Objetivo: Normaliza um código textual (NCM, EAN, CST) lido da célula.
# Explicação em detalhe: mesma lógica de importacao_icms_ncm.py — se o
# Excel converteu o código pra número (perde o formato texto), remove o
# ".0" residual do float. Nunca faz padding de zero à esquerda.
def _normalizar_codigo_celula(valor):
    if valor is None:
        return None
    if isinstance(valor, float):
        texto = str(int(valor)) if valor.is_integer() else str(valor)
    else:
        texto = str(valor)
    texto = texto.strip()
    return texto or None


# Função Objetivo: Representa 1 linha (EAN) já reduzida a NCM + CST + PIS + COFINS.
class LinhaPisCofinsNcmCst:

    def __init__(self, linha_bruta, conversor):
        self.linha_bruta = linha_bruta
        self.conversor = conversor

        self.ean = None
        self.ncm = None
        self.cst = None
        self.pis = None
        self.cofins = None

    # Fração (ex: 0,0165) -> percentual (ex: 1.65), preservando em branco —
    # mesma convenção de importacao_icms_ncm.py, nunca vira 0% por acidente.
    def _fracao_para_percentual_ou_none(self, valor_coluna):
        fracao = self.conversor.para_decimal(valor_coluna)
        if fracao is None:
            return None
        return (fracao * 100).quantize(DUAS_CASAS_DECIMAIS)

    def extrair_campos(self):
        self.ean = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_EAN))
        self.ncm = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_NCM))
        self.cst = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_CST))
        self.pis = self._fracao_para_percentual_ou_none(self.linha_bruta.get(COLUNA_PIS))
        self.cofins = self._fracao_para_percentual_ou_none(self.linha_bruta.get(COLUNA_COFINS))
        return self

    # Precisa de NCM E de CST — os dois formam a chave do grupo.
    def esta_valida(self):
        return bool(self.ncm) and bool(self.cst)


# Função Objetivo: Registra a rejeição de 1 grupo NCM+CST — qual campo
# (PIS ou COFINS) divergiu e entre quais EANs.
class GrupoRejeitado:

    MAXIMO_EXEMPLOS_POR_GRUPO = 3

    def __init__(self, ncm, cst, campo, valores_conflitantes):
        self.ncm = ncm
        self.cst = cst
        self.campo = campo
        self.valores_conflitantes = valores_conflitantes  # lista de (ean, valor)

    # Agrupa os EANs conflitantes por valor, do mais pro menos frequente —
    # mesma lógica de NcmRejeitado em importacao_icms_ncm.py.
    def _grupos_por_valor(self):
        grupos = {}
        for ean, valor in self.valores_conflitantes:
            grupos.setdefault(valor, []).append(ean)
        return sorted(grupos.items(), key=lambda item: -len(item[1]))

    def __str__(self):
        grupos = self._grupos_por_valor()
        total = len(self.valores_conflitantes)

        linhas = [f'NCM {self.ncm} + CST {self.cst} — campo {self.campo} diverge entre {total} EANs:']
        for valor, eans in grupos:
            valor_exibido = str(valor) if valor is not None else 'em branco'
            if len(eans) <= self.MAXIMO_EXEMPLOS_POR_GRUPO:
                exemplos = ', '.join(eans)
                linhas.append(f'    {valor_exibido}: {len(eans)} EAN(s) — {exemplos}')
            else:
                exemplos = ', '.join(eans[:self.MAXIMO_EXEMPLOS_POR_GRUPO])
                linhas.append(f'    {valor_exibido}: {len(eans)} EANs — ex: {exemplos}, ...')
        return '\n'.join(linhas)


# Função Objetivo: Agrupa as linhas por NCM+CST e aplica a regra de consistência.
class AgrupadorPisCofinsPorNcmCst:

    def __init__(self):
        self.linhas_por_grupo = {}  # (ncm, cst) -> lista de LinhaPisCofinsNcmCst
        self.sem_ncm_ou_cst_na_planilha = 0

        self.aceitos = {}  # (ncm, cst) -> {'pis': Decimal|None, 'cofins': Decimal|None}
        self.rejeitados = []  # lista de GrupoRejeitado

    def adicionar_linha(self, linha):
        if not linha.esta_valida():
            self.sem_ncm_ou_cst_na_planilha += 1
            return
        self.linhas_por_grupo.setdefault((linha.ncm, linha.cst), []).append(linha)

    # Função Objetivo: Decide se 1 grupo NCM+CST é aceito (e com quais
    # valores) ou rejeitado (e por quê). Checa PIS e COFINS separadamente
    # — se só 1 dos 2 divergir, rejeita mesmo assim (o grupo inteiro).
    def _validar_grupo(self, ncm, cst, linhas):
        if len(linhas) == 1:
            linha = linhas[0]
            return {'pis': linha.pis, 'cofins': linha.cofins}, None

        for campo, extrator in [('PIS', lambda l: l.pis), ('COFINS', lambda l: l.cofins)]:
            valores_encontrados = {extrator(linha) for linha in linhas}
            if len(valores_encontrados) > 1:
                conflitantes = [(linha.ean, extrator(linha)) for linha in linhas]
                return None, GrupoRejeitado(ncm, cst, campo, conflitantes)

        return {'pis': linhas[0].pis, 'cofins': linhas[0].cofins}, None

    def processar(self):
        for (ncm, cst), linhas in self.linhas_por_grupo.items():
            valores, rejeicao = self._validar_grupo(ncm, cst, linhas)
            if rejeicao:
                self.rejeitados.append(rejeicao)
            else:
                self.aceitos[(ncm, cst)] = valores

    # Função Objetivo: Relatório NÃO-BLOQUEANTE — NCMs aceitos que aparecem
    # com mais de 1 CST. Não rejeita nada (PIS/COFINS já bateram por
    # NCM+CST); só avisa, porque no levantamento real isso costumou ser
    # sinal de CST cadastrado errado no produto, não variação legítima.
    def ncms_com_multiplos_csts(self):
        csts_por_ncm = {}
        for (ncm, cst), linhas in self.linhas_por_grupo.items():
            if (ncm, cst) not in self.aceitos:
                continue  # grupo rejeitado não entra no relatório informativo
            csts_por_ncm.setdefault(ncm, []).append((cst, len(linhas)))

        return {
            ncm: sorted(csts, key=lambda item: -item[1])
            for ncm, csts in csts_por_ncm.items()
            if len(csts) > 1
        }

    def relatorio_resumo(self):
        return (
            f'[PIS/COFINS POR NCM+CST] Grupos (NCM+CST) distintos encontrados: {len(self.linhas_por_grupo)}\n'
            f'    Aceitos:    {len(self.aceitos)}\n'
            f'    Rejeitados: {len(self.rejeitados)}\n'
            f'    Linhas sem NCM ou sem CST na planilha (ignoradas): {self.sem_ncm_ou_cst_na_planilha}'
        )


# Função Objetivo: Ponto de entrada — lê a planilha inteira e devolve o agrupador já processado.
def agrupar_pis_cofins_por_ncm_cst(caminho_planilha):
    conversor = ConversorCelulaExcel(origem='openpyxl')
    agrupador = AgrupadorPisCofinsPorNcmCst()

    for linha_bruta in ler_linhas_planilha_impostos_saida(caminho_planilha):
        linha = LinhaPisCofinsNcmCst(linha_bruta, conversor).extrair_campos()
        agrupador.adicionar_linha(linha)

    agrupador.processar()
    return agrupador


# Função Objetivo: Grava em PisCofinsNcmCst os grupos aceitos por
# AgrupadorPisCofinsPorNcmCst.
# Explicação em detalhe: mesmo padrão de PersistidorIcmsNcm — nunca
# compara valor novo com o que já está gravado, o dado que passou na
# validação é sempre a verdade, sobrescreve sem comparar. NCM+CST que não
# veio nessa rodada continua como estava.
class PersistidorPisCofinsNcmCst:

    def __init__(self):
        self.existentes = {}  # (ncm, cst) -> PisCofinsNcmCst
        self.para_criar = []
        self.para_atualizar = []

    def carregar_existentes(self):
        self.existentes = {(r.ncm, r.cst): r for r in PisCofinsNcmCst.objects.all()}

    def processar(self, aceitos):
        for (ncm, cst), valores in aceitos.items():
            existente = self.existentes.get((ncm, cst))
            if existente:
                existente.pis = valores['pis']
                existente.cofins = valores['cofins']
                self.para_atualizar.append(existente)
            else:
                novo = PisCofinsNcmCst(ncm=ncm, cst=cst, pis=valores['pis'], cofins=valores['cofins'])
                self.para_criar.append(novo)
                self.existentes[(ncm, cst)] = novo

    def salvar(self):
        if self.para_criar:
            PisCofinsNcmCst.objects.bulk_create(self.para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.para_atualizar:
            PisCofinsNcmCst.objects.bulk_update(self.para_atualizar, ['pis', 'cofins'], batch_size=BATCH_SIZE_PADRAO)

    def relatorio_resumo(self):
        return (
            f'[PIS/COFINS POR NCM+CST] Gravação concluída!\n'
            f'    Criados (NCM+CST novos):            {len(self.para_criar)}\n'
            f'    Atualizados (NCM+CST já existiam):  {len(self.para_atualizar)}'
        )


# Função Objetivo: Ponto de entrada do comando — lê, agrupa, valida e grava, do arquivo ao banco.
def importar_pis_cofins_por_ncm_cst(stdout, style, caminho_planilha=None):
    if caminho_planilha is None:
        empresa = obter_empresa_ativa()
        if empresa is None:
            raise RuntimeError(
                'Nenhuma empresa ativa — rode este comando com --empresa=MAGAZINE '
                'ou --empresa=SAMVALE.'
            )
        caminho_planilha = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]

    stdout.write('[PIS/COFINS POR NCM+CST] Lendo planilha Busca Legal...')

    agrupador = agrupar_pis_cofins_por_ncm_cst(caminho_planilha)

    stdout.write('')
    stdout.write(style.SUCCESS(agrupador.relatorio_resumo()))

    if agrupador.rejeitados:
        stdout.write('')
        stdout.write(style.WARNING('[GRUPOS REJEITADOS — DIVERGÊNCIA ENTRE EANs, NADA GRAVADO DESTES]'))
        for rejeitado in agrupador.rejeitados:
            stdout.write('')
            stdout.write(style.WARNING(str(rejeitado)))

    multi_cst = agrupador.ncms_com_multiplos_csts()
    if multi_cst:
        stdout.write('')
        stdout.write(style.WARNING(
            '[AVISO INFORMATIVO — NÃO BLOQUEIA O IMPORT] '
            'NCMs com mais de 1 CST — confira se é variação tributária legítima ou cadastro errado:'
        ))
        for ncm, csts in sorted(multi_cst.items()):
            descricao_csts = ', '.join(f'CST {cst} ({total} EAN(s))' for cst, total in csts)
            stdout.write(style.WARNING(f'    NCM {ncm}: {descricao_csts}'))

    persistidor = PersistidorPisCofinsNcmCst()
    persistidor.carregar_existentes()
    persistidor.processar(agrupador.aceitos)
    persistidor.salvar()

    stdout.write('')
    stdout.write(style.SUCCESS(persistidor.relatorio_resumo())) 