# impostos/funcoes_auxiliares/preenchimento_impostos_saida.py

# Função Objetivo: Preenche os 5 campos fiscais de saída do Produto a
# partir de 2 fontes — camada 1 do plano de Impostos de Saída (ver
# checkpoint no vault), agora reescrita pra fonte única (ver Decisão no
# vault: "Campos Fiscais de Saida no Produto Passam a Ser Alimentados
# pelas Tabelas Normalizadas"):
#   - cst_saida: direto da planilha Busca Legal, por EAN (sem tabela
#     normalizada própria — ele É a chave de busca usada em
#     PisCofinsNcmCst).
#   - icms_saida_sp / icms_saida_media: de IcmsNcmUf, por NCM do Produto
#     (SP direto; Média reaproveitando calcular_media_ponderada(), já
#     usada na tela de ICMS por NCM — nunca recalculada aqui de outro
#     jeito).
#   - pis_percentual / cofins_percentual: de PisCofinsNcmCst, por NCM do
#     Produto + CST lido NESTA MESMA linha da planilha.
#
# Regra de fallback (decidida no vault, vale pros 5 campos): quando não
# existe dado validado pra 1 campo (produto sem NCM, NCM sem tabela, CST
# sem match, ou coluna vazia na planilha pro CST), esse campo específico
# não é tocado — o valor que já estava gravado permanece. Nunca zera nem
# limpa por falta de dado.
#
# Nunca cria Produto novo a partir de dado fiscal — produto só nasce do ERP
# (ver importar_produtos_erp.py). EAN sem produto correspondente no banco é
# só reportado, nunca vira produto novo.

from decimal import Decimal

import openpyxl

from core.empresa import obter_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from impostos.models import IcmsNcmUf, PisCofinsNcmCst
from produtos.models import Produto

CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Arquivos usados para Popular Banco/Impostos Saida/TABELA SAIDA POR UF MAGAZINE.xlsx',
    EMPRESA_SAMVALE: 'Arquivos usados para Popular Banco/Impostos Saida/TABELA SAIDA POR UF SAMVALE.xlsx',
}

# * [EXPLICAÇÃO] → Nome exato das colunas na linha 2 da planilha Busca
#                  Legal (linha 1 é só o grupo — ENTRADA/SAÍDA/UF de
#                  destino — descartada). Se algum desses nomes não bater
#                  com o cabeçalho real da planilha, a coluna some do
#                  dicionário da linha. ICMS/ICMS MÉDIA/PIS/COFINS não são
#                  mais lidos daqui pra alimentar o Produto — só CST (os
#                  outros 4 campos agora vêm de IcmsNcmUf/PisCofinsNcmCst).
COLUNA_EAN = 'Cód Barras'
COLUNA_CST = 'CST'  # mesma coluna que importacao_pis_cofins_ncm_cst.py já lê


# Função Objetivo: Lê a planilha Busca Legal (cabeçalho de 2 linhas), devolvendo 1 dicionário por linha de dado.
# Explicação em detalhe: diferente de ler_linhas_planilha_erp (cabeçalho de
# 1 linha só, com colunas duplicadas) — aqui a linha 1 é o grupo (descartada),
# a linha 2 é o nome real da coluna, e não há coluna duplicada nesta
# planilha, então não precisa da lógica de resolução de ambiguidade.
def ler_linhas_planilha_impostos_saida(caminho):
    workbook = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    planilha = workbook.active

    linhas = planilha.iter_rows(values_only=True)
    next(linhas)  # linha 1 — grupo (ENTRADA/SAÍDA/ICMS SAÍDA POR UF DE DESTINO), não usada aqui
    cabecalho = next(linhas)  # linha 2 — nome real de cada coluna

    linhas_como_dicionario = []
    for linha_bruta in linhas:
        if all(valor is None for valor in linha_bruta):
            continue  # linha em branco no fim da planilha
        linhas_como_dicionario.append(dict(zip(cabecalho, linha_bruta)))

    workbook.close()
    return linhas_como_dicionario


