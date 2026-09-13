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
#
# Correção de 13/09/2026 (ver Descoberta "Auditoria Fiscal de Impostos de
# Saida" no vault): a validação agora é EXAUSTIVA — checa PIS E COFINS
# sempre, registrando os 2 se os 2 divergirem, em vez de parar no 1º campo
# divergente encontrado. Não muda se o grupo é aceito ou rejeitado (1
# campo divergente já rejeita o grupo inteiro, antes e depois desta
# correção) — muda só a completude do que fica registrado sobre a
# rejeição, agora persistida (Camada A da auditoria, ver
# PisCofinsNcmCstRejeitado em impostos/models.py) em vez de só impressa
# no stdout e descartada.

import shutil
from decimal import Decimal

import pandas as pd
from django.db import transaction
from django.utils import timezone
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.empresa import obter_alias_banco_ativo, obter_empresa_ativa
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA,
    COLUNA_EAN,
    ler_linhas_planilha_impostos_saida,
)
from impostos.models import PisCofinsNcmCst, PisCofinsNcmCstRejeitado
from produtos.models import Produto

COLUNA_NCM = 'NCM'
COLUNA_PIS = 'PIS'
COLUNA_COFINS = 'COFINS'

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
        self.pis = self._fracao_para_percentual_ou_none(self.linha_bruta.get(COLUNA_PIS))
        self.cofins = self._fracao_para_percentual_ou_none(self.linha_bruta.get(COLUNA_COFINS))
        return self

    # Função Objetivo: Aplica o CST (Produto.cst_saida), buscado em lote por
    # EAN fora desta classe (ver agrupar_pis_cofins_por_ncm_cst). 13/09/2026
    # — CST deixou de vir da planilha (Etapa 4 do roteiro de execução, mesma
    # mudança já aplicada ao ICMS na Etapa 3a): passa a vir de
    # Produto.cst_saida, já gravado por preencher_CST_produtos.
    def aplicar_cst_saida(self, cst_saida):
        self.cst = cst_saida
        return self

    # Precisa de NCM E de CST — os dois formam a chave do grupo.
    def esta_valida(self):
        return bool(self.ncm) and bool(self.cst)


