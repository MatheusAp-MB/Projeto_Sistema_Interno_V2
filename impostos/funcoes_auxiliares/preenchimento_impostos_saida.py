# impostos/funcoes_auxiliares/preenchimento_impostos_saida.py

# Função Objetivo: Preenche os 5 campos fiscais de saída do Produto a
# partir de 2 fontes — camada 1 do plano de Impostos de Saída (ver
# checkpoint no vault), reescrita pra fonte única (ver Decisão no vault:
# "Campos Fiscais de Saida no Produto Passam a Ser Alimentados pelas
# Tabelas Normalizadas") e depois corrigida pra rodar sobre o catálogo
# inteiro, não só quem está na planilha (ver Descoberta no vault):
#   - cst_saida: direto da planilha Busca Legal, por EAN (sem tabela
#     normalizada própria — ele É a chave de busca usada em
#     PisCofinsNcmCst, e agora também em IcmsNcmUf). Único campo que ainda
#     depende de o produto estar na planilha desta rodada.
#   - icms_saida_sp / icms_saida_media: de IcmsNcmUf, por NCM + CST +
#     Origem da Mercadoria (Cadastro) do Produto (decisão no vault,
#     13/09/2026 — "Chave de Consolidacao do ICMS por NCM Passa a Incluir
#     CST e Origem da Mercadoria": NCM sozinho não garante os mesmos 27
#     valores). SP direto; Média reaproveitando calcular_media_ponderada(),
#     já usada na tela de ICMS por NCM — nunca recalculada aqui de outro
#     jeito. Precisam de CST pra buscar (igual PIS/COFINS já precisava) —
#     produto sem CST não tem como ter os 2 campos preenchidos por esta
#     tabela agora. Origem vem de
#     produto.impostos_entrada.origem_mercadoria_cadastro — None quando o
#     produto não tem essa sincronização ainda, e None é um valor de chave
#     válido (mesma filosofia do resto da auditoria).
#   - pis_percentual / cofins_percentual: de PisCofinsNcmCst, por NCM do
#     Produto + CST — o CST lido nesta rodada da planilha quando existir,
#     senão o cst_saida que já estava gravado (não precisa vir tudo da
#     mesma linha). Rodam pra TODO produto com NCM+CST salvos.
#
# Regra de fallback (decidida no vault, 13/09/2026 — revista): pro
# cst_saida, quando o EAN não está na planilha desta rodada, o campo não
# é tocado, mantém o valor antigo (nunca existiu uma versão "pré-tabela"
# desse campo pra desconfiar). Pros outros 4 campos (vindos das tabelas
# normalizadas), a regra mudou: quando não existe mais dado validado, o
# campo é explicitamente limpo (None) em vez de manter o que estava lá —
# porque esse valor antigo pode ser resquício de antes de qualquer
# validação por NCM existir (dado nunca conferido, indistinguível de um
# validado só de olhar o campo). Isso é seguro mesmo com planilhas
# futuras menores ou com divergência nova: IcmsNcmUf/PisCofinsNcmCst
# nunca apagam nem regridem um NCM(+CST) já aceito antes — só param de
# tocar nele quando sai da planilha ou é rejeitado numa rodada futura —
# então um produto que já validou uma vez nunca perde esse dado depois.
#
# Nunca cria Produto novo a partir de dado fiscal — produto só nasce do ERP
# (ver importar_produtos_erp.py). EAN sem produto correspondente no banco é
# só reportado, nunca vira produto novo.
#
# Correção de 13/09/2026, mais tarde ainda: a saída no terminal foi
# reescrita usando rich (Table/Panel/Columns) + pandas (organiza os 3
# campos vindos das tabelas normalizadas numa única tabela) — mesmo
# tratamento já aplicado em importacao_icms_ncm.py, pro texto corrido virar
# tabelas. Nenhuma regra de negócio muda. ImportadorImpostosSaida.relatorio()
# continua existindo do jeito que estava (mesmo padrão de método que os
# outros importadores do projeto usam, ver
# core/management/commands/popular_banco_suporte/*.py) — só deixou de ser
# chamado por preencher_impostos_saida, que agora monta a saída direto com
# rich/pandas a partir dos mesmos contadores públicos do importador.
#
# Correção de 13/09/2026, mais tarde ainda (achado do Matheus): virar
# tabela resolve legibilidade, mas não usa cor nenhuma pra separar "número
# normal" de "número que merece atenção" — e o mais importante dos 3
# contadores por campo é "zerado nesta rodada" (dado que ANTES estava
# validado e acabou de ser apagado agora), não "validado" nem "continua
# vazio". Essa tela é debug (pro Matheus e pra mim, Claude, entendermos se
# o código tá se comportando certo — não é tela de usuário final), então o
# que importa é esse número saltar aos olhos quando não for 0, em vez de
# ficar com o mesmo peso visual dos outros 2. Também: "sem atualização" em
# cst_saida parece alarmante mas é esperado (produto fora da planilha
# desta rodada) — ganhou legenda pra não confundir com anomalia.