# Função Objetivo: Normaliza um código textual (EAN, CST) lido da célula.
# Explicação em detalhe: mesma lógica já usada em
# preencher_cest_planilha_samvale.py e em importacao_icms_ncm.py/
# importacao_pis_cofins_ncm_cst.py (lá como _normalizar_codigo_celula) — se
# o Excel converteu o código pra número (perde o formato texto), remove o
# ".0" residual do float. Nunca faz padding de zero à esquerda: melhor não
# casar com nada (contabilizado como "sem correspondência") do que casar
# errado. Renomeada de _normalizar_ean pra _normalizar_codigo_celula porque
# agora normaliza EAN e CST — mesmo nome já usado pra essa lógica idêntica
# nos outros 2 módulos de import da planilha Busca Legal.
def _normalizar_codigo_celula(valor):
    if valor is None:
        return None
    if isinstance(valor, float):
        texto = str(int(valor)) if valor.is_integer() else str(valor)
    else:
        texto = str(valor)
    texto = texto.strip()
    return texto or None


# Função Objetivo: Normaliza um código JÁ PERSISTIDO (NCM do Produto, ou
# vindo de IcmsNcmUf/PisCofinsNcmCst) pra comparação na busca da fonte
# única.
# Explicação em detalhe (13/09/2026): diferente de _normalizar_codigo_celula
# (que trata valor CRU vindo do Excel, podendo ser float) — aqui os 2 lados
# da comparação já são texto vindo do banco. Mesmo assim, aplica a mesma
# limpeza de ".0" residual nos 2 lados (Produto.ncm E o ncm das tabelas
# normalizadas), porque Produto.ncm vem do ERP via conversão genérica pra
# texto (ConversorCelulaExcel.para_texto), que NÃO tira esse ".0" quando o
# Excel do ERP lê o NCM como número — diferente da normalização já aplicada
# ao gravar IcmsNcmUf/PisCofinsNcmCst. Normaliza os 2 lados sempre, mesmo
# quando 1 deles já devia estar limpo, pra nunca depender de as duas fontes
# virem no mesmo formato por acaso (decisão do Matheus, 13/09/2026).
def _normalizar_chave_para_busca(valor):
    if not valor:
        return None
    texto = str(valor).strip()
    if texto.endswith('.0'):
        texto = texto[:-2]
    return texto or None


# Função Objetivo: Representa 1 linha da planilha, já reduzida ao que essa
# camada ainda lê direto do arquivo — EAN (chave de casamento) e CST (única
# coisa que continua vindo direto da planilha; os outros 4 campos vêm das
# tabelas normalizadas, resolvidos em ImportadorImpostosSaida, não aqui).
class LinhaImpostoSaida:

    CAMPOS_PRODUTO = ['cst_saida', 'icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual']

    def __init__(self, linha_bruta):
        self.linha_bruta = linha_bruta

        self.ean = None
        self.cst_saida = None

    def extrair_campos(self):
        self.ean = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_EAN))
        self.cst_saida = _normalizar_codigo_celula(self.linha_bruta.get(COLUNA_CST))
        return self

    # Função Objetivo: Diz se essa linha tem o dado mínimo pra casar com um Produto.
    def esta_valida(self):
        return bool(self.ean)

    # Função Objetivo: Devolve os campos prontos pra sobrescrever num Produto existente.
    # Explicação em detalhe: cst_saida só entra no dict se a planilha trouxe
    # valor pra essa linha — se vier em branco, o campo nem aparece aqui, e
    # quem chama (setattr campo a campo) simplesmente não toca no produto,
    # mantendo o valor antigo (regra "sem dado validado, fica o antigo",
    # decidida no vault).
    def para_dict_produto(self):
        dados = {}
        if self.cst_saida is not None:
            dados['cst_saida'] = self.cst_saida
        return dados


