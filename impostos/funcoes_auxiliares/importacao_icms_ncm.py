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
# dentro de um mesmo NCM. Por isso:
#   - CST: vem direto da planilha, mesma coluna 'CST' que
#     importacao_pis_cofins_ncm_cst.py já lê (nunca inventado aqui).
#   - Origem da Mercadoria: NÃO existe na planilha — vem do CADASTRO DO
#     PRODUTO (Produto → impostos_entrada.origem_mercadoria_cadastro),
#     buscada em lote por EAN (1 única query, nunca N+1). Produto sem essa
#     origem sincronizada entra com origem=None — um valor de chave válido
#     como outro qualquer (mesma filosofia de PisCofinsNcmCst.pis/cofins:
#     em branco continua em branco, nunca vira um valor por acidente),
#     nunca motivo pra excluir a linha da validação.

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
from produtos.models import Produto

COLUNA_NCM = 'NCM'
COLUNA_CST = 'CST'  # mesma coluna que importacao_pis_cofins_ncm_cst.py já lê

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
        self.cst = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_CST))
        self.valores_por_uf = {
            uf: self._fracao_para_percentual_ou_none(self.linha_bruta.get(uf))
            for uf in UFS_ORDENADAS
        }
        return self

    # Função Objetivo: Aplica a Origem do Cadastro (buscada em lote por
    # EAN, fora desta classe — ver agrupar_icms_por_ncm) — nunca lida
    # direto da planilha, que não tem essa coluna.
    def aplicar_origem_cadastro(self, origem_mercadoria_cadastro):
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


# Função Objetivo: Agrupa as linhas por NCM+CST+Origem e aplica a regra de consistência.
class AgrupadorIcmsPorNcm:

    def __init__(self):
        self.linhas_por_grupo = {}  # (ncm, cst, origem) -> lista de LinhaIcmsNcm
        self.sem_ncm_ou_cst_na_planilha = 0

        self.aceitos = {}  # (ncm, cst, origem) -> {uf: Decimal}, só UFs preenchidas
        self.rejeitados = []  # lista de NcmRejeitado

    def adicionar_linha(self, linha):
        if not linha.esta_valida():
            self.sem_ncm_ou_cst_na_planilha += 1
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

    def relatorio_resumo(self):
        return (
            f'[ICMS POR NCM] Grupos (NCM+CST+Origem) distintos encontrados: {len(self.linhas_por_grupo)}\n'
            f'    Aceitos:    {len(self.aceitos)}\n'
            f'    Rejeitados: {len(self.rejeitados)}\n'
            f'    Linhas sem NCM ou sem CST na planilha (ignoradas): {self.sem_ncm_ou_cst_na_planilha}'
        )


# Função Objetivo: Busca em lote (1 única query, nunca N+1) a Origem da
# Mercadoria do Cadastro pra um conjunto de EANs — usada só aqui, porque a
# planilha Busca Legal não tem essa coluna (ver comentário no topo do
# arquivo). EAN sem Produto correspondente, ou Produto sem
# impostos_entrada sincronizado, simplesmente não aparece com valor no
# dict (values_list faz LEFT JOIN — vem None, nunca lança exceção) — quem
# chama trata a ausência como origem=None (valor de chave válido).
def _buscar_origem_cadastro_por_ean(eans):
    return dict(
        Produto.objects.filter(ean__in=eans).values_list('ean', 'impostos_entrada__origem_mercadoria_cadastro')
    )


# Função Objetivo: Ponto de entrada — lê a planilha inteira, busca a Origem
# do Cadastro em lote e devolve o agrupador já processado.
def agrupar_icms_por_ncm(caminho_planilha):
    conversor = ConversorCelulaExcel(origem='openpyxl')
    agrupador = AgrupadorIcmsPorNcm()

    linhas = [
        LinhaIcmsNcm(linha_bruta, conversor).extrair_campos()
        for linha_bruta in ler_linhas_planilha_impostos_saida(caminho_planilha)
    ]

    eans_da_planilha = {linha.ean for linha in linhas if linha.ean}
    origem_por_ean = _buscar_origem_cadastro_por_ean(eans_da_planilha)

    for linha in linhas:
        linha.aplicar_origem_cadastro(origem_por_ean.get(linha.ean))
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

    def relatorio_resumo(self):
        return (
            f'[ICMS POR NCM] Gravação concluída!\n'
            f'    Criados (NCM+CST+Origem+UF novos):            {len(self.para_criar)}\n'
            f'    Atualizados (NCM+CST+Origem+UF já existiam):  {len(self.para_atualizar)}'
        )


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
        stdout.write(style.WARNING('[GRUPOS REJEITADOS — DIVERGÊNCIA ENTRE EANs, NADA GRAVADO DESTES]'))
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

    # 1 ÚNICA transação: os grupos aceitos (criados/atualizados) e a
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
        f'[AUDITORIA] {len(agrupador.rejeitados)} grupo(s) NCM+CST+Origem rejeitado(s) registrados pra '
        f'consulta (tela de produto e tela de Auditoria Fiscal), constatado em '
        f'{timezone.localtime(constatado_em):%d/%m/%Y %H:%M:%S}.'
    ))