# arquivos_referencia/funcoes_auxiliares/atualizacao_do_sistema.py

# Função Objetivo: PASSO 2 da tela "Arquivos de referência" — atualizar o SISTEMA (banco) com o que está no Drive. Para 1 arquivo de
# referência e 1 EMPRESA por vez: lê o arquivo do Drive (só na memória, nada em disco), confere com a MESMA auditoria do envio e, se estiver sem
# erros, grava nas tabelas do banco DAQUELA empresa usando as MESMAS rotinas do "popular banco" (as classes ImportadorFrete*; nenhuma
# cópia da lógica de ler a planilha e gravar). Devolve um dicionário com o resultado pronto para a tela.
#
# * [DECISÃO, 14/10/2026] → Fluxo em 2 passos separados: (1) conferir e enviar ao Drive; (2) atualizar o sistema com o que está lá —
#   este arquivo é o passo 2. O Drive é a fonte única: nada aqui lê arquivo do computador de quem clicou.
# * [DECISÃO, 15/10/2026] → 1º ciclo do passo 2: só as 4 TABELAS DE FRETE. As 2 planilhas do Busca Legal (ICMS/PIS/COFINS) entram em um
#   ciclo próprio, porque o pipeline delas é bem maior.
# * [DECISÃO, 16/10/2026] → A planilha BUSCA LEGAL (impostos de saída) da empresa selecionada entra no botão, no modo EXPANDIR: o que está na
#   planilha entra (novo) ou é atualizado (existente) e NADA é apagado por não estar nela (pedido do Matheus). Roda os 4 passos do terminal,
#   em ordem e numa transação só (importacao_busca_legal.py). As tabelas de frete seguem espelhando o arquivo (acima). Para o Busca Legal as
#   colunas "Novas/Mudaram/Iguais/Removidas" do histórico contam GRUPOS fiscais.
# * [DECISÃO, 16/10/2026] → Busca Legal, modo SUBSTITUIR (opção B do Matheus): o sistema da empresa fica LITERALMENTE igual à planilha, apagando o
#   que ela não tem (importacao_busca_legal.py explica o que sai). Duas travas aqui: (1) PRÉVIA — `simular=True` roda tudo numa transação que é
#   desfeita no fim e devolve o que SERIA apagado, sem gravar nada (nem o histórico); (2) o Substituir de verdade só roda se vier junto o md5 do
#   arquivo cuja prévia a pessoa leu, e esse md5 ainda for o do arquivo que está no Drive agora: se alguém trocou o arquivo no meio do caminho,
#   NADA é gravado e a pessoa lê a prévia do arquivo novo. O Expandir não tem prévia nem essa trava (não apaga nada).
# * [DECISÃO, 16/10/2026] → O MODO da Busca Legal (Expandir/Substituir) NÃO é escolhido aqui: é uma configuração da EMPRESA (card no topo da tela; ver
#   configuracao_da_importacao.py) que vale para o envio e para esta atualização. Atualizar o sistema só LÊ esse modo (do banco da empresa pedida) e o aplica;
#   sem configuração gravada é Expandir, que nunca apaga. As travas do Substituir (prévia + md5) continuam aqui, no momento de gravar. Só a PRÉVIA fixa o modo
#   (modo=Substituir, simular=True).
# * [DECISÃO, 16/10/2026] → INDEPENDÊNCIA entre as empresas (igual à Gestão de APIs): o botão atualiza SÓ a empresa selecionada na tela.
#   Antes gravava nas duas de uma vez (decisão de 15/10/2026, revogada pelo Matheus em 16/10/2026). O arquivo do Drive continua um só
#   para as duas, mas cada empresa atualiza o seu banco quando quiser, separadamente: atualizar a Magazine nunca mexe na Samvale.
# * [DECISÃO, 15/10/2026] → A atualização ESPELHA o arquivo: o que está no arquivo entra (novas) ou é atualizado (mudaram), e o que o
#   sistema tem e o arquivo NÃO tem é REMOVIDO — para o banco ficar 100% síncrono com o arquivo (antes só criava e atualizava; decisão do
#   Matheus de 15/10/2026 depois de ver 224 linhas de sobra na Samvale). Tudo na mesma transação da tabela.
# * [DECISÃO, 15/10/2026] → Cada atualização bem-sucedida grava, no banco da empresa, "quando e com qual arquivo" (historico_da_atualizacao.py),
#   dentro da MESMA transação: a tela mostra a data da última atualização e se o sistema está em dia com o Drive.
# * [EXPLICAÇÃO] → Regras de segurança, nesta ordem:
#   1) Arquivo que o Drive não tem, ou que o Drive não deixou ler por inteiro (checksum), não segue.
#   2) A auditoria roda DE NOVO sobre o que veio do Drive (o arquivo pode ter sido trocado à mão lá): com erro, NADA é gravado.
#   3) A tabela é gravada "tudo ou nada" (transação): se o importador apontar qualquer erro de linha, ou se a conta final não fechar
#      (o banco precisa ficar com exatamente as linhas do arquivo), a gravação inteira é desfeita — nunca fica meia tabela nova, nem
#      tabela sem as linhas que o arquivo mandou remover.
#   4) Só o banco da empresa pedida é lido e gravado; o da outra empresa nem é aberto.
# * [EXPLICAÇÃO] → Como se conta "novas / mudaram / iguais / removidas": tira-se uma fotografia da tabela antes e outra depois (valores
#   de cada linha, pela chave interna) e compara-se. Não se usa a conta "Atualizados" do importador, porque ele regrava TODA linha que
#   casa com o arquivo, tenha mudado ou não. "Removidas" = linhas que já existiam no banco e o arquivo não menciona.
# * [IMPORTANTE] → Os importadores (o mesmo código do "popular banco") só CRIAM e ATUALIZAM; quem REMOVE o que sobrou é este módulo, logo
#   depois do importador e DENTRO da mesma transação. O "popular banco" de terminal continua como sempre foi (não remove nada).
# * [DECISÃO, 16/10/2026] → Ciclo 3: este passo NÃO recalcula grade nenhuma (continua só gravando o arquivo), mas diz à tela QUAIS grades de preço locais
#   (Magalu, TikTok Shop, Amazon, Raia, Shopee) usam o que acabou de mudar (`grades_a_recalcular`, de recalculo_das_grades.py). A tela as recalcula
#   logo depois, uma por pedido (view_recalcular_grade). "Já estava em dia" não recalcula nada. A grade do Mercado Livre (usa a API do ML) fica para o
#   ciclo 4: enquanto isso, quando o que mudou também a afeta, o resultado avisa que ela continua com os preços de antes (`grade_do_ml_pendente`).
# * [EXPLICAÇÃO] → O importador escolhe o banco pela empresa ativa da requisição (EmpresaRouter). Por isso a gravação define a empresa
#   pedida como ativa e SEMPRE devolve a original no fim (a requisição continua na empresa que a pessoa escolheu na tela).