# Função Objetivo: Orquestra o preenchimento inteiro — planilha (cst_saida)
# + tabelas normalizadas IcmsNcmUf/PisCofinsNcmCst (os outros 4 campos) —
# até o banco.
class ImportadorImpostosSaida:

    # Função Objetivo: Resolve o caminho da planilha sozinho a partir da empresa ativa, se não vier explícito.
    def __init__(self, caminho_planilha=None):
        if caminho_planilha is None:
            empresa = obter_empresa_ativa()
            if empresa is None:
                raise RuntimeError(
                    'Nenhuma empresa ativa — rode este comando com --empresa=MAGAZINE '
                    'ou --empresa=SAMVALE.'
                )
            caminho_planilha = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]

        self.caminho_planilha = caminho_planilha

        self.produtos_por_ean = {}
        self.produtos_para_atualizar = []

        self.icms_por_ncm = {}            # ncm normalizado -> {uf: aliquota}
        self.pis_cofins_por_ncm_cst = {}  # (ncm normalizado, cst normalizado) -> (pis, cofins)

        self.atualizados = 0
        self.sem_ean_na_planilha = 0
        self.eans_duplicados_na_planilha = 0
        self.sem_produto_correspondente = 0
        self.eans_sem_produto = []

        # Contadores por campo — "de_tabela"/"de_planilha" é quanto veio de
        # dado validado nesta rodada; "mantido" é quanto ficou com o valor
        # antigo por falta de dado (regra do vault: nunca zera por acidente).
        self.cst_de_planilha = 0
        self.cst_mantido = 0
        self.icms_sp_de_tabela = 0
        self.icms_sp_mantido = 0
        self.icms_media_de_tabela = 0
        self.icms_media_mantido = 0
        self.pis_cofins_de_tabela = 0
        self.pis_cofins_mantido = 0

    # Função Objetivo: Carrega em memória os produtos já existentes, só com os campos que este comando toca.
    # Explicação em detalhe: 'ncm' entra aqui porque agora é a chave de
    # busca nas tabelas normalizadas — sem isso no .only(), cada acesso a
    # produto.ncm dispararia 1 query extra por produto (N+1).
    def carregar_produtos_existentes(self):
        self.produtos_por_ean = {
            produto.ean: produto
            for produto in Produto.objects.only(
                'id', 'ean', 'ncm', 'cst_saida',
                'icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual',
            )
        }

    # Função Objetivo: Carrega em memória, 1 única vez, as 2 tabelas
    # normalizadas (fonte única) — mesmo padrão de carregar_produtos_existentes,
    # pra não bater no banco por produto.
    def carregar_tabelas_normalizadas(self):
        for registro in IcmsNcmUf.objects.all():
            ncm = _normalizar_chave_para_busca(registro.ncm)
            if ncm is None:
                continue
            self.icms_por_ncm.setdefault(ncm, {})[registro.uf] = registro.aliquota

        for registro in PisCofinsNcmCst.objects.all():
            ncm = _normalizar_chave_para_busca(registro.ncm)
            cst = _normalizar_chave_para_busca(registro.cst)
            if ncm is None or cst is None:
                continue
            self.pis_cofins_por_ncm_cst[(ncm, cst)] = (registro.pis, registro.cofins)

    # Função Objetivo: Resolve os 4 campos vindos das tabelas normalizadas
    # pra 1 produto — só entra no dict o que foi de fato encontrado; o que
    # não foi encontrado nem aparece, e quem chama (setattr campo a campo)
    # não toca no produto, mantendo o valor antigo.
    # Explicação em detalhe: o CST usado na busca de PIS/COFINS é o LIDO
    # NESTA MESMA LINHA da planilha (cst_saida_da_linha), não o que já
    # estava gravado no produto — os dois vêm da mesma linha/planilha, e
    # usar um CST antigo aqui poderia buscar com chave desatualizada.
    # NCM+CST encontrado é considerado dado validado mesmo quando pis/cofins
    # vêm em branco na tabela (produto monofásico) — em branco ali é uma
    # resposta validada (0%), não "sem dado", por isso grava 0 em vez de
    # manter o antigo.
    def _calcular_campos_por_tabela(self, produto, cst_saida_da_linha):
        campos = {}

        ncm_produto = _normalizar_chave_para_busca(produto.ncm)
        if ncm_produto is None:
            return campos

        valores_por_uf = self.icms_por_ncm.get(ncm_produto)
        if valores_por_uf:
            aliquota_sp = valores_por_uf.get('SP')
            if aliquota_sp is not None:
                campos['icms_saida_sp'] = aliquota_sp

            # Import local — evita ciclo de import: exibicao_icms_por_ncm.py
            # importa de importacao_icms_ncm.py, que por sua vez importa
            # deste módulo (preenchimento_impostos_saida.py) as constantes
            # da planilha. Um import no topo deste arquivo fecharia o ciclo.
            from impostos.funcoes_auxiliares.exibicao_icms_por_ncm import calcular_media_ponderada
            media = calcular_media_ponderada(valores_por_uf)
            if media is not None:
                campos['icms_saida_media'] = media

        cst_normalizado = _normalizar_chave_para_busca(cst_saida_da_linha)
        if cst_normalizado is not None:
            chave = (ncm_produto, cst_normalizado)
            if chave in self.pis_cofins_por_ncm_cst:
                pis, cofins = self.pis_cofins_por_ncm_cst[chave]
                campos['pis_percentual'] = pis if pis is not None else Decimal('0')
                campos['cofins_percentual'] = cofins if cofins is not None else Decimal('0')

        return campos

    # Função Objetivo: Lê a planilha inteira e casa cada linha com o Produto correspondente.
    def processar_planilha(self):
        eans_ja_processados = set()

        for linha_bruta in ler_linhas_planilha_impostos_saida(self.caminho_planilha):
            linha = LinhaImpostoSaida(linha_bruta).extrair_campos()

            if not linha.esta_valida():
                self.sem_ean_na_planilha += 1
                continue

            if linha.ean in eans_ja_processados:
                self.eans_duplicados_na_planilha += 1
                continue
            eans_ja_processados.add(linha.ean)

            produto = self.produtos_por_ean.get(linha.ean)
            if produto is None:
                self.sem_produto_correspondente += 1
                self.eans_sem_produto.append(linha.ean)
                continue

            campos_planilha = linha.para_dict_produto()
            campos_tabela = self._calcular_campos_por_tabela(produto, linha.cst_saida)

            if 'cst_saida' in campos_planilha:
                self.cst_de_planilha += 1
            else:
                self.cst_mantido += 1

            if 'icms_saida_sp' in campos_tabela:
                self.icms_sp_de_tabela += 1
            else:
                self.icms_sp_mantido += 1

            if 'icms_saida_media' in campos_tabela:
                self.icms_media_de_tabela += 1
            else:
                self.icms_media_mantido += 1

            if 'pis_percentual' in campos_tabela:
                self.pis_cofins_de_tabela += 1
            else:
                self.pis_cofins_mantido += 1

            for campo, valor in {**campos_planilha, **campos_tabela}.items():
                setattr(produto, campo, valor)

            self.produtos_para_atualizar.append(produto)
            self.atualizados += 1

    # Função Objetivo: Grava tudo no banco em lote, 1 única vez.
    def salvar(self):
        if self.produtos_para_atualizar:
            Produto.objects.bulk_update(
                self.produtos_para_atualizar, LinhaImpostoSaida.CAMPOS_PRODUTO, batch_size=BATCH_SIZE_PADRAO,
            )

    # Função Objetivo: Roda o preenchimento inteiro, da planilha e das tabelas normalizadas ao banco.
    def rodar_preenchimento_completo(self):
        self.carregar_produtos_existentes()
        self.carregar_tabelas_normalizadas()
        self.processar_planilha()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[IMPOSTOS DE SAÍDA] Concluído!\n'
            f'    Produtos atualizados: {self.atualizados}\n'
            f'    Linhas sem EAN na planilha (ignoradas): {self.sem_ean_na_planilha}\n'
            f'    EAN duplicado na planilha (mantida a 1ª ocorrência): {self.eans_duplicados_na_planilha}\n'
            f'    EAN da planilha sem produto correspondente no banco: {self.sem_produto_correspondente}\n'
            f'\n'
            f'    Por campo (validado nesta rodada / manteve valor antigo):\n'
            f'        cst_saida:                    {self.cst_de_planilha} / {self.cst_mantido}\n'
            f'        icms_saida_sp (IcmsNcmUf):    {self.icms_sp_de_tabela} / {self.icms_sp_mantido}\n'
            f'        icms_saida_media (calculado): {self.icms_media_de_tabela} / {self.icms_media_mantido}\n'
            f'        pis/cofins (PisCofinsNcmCst): {self.pis_cofins_de_tabela} / {self.pis_cofins_mantido}'
        )


# Função Objetivo: Ponto de entrada chamado pelo Command.
def preencher_impostos_saida(stdout, style):
    stdout.write('[IMPOSTOS DE SAÍDA] Lendo planilha Busca Legal...')

    importador = ImportadorImpostosSaida().rodar_preenchimento_completo()

    stdout.write('')
    stdout.write(style.SUCCESS(importador.relatorio()))

    if importador.eans_sem_produto:
        stdout.write(style.WARNING(
            '\n[EAN DA PLANILHA SEM PRODUTO CORRESPONDENTE NO BANCO — CONFERIR]'
        ))
        for ean in importador.eans_sem_produto:
            stdout.write(style.WARNING(f'    {ean}'))