# impostos/funcoes_auxiliares/importacao_icms_ncm.py

# Função Objetivo: Lê a planilha Busca Legal, agrupa por NCM + CST + Origem
# da Mercadoria (Cadastro) e valida consistência entre os EANs de cada
# grupo — produz o dado já "tratado", pronto pra gravar em IcmsNcmUf
# (decisão no vault: import tratado, nunca direto). Não grava no banco —
# isso fica pra outro módulo, na camada seguinte.
#
# Regra de validação (decidida no vault): todos os EANs de 1 mesmo grupo
# NCM+CST+Origem precisam concordar em cada 1 das 27 UFs — mesmo valor
# preenchido, ou todos em branco. Qualquer divergência (inclusive
# preenchido vs em branco) rejeita o GRUPO INTEIRO, não só a UF que
# divergiu.
#
# Correção de 13/09/2026 (ver Descoberta "Auditoria Fiscal de Impostos de
# Saida" no vault): a validação agora é EXAUSTIVA — varre as 27 UFs e
# registra TODAS as que divergem, não só a 1ª encontrada. Antes, achar 1
# divergência (ex: UF AC) escondia qualquer outra divergência numa UF
# posterior (ex: SP) — mesmo corrigindo a 1ª na planilha, não dava pra
# garantir que o grupo não tinha outro problema escondido. Isso NÃO muda se
# o grupo é aceito ou rejeitado (1 UF divergente já rejeita o grupo
# inteiro, antes e depois desta correção) — muda só a completude do que
# fica registrado SOBRE a rejeição, que agora é persistido (Camada A da
# auditoria, ver IcmsNcmRejeitado em impostos/models.py) em vez de só
# impresso no stdout e descartado.
#
# Correção de 13/09/2026, mais tarde (ver Decisão no vault: "Chave de
# Consolidacao do ICMS por NCM Passa a Incluir CST e Origem da
# Mercadoria"): o agrupamento deixou de ser só por NCM. Consulta externa
# (Gemini) + achado já existente no vault (12/09/2026, ver Descoberta "PIS
# e COFINS São Função de NCM + CST") confirmaram que NCM sozinho não
# garante os mesmos 27 valores — CST (regime de tributação) e Origem da
# Mercadoria (nacional/importado) também definem legitimamente a alíquota
# dentro de um mesmo NCM. Por isso os 2 entram na chave do grupo, junto
# com NCM.
#
# 13/09/2026, mais tarde ainda (Decisão no vault: "Fluxo de Impostos de
# Saida Passa a 4 Comandos Auto-Suficientes, CST Isolado em Comando
# Proprio Como Fonte Unica" — Etapa 3a do roteiro de execução): CST DEIXA
# de vir da planilha — passa a vir de Produto.cst_saida, já gravado por
# preencher_CST_produtos (Passo 1 do fluxo). Origem da Mercadoria já
# vinha do Produto desde mais cedo (NÃO existe coluna própria na
# planilha). Os 2 agora são buscados JUNTOS, numa única query em lote
# por EAN (1 query, nunca N+1) — Produto sem cst_saida gravado ou sem
# origem sincronizada entra com o campo em None: um valor de chave
# válido como outro qualquer (mesma filosofia de
# PisCofinsNcmCst.pis/cofins — em branco continua em branco, nunca vira
# um valor por acidente); linha sem CST (None) continua rejeitada por
# esta_valida(), igual sempre foi.
#
# Correção de 13/09/2026, mais tarde ainda: a saída no terminal foi
# reescrita usando rich (Table/Panel) + pandas (organiza e ordena as
# linhas antes de virar Table) — antes, cada grupo rejeitado imprimia um
# bloco de texto puro, aninhado UF-a-UF e valor-a-valor, que ficava difícil
# de ler com muitos EANs no grupo. A regra de negócio (validação,
# agrupamento, gravação) não muda em nada — só a FORMA como o que já era
# calculado aparece no terminal. NcmRejeitado.__str__ e para_dict_auditoria
# continuam do jeito que estavam (o 1º ainda serve pra depuração no shell,
# o 2º é o que grava a auditoria completa em IcmsNcmRejeitado) — nenhum dos
# dois é usado pelo stdout do comando desde esta correção.
#
# Correção de 13/09/2026, mais tarde ainda (achado do Matheus, vendo o
# output real): virar texto corrido em tabela resolve legibilidade, mas
# não resolve UTILIDADE — reparamos que, num grupo rejeitado com muitas
# UFs divergentes, o padrão de divergência costuma se repetir IDÊNTICO em
# quase todas as UFs (o mesmo 1 EAN sempre no lado minoritário), e a
# tabela UF-a-UF escondia isso atrás de repetição em vez de mostrar. Esta
# tela é debug pro Matheus e pra mim (Claude) entendermos se o CÓDIGO tá
# se comportando certo — não é tela de usuário final (essa é a Auditoria
# Fiscal em HTML) — então o que importa aqui é responder rápido "isso é
# 1 produto cadastrado errado (dado sujo, comportamento normal) ou um
# padrão estranho que sugere bug na minha lógica de agrupamento?".
# NcmRejeitado.montar_diagnostico_eans/resumir_diagnostico fazem essa
# pergunta por EAN (quantas UFs cada EAN ficou no lado minoritário) em vez
# de deixar quem lê escanear 24 linhas repetidas pra perceber à mão. A
# tabela UF-a-UF continua existindo (ainda serve pra conferir os valores
# de verdade), só que como detalhe secundário, depois do diagnóstico.