import importlib
import io
import logging
import threading
from dataclasses import dataclass

from django.apps import apps
from django.db import transaction

from core.empresa import (
    ALIAS_BANCO_POR_EMPRESA, EMPRESA_MAGAZINE, EMPRESA_SAMVALE, EMPRESAS_VALIDAS, definir_empresa_ativa, obter_empresa_ativa,
)

from .auditor_de_arquivos import auditar_arquivo
from .catalogo_arquivos import ARQUIVOS, GRUPO_IMPOSTOS_SAIDA, arquivo_e_da_empresa
from .configuracao_da_importacao import modo_da_busca_legal
from .envio_ao_drive import ArquivoAusenteNoDrive, ErroDoEnvio, ler_do_drive
from .historico_da_atualizacao import registrar, tabela_existe
from .importacao_busca_legal import MODO_EXPANDIR, MODO_SUBSTITUIR, MODOS_VALIDOS, ImportacaoDeImpostosRecusada, executar_busca_legal
from .recalculo_das_grades import SaidaSilenciosa as _SaidaSilenciosa, grades_afetadas
from .relatorio_auditoria import formatar_tamanho

logger = logging.getLogger(__name__)

PACOTE_DOS_IMPORTADORES = 'core.management.commands.popular_banco_suporte'
MAXIMO_DE_MOTIVOS_MOSTRADOS = 5
TAMANHO_DO_LOTE_DE_REMOCAO = 500   # chaves por DELETE (o MySQL aceita listas grandes, mas lotes pequenos são mais seguros)