# Função Objetivo: Registra a rejeição de 1 grupo NCM+CST — TODOS os
# campos (PIS e/ou COFINS) que divergem entre os EANs do grupo (não só o
# 1º encontrado, ver comentário no topo do arquivo), e quantos EANs
# formam o grupo.
class GrupoRejeitado:

    MAXIMO_EXEMPLOS_POR_GRUPO = 3

    def __init__(self, ncm, cst, total_eans_no_grupo, divergencias_por_campo):
        self.ncm = ncm
        self.cst = cst
        self.total_eans_no_grupo = total_eans_no_grupo
        # {'PIS': [(ean, valor), ...], 'COFINS': [...]} — só os campos que
        # de fato divergiram (1 ou os 2).
        self.divergencias_por_campo = divergencias_por_campo

    # Agrupa 1 lista (ean, valor) por valor, do mais pro menos frequente —
    # mesma lógica de NcmRejeitado._grupos_por_valor em importacao_icms_ncm.py.
    # Reaproveitada pelo __str__ (trunca em 3 exemplos) e por
    # para_dict_auditoria (persistido, sem truncar nenhum).
    @staticmethod
    def _grupos_por_valor(conflitantes):
        grupos = {}
        for ean, valor in conflitantes:
            grupos.setdefault(valor, []).append(ean)
        return sorted(grupos.items(), key=lambda item: -len(item[1]))

    # Função Objetivo: Relatório pro TERMINAL — trunca em 3 exemplos por
    # grupo de valor. Nunca usado pra persistir nada (ver para_dict_auditoria).
    def __str__(self):
        campos_ordenados = sorted(self.divergencias_por_campo)
        linhas = [
            f'NCM {self.ncm} + CST {self.cst} — diverge em {len(campos_ordenados)} campo(s) de '
            f'{self.total_eans_no_grupo} EAN(s) no grupo: {", ".join(campos_ordenados)}'
        ]
        for campo in campos_ordenados:
            conflitantes = self.divergencias_por_campo[campo]
            linhas.append(f'  {campo}:')
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
    # JSONField de PisCofinsNcmCstRejeitado (Camada A da auditoria, ver
    # impostos/models.py). Mesma lógica de NcmRejeitado.para_dict_auditoria
    # em importacao_icms_ncm.py — nunca esconde EAN nenhum atrás de "...".
    def para_dict_auditoria(self):
        resultado = {}
        for campo, conflitantes in self.divergencias_por_campo.items():
            grupos = self._grupos_por_valor(conflitantes)
            resultado[campo] = [
                {
                    'valor': str(valor) if valor is not None else None,
                    'qtd_eans': len(eans),
                    'eans': eans,
                }
                for valor, eans in grupos
            ]
        return resultado

    # Função Objetivo: Mesmos dados de __str__ (por campo, agrupado por
    # valor — do mais pro menos frequente), só que como DataFrame, pronto
    # pra virar rich.table.Table no terminal (ver
    # importar_pis_cofins_por_ncm_cst). Trunca exemplos em
    # MAXIMO_EXEMPLOS_POR_GRUPO igual ao __str__ — é exibição de terminal;
    # quem nunca trunca nada é para_dict_auditoria, que vai pro banco.
    # Mesmo padrão de NcmRejeitado.montar_dataframe_divergencias em
    # importacao_icms_ncm.py, trocando 'UF' por 'Campo' (aqui só existem 2
    # campos possíveis — PIS e COFINS —, nunca 27 UFs como lá).
    def montar_dataframe_divergencias(self):
        linhas = []
        for campo in sorted(self.divergencias_por_campo):
            for valor, eans in self._grupos_por_valor(self.divergencias_por_campo[campo]):
                valor_exibido = str(valor) if valor is not None else 'em branco'
                if len(eans) <= self.MAXIMO_EXEMPLOS_POR_GRUPO:
                    exemplos = ', '.join(eans)
                else:
                    exemplos = ', '.join(eans[:self.MAXIMO_EXEMPLOS_POR_GRUPO])
                    exemplos += f', ... (+{len(eans) - self.MAXIMO_EXEMPLOS_POR_GRUPO})'
                linhas.append({'Campo': campo, 'Valor': valor_exibido, 'Qtd EANs': len(eans), 'Exemplos': exemplos})
        return pd.DataFrame(linhas, columns=['Campo', 'Valor', 'Qtd EANs', 'Exemplos'])


# Função Objetivo: Agrupa as linhas por NCM+CST e aplica a regra de consistência.
class AgrupadorPisCofinsPorNcmCst:

    def __init__(self):
        self.linhas_por_grupo = {}  # (ncm, cst) -> lista de LinhaPisCofinsNcmCst
        # 13/09/2026 — renomeado de sem_ncm_ou_cst_na_planilha: CST não vem
        # mais da planilha (Etapa 4), então o nome antigo afirmava uma fonte
        # que não é mais verdade pro CST (mesmo rename já feito em
        # importacao_icms_ncm.py na Etapa 3a).
        self.sem_ncm_na_planilha_ou_sem_cst_no_produto = 0

        self.aceitos = {}  # (ncm, cst) -> {'pis': Decimal|None, 'cofins': Decimal|None}
        self.rejeitados = []  # lista de GrupoRejeitado

    def adicionar_linha(self, linha):
        if not linha.esta_valida():
            self.sem_ncm_na_planilha_ou_sem_cst_no_produto += 1
            return
        self.linhas_por_grupo.setdefault((linha.ncm, linha.cst), []).append(linha)

    # Função Objetivo: Decide se 1 grupo NCM+CST é aceito (e com quais
    # valores) ou rejeitado (e por quê). Checa PIS e COFINS — EXAUSTIVO
    # desde 13/09/2026 (ver comentário no topo do arquivo): sempre avalia
    # os 2 campos, registrando ambos se os 2 divergirem, em vez de parar
    # no 1º divergente. O grupo ainda é rejeitado com 1 campo divergente
    # só, mas o registro da rejeição agora é completo.
    def _validar_grupo(self, ncm, cst, linhas):
        if len(linhas) == 1:
            linha = linhas[0]
            return {'pis': linha.pis, 'cofins': linha.cofins}, None

        divergencias_por_campo = {}
        for campo, extrator in [('PIS', lambda l: l.pis), ('COFINS', lambda l: l.cofins)]:
            valores_encontrados = {extrator(linha) for linha in linhas}
            if len(valores_encontrados) > 1:
                divergencias_por_campo[campo] = [(linha.ean, extrator(linha)) for linha in linhas]

        if divergencias_por_campo:
            return None, GrupoRejeitado(ncm, cst, len(linhas), divergencias_por_campo)

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