import shutil
from decimal import Decimal

import pandas as pd
from django.db import transaction
from django.utils import timezone
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.empresa import obter_alias_banco_ativo, obter_empresa_ativa
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA,
    COLUNA_EAN,
    ler_linhas_planilha_impostos_saida,
)
from impostos.models import IcmsNcmRejeitado, IcmsNcmUf
from produtos.models import Produto

COLUNA_NCM = 'NCM'

UFS_ORDENADAS = [
    'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT',
    'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO',
]

DUAS_CASAS_DECIMAIS = Decimal('0.01')


# Função Objetivo: Normaliza um código textual (NCM, EAN, CST) lido da célula.
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


# Função Objetivo: Representa 1 linha (EAN) já reduzida a NCM + CST +
# Origem (Cadastro) + as 27 UFs.
class LinhaIcmsNcm:

    def __init__(self, linha_bruta, conversor):
        self.linha_bruta = linha_bruta
        self.conversor = conversor

        self.ean = None
        self.ncm = None
        self.cst = None
        self.origem_mercadoria_cadastro = None
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

    # Função Objetivo: Aplica CST (Produto.cst_saida) e Origem do Cadastro
    # (Produto → impostos_entrada.origem_mercadoria_cadastro) — os 2
    # buscados em lote por EAN, fora desta classe (ver agrupar_icms_por_ncm).
    # 13/09/2026 — CST deixou de vir da planilha (Etapa 3a do roteiro de
    # execução): agora os 2 campos têm a mesma origem (Produto) e são
    # aplicados juntos.
    def aplicar_cst_e_origem(self, cst_saida, origem_mercadoria_cadastro):
        self.cst = cst_saida
        self.origem_mercadoria_cadastro = origem_mercadoria_cadastro
        return self

    # Precisa de NCM E de CST — os dois (+ Origem, que pode legitimamente
    # ser None) formam a chave do grupo.
    def esta_valida(self):
        return bool(self.ncm) and bool(self.cst)


