# teste.py
#
# Função Objetivo: Prever, com dado real das 2 planilhas oficiais da Busca
# Legal (MAGAZINE e SAMVALE), o resultado exato que o import tratado da
# tabela PisCofinsNcmCst produziria — antes de escrever o comando de
# verdade. Roda a mesma lógica de agrupamento/rejeição já usada no ICMS
# (AgrupadorIcmsPorNcm), adaptada pra chave NCM+CST, e mostra:
#   1) quantos grupos (NCM+CST) seriam criados, e uma amostra deles;
#   2) se algum grupo tem divergência de PIS/COFINS de verdade (rejeitaria);
#   3) um relatório NÃO-BLOQUEANTE de NCMs com mais de 1 CST — não impede
#      o import, só avisa, porque já sabemos que isso costuma ser sinal de
#      cadastro errado (ver Descoberta no vault).
#
# Não grava nada no banco — só lê as 2 planilhas e reporta no terminal.

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from decimal import Decimal

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA,
    COLUNA_EAN,
    ler_linhas_planilha_impostos_saida,
)

COLUNA_NCM = 'NCM'
COLUNA_PIS = 'PIS'
COLUNA_COFINS = 'COFINS'
COLUNA_CST = 'CST'

DUAS_CASAS_DECIMAIS = Decimal('0.01')
MAXIMO_EXEMPLOS_POR_GRUPO = 3
MAXIMO_LINHAS_AMOSTRA = 15


# Função Objetivo: Normaliza um código textual (NCM, EAN, CST) lido da célula.
# Mesma lógica já usada em importacao_icms_ncm.py — se o Excel converteu o
# código pra número (perde o formato texto), remove o ".0" residual do float.
def _normalizar_codigo_celula(valor):
    if valor is None:
        return None
    if isinstance(valor, float):
        texto = str(int(valor)) if valor.is_integer() else str(valor)
    else:
        texto = str(valor)
    texto = texto.strip()
    return texto or None


# Função Objetivo: Representa 1 linha (EAN) já reduzida aos campos que este teste avalia.
class LinhaFiscal:

    def __init__(self, linha_bruta, conversor):
        self.linha_bruta = linha_bruta
        self.conversor = conversor
        self.ean = None
        self.ncm = None
        self.pis = None
        self.cofins = None
        self.cst = None

    # Fração (ex: 0,0165) -> percentual (ex: 1.65), preservando em branco como None.
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
        self.cst = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_CST))
        return self

    # Precisa de NCM E de CST — sem os dois, não dá pra formar a chave do grupo.
    def esta_valida(self):
        return bool(self.ncm) and bool(self.cst)


def _formatar_valor(valor):
    return 'em branco' if valor is None else str(valor)


# Função Objetivo: Representa 1 grupo (NCM, CST) já tratado — o que viraria
# 1 linha da tabela PisCofinsNcmCst se o import rodasse agora.
class GrupoPisCofinsNcmCst:

    def __init__(self, ncm, cst, linhas):
        self.ncm = ncm
        self.cst = cst
        self.linhas = linhas
        self.eans = [linha.ean for linha in linhas]
        self.pis_divergente = False
        self.cofins_divergente = False
        self.pis = None
        self.cofins = None

    # Função Objetivo: mesma regra do ICMS — só aceita o grupo se todos os
    # EANs concordarem no valor. Se divergir, rejeita e informa (nunca
    # grava um valor "no chute").
    def validar_e_tratar(self):
        valores_pis = {linha.pis for linha in self.linhas}
        valores_cofins = {linha.cofins for linha in self.linhas}

        if len(valores_pis) > 1:
            self.pis_divergente = True
        else:
            self.pis = self.linhas[0].pis

        if len(valores_cofins) > 1:
            self.cofins_divergente = True
        else:
            self.cofins = self.linhas[0].cofins

        return self

    def foi_rejeitado(self):
        return self.pis_divergente or self.cofins_divergente

    def _formatar_divergencia_campo(self, campo, extrator):
        grupos = {}
        for linha in self.linhas:
            grupos.setdefault(extrator(linha), []).append(linha.ean)
        grupos_ordenados = sorted(grupos.items(), key=lambda item: -len(item[1]))
        partes = []
        for valor, eans in grupos_ordenados:
            valor_exibido = _formatar_valor(valor)
            if len(eans) <= MAXIMO_EXEMPLOS_POR_GRUPO:
                partes.append(f'{valor_exibido}: {len(eans)} EAN(s) — {", ".join(eans)}')
            else:
                exemplos = ', '.join(eans[:MAXIMO_EXEMPLOS_POR_GRUPO])
                partes.append(f'{valor_exibido}: {len(eans)} EANs — ex: {exemplos}, ...')
        return f'      {campo}: ' + ' | '.join(partes)

    def __str__(self):
        if not self.foi_rejeitado():
            return (f'  OK   NCM {self.ncm} + CST {self.cst}: '
                    f'PIS {_formatar_valor(self.pis)}, COFINS {_formatar_valor(self.cofins)} '
                    f'({len(self.eans)} EAN(s))')

        linhas_texto = [f'  REJEITADO   NCM {self.ncm} + CST {self.cst} — divergência:']
        if self.pis_divergente:
            linhas_texto.append(self._formatar_divergencia_campo('PIS', lambda l: l.pis))
        if self.cofins_divergente:
            linhas_texto.append(self._formatar_divergencia_campo('COFINS', lambda l: l.cofins))
        return '\n'.join(linhas_texto)