import shutil
from decimal import Decimal

import openpyxl
import pandas as pd
from django.core.exceptions import ObjectDoesNotExist
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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


# Função Objetivo: Orquestra o preenchimento inteiro — planilha (só
# cst_saida) + tabelas normalizadas IcmsNcmUf/PisCofinsNcmCst (os outros 4
# campos) — até o banco. Roda sobre TODO produto carregado, não só quem
# tem linha na planilha desta rodada — a planilha deixou de ser "lista de
# presença": só decide quem recebe cst_saida atualizado; os outros 4
# campos são recalculados pra qualquer produto com NCM/CST já salvos (ver
# Descoberta no vault sobre o loop restrito à planilha deixando produto de
# fora). Os 4 campos recalculados são explicitamente limpos (None) quando
# deixam de ter dado validado — nunca ficam com um valor de antes da
# reescrita pra fonte única, sem validação nenhuma por trás (ver Decisão
# no vault, 13/09/2026).
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

        # (ncm, cst, origem) normalizados -> {uf: aliquota} — chave
        # expandida em 13/09/2026 (ver Decisão no vault sobre CST+Origem
        # no ICMS).
        self.icms_por_grupo = {}
        self.pis_cofins_por_ncm_cst = {}  # (ncm normalizado, cst normalizado) -> (pis, cofins)
        self.cst_por_ean = {}             # ean -> cst_saida lido nesta rodada da planilha

        self.atualizados = 0
        self.sem_ean_na_planilha = 0
        self.eans_duplicados_na_planilha = 0
        self.sem_produto_correspondente = 0
        self.eans_sem_produto = []

        # cst_saida: só vem direto da planilha, por EAN, sem nenhuma
        # conferência cruzada entre produtos (diferente dos outros 4,
        # explicado abaixo) — por isso os nomes não usam "validado" aqui.
        # 2 situações: a planilha trouxe CST novo pra esse EAN nesta
        # rodada (atualizado), ou não trouxe (o campo não é tocado — pode
        # já ter um CST de rodada anterior, ou pode nunca ter tido
        # nenhum; o nome não afirma qual dos dois é o caso).
        self.cst_atualizado_pela_planilha = 0
        self.cst_sem_atualizacao_na_planilha = 0

        # Os outros 4 campos vêm das tabelas normalizadas, que exigem
        # 100% de acordo entre todos os produtos do mesmo NCM(+CST) — por
        # isso "validado" aqui é uma garantia real, diferente do
        # cst_saida. Quando não há mais dado validado, o campo é
        # explicitamente zerado (None), nunca deixado com um valor antigo
        # que pode ser resquício de antes de qualquer validação por NCM
        # existir. 3 situações por campo, nomeadas só pelo que aconteceu
        # (ou não) NESTA rodada — nenhum nome afirma histórico que o
        # código não pode provar: validado (achou dado validado agora) /
        # zerado_nesta_rodada (tinha valor, não achou mais dado validado,
        # foi zerado agora) / continua_vazio (já estava vazio antes, nada
        # muda agora).
        self.icms_sp_validado = 0
        self.icms_sp_zerado_nesta_rodada = 0
        self.icms_sp_continua_vazio = 0
        self.icms_media_validado = 0
        self.icms_media_zerado_nesta_rodada = 0
        self.icms_media_continua_vazio = 0
        self.pis_cofins_validado = 0
        self.pis_cofins_zerado_nesta_rodada = 0
        self.pis_cofins_continua_vazio = 0

    # Função Objetivo: Carrega em memória os produtos já existentes, só com os campos que este comando toca.
    # Explicação em detalhe: 'ncm' entra aqui porque agora é a chave de
    # busca nas tabelas normalizadas — sem isso no .only(), cada acesso a
    # produto.ncm dispararia 1 query extra por produto (N+1).
    def carregar_produtos_existentes(self):
        # select_related('impostos_entrada') + only(...) com o campo por
        # trás do "." — 1 único JOIN pra todo o catálogo, nunca 1 query
        # extra por produto pra descobrir a Origem do Cadastro (mesma
        # garantia de "sem N+1" do resto do arquivo). Produto sem
        # impostos_entrada sincronizado continua acessível — só o acesso a
        # produto.impostos_entrada levanta ObjectDoesNotExist, tratado em
        # processar_todos_os_produtos.
        self.produtos_por_ean = {
            produto.ean: produto
            for produto in Produto.objects.select_related('impostos_entrada').only(
                'id', 'ean', 'ncm', 'cst_saida',
                'icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual',
                'impostos_entrada__origem_mercadoria_cadastro',
            )
        }

    # Função Objetivo: Carrega em memória, 1 única vez, as 2 tabelas
    # normalizadas (fonte única) — mesmo padrão de carregar_produtos_existentes,
    # pra não bater no banco por produto.
    def carregar_tabelas_normalizadas(self):
        for registro in IcmsNcmUf.objects.all():
            ncm = _normalizar_chave_para_busca(registro.ncm)
            cst = _normalizar_chave_para_busca(registro.cst)
            if ncm is None or cst is None:
                continue
            origem = _normalizar_chave_para_busca(registro.origem_mercadoria_cadastro)
            self.icms_por_grupo.setdefault((ncm, cst, origem), {})[registro.uf] = registro.aliquota

        for registro in PisCofinsNcmCst.objects.all():
            ncm = _normalizar_chave_para_busca(registro.ncm)
            cst = _normalizar_chave_para_busca(registro.cst)
            if ncm is None or cst is None:
                continue
            self.pis_cofins_por_ncm_cst[(ncm, cst)] = (registro.pis, registro.cofins)

    # Função Objetivo: Resolve os 4 campos vindos das tabelas normalizadas
    # pra 1 produto — só entra no dict o que foi de fato encontrado; o que
    # não foi encontrado nem aparece aqui (quem decide o que fazer com a
    # ausência — limpar pra None ou deixar como já estava vazio — é quem
    # chama, em processar_todos_os_produtos, não esta função).
    # Explicação em detalhe: o CST usado na busca (ICMS E PIS/COFINS,
    # desde 13/09/2026 — ver Decisão no vault) é o LIDO NESTA MESMA LINHA
    # da planilha (cst_saida_da_linha), não o que já estava gravado no
    # produto — os dois vêm da mesma linha/planilha, e usar um CST antigo
    # aqui poderia buscar com chave desatualizada. origem_produto é
    # sempre a Origem do CADASTRO (produto.impostos_entrada — resolvida
    # por quem chama, nunca aqui, pra não repetir o try/except em cada
    # produto), None quando o produto não tem essa sincronização ainda —
    # None é um valor de chave válido, casa com IcmsNcmUf que também tem
    # origem=None pros mesmos casos.
    # Grupo (NCM+CST+Origem) encontrado é considerado dado validado mesmo
    # quando os campos vêm em branco na tabela (produto monofásico, ou
    # ICMS genuinamente ausente numa UF) — em branco ali é uma resposta
    # validada, não "sem dado".
    def _calcular_campos_por_tabela(self, produto, cst_saida_da_linha, origem_produto):
        campos = {}

        ncm_produto = _normalizar_chave_para_busca(produto.ncm)
        if ncm_produto is None:
            return campos

        cst_normalizado = _normalizar_chave_para_busca(cst_saida_da_linha)
        if cst_normalizado is None:
            return campos

        origem_normalizada = _normalizar_chave_para_busca(origem_produto)

        valores_por_uf = self.icms_por_grupo.get((ncm_produto, cst_normalizado, origem_normalizada))
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

        chave_pis_cofins = (ncm_produto, cst_normalizado)
        if chave_pis_cofins in self.pis_cofins_por_ncm_cst:
            pis, cofins = self.pis_cofins_por_ncm_cst[chave_pis_cofins]
            campos['pis_percentual'] = pis if pis is not None else Decimal('0')
            campos['cofins_percentual'] = cofins if cofins is not None else Decimal('0')

        return campos

    # Função Objetivo: Lê a planilha só pra extrair EAN + CST — a ÚNICA
    # coisa que ainda vem dela. Não decide mais quem é processado (isso
    # agora é processar_todos_os_produtos); só alimenta cst_por_ean.
    def carregar_cst_da_planilha(self):
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

            if linha.ean not in self.produtos_por_ean:
                self.sem_produto_correspondente += 1
                self.eans_sem_produto.append(linha.ean)
                continue

            if linha.cst_saida is not None:
                self.cst_por_ean[linha.ean] = linha.cst_saida

    # Função Objetivo: Passa por TODO produto carregado — não só quem tem
    # linha na planilha desta rodada. cst_saida só atualiza pra quem tem
    # linha (via cst_por_ean); quando não tem, o campo não é tocado —
    # nunca existiu uma "versão pré-validação" desse campo pra desconfiar.
    # Os outros 4 campos são diferentes: quando não há mais dado validado
    # pra eles, são explicitamente zerados (None) em vez de manter o que
    # estivesse lá — esse valor antigo pode ser resquício de antes de
    # qualquer validação por NCM existir (ver Descoberta no vault).
    # Explicação em detalhe: quando a planilha não trouxe CST novo pra
    # este EAN nesta rodada, usa o cst_saida que já está gravado no
    # produto (de uma rodada anterior) como chave de busca em
    # PisCofinsNcmCst — não precisa vir tudo da mesma linha pra continuar
    # funcionando. Isso é seguro mesmo com planilhas futuras menores ou
    # com divergência nova: IcmsNcmUf/PisCofinsNcmCst nunca apagam nem
    # regridem um NCM(+CST) já aceito antes (ver PersistidorIcmsNcm/
    # PersistidorPisCofinsNcmCst) — só ficam sem tocar nele quando sai da
    # planilha ou é rejeitado numa rodada futura, então um produto que já
    # validou uma vez nunca perde esse dado depois.
    def processar_todos_os_produtos(self):
        for ean, produto in self.produtos_por_ean.items():
            cst_da_planilha = self.cst_por_ean.get(ean)
            cst_para_busca = cst_da_planilha if cst_da_planilha is not None else produto.cst_saida

            # Origem do Cadastro — só existe quando o produto já tem
            # impostos_entrada sincronizado (Sysemp/XML). Ausência é caso
            # normal (mesmo padrão de produtos/views.py), nunca erro.
            try:
                origem_produto = produto.impostos_entrada.origem_mercadoria_cadastro
            except ObjectDoesNotExist:
                origem_produto = None

            campos_tabela = self._calcular_campos_por_tabela(produto, cst_para_busca, origem_produto)

            campos = {}
            if cst_da_planilha is not None:
                campos['cst_saida'] = cst_da_planilha
                self.cst_atualizado_pela_planilha += 1
            else:
                self.cst_sem_atualizacao_na_planilha += 1

            if 'icms_saida_sp' in campos_tabela:
                campos['icms_saida_sp'] = campos_tabela['icms_saida_sp']
                self.icms_sp_validado += 1
            elif produto.icms_saida_sp is not None:
                campos['icms_saida_sp'] = None
                self.icms_sp_zerado_nesta_rodada += 1
            else:
                self.icms_sp_continua_vazio += 1

            if 'icms_saida_media' in campos_tabela:
                campos['icms_saida_media'] = campos_tabela['icms_saida_media']
                self.icms_media_validado += 1
            elif produto.icms_saida_media is not None:
                campos['icms_saida_media'] = None
                self.icms_media_zerado_nesta_rodada += 1
            else:
                self.icms_media_continua_vazio += 1

            if 'pis_percentual' in campos_tabela:
                campos['pis_percentual'] = campos_tabela['pis_percentual']
                campos['cofins_percentual'] = campos_tabela['cofins_percentual']
                self.pis_cofins_validado += 1
            elif produto.pis_percentual is not None or produto.cofins_percentual is not None:
                campos['pis_percentual'] = None
                campos['cofins_percentual'] = None
                self.pis_cofins_zerado_nesta_rodada += 1
            else:
                self.pis_cofins_continua_vazio += 1

            if campos:
                for campo, valor in campos.items():
                    setattr(produto, campo, valor)
                self.produtos_para_atualizar.append(produto)
                self.atualizados += 1

    # Função Objetivo: Grava tudo no banco em lote, 1 única vez.
    def salvar(self):
        if self.produtos_para_atualizar:
            Produto.objects.bulk_update(
                self.produtos_para_atualizar, LinhaImpostoSaida.CAMPOS_PRODUTO, batch_size=BATCH_SIZE_PADRAO,
            )

    # Função Objetivo: Roda o preenchimento inteiro — produtos + tabelas + CST da planilha — até o banco.
    def rodar_preenchimento_completo(self):
        self.carregar_produtos_existentes()
        self.carregar_tabelas_normalizadas()
        self.carregar_cst_da_planilha()
        self.processar_todos_os_produtos()
        self.salvar()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[IMPOSTOS DE SAÍDA] Concluído!\n'
            f'    Produtos com pelo menos 1 campo atualizado nesta rodada: {self.atualizados}\n'
            f'    (agora cobre o catálogo inteiro, não só quem tem linha na planilha)\n'
            f'    Linhas sem EAN na planilha (ignoradas): {self.sem_ean_na_planilha}\n'
            f'    EAN duplicado na planilha (mantida a 1ª ocorrência): {self.eans_duplicados_na_planilha}\n'
            f'    EAN da planilha sem produto correspondente no banco: {self.sem_produto_correspondente}\n'
            f'\n'
            f'    cst_saida (direto da planilha, por EAN, sem conferência cruzada — atualizado pela '
            f'planilha nesta rodada / sem atualização na planilha nesta rodada):\n'
            f'        {self.cst_atualizado_pela_planilha} / {self.cst_sem_atualizacao_na_planilha}\n'
            f'\n'
            f'    Os outros 4 campos (buscados por NCM/CST nas tabelas normalizadas, com conferência '
            f'cruzada entre produtos — validado / zerado nesta rodada por falta de dado validado / '
            f'já estava vazio, continua vazio):\n'
            f'        icms_saida_sp (IcmsNcmUf):    '
            f'{self.icms_sp_validado} / {self.icms_sp_zerado_nesta_rodada} / {self.icms_sp_continua_vazio}\n'
            f'        icms_saida_media (calculado): '
            f'{self.icms_media_validado} / {self.icms_media_zerado_nesta_rodada} / '
            f'{self.icms_media_continua_vazio}\n'
            f'        pis/cofins (PisCofinsNcmCst): '
            f'{self.pis_cofins_validado} / {self.pis_cofins_zerado_nesta_rodada} / '
            f'{self.pis_cofins_continua_vazio}'
        )