# Função Objetivo: Registra a rejeição de 1 grupo NCM+CST+Origem — TODAS as
# UFs que divergem entre os EANs desse grupo (não só a 1ª encontrada, ver
# comentário no topo do arquivo), e quantos EANs formam o grupo.
class NcmRejeitado:

    MAXIMO_EXEMPLOS_POR_GRUPO = 3

    def __init__(self, ncm, cst, origem_mercadoria_cadastro, total_eans_no_grupo, divergencias_por_uf):
        self.ncm = ncm
        self.cst = cst
        self.origem_mercadoria_cadastro = origem_mercadoria_cadastro
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
    # grupo de valor, só pra não poluir o stdout num grupo com muitos EANs.
    # Nunca usado pra persistir nada (ver para_dict_auditoria pra isso).
    def __str__(self):
        origem_exibida = self.origem_mercadoria_cadastro if self.origem_mercadoria_cadastro is not None else 'em branco'
        ufs_ordenadas = sorted(self.divergencias_por_uf)
        linhas = [
            f'NCM {self.ncm} + CST {self.cst} + Origem {origem_exibida} — diverge em '
            f'{len(ufs_ordenadas)} UF(s) de {self.total_eans_no_grupo} EAN(s) no grupo: '
            f'{", ".join(ufs_ordenadas)}'
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

    # Função Objetivo: Mesmos dados de __str__ (por UF, agrupado por valor —
    # do mais pro menos frequente), só que como DataFrame, pronto pra virar
    # rich.table.Table no terminal (ver importar_icms_por_ncm). Trunca
    # exemplos em MAXIMO_EXEMPLOS_POR_GRUPO igual ao __str__ — é exibição de
    # terminal; quem nunca trunca nada é para_dict_auditoria, que vai pro banco.
    def montar_dataframe_divergencias(self):
        linhas = []
        for uf in sorted(self.divergencias_por_uf):
            for valor, eans in self._grupos_por_valor(self.divergencias_por_uf[uf]):
                valor_exibido = str(valor) if valor is not None else 'em branco'
                if len(eans) <= self.MAXIMO_EXEMPLOS_POR_GRUPO:
                    exemplos = ', '.join(eans)
                else:
                    exemplos = ', '.join(eans[:self.MAXIMO_EXEMPLOS_POR_GRUPO])
                    exemplos += f', ... (+{len(eans) - self.MAXIMO_EXEMPLOS_POR_GRUPO})'
                linhas.append({'UF': uf, 'Valor': valor_exibido, 'Qtd EANs': len(eans), 'Exemplos': exemplos})
        return pd.DataFrame(linhas, columns=['UF', 'Valor', 'Qtd EANs', 'Exemplos'])

    # Função Objetivo: Pra cada EAN do grupo, conta em quantas UFs
    # divergentes ele ficou no lado MINORITÁRIO (fora do maior grupo de
    # valor daquela UF) — sem isso, quem olha o terminal tem que escanear
    # UF por UF pra perceber à mão se é sempre o mesmo produto causando a
    # rejeição inteira, ou se são vários produtos diferentes sem padrão.
    # UFs onde os valores empatam no topo (sem 1 grupo majoritário claro,
    # ex: 50%/50%) não contam ninguém como minoria — ninguém é claramente
    # "o errado" ali — e entram no 2º valor de retorno (ufs_sem_maioria_clara).
    def montar_diagnostico_eans(self):
        total_ufs = len(self.divergencias_por_uf)
        vezes_em_minoria = {}
        ufs_sem_maioria_clara = 0
        for conflitantes in self.divergencias_por_uf.values():
            grupos = self._grupos_por_valor(conflitantes)
            empate_no_topo = len(grupos) > 1 and len(grupos[0][1]) == len(grupos[1][1])
            if empate_no_topo:
                ufs_sem_maioria_clara += 1
                continue
            eans_maioria = set(grupos[0][1])
            for ean, valor in conflitantes:
                if ean not in eans_maioria:
                    vezes_em_minoria[ean] = vezes_em_minoria.get(ean, 0) + 1
        linhas = [
            {'EAN': ean, 'Divergiu': f'{qtd} de {total_ufs} UF(s)'}
            for ean, qtd in sorted(vezes_em_minoria.items(), key=lambda item: -item[1])
        ]
        dataframe = pd.DataFrame(linhas, columns=['EAN', 'Divergiu'])
        return dataframe, ufs_sem_maioria_clara

    # Função Objetivo: Resumo de 1 linha do diagnóstico acima, com estilo
    # (cor) — verde quando há 1 causador claro (caso mais simples: 1
    # produto errado, resto do grupo consistente), amarelo quando há mais
    # de 1 EAN suspeito (precisa olhar com mais calma), vermelho quando
    # nenhum EAN se destaca (divergência bem distribuída — pode ser
    # divergência real de tabela, não 1 produto cadastrado errado).
    def resumir_diagnostico(self):
        dataframe, ufs_ambiguas = self.montar_diagnostico_eans()
        if dataframe.empty:
            texto, estilo = 'sem padrão claro', 'red'
        elif len(dataframe) == 1:
            texto, estilo = f'1 EAN provável ({dataframe.iloc[0]["EAN"]})', 'green'
        else:
            texto, estilo = f'{len(dataframe)} EAN(s) suspeitos', 'yellow'
        if ufs_ambiguas:
            texto += f' (+{ufs_ambiguas} UF sem maioria clara)'
        return texto, estilo


# Função Objetivo: Agrupa as linhas por NCM+CST+Origem e aplica a regra de consistência.
class AgrupadorIcmsPorNcm:

    def __init__(self):
        self.linhas_por_grupo = {}  # (ncm, cst, origem) -> lista de LinhaIcmsNcm
        # 13/09/2026 — renomeado de sem_ncm_ou_cst_na_planilha: CST não
        # vem mais da planilha (Etapa 3a), então o nome antigo afirmava
        # uma fonte que não é mais verdade pro CST.
        self.sem_ncm_na_planilha_ou_sem_cst_no_produto = 0

        self.aceitos = {}  # (ncm, cst, origem) -> {uf: Decimal}, só UFs preenchidas
        self.rejeitados = []  # lista de NcmRejeitado

    def adicionar_linha(self, linha):
        if not linha.esta_valida():
            self.sem_ncm_na_planilha_ou_sem_cst_no_produto += 1
            return
        chave = (linha.ncm, linha.cst, linha.origem_mercadoria_cadastro)
        self.linhas_por_grupo.setdefault(chave, []).append(linha)

    # Função Objetivo: Decide se 1 grupo NCM+CST+Origem é aceito (e com quais valores) ou rejeitado (e por quê).
    # Explicação em detalhe: usa um set() dos valores encontrados por UF —
    # None entra no set igual a qualquer Decimal, então "1 EAN preenchido +
    # 1 EAN em branco" vira set de tamanho 2 (diverge) exatamente igual a
    # "2 EANs com valores numéricos diferentes". EXAUSTIVO desde 13/09/2026
    # (ver comentário no topo do arquivo): varre as 27 UFs inteiras,
    # acumulando TODAS as divergentes em vez de retornar na 1ª encontrada —
    # o grupo ainda é rejeitado com 1 divergência só, mas o registro da
    # rejeição agora é completo, nunca escondendo uma 2ª UF problemática.
    def _validar_grupo(self, ncm, cst, origem, linhas):
        if len(linhas) == 1:
            return linhas[0].valores_por_uf, None

        divergencias_por_uf = {}
        for uf in UFS_ORDENADAS:
            valores_encontrados = {linha.valores_por_uf[uf] for linha in linhas}
            if len(valores_encontrados) > 1:
                divergencias_por_uf[uf] = [(linha.ean, linha.valores_por_uf[uf]) for linha in linhas]

        if divergencias_por_uf:
            return None, NcmRejeitado(ncm, cst, origem, len(linhas), divergencias_por_uf)

        return linhas[0].valores_por_uf, None

    def processar(self):
        for (ncm, cst, origem), linhas in self.linhas_por_grupo.items():
            valores, rejeicao = self._validar_grupo(ncm, cst, origem, linhas)
            if rejeicao:
                self.rejeitados.append(rejeicao)
            else:
                self.aceitos[(ncm, cst, origem)] = {uf: valor for uf, valor in valores.items() if valor is not None}


# Função Objetivo: Busca em lote (1 única query, nunca N+1) o CST de saída
# e a Origem da Mercadoria do Cadastro pra um conjunto de EANs — os 2 vêm
# do Produto agora (CST desde a Etapa 3a do roteiro de execução, Origem já
# vinha assim porque a planilha Busca Legal nunca teve essa coluna). EAN
# sem Produto correspondente, Produto sem cst_saida gravado, ou sem
# impostos_entrada sincronizado, simplesmente não aparece (ou aparece com
# None) no dict — values_list faz LEFT JOIN na relação de impostos_entrada,
# nunca lança exceção — quem chama trata a ausência como (None, None),
# valores de chave válidos.
def _buscar_cst_saida_e_origem_cadastro_por_ean(eans):
    return {
        ean: (cst_saida, origem)
        for ean, cst_saida, origem in Produto.objects.filter(ean__in=eans).values_list(
            'ean', 'cst_saida', 'impostos_entrada__origem_mercadoria_cadastro',
        )
    }


# Função Objetivo: Ponto de entrada — lê a planilha inteira, busca CST +
# Origem do Cadastro em lote (Produto) e devolve o agrupador já processado.
def agrupar_icms_por_ncm(caminho_planilha):
    conversor = ConversorCelulaExcel(origem='openpyxl')
    agrupador = AgrupadorIcmsPorNcm()

    linhas = [
        LinhaIcmsNcm(linha_bruta, conversor).extrair_campos()
        for linha_bruta in ler_linhas_planilha_impostos_saida(caminho_planilha)
    ]

    eans_da_planilha = {linha.ean for linha in linhas if linha.ean}
    dados_por_ean = _buscar_cst_saida_e_origem_cadastro_por_ean(eans_da_planilha)

    for linha in linhas:
        cst_saida, origem = dados_por_ean.get(linha.ean, (None, None))
        linha.aplicar_cst_e_origem(cst_saida, origem)
        agrupador.adicionar_linha(linha)

    agrupador.processar()
    return agrupador


# Função Objetivo: Grava em IcmsNcmUf os grupos aceitos por AgrupadorIcmsPorNcm.
# Explicação em detalhe: nunca compara valor novo com o que já está
# gravado — o dado que chegou e passou na validação é sempre a verdade,
# sobrescreve sem comparar (decisão do Matheus). NCM+CST+Origem+UF que não
# vieram nessa rodada continuam como estavam — a planilha só atualiza/cria
# o que ela possui, nunca apaga o que já existe.
class PersistidorIcmsNcm:

    def __init__(self):
        self.existentes = {}  # (ncm, cst, origem, uf) -> IcmsNcmUf
        self.para_criar = []
        self.para_atualizar = []

    def carregar_existentes(self):
        self.existentes = {
            (r.ncm, r.cst, r.origem_mercadoria_cadastro, r.uf): r
            for r in IcmsNcmUf.objects.all()
        }

    def processar(self, aceitos):
        for (ncm, cst, origem), valores_por_uf in aceitos.items():
            for uf, aliquota in valores_por_uf.items():
                chave = (ncm, cst, origem, uf)
                existente = self.existentes.get(chave)
                if existente:
                    existente.aliquota = aliquota
                    self.para_atualizar.append(existente)
                else:
                    novo = IcmsNcmUf(ncm=ncm, cst=cst, origem_mercadoria_cadastro=origem, uf=uf, aliquota=aliquota)
                    self.para_criar.append(novo)
                    self.existentes[chave] = novo

    def salvar(self):
        if self.para_criar:
            IcmsNcmUf.objects.bulk_create(self.para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.para_atualizar:
            IcmsNcmUf.objects.bulk_update(self.para_atualizar, ['aliquota'], batch_size=BATCH_SIZE_PADRAO)


# Função Objetivo: Grava (substituição TOTAL, a cada rodada) o motivo de
# cada grupo NCM+CST+Origem rejeitado nesta importação — Camada A da
# auditoria fiscal (ver IcmsNcmRejeitado em impostos/models.py pro porquê
# de nunca fazer update incremental aqui, ao contrário de PersistidorIcmsNcm).
class PersistidorIcmsNcmRejeitado:

    def __init__(self, constatado_em):
        self.constatado_em = constatado_em

    def salvar(self, rejeitados):
        IcmsNcmRejeitado.objects.all().delete()
        novos = [
            IcmsNcmRejeitado(
                ncm=rejeitado.ncm,
                cst=rejeitado.cst,
                origem_mercadoria_cadastro=rejeitado.origem_mercadoria_cadastro,
                qtd_ufs_divergentes=len(rejeitado.divergencias_por_uf),
                qtd_eans_no_grupo=rejeitado.total_eans_no_grupo,
                divergencias_por_uf=rejeitado.para_dict_auditoria(),
                constatado_em=self.constatado_em,
            )
            for rejeitado in rejeitados
        ]
        if novos:
            IcmsNcmRejeitado.objects.bulk_create(novos, batch_size=BATCH_SIZE_PADRAO)


# Função Objetivo: 1 linha por grupo NCM+CST+Origem rejeitado, já com o
# diagnóstico de causa (ver NcmRejeitado.resumir_diagnostico) — visão geral
# pra saber, sem entrar no detalhe UF-a-UF de nenhum grupo, se é 1 produto
# errado (fácil, verde) ou uma divergência sem causador claro (precisa
# olhar com mais calma, amarelo/vermelho). Recebe a lista já na ordem que
# deve aparecer — não ordena de novo aqui (ver importar_icms_por_ncm).
def _montar_dataframe_resumo_rejeitados(rejeitados_ordenados):
    linhas = []
    for rejeitado in rejeitados_ordenados:
        texto_diagnostico, estilo_diagnostico = rejeitado.resumir_diagnostico()
        linhas.append({
            'NCM': rejeitado.ncm,
            'CST': rejeitado.cst,
            'Origem': (
                rejeitado.origem_mercadoria_cadastro
                if rejeitado.origem_mercadoria_cadastro is not None else 'em branco'
            ),
            'Diagnóstico': texto_diagnostico,
            'Estilo': estilo_diagnostico,  # só orienta a cor da célula — nunca vira coluna exibida
            'EANs no Grupo': rejeitado.total_eans_no_grupo,
            'UFs Divergentes': len(rejeitado.divergencias_por_uf),
        })
    return pd.DataFrame(linhas, columns=[
        'NCM', 'CST', 'Origem', 'Diagnóstico', 'Estilo', 'EANs no Grupo', 'UFs Divergentes',
    ])


# Função Objetivo: Cria o Console com 1 coluna de margem abaixo da
# largura detectada do terminal. Corrigido em 13/09/2026: Panel sempre
# estica pra largura TOTAL do console (diferente de Table, que segue o
# conteúdo) — quando essa largura bate exatamente com a largura real do
# terminal do usuário, o próprio terminal quebra linha sem imprimir \n,
# colando a borda do Panel no conteúdo (visto em terminais MINGW64/Git
# Bash reais do Matheus, sempre em Panel, nunca em Table). A margem de
# 1 coluna evita que o Rich e o terminal disputem a última coluna.
def _console_com_margem():
    largura_detectada = shutil.get_terminal_size(fallback=(80, 24)).columns
    return Console(width=max(largura_detectada - 1, 20))


# Função Objetivo: Converte um DataFrame (sempre pequeno — resumo ou
# detalhe de 1 grupo, nunca a planilha inteira) num rich.table.Table
# pronto pra console.print — única ponte entre pandas (organiza/ordena as
# linhas) e rich (exibe colorido no terminal).
def _dataframe_para_tabela_rich(dataframe, titulo, colunas_numericas=(), border_style=None):
    tabela = Table(title=titulo, border_style=border_style)
    for coluna in dataframe.columns:
        tabela.add_column(coluna, justify='right' if coluna in colunas_numericas else 'left')
    for linha in dataframe.itertuples(index=False):
        tabela.add_row(*(str(valor) for valor in linha))
    return tabela


# Função Objetivo: Mesma ideia de _dataframe_para_tabela_rich, só que pra
# visão geral dos rejeitados especificamente — precisa colorir só a
# CÉLULA de Diagnóstico conforme a coluna 'Estilo' (nunca exibida como
# coluna de verdade), e a genérica só sabe estilizar coluna inteira.
def _tabela_resumo_rejeitados_para_rich(dataframe):
    tabela = Table(title='Visão geral — 1 linha por grupo rejeitado (maior grupo primeiro)')
    colunas_exibidas = [coluna for coluna in dataframe.columns if coluna != 'Estilo']
    for coluna in colunas_exibidas:
        tabela.add_column(coluna, justify='right' if coluna in ('EANs no Grupo', 'UFs Divergentes') else 'left')
    for registro in dataframe.to_dict('records'):
        tabela.add_row(*(
            Text(str(registro[coluna]), style=registro['Estilo']) if coluna == 'Diagnóstico' else str(registro[coluna])
            for coluna in colunas_exibidas
        ))
    return tabela


# Função Objetivo: Ponto de entrada do comando — lê, agrupa, valida e grava, do arquivo ao banco.
def importar_icms_por_ncm(stdout, style, caminho_planilha=None):
    console = _console_com_margem()

    if caminho_planilha is None:
        empresa = obter_empresa_ativa()
        if empresa is None:
            raise RuntimeError(
                'Nenhuma empresa ativa — rode este comando com --empresa=MAGAZINE '
                'ou --empresa=SAMVALE.'
            )
        caminho_planilha = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]

    console.print('[bold]ICMS por NCM[/bold] — lendo planilha Busca Legal...')

    agrupador = agrupar_icms_por_ncm(caminho_planilha)

    tabela_agrupamento = Table(title='ICMS por NCM — Agrupamento (NCM + CST + Origem)')
    tabela_agrupamento.add_column('Métrica')
    tabela_agrupamento.add_column('Quantidade', justify='right')
    tabela_agrupamento.add_row(
        'Grupos (NCM+CST+Origem) distintos encontrados', str(len(agrupador.linhas_por_grupo)),
    )
    tabela_agrupamento.add_row('Aceitos', str(len(agrupador.aceitos)), style='green')
    tabela_agrupamento.add_row(
        'Rejeitados', str(len(agrupador.rejeitados)), style='yellow' if agrupador.rejeitados else None,
    )
    tabela_agrupamento.add_row(
        'Sem NCM na planilha ou sem CST no Produto (ignoradas)',
        str(agrupador.sem_ncm_na_planilha_ou_sem_cst_no_produto),
    )
    console.print()
    console.print(tabela_agrupamento)

    if agrupador.rejeitados:
        # Mesma ordem na visão geral E no detalhe abaixo — maior grupo
        # primeiro nas 2 (achado real de 13/09/2026: sem isso, a visão
        # geral promete "maior grupo primeiro" mas o detalhe entrava na
        # ordem de leitura da planilha, as 2 listas discordavam entre si e
        # confundia mais do que ajudava).
        rejeitados_ordenados = sorted(agrupador.rejeitados, key=lambda r: -r.total_eans_no_grupo)

        # Nota de 1 linha só — quem roda isso já conhece a regra (é dev do
        # próprio sistema), repetir o parágrafo inteiro toda rodada é
        # ruído, não ajuda a debugar nada novo.
        console.print()
        console.print(
            f'[yellow]{len(agrupador.rejeitados)} grupo(s) rejeitado(s)[/yellow] — nada gravado destes '
            f'(regra: 100% de acordo entre os EANs do grupo, em todas as 27 UFs).'
        )

        console.print()
        console.print(_tabela_resumo_rejeitados_para_rich(_montar_dataframe_resumo_rejeitados(rejeitados_ordenados)))

        for rejeitado in rejeitados_ordenados:
            origem_exibida = (
                rejeitado.origem_mercadoria_cadastro
                if rejeitado.origem_mercadoria_cadastro is not None else 'em branco'
            )
            titulo_grupo = (
                f'NCM {rejeitado.ncm} + CST {rejeitado.cst} + Origem {origem_exibida} — '
                f'{len(rejeitado.divergencias_por_uf)} UF(s) de {rejeitado.total_eans_no_grupo} EAN(s) no grupo'
            )
            dataframe_eans, ufs_ambiguas = rejeitado.montar_diagnostico_eans()

            # Identidade do grupo impressa 1 VEZ só, como texto corrido —
            # achado real de 13/09/2026 (Matheus viu no terminal de
            # verdade): repetir essa string longa como title= de Table
            # quebra feio, porque rich.table.Table dimensiona a caixa pelo
            # conteúdo das colunas, não pela largura do terminal — numa
            # tabela estreita (ex: só EAN + Divergiu), um título mais
            # comprido que a tabela vira várias linhas centralizadas
            # fragmentadas. Panel não tem esse problema (estica pra largura
            # do console), mas repetir a mesma frase longa 3x por grupo
            # (Panel/Table/Table) também era ruído. Título de cada widget
            # agora é curto e fixo; a identidade completa do grupo vem 1
            # vez, em texto plano, antes de tudo.
            console.print()
            console.print(f'[bold]{titulo_grupo}[/bold]')

            # Diagnóstico primeiro — é a pergunta que importa pra debugar
            # ("isso é 1 produto errado, ou parece bug na minha lógica?"),
            # antes do detalhe UF-a-UF (que continua abaixo, pra quem
            # quiser conferir os valores de verdade).
            if dataframe_eans.empty:
                console.print(Panel(
                    'Divergência dividida igualmente entre os EANs em todas as UFs — nenhum EAN se '
                    'destaca como causador; pode ser divergência real de tabela, não 1 produto '
                    'cadastrado errado. Vale conferir a lógica de agrupamento se isso for inesperado.',
                    title='Sem causador claro', border_style='red',
                ))
            elif len(dataframe_eans) == 1:
                (ean_causador,) = dataframe_eans['EAN']
                divergiu_texto = dataframe_eans.iloc[0]['Divergiu']
                console.print(Panel(
                    f'[bold green]EAN {ean_causador}[/bold green] é o único que diverge — provável '
                    f'causador (diverge em {divergiu_texto}). Os outros EANs do grupo concordam entre '
                    f'si em todas as UFs — caso simples de conferir no cadastro do produto.',
                    title='Provável causador', border_style='green',
                ))
            else:
                console.print(_dataframe_para_tabela_rich(
                    dataframe_eans, titulo='EANs suspeitos', border_style='yellow',
                ))

            if ufs_ambiguas:
                console.print(
                    f'[yellow]{ufs_ambiguas} UF(s) sem maioria clara[/yellow] (dividido igualmente entre '
                    f'valores — não contado no diagnóstico acima).'
                )

            console.print(_dataframe_para_tabela_rich(
                rejeitado.montar_dataframe_divergencias(),
                titulo='Detalhe UF-a-UF',
                colunas_numericas=('Qtd EANs',),
            ))

    # Momento único desta rodada — TODO IcmsNcmRejeitado gravado agora
    # carrega o MESMO instante, mesmo que a gravação em si leve alguns
    # milissegundos linha a linha (garantia do vault, 13/09/2026).
    constatado_em = timezone.now()

    persistidor = PersistidorIcmsNcm()
    persistidor.carregar_existentes()
    persistidor.processar(agrupador.aceitos)

    persistidor_rejeitados = PersistidorIcmsNcmRejeitado(constatado_em)

    with transaction.atomic(using=obter_alias_banco_ativo()):
        persistidor.salvar()
        persistidor_rejeitados.salvar(agrupador.rejeitados)

    resumo_final = (
        f'[bold]Criados[/bold] (NCM+CST+Origem+UF novos)             {len(persistidor.para_criar)}\n'
        f'[bold]Atualizados[/bold] (NCM+CST+Origem+UF já existiam)   {len(persistidor.para_atualizar)}\n'
        f'Rejeitados registrados p/ auditoria                        {len(agrupador.rejeitados)}'
    )
    console.print()
    console.print(Panel(resumo_final, title='ICMS por NCM — Gravação concluída', border_style='green'))

    stdout.write(style.SUCCESS(
        f'[ICMS POR NCM] Importação concluída — {len(agrupador.rejeitados)} grupo(s) rejeitado(s) '
        f'registrado(s) pra consulta (tela de produto e tela de Auditoria Fiscal), constatado em '
        f'{timezone.localtime(constatado_em):%d/%m/%Y %H:%M:%S}.'
    ))