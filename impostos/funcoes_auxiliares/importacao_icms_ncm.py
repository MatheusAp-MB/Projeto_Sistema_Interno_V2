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
# branco) rejeita o NCM INTEIRO, não só a UF que divergiu.
#
# Correção de 13/09/2026 (ver Descoberta "Auditoria Fiscal de Impostos de
# Saida" no vault): a validação agora é EXAUSTIVA — varre as 27 UFs e
# registra TODAS as que divergem, não só a 1ª encontrada. Antes, achar 1
# divergência (ex: UF AC) escondia qualquer outra divergência numa UF
# posterior (ex: SP) — mesmo corrigindo a 1ª na planilha, não dava pra
# garantir que o NCM não tinha outro problema escondido. Isso NÃO muda se
# o NCM é aceito ou rejeitado (1 UF divergente já rejeita o NCM inteiro,
# antes e depois desta correção) — muda só a completude do que fica
# registrado SOBRE a rejeição, que agora é persistido (Camada A da
# auditoria, ver IcmsNcmRejeitado em impostos/models.py) em vez de só
# impresso no stdout e descartado.

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.empresa import obter_alias_banco_ativo, obter_empresa_ativa
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA,
    COLUNA_EAN,
    ler_linhas_planilha_impostos_saida,
)
from impostos.models import IcmsNcmRejeitado, IcmsNcmUf

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


# Função Objetivo: Registra a rejeição de 1 NCM — TODAS as UFs que
# divergem entre os EANs desse NCM (não só a 1ª encontrada, ver comentário
# no topo do arquivo), e quantos EANs formam o grupo.
class NcmRejeitado:

    MAXIMO_EXEMPLOS_POR_GRUPO = 3

    def __init__(self, ncm, total_eans_no_grupo, divergencias_por_uf):
        self.ncm = ncm
        self.total_eans_no_grupo = total_eans_no_grupo
        # {uf: [(ean, valor), ...]} — 1 entrada por UF divergente, TODAS.
        self.divergencias_por_uf = divergencias_por_uf

    # Função Objetivo: Agrupa 1 lista (ean, valor) por valor, do mais pro menos frequente.
    # Explicação em detalhe: o valor mais comum normalmente é o "certo" e os
    # poucos que destoam são o problema real de verdade — separar isso é o
    # que deixa o relatório legível, em vez de despejar todos os EANs numa
    # linha só (o que virava ilegível com NCMs de 20+ produtos). Reaproveitada
    # tanto pelo __str__ (terminal, trunca em 3 exemplos) quanto por
    # para_dict_auditoria (persistido, sem truncar nenhum).
    @staticmethod
    def _grupos_por_valor(conflitantes):
        grupos = {}
        for ean, valor in conflitantes:
            grupos.setdefault(valor, []).append(ean)
        return sorted(grupos.items(), key=lambda item: -len(item[1]))

    # Função Objetivo: Relatório pro TERMINAL — trunca em 3 exemplos por
    # grupo de valor, só pra não poluir o stdout num NCM com muitos EANs.
    # Nunca usado pra persistir nada (ver para_dict_auditoria pra isso).
    def __str__(self):
        ufs_ordenadas = sorted(self.divergencias_por_uf)
        linhas = [
            f'NCM {self.ncm} — diverge em {len(ufs_ordenadas)} UF(s) de {self.total_eans_no_grupo} '
            f'EAN(s) no grupo: {", ".join(ufs_ordenadas)}'
        ]
        for uf in ufs_ordenadas:
            conflitantes = self.divergencias_por_uf[uf]
            linhas.append(f'  UF {uf}:')
            for valor, eans in self._grupos_por_valor(conflitantes):
                valor_exibido = str(valor) if valor is not None else 'em branco'
                if len(eans) <= self.MAXIMO_EXEMPLOS_POR_GRUPO:
                    exemplos = ', '.join(eans)
                    linhas.append(f'      {valor_exibido}: {len(eans)} EAN(s) — {exemplos}')
                else:
                    exemplos = ', '.join(eans[:self.MAXIMO_EXEMPLOS_POR_GRUPO])
                    linhas.append(f'      {valor_exibido}: {len(eans)} EANs — ex: {exemplos}, ...')
        return '\n'.join(linhas)

    # Função Objetivo: Estrutura COMPLETA, sem truncar — pronta pro
    # JSONField de IcmsNcmRejeitado (Camada A da auditoria, ver
    # impostos/models.py). Diferente de __str__ (só terminal, trunca em 3
    # exemplos), aqui NENHUM EAN fica de fora — decisão do vault, 13/09/2026:
    # a auditoria persistida não pode esconder exemplo nenhum atrás de um
    # "...". Decimal vira string (JSON não serializa Decimal nativamente
    # sem risco de perder precisão) — nunca float, pra nunca arredondar o
    # que a planilha realmente tinha.
    def para_dict_auditoria(self):
        resultado = {}
        for uf, conflitantes in self.divergencias_por_uf.items():
            grupos = self._grupos_por_valor(conflitantes)
            resultado[uf] = [
                {
                    'valor': str(valor) if valor is not None else None,
                    'qtd_eans': len(eans),
                    'eans': eans,
                }
                for valor, eans in grupos
            ]
        return resultado


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
    # "2 EANs com valores numéricos diferentes". EXAUSTIVO desde 13/09/2026
    # (ver comentário no topo do arquivo): varre as 27 UFs inteiras,
    # acumulando TODAS as divergentes em vez de retornar na 1ª encontrada —
    # o NCM ainda é rejeitado com 1 divergência só, mas o registro da
    # rejeição agora é completo, nunca escondendo uma 2ª UF problemática.
    def _validar_ncm(self, ncm, linhas):
        if len(linhas) == 1:
            return linhas[0].valores_por_uf, None

        divergencias_por_uf = {}
        for uf in UFS_ORDENADAS:
            valores_encontrados = {linha.valores_por_uf[uf] for linha in linhas}
            if len(valores_encontrados) > 1:
                divergencias_por_uf[uf] = [(linha.ean, linha.valores_por_uf[uf]) for linha in linhas]

        if divergencias_por_uf:
            return None, NcmRejeitado(ncm, len(linhas), divergencias_por_uf)

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