# Função Objetivo: Cria o Console com 1 coluna de margem abaixo da
# largura detectada do terminal (mesma correção de
# importacao_icms_ncm.py, ver comentário lá — duplicada aqui de
# propósito, cada módulo de preenchimento fica autocontido). Panel
# sempre estica pra largura TOTAL do console (Table segue o conteúdo);
# quando essa largura bate exatamente com a do terminal real do
# usuário, o terminal quebra linha sem \n e cola a borda do Panel no
# conteúdo. A margem de 1 coluna evita a disputa pela última coluna.
def _console_com_margem():
    largura_detectada = shutil.get_terminal_size(fallback=(80, 24)).columns
    return Console(width=max(largura_detectada - 1, 20))


# Função Objetivo: Ponto de entrada chamado pelo Command.
def preencher_impostos_saida(stdout, style):
    console = _console_com_margem()

    console.print('[bold]Impostos de Saída[/bold] — lendo planilha Busca Legal...')

    importador = ImportadorImpostosSaida().rodar_preenchimento_completo()

    tabela_leitura = Table(title='Impostos de Saída — Leitura da planilha')
    tabela_leitura.add_column('Métrica')
    tabela_leitura.add_column('Quantidade', justify='right')
    tabela_leitura.add_row('Linhas sem EAN na planilha (ignoradas)', str(importador.sem_ean_na_planilha))
    tabela_leitura.add_row(
        'EAN duplicado na planilha (mantida a 1ª ocorrência)', str(importador.eans_duplicados_na_planilha),
    )
    tabela_leitura.add_row(
        'EAN da planilha sem produto correspondente no banco', str(importador.sem_produto_correspondente),
        style='yellow' if importador.sem_produto_correspondente else None,
    )
    console.print()
    console.print(tabela_leitura)

    tabela_cst = Table(
        title='cst_saida — direto da planilha, por EAN (sem conferência cruzada)',
        caption='"Sem atualização" é esperado pra EAN que não veio na planilha desta rodada — mantém o CST antigo, não é anomalia.',
    )
    tabela_cst.add_column('Situação')
    tabela_cst.add_column('Quantidade', justify='right')
    tabela_cst.add_row('Atualizado pela planilha nesta rodada', str(importador.cst_atualizado_pela_planilha))
    tabela_cst.add_row('Sem atualização na planilha nesta rodada', str(importador.cst_sem_atualizacao_na_planilha))
    console.print()
    console.print(tabela_cst)

    # 1 linha por campo — o pedaço que mais se beneficia de virar tabela:
    # antes eram 3 linhas de texto corrido, cada 1 com 3 números separados
    # só por "/", sem nenhum cabeçalho dizendo o que cada número significa.
    dataframe_campos = pd.DataFrame([
        {
            'Campo': 'icms_saida_sp (IcmsNcmUf)',
            'Validado': importador.icms_sp_validado,
            'Zerado nesta rodada': importador.icms_sp_zerado_nesta_rodada,
            'Já vazio, continua vazio': importador.icms_sp_continua_vazio,
        },
        {
            'Campo': 'icms_saida_media (calculado)',
            'Validado': importador.icms_media_validado,
            'Zerado nesta rodada': importador.icms_media_zerado_nesta_rodada,
            'Já vazio, continua vazio': importador.icms_media_continua_vazio,
        },
        {
            'Campo': 'pis/cofins (PisCofinsNcmCst)',
            'Validado': importador.pis_cofins_validado,
            'Zerado nesta rodada': importador.pis_cofins_zerado_nesta_rodada,
            'Já vazio, continua vazio': importador.pis_cofins_continua_vazio,
        },
    ], columns=['Campo', 'Validado', 'Zerado nesta rodada', 'Já vazio, continua vazio'])

    # Monta a tabela à mão, célula a célula, em vez de 1 função genérica
    # DataFrame->Table (como em importacao_icms_ncm.py) porque "Zerado
    # nesta rodada" precisa de cor por CÉLULA quando > 0 — é o número mais
    # importante dos 3 (dado que ANTES validava e agora foi apagado), e
    # não pode ficar com o mesmo peso visual de "Validado" (esperado/bom)
    # ou "Já vazio" (não mudou nada).
    tabela_campos = Table(title='Campos vindos das tabelas normalizadas (conferência cruzada entre produtos)')
    tabela_campos.add_column('Campo')
    tabela_campos.add_column('Validado', justify='right')
    tabela_campos.add_column('Zerado nesta rodada', justify='right')
    tabela_campos.add_column('Já vazio, continua vazio', justify='right')
    houve_zeragem = False
    for registro in dataframe_campos.to_dict('records'):
        zerado = registro['Zerado nesta rodada']
        houve_zeragem = houve_zeragem or zerado > 0
        celula_zerado = Text(str(zerado), style='bold red') if zerado > 0 else Text(str(zerado))
        tabela_campos.add_row(
            registro['Campo'], str(registro['Validado']), celula_zerado, str(registro['Já vazio, continua vazio']),
        )
    console.print()
    console.print(tabela_campos)

    console.print()
    texto_final = (
        f'[bold]Produtos com pelo menos 1 campo atualizado nesta rodada:[/bold] {importador.atualizados}\n'
        f'(cobre o catálogo inteiro, não só quem tem linha na planilha)'
    )
    if houve_zeragem:
        texto_final += (
            '\n[bold yellow]Atenção:[/bold yellow] algum campo foi zerado nesta rodada (ver "Zerado nesta '
            'rodada" na tabela acima) — confirme se é esperado antes de seguir.'
        )
    console.print(Panel(
        texto_final,
        title='Impostos de Saída — Concluído',
        border_style='yellow' if houve_zeragem else 'green',
    ))

    if importador.eans_sem_produto:
        console.print()
        console.print(Panel(
            Columns(importador.eans_sem_produto, equal=True, expand=True),
            title=(
                f'{len(importador.eans_sem_produto)} EAN(s) da planilha sem Produto '
                f'correspondente no banco — conferir'
            ),
            border_style='yellow',
        ))

    stdout.write(style.SUCCESS(
        f'[IMPOSTOS DE SAÍDA] Concluído — {importador.atualizados} produto(s) com pelo menos 1 campo '
        f'atualizado nesta rodada.'
    ))