# Função Objetivo: Busca em lote (1 única query, nunca N+1) o CST de saída
# pra um conjunto de EANs — Produto.cst_saida, já gravado por
# preencher_CST_produtos (Etapa 4 do roteiro de execução, mesmo padrão já
# usado em importacao_icms_ncm.py). EAN sem Produto correspondente, ou
# Produto sem cst_saida gravado, simplesmente não aparece com valor no
# dict — quem chama trata a ausência como cst=None (esta_valida() rejeita
# a linha, igual sempre foi pra CST ausente).
def _buscar_cst_saida_por_ean(eans):
    return dict(Produto.objects.filter(ean__in=eans).values_list('ean', 'cst_saida'))


# Função Objetivo: Ponto de entrada — lê a planilha inteira, busca o CST em
# lote (Produto.cst_saida) e devolve o agrupador já processado.
def agrupar_pis_cofins_por_ncm_cst(caminho_planilha):
    conversor = ConversorCelulaExcel(origem='openpyxl')
    agrupador = AgrupadorPisCofinsPorNcmCst()

    linhas = [
        LinhaPisCofinsNcmCst(linha_bruta, conversor).extrair_campos()
        for linha_bruta in ler_linhas_planilha_impostos_saida(caminho_planilha)
    ]

    eans_da_planilha = {linha.ean for linha in linhas if linha.ean}
    cst_por_ean = _buscar_cst_saida_por_ean(eans_da_planilha)

    for linha in linhas:
        linha.aplicar_cst_saida(cst_por_ean.get(linha.ean))
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


# Função Objetivo: Grava (substituição TOTAL, a cada rodada) o motivo de
# cada grupo NCM+CST rejeitado nesta importação — Camada A da auditoria
# fiscal (ver PisCofinsNcmCstRejeitado em impostos/models.py pro porquê de
# nunca fazer update incremental aqui, ao contrário de
# PersistidorPisCofinsNcmCst).
class PersistidorPisCofinsNcmCstRejeitado:

    def __init__(self, constatado_em):
        self.constatado_em = constatado_em

    def salvar(self, rejeitados):
        PisCofinsNcmCstRejeitado.objects.all().delete()
        novos = [
            PisCofinsNcmCstRejeitado(
                ncm=rejeitado.ncm,
                cst=rejeitado.cst,
                qtd_eans_no_grupo=rejeitado.total_eans_no_grupo,
                campos_divergentes=rejeitado.para_dict_auditoria(),
                constatado_em=self.constatado_em,
            )
            for rejeitado in rejeitados
        ]
        if novos:
            PisCofinsNcmCstRejeitado.objects.bulk_create(novos, batch_size=BATCH_SIZE_PADRAO)


# Função Objetivo: 1 linha por grupo NCM+CST rejeitado — visão geral pra
# saber, sem entrar no detalhe campo-a-campo de nenhum grupo, quantos EANs
# e quais campos (PIS e/ou COFINS) cada rejeição envolve. Recebe a lista
# já na ordem que deve aparecer — não ordena de novo aqui (ver
# importar_pis_cofins_por_ncm_cst). Mesmo padrão de
# _montar_dataframe_resumo_rejeitados em importacao_icms_ncm.py.
def _montar_dataframe_resumo_rejeitados(rejeitados_ordenados):
    linhas = []
    for rejeitado in rejeitados_ordenados:
        campos_ordenados = sorted(rejeitado.divergencias_por_campo)
        linhas.append({
            'NCM': rejeitado.ncm,
            'CST': rejeitado.cst,
            'Campos Divergentes': ', '.join(campos_ordenados),
            'EANs no Grupo': rejeitado.total_eans_no_grupo,
        })
    return pd.DataFrame(linhas, columns=['NCM', 'CST', 'Campos Divergentes', 'EANs no Grupo'])


# Função Objetivo: Cria o Console com 1 coluna de margem abaixo da
# largura detectada do terminal (mesma correção de importacao_icms_ncm.py
# e preenchimento_impostos_saida.py, ver comentário lá — duplicada aqui de
# propósito, cada módulo fica autocontido). Panel sempre estica pra
# largura TOTAL do console (Table segue o conteúdo); quando essa largura
# bate exatamente com a do terminal real do usuário, o terminal quebra
# linha sem \n e cola a borda do Panel no conteúdo. A margem de 1 coluna
# evita a disputa pela última coluna.
def _console_com_margem():
    largura_detectada = shutil.get_terminal_size(fallback=(80, 24)).columns
    return Console(width=max(largura_detectada - 1, 20))


# Função Objetivo: Converte um DataFrame (sempre pequeno — resumo ou
# detalhe de 1 grupo, nunca a planilha inteira) num rich.table.Table
# pronto pra console.print — única ponte entre pandas (organiza/ordena as
# linhas) e rich (exibe colorido no terminal). Mesma função de
# importacao_icms_ncm.py, duplicada aqui pelo mesmo motivo de
# _console_com_margem.
def _dataframe_para_tabela_rich(dataframe, titulo, colunas_numericas=(), border_style=None):
    tabela = Table(title=titulo, border_style=border_style)
    for coluna in dataframe.columns:
        tabela.add_column(coluna, justify='right' if coluna in colunas_numericas else 'left')
    for linha in dataframe.itertuples(index=False):
        tabela.add_row(*(str(valor) for valor in linha))
    return tabela