# Função Objetivo: gera o relatório NÃO-BLOQUEANTE de NCMs com mais de 1
# CST — não impede nada, só sinaliza, porque já sabemos (ver Descoberta no
# vault) que isso costuma ser cadastro errado, não variação tributária legítima.
def _relatorio_ncms_com_multiplos_csts(grupos_aceitos):
    por_ncm = {}
    for grupo in grupos_aceitos:
        por_ncm.setdefault(grupo.ncm, []).append(grupo)

    multi_cst = {ncm: grupos for ncm, grupos in por_ncm.items() if len(grupos) > 1}
    if not multi_cst:
        print('  Nenhum NCM com mais de 1 CST nesta planilha.')
        return

    for ncm, grupos in sorted(multi_cst.items()):
        csts_e_contagens = ', '.join(
            f'CST {g.cst} ({len(g.eans)} EAN(s))' for g in sorted(grupos, key=lambda g: -len(g.eans))
        )
        print(f'  ⚠ NCM {ncm}: {len(grupos)} CSTs — {csts_e_contagens}')


# Função Objetivo: Lê a planilha oficial de 1 empresa, agrupa por NCM+CST,
# valida cada grupo e mostra a amostra + o relatório informativo.
def analisar_empresa(empresa):
    caminho = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]
    print(f'\n{"=" * 72}')
    print(f'{empresa} — {caminho}')
    print('=' * 72)

    conversor = ConversorCelulaExcel(origem='openpyxl')
    linhas = []
    ignoradas = 0
    for linha_bruta in ler_linhas_planilha_impostos_saida(caminho):
        linha = LinhaFiscal(linha_bruta, conversor).extrair_campos()
        if not linha.esta_valida():
            ignoradas += 1
            continue
        linhas.append(linha)

    print(f'Linhas lidas com NCM+CST: {len(linhas)} (sem NCM ou sem CST, ignoradas: {ignoradas})')

    por_ncm_cst = {}
    for linha in linhas:
        por_ncm_cst.setdefault((linha.ncm, linha.cst), []).append(linha)

    grupos = [
        GrupoPisCofinsNcmCst(ncm, cst, linhas_do_grupo).validar_e_tratar()
        for (ncm, cst), linhas_do_grupo in por_ncm_cst.items()
    ]
    grupos.sort(key=lambda g: (g.ncm, g.cst))

    aceitos = [g for g in grupos if not g.foi_rejeitado()]
    rejeitados = [g for g in grupos if g.foi_rejeitado()]

    print(f'\nGrupos (NCM+CST) encontrados: {len(grupos)} — {len(aceitos)} aceitos, {len(rejeitados)} rejeitados.')

    if rejeitados:
        print('\n--- Grupos rejeitados (divergência de PIS/COFINS dentro do mesmo NCM+CST) ---')
        for grupo in rejeitados:
            print(grupo)
    else:
        print('Nenhum grupo rejeitado — bate com o que já tínhamos validado antes.')

    print(f'\n--- Amostra do que a tabela PisCofinsNcmCst teria (primeiros {MAXIMO_LINHAS_AMOSTRA} grupos aceitos) ---')
    for grupo in aceitos[:MAXIMO_LINHAS_AMOSTRA]:
        print(grupo)
    if len(aceitos) > MAXIMO_LINHAS_AMOSTRA:
        print(f'  ... e mais {len(aceitos) - MAXIMO_LINHAS_AMOSTRA} grupo(s).')

    print('\n--- Relatório informativo: NCMs com mais de 1 CST (não bloqueia, só avisa) ---')
    _relatorio_ncms_com_multiplos_csts(aceitos)

    return {
        'total_grupos': len(grupos),
        'aceitos': len(aceitos),
        'rejeitados': len(rejeitados),
    }


if __name__ == '__main__':
    resultados = {
        empresa: analisar_empresa(empresa)
        for empresa in (EMPRESA_MAGAZINE, EMPRESA_SAMVALE)
    }

    print(f'\n{"=" * 72}')
    print('RESUMO FINAL')
    print('=' * 72)
    for empresa, resultado in resultados.items():
        print(f'{empresa}: {resultado["total_grupos"]} grupos '
              f'({resultado["aceitos"]} aceitos, {resultado["rejeitados"]} rejeitados)')