# Função Objetivo: Grava (substituição TOTAL, a cada rodada) o motivo de
# cada NCM rejeitado nesta importação — Camada A da auditoria fiscal (ver
# IcmsNcmRejeitado em impostos/models.py pro porquê de nunca fazer update
# incremental aqui, ao contrário de PersistidorIcmsNcm).
class PersistidorIcmsNcmRejeitado:

    def __init__(self, constatado_em):
        self.constatado_em = constatado_em

    def salvar(self, rejeitados):
        IcmsNcmRejeitado.objects.all().delete()
        novos = [
            IcmsNcmRejeitado(
                ncm=rejeitado.ncm,
                qtd_ufs_divergentes=len(rejeitado.divergencias_por_uf),
                qtd_eans_no_grupo=rejeitado.total_eans_no_grupo,
                divergencias_por_uf=rejeitado.para_dict_auditoria(),
                constatado_em=self.constatado_em,
            )
            for rejeitado in rejeitados
        ]
        if novos:
            IcmsNcmRejeitado.objects.bulk_create(novos, batch_size=BATCH_SIZE_PADRAO)


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

    # Momento único desta rodada — TODO IcmsNcmRejeitado gravado agora
    # carrega o MESMO instante, mesmo que a gravação em si leve alguns
    # milissegundos linha a linha (garantia do vault, 13/09/2026).
    constatado_em = timezone.now()

    persistidor = PersistidorIcmsNcm()
    persistidor.carregar_existentes()
    persistidor.processar(agrupador.aceitos)

    persistidor_rejeitados = PersistidorIcmsNcmRejeitado(constatado_em)

    # 1 ÚNICA transação: os NCMs aceitos (criados/atualizados) e a
    # substituição total da auditoria de rejeitados entram juntos, ou
    # nenhum dos dois entra — nunca um sem o outro, mesmo se o processo
    # cair no meio (garantia do vault, 13/09/2026). using=obter_alias_banco_ativo()
    # é OBRIGATÓRIO aqui: como o EmpresaRouter roteia os models desta app
    # pro alias 'magazine'/'samvale' (nunca 'default'), um bare
    # transaction.atomic() (sem using=) abriria a transação na conexão
    # ERRADA — a do alias 'default', que é uma conexão DIFERENTE mesmo
    # apontando pro mesmo banco físico do Magazine — e não protegeria
    # nenhuma das escritas de verdade, que acontecem na conexão do alias
    # ativo. Ver core/database_router.py + core/empresa.py.
    with transaction.atomic(using=obter_alias_banco_ativo()):
        persistidor.salvar()
        persistidor_rejeitados.salvar(agrupador.rejeitados)

    stdout.write('')
    stdout.write(style.SUCCESS(persistidor.relatorio_resumo()))
    stdout.write(style.SUCCESS(
        f'[AUDITORIA] {len(agrupador.rejeitados)} NCM(s) rejeitado(s) registrados pra consulta '
        f'(tela de produto e tela de Auditoria Fiscal), constatado em '
        f'{timezone.localtime(constatado_em):%d/%m/%Y %H:%M:%S}.'
    ))