# Função Objetivo: Ponto de entrada do comando — lê, agrupa, valida e grava, do arquivo ao banco.
# Redesenho de 13/09/2026: mesmo tratamento visual (Rich + pandas) já
# aplicado em importacao_icms_ncm.py e preenchimento_impostos_saida.py —
# console com margem (evita o bug de borda do Panel colada), tabelas em
# vez de texto corrido, título de cada widget curto (evita o bug de
# título fragmentado em Table estreita), identidade de cada grupo impressa
# 1 vez em texto plano antes do detalhe. A lógica de agrupar/validar/gravar
# não muda em nada — só a exibição no terminal.
def importar_pis_cofins_por_ncm_cst(stdout, style, caminho_planilha=None):
    console = _console_com_margem()

    if caminho_planilha is None:
        empresa = obter_empresa_ativa()
        if empresa is None:
            raise RuntimeError(
                'Nenhuma empresa ativa — rode este comando com --empresa=MAGAZINE '
                'ou --empresa=SAMVALE.'
            )
        caminho_planilha = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]

    console.print('[bold]PIS/COFINS por NCM+CST[/bold] — lendo planilha Busca Legal...')

    agrupador = agrupar_pis_cofins_por_ncm_cst(caminho_planilha)

    tabela_agrupamento = Table(title='PIS/COFINS por NCM+CST — Agrupamento (NCM + CST)')
    tabela_agrupamento.add_column('Métrica')
    tabela_agrupamento.add_column('Quantidade', justify='right')
    tabela_agrupamento.add_row(
        'Grupos (NCM+CST) distintos encontrados', str(len(agrupador.linhas_por_grupo)),
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
        # primeiro nas 2 (mesma correção de 13/09/2026 de
        # importacao_icms_ncm.py).
        rejeitados_ordenados = sorted(agrupador.rejeitados, key=lambda r: -r.total_eans_no_grupo)

        console.print()
        console.print(
            f'[yellow]{len(agrupador.rejeitados)} grupo(s) rejeitado(s)[/yellow] — nada gravado destes '
            f'(regra: PIS e COFINS precisam bater entre todos os EANs do grupo).'
        )

        console.print()
        console.print(_dataframe_para_tabela_rich(
            _montar_dataframe_resumo_rejeitados(rejeitados_ordenados),
            titulo='Visão geral — 1 linha por grupo rejeitado (maior grupo primeiro)',
            colunas_numericas=('EANs no Grupo',),
        ))

        for rejeitado in rejeitados_ordenados:
            campos_ordenados = sorted(rejeitado.divergencias_por_campo)

            # Identidade do grupo impressa 1 VEZ só, como texto corrido —
            # mesma correção de 13/09/2026 de importacao_icms_ncm.py: título
            # comprido numa Table estreita fragmenta em várias linhas
            # centralizadas (Table dimensiona pelo conteúdo, não pela
            # largura do console; Panel não tem esse problema, mas repetir a
            # mesma frase longa em cada widget também é ruído).
            titulo_grupo = (
                f'NCM {rejeitado.ncm} + CST {rejeitado.cst} — diverge em {len(campos_ordenados)} '
                f'campo(s) de {rejeitado.total_eans_no_grupo} EAN(s) no grupo: {", ".join(campos_ordenados)}'
            )
            console.print()
            console.print(f'[bold]{titulo_grupo}[/bold]')

            console.print(_dataframe_para_tabela_rich(
                rejeitado.montar_dataframe_divergencias(),
                titulo='Detalhe por campo',
                colunas_numericas=('Qtd EANs',),
            ))

    multi_cst = agrupador.ncms_com_multiplos_csts()
    if multi_cst:
        console.print()
        console.print(
            '[yellow]Aviso informativo (não bloqueia o import):[/yellow] NCMs com mais de 1 CST aceito — '
            'confira se é variação tributária legítima ou cadastro de CST errado.'
        )

        tabela_multi_cst = Table(title='NCMs com mais de 1 CST aceito')
        tabela_multi_cst.add_column('NCM')
        tabela_multi_cst.add_column('CSTs (qtd. de EANs)')
        for ncm, csts in sorted(multi_cst.items()):
            descricao_csts = ', '.join(f'CST {cst} ({total} EAN(s))' for cst, total in csts)
            tabela_multi_cst.add_row(ncm, descricao_csts)
        console.print(tabela_multi_cst)

    # Momento único desta rodada — mesma garantia de importar_icms_por_ncm.
    constatado_em = timezone.now()

    persistidor = PersistidorPisCofinsNcmCst()
    persistidor.carregar_existentes()
    persistidor.processar(agrupador.aceitos)

    persistidor_rejeitados = PersistidorPisCofinsNcmCstRejeitado(constatado_em)

    # 1 ÚNICA transação — mesma garantia (e mesmo motivo pro using=) de
    # importar_icms_por_ncm em importacao_icms_ncm.py.
    with transaction.atomic(using=obter_alias_banco_ativo()):
        persistidor.salvar()
        persistidor_rejeitados.salvar(agrupador.rejeitados)

    resumo_final = (
        f'[bold]Criados[/bold] (NCM+CST novos)            {len(persistidor.para_criar)}\n'
        f'[bold]Atualizados[/bold] (NCM+CST já existiam)  {len(persistidor.para_atualizar)}\n'
        f'Rejeitados registrados p/ auditoria               {len(agrupador.rejeitados)}'
    )
    console.print()
    console.print(Panel(resumo_final, title='PIS/COFINS por NCM+CST — Gravação concluída', border_style='green'))

    stdout.write(style.SUCCESS(
        f'[PIS/COFINS POR NCM+CST] Importação concluída — {len(agrupador.rejeitados)} grupo(s) rejeitado(s) '
        f'registrado(s) pra consulta (tela de produto e tela de Auditoria Fiscal), constatado em '
        f'{timezone.localtime(constatado_em):%d/%m/%Y %H:%M:%S}.'
    )) 