# Resultado de 1 ARQUIVO (a tela mostra ícone + texto para cada um).
STATUS_ATUALIZADO = 'ok'                    # gravado na empresa
STATUS_NAO_ATUALIZOU = 'nao_atualizou'      # nada gravado (importador apontou erro ou o banco falhou) — banco intacto
STATUS_ARQUIVO_COM_ERROS = 'erro_no_arquivo'  # a auditoria do arquivo que está no Drive recusou
STATUS_SEM_ARQUIVO = 'sem_arquivo'          # o Drive ainda não tem o arquivo
STATUS_FALHA_DO_DRIVE = 'falha_drive'       # login vencido, sem internet, sem permissão...
STATUS_OCUPADO = 'ocupado'                  # já tem uma atualização deste arquivo, nesta empresa, em andamento
STATUS_FALHA_DO_SISTEMA = 'falha_sistema'   # bug nosso (o detalhe vai para o terminal do servidor)
STATUS_PREVIA = 'previa'                    # Substituir: o que SERIA feito (nada foi gravado)
STATUS_PREVIA_INVALIDA = 'previa_invalida'  # Substituir sem prévia lida, ou o arquivo do Drive mudou depois dela: nada foi gravado

# Resultado de 1 arquivo em 1 EMPRESA.
EMPRESA_ATUALIZADA = 'ok'
EMPRESA_RECUSADA = 'recusada'               # o importador achou erro de linha: a gravação foi desfeita
EMPRESA_FALHOU = 'falha'                    # erro do banco/sistema: a gravação foi desfeita

NOMES_CURTOS_DAS_EMPRESAS = {EMPRESA_MAGAZINE: 'Magazine', EMPRESA_SAMVALE: 'Samvale'}


@dataclass(frozen=True)
class ImportacaoDeTabela:
    modulo: str     # módulo do importador, dentro de PACOTE_DOS_IMPORTADORES
    classe: str     # classe ImportadorFrete* (a MESMA que o popular banco usa)
    app: str        # app do model (para achar o model sem importar à força)
    modelo: str
    grade: str      # nome da grade de preços que usa esta tabela (informativo; quem decide o que recalcular é recalculo_das_grades.py)


# id do cartão (catalogo_arquivos.py) -> como importar. É a lista FECHADA do que o botão atualiza hoje.
IMPORTACOES = {
    'frete-mercado-livre': ImportacaoDeTabela('importar_tabela_frete_ml', 'ImportadorFreteML', 'mercado_livre', 'FreteML', 'Mercado Livre'),
    'frete-magalu': ImportacaoDeTabela('importar_tabela_frete_magalu', 'ImportadorFreteMagalu', 'magalu', 'FreteMagalu', 'Magalu'),
    'frete-tiktok-shop': ImportacaoDeTabela('importar_tabela_frete_tiktok', 'ImportadorFreteTiktok', 'tiktok', 'FreteTiktok', 'TikTok Shop'),
    'frete-amazon': ImportacaoDeTabela('importar_tabela_frete_amazon', 'ImportadorFreteAmazon', 'precificacao', 'FreteAmazon', 'Amazon'),
}

# As planilhas do Busca Legal (1 por empresa) não passam pelos importadores de frete: têm o pipeline de 4 passos de importacao_busca_legal.py.
IDS_DA_BUSCA_LEGAL = frozenset(arquivo.id for arquivo in ARQUIVOS if arquivo.grupo == GRUPO_IMPOSTOS_SAIDA)

# Cada (arquivo, empresa) tem a sua trava: dois cliques (ou duas abas) no mesmo arquivo da mesma empresa não gravam ao mesmo tempo — mas a
# Magazine e a Samvale podem atualizar o mesmo arquivo ao mesmo tempo, porque são bancos separados. A trava vale dentro de 1 processo
# do servidor; o que protege o banco de verdade é a transação da tabela.
_TRAVA_GERAL = threading.Lock()
_TRAVAS_POR_ARQUIVO_E_EMPRESA = {}


def _trava_do_arquivo(id_do_arquivo, empresa):
    with _TRAVA_GERAL:
        return _TRAVAS_POR_ARQUIVO_E_EMPRESA.setdefault((id_do_arquivo, empresa), threading.Lock())


# Função Objetivo: Os arquivos do catálogo que o botão "Atualizar o sistema com o Drive" atualiza hoje PARA ESTA EMPRESA, na ordem da tela.
def arquivos_que_o_botao_atualiza(empresa):
    return [arquivo for arquivo in ARQUIVOS if o_botao_atualiza(arquivo.id) and arquivo_e_da_empresa(arquivo, empresa)]


def o_botao_atualiza(id_do_arquivo):
    return id_do_arquivo in IMPORTACOES or id_do_arquivo in IDS_DA_BUSCA_LEGAL


# * [EXPLICAÇÃO] → `_SaidaSilenciosa` (importada acima de recalculo_das_grades.py) é onde os importadores escrevem "[FRETE ML] ... 10/40 linhas":
#   ninguém lê, então se descarta (o resultado vai para a tela). A tela de recálculo das grades usa a mesma.


# Função Objetivo: O importador achou erro de linha: a transação inteira daquela tabela é desfeita (levanta dentro do bloco atômico).
class _ImportacaoRecusada(Exception):

    def __init__(self, motivos):
        super().__init__('; '.join(motivos[:3]))
        self.motivos = motivos


# Função Objetivo: Fotografia de uma tabela: {chave interna: (valor de cada coluna)}. Lê do banco da empresa pedida, explicitamente.
def _fotografar(modelo, alias):
    colunas = [campo.attname for campo in modelo._meta.concrete_fields if not campo.primary_key]
    return {linha[0]: linha[1:] for linha in modelo.objects.using(alias).values_list('pk', *colunas)}


# Função Objetivo: Tudo que o importador reclamou (erro de linha; no ML também "regime não reconhecido", que ele só pula em silêncio).
def _motivos_do_importador(importador):
    bruto = list(importador.erros) + list(getattr(importador, 'regimes_nao_reconhecidos', []))
    return [texto.strip() for texto in bruto]


def _cortar_motivos(motivos):
    return motivos[:MAXIMO_DE_MOTIVOS_MOSTRADOS], max(0, len(motivos) - MAXIMO_DE_MOTIVOS_MOSTRADOS)


# Função Objetivo: Remove do banco as linhas pedidas (as que o arquivo não tem), em lotes. Só roda dentro da transação da importação.
def _remover_linhas(modelo, alias, chaves):
    chaves = sorted(chaves)
    for inicio in range(0, len(chaves), TAMANHO_DO_LOTE_DE_REMOCAO):
        modelo.objects.using(alias).filter(pk__in=chaves[inicio:inicio + TAMANHO_DO_LOTE_DE_REMOCAO]).delete()


# Função Objetivo: O jeito de gravar uma TABELA DE FRETE (espelho do arquivo): importa, remove o que o arquivo não tem e confere a conta.
# Devolve a função que _gravar_na_empresa roda DENTRO da transação da empresa.
def _executar_frete(importacao, lido):
    modulo = importlib.import_module(f'{PACOTE_DOS_IMPORTADORES}.{importacao.modulo}')
    classe_do_importador = getattr(modulo, importacao.classe)
    modelo = apps.get_model(importacao.app, importacao.modelo)

    def executar(alias):
        antes = _fotografar(modelo, alias)
        # Planilha NOVA na memória a cada empresa: o importador lê o arquivo do começo.
        importador = classe_do_importador(io.BytesIO(lido['conteudo']), _SaidaSilenciosa())
        importador.rodar_importacao_completa()
        motivos = _motivos_do_importador(importador)
        if motivos:
            raise _ImportacaoRecusada(motivos)

        # "Tocadas" = linhas que já existiam e que o arquivo menciona. Todo o resto do que existia é sobra: o arquivo é a verdade,
        # então sai do banco (espelho). Linhas criadas agora não estão em `antes`, portanto nunca entram na remoção.
        tocadas = {registro.pk for registro in importador.para_atualizar}
        a_remover = antes.keys() - tocadas
        _remover_linhas(modelo, alias, a_remover)
        depois = _fotografar(modelo, alias)

        criados = len(depois.keys() - antes.keys())
        mudaram = sum(1 for chave in tocadas if antes[chave] != depois[chave])
        # Conta de segurança: depois do espelho o banco tem EXATAMENTE as linhas que o arquivo mandou (as que já existiam + as novas).
        if len(depois) != len(tocadas) + criados:
            raise RuntimeError(
                f'O espelho não fechou: {len(depois)} linhas no banco, esperado {len(tocadas) + criados} '
                f'({len(tocadas)} existentes + {criados} novas).'
            )
        return {
            'criados': criados, 'mudaram': mudaram, 'iguais': len(tocadas) - mudaram, 'removidas': len(a_remover),
            'nada_mudou': not (criados or mudaram or a_remover),
        }

    return executar


# Função Objetivo: O jeito de gravar a planilha BUSCA LEGAL (impostos de saída, modo Expandir ou Substituir): os 4 passos do terminal numa transação só.
def _executar_busca_legal(lido, modo):
    def executar(alias):
        try:
            return executar_busca_legal(lido['conteudo'], alias, modo)
        except ImportacaoDeImpostosRecusada as recusa:
            raise _ImportacaoRecusada(recusa.motivos)

    return executar


# Função Objetivo: Grava 1 arquivo, no banco de 1 empresa, "tudo ou nada": abre a transação, roda `executar(alias)` (o jeito próprio de cada
# tipo de arquivo: frete ou Busca Legal) e registra no histórico — tudo na MESMA transação. Devolve o resultado dessa empresa para a tela.
# `lido` é o que ler_do_drive devolveu. `executar` devolve {'criados', 'mudaram', 'iguais', 'removidas', 'nada_mudou', ...extras para a tela}.
# `simular=True` (prévia do Substituir): roda TUDO igual, mas a transação é DESFEITA no fim e o histórico não é gravado — o banco fica como estava.
def _gravar_na_empresa(arquivo, lido, empresa, executar_do_arquivo, simular=False):
    alias = ALIAS_BANCO_POR_EMPRESA[empresa]
    resultado = {
        'empresa': empresa, 'nome': _nome_da_empresa(empresa), 'status': EMPRESA_ATUALIZADA,
        'criados': 0, 'mudaram': 0, 'iguais': 0, 'removidas': 0, 'nada_mudou': True, 'motivos': [], 'motivos_ocultos': 0, 'mensagem': '',
        'etapas': [], 'atencoes': [], 'produtos_mudaram': 0, 'produtos_perderam_cst': 0, 'rejeitados': 0, 'modo': MODO_EXPANDIR, 'substituicao': None,
    }
    empresa_da_requisicao = obter_empresa_ativa()
    definir_empresa_ativa(empresa)
    try:
        # Sem a tabela do histórico (falta rodar o migrate neste banco) nada é gravado: o histórico faz parte da atualização.
        if not tabela_existe(alias):
            resultado.update(
                status=EMPRESA_FALHOU,
                mensagem='O banco desta empresa ainda não tem a tabela do histórico de atualizações. Rode makemigrations e migrate '
                         '(app arquivos_referencia) para este banco. Nada foi gravado aqui.',
            )
            return resultado

        executar = executar_do_arquivo(lido)
        with transaction.atomic(using=alias):
            numeros = executar(alias)
            if simular:
                transaction.set_rollback(True, using=alias)   # prévia: nada fica gravado, nem o histórico
            else:
                registrar(
                    alias, arquivo.id, lido['md5'], lido['modificado_em'],
                    novas=numeros['criados'], mudaram=numeros['mudaram'], iguais=numeros['iguais'], removidas=numeros['removidas'],
                )
        resultado.update(numeros)
    except _ImportacaoRecusada as recusa:
        motivos, ocultos = _cortar_motivos(recusa.motivos)
        resultado.update(
            status=EMPRESA_RECUSADA, motivos=motivos, motivos_ocultos=ocultos,
            mensagem='O importador achou problema no arquivo. Nada foi gravado nesta empresa.',
        )
    except Exception:
        logger.exception('Atualização do sistema: falha ao gravar %s na empresa %s', arquivo.id, empresa)
        resultado.update(
            status=EMPRESA_FALHOU,
            mensagem='Erro do próprio sistema ao gravar nesta empresa. Nada foi gravado aqui (a gravação é desfeita). Veja o terminal do servidor.',
        )
    finally:
        definir_empresa_ativa(empresa_da_requisicao)
    return resultado


def _nome_da_empresa(empresa):
    return NOMES_CURTOS_DAS_EMPRESAS.get(empresa, empresa.title())


# `empresas` = lista com 1 item (a empresa atualizada): a tela mostra a tabela "Novas / Mudaram / Iguais / Removidas" dessa empresa.
def _resultado_base(arquivo, empresa, status, mensagem='', **extras):
    return {
        'arquivo_id': arquivo.id, 'nome': arquivo.nome, 'icone': arquivo.icone, 'nome_no_drive': arquivo.nome_no_drive, 'status': status,
        'empresa': empresa, 'empresa_nome': _nome_da_empresa(empresa),
        'mensagem': mensagem, 'drive': None, 'notas': [], 'motivos': [], 'motivos_ocultos': 0, 'empresas': [],
        'renovar_autorizacao': False, 'grades_a_recalcular': (), 'grade_do_ml_pendente': False, **extras,
    }


# Função Objetivo: Resultado para um erro do PRÓPRIO sistema (bug) que escapou: a view usa quando o resto quebrou.
def resultado_de_falha_do_sistema(arquivo, empresa):
    return _resultado_base(
        arquivo, empresa, STATUS_FALHA_DO_SISTEMA,
        'Erro do próprio sistema ao atualizar (não é problema do arquivo). Veja o terminal do servidor.',
    )


def _resumo_da_empresa(resultado_da_empresa):
    nome = resultado_da_empresa['nome']
    if resultado_da_empresa['status'] == EMPRESA_ATUALIZADA:
        if resultado_da_empresa['nada_mudou']:
            return STATUS_ATUALIZADO, f'Nada mudou: o sistema da {nome} já tinha exatamente o que está no Drive.'
        if resultado_da_empresa['rejeitados'] and not (resultado_da_empresa['criados'] or resultado_da_empresa['mudaram'] or resultado_da_empresa['produtos_mudaram']):
            return STATUS_ATUALIZADO, f'Nenhum valor mudou no sistema da {nome}, mas a planilha tem grupos rejeitados (o valor que já estava no sistema foi mantido) — veja abaixo.'
        if resultado_da_empresa['modo'] == MODO_SUBSTITUIR:
            return STATUS_ATUALIZADO, f'Sistema da {nome} agora é IGUAL à planilha do Drive: o que ela não tinha foi apagado.'
        return STATUS_ATUALIZADO, f'Sistema da {nome} atualizado com o arquivo do Drive.'
    return STATUS_NAO_ATUALIZOU, f'Nada foi gravado no sistema da {nome} — veja o motivo abaixo.'


# Função Objetivo: Atualiza o sistema de UMA empresa com UM arquivo do Drive. `arquivo` é um ArquivoDeReferencia do catálogo (a view já
# conferiu que o botão o atualiza e que ele é visível para esta empresa); `empresa` é a empresa selecionada na tela. Falha PREVISTA vira
# resultado (para a tela); bug do sistema sobe como exceção (a view registra e avisa).
# Só a planilha Busca Legal tem `modo` (Expandir/Substituir) e `simular` (a prévia do Substituir: nada é gravado). `modo=None` (o jeito normal de gravar) = o modo
# configurado para a empresa (Expandir se não houver); só a prévia passa `modo=MODO_SUBSTITUIR` de propósito. `md5_da_previa` = o md5 do arquivo cuja
# prévia a pessoa leu: obrigatório (e conferido com o do Drive agora) quando o Substituir vai gravar de verdade.
def atualizar_arquivo(arquivo, empresa, modo=None, simular=False, md5_da_previa=None):
    # Proteção de quem chama: empresa desconhecida ou arquivo de outra empresa nunca chega a tocar em banco nenhum.
    if empresa not in EMPRESAS_VALIDAS:
        raise ValueError(f'Empresa desconhecida: {empresa!r}')
    if not arquivo_e_da_empresa(arquivo, empresa):
        raise ValueError(f'O arquivo {arquivo.id} não é da empresa {empresa}.')
    if modo is not None and modo not in MODOS_VALIDOS:
        raise ValueError(f'Modo de atualização desconhecido: {modo!r}')
    importacao = IMPORTACOES.get(arquivo.id)   # None = planilha do Busca Legal (outro pipeline)
    if importacao is not None and (modo not in (None, MODO_EXPANDIR) or simular):
        raise ValueError('Modo Substituir e prévia só existem para a planilha Busca Legal; as tabelas de frete já espelham o arquivo.')
    if simular and modo != MODO_SUBSTITUIR:
        raise ValueError('A prévia só existe para o modo Substituir (o Expandir não apaga nada).')
    nome = _nome_da_empresa(empresa)

    trava = _trava_do_arquivo(arquivo.id, empresa)
    if not trava.acquire(blocking=False):
        return _resultado_base(
            arquivo, empresa, STATUS_OCUPADO,
            f'Já tem uma atualização deste arquivo na {nome} em andamento (outra pessoa ou outra aba). Espere terminar e tente de novo.',
        )
    try:
        try:
            lido = ler_do_drive(arquivo)
        except ArquivoAusenteNoDrive as problema:
            return _resultado_base(arquivo, empresa, STATUS_SEM_ARQUIVO, problema.mensagem)
        except ErroDoEnvio as problema:
            return _resultado_base(
                arquivo, empresa, STATUS_FALHA_DO_DRIVE, problema.resumo, renovar_autorizacao=problema.renovar_autorizacao,
            )

        if importacao is not None:
            modo = MODO_EXPANDIR   # as tabelas de frete não têm modo: sempre espelham o arquivo
        elif modo is None:
            # O modo configurado para a empresa (banco dela); qualquer coisa fora do esperado vira o padrão seguro, que não apaga.
            modo = modo_da_busca_legal(empresa)
            if modo not in MODOS_VALIDOS:
                modo = MODO_EXPANDIR
        conteudo = lido['conteudo']
        drive = {
            'tamanho_texto': formatar_tamanho(lido['tamanho_em_bytes']), 'modificado_em': lido['modificado_em'],
            'copias': lido['copias'], 'caminho': lido['caminho'], 'md5': lido['md5'],
        }
        if modo == MODO_SUBSTITUIR and not simular and (not md5_da_previa or md5_da_previa != lido['md5']):
            # Trava do Substituir: só apaga o que a pessoa VIU na prévia. Sem prévia, ou com o arquivo do Drive trocado depois dela: nada é gravado.
            return _resultado_base(
                arquivo, empresa, STATUS_PREVIA_INVALIDA,
                ('O modo da Busca Legal está em SUBSTITUIR (apaga o que a planilha não tem), mas esta tela não mostrou a prévia do que será apagado '
                 '(o modo foi mudado depois que a tela abriu). Nada foi gravado: recarregue a página e atualize de novo.'
                 if not md5_da_previa else
                 'O arquivo que está no Drive mudou depois da prévia que você leu (alguém enviou outro arquivo). Nada foi gravado: abra a '
                 'atualização de novo e leia a prévia do arquivo novo.'),
                drive=drive,
            )
        notas = []
        if lido['copias'] > 1:
            notas.append(f'Há {lido["copias"]} cópias deste arquivo na pasta do Drive; foi lida a mais recente.')

        relatorio = auditar_arquivo(arquivo, conteudo, lido['nome'], tamanho_em_bytes=len(conteudo))
        if not relatorio.pode_enviar:
            motivos = [f'{achado.onde}: {achado.o_que}' for achado in relatorio.erros]
            mostrados, ocultos = _cortar_motivos(motivos)
            ocultos += relatorio.erros_ocultos
            return _resultado_base(
                arquivo, empresa, STATUS_ARQUIVO_COM_ERROS,
                f'O arquivo que está no Drive não passou na conferência ({relatorio.total_de_erros} '
                f'{"erro" if relatorio.total_de_erros == 1 else "erros"}). Nada foi gravado no sistema da {nome}. '
                'Corrija o arquivo e envie de novo pelo cartão.',
                drive=drive, notas=notas, motivos=mostrados, motivos_ocultos=ocultos,
            )
        if relatorio.total_de_avisos:
            notas.append(
                f'A conferência achou {relatorio.total_de_avisos} {"aviso" if relatorio.total_de_avisos == 1 else "avisos"} neste arquivo '
                '(avisos não impedem a atualização).'
            )

        executar_do_arquivo = (lambda lido_: _executar_busca_legal(lido_, modo)) if importacao is None else (lambda lido_: _executar_frete(importacao, lido_))
        da_empresa = _gravar_na_empresa(arquivo, lido, empresa, executar_do_arquivo, simular=simular)
        if simular and da_empresa['status'] == EMPRESA_ATUALIZADA:
            # Prévia pronta: nada foi gravado (a transação foi desfeita). `drive['md5']` identifica o arquivo que esta prévia mostrou.
            return _resultado_base(arquivo, empresa, STATUS_PREVIA, '', drive=drive, notas=notas, empresas=[da_empresa])
        status, mensagem = _resumo_da_empresa(da_empresa)
        # Dado mudou: quais grades de preço usam isso. As locais são recalculadas pela tela logo depois (1 pedido por grade); a do Mercado Livre
        # ainda não faz parte do botão, e esse aviso existe para a diferença nunca passar em silêncio.
        grades, grade_do_ml_pendente = (), False
        if da_empresa['status'] == EMPRESA_ATUALIZADA and not da_empresa['nada_mudou']:
            grades, grade_do_ml_pendente = grades_afetadas(arquivo.id, importacao is None, da_empresa)
            if grade_do_ml_pendente:
                notas.append(
                    f'A grade de precificação do Mercado Livre da {nome} ainda NÃO foi recalculada com esta mudança: ela continua com os preços '
                    'calculados antes até ser recalculada (esse recálculo usa a API do Mercado Livre e ainda não faz parte deste botão).'
                )
        return _resultado_base(
            arquivo, empresa, status, mensagem, drive=drive, notas=notas, empresas=[da_empresa],
            grades_a_recalcular=grades, grade_do_ml_pendente=grade_do_ml_pendente,
        )
    finally:
        trava.release()
