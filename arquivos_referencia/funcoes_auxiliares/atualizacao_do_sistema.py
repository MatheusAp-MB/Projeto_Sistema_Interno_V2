# arquivos_referencia/funcoes_auxiliares/atualizacao_do_sistema.py

# Função Objetivo: PASSO 2 da tela "Arquivos de referência" — atualizar o SISTEMA (banco) com o que está no Drive. Para 1 arquivo de
# referência por vez: lê o arquivo do Drive (só na memória, nada em disco), confere com a MESMA auditoria do envio e, se estiver sem erros, grava nas tabelas
# do banco das DUAS empresas (Magazine e Samvale) usando as MESMAS rotinas do "popular banco" (as classes ImportadorFrete*; nenhuma
# cópia da lógica de ler a planilha e gravar). Devolve um dicionário com o resultado pronto para a tela.
#
# * [DECISÃO, 14/10/2026] → Fluxo em 2 passos separados: (1) conferir e enviar ao Drive; (2) atualizar o sistema com o que está lá —
#   este arquivo é o passo 2. O Drive é a fonte única: nada aqui lê arquivo do computador de quem clicou.
# * [DECISÃO, 15/10/2026] → 1º ciclo do passo 2: só as 4 TABELAS DE FRETE (valem para as duas empresas, então o botão grava nas duas).
#   As 2 planilhas do Busca Legal (ICMS/PIS/COFINS) entram em um ciclo próprio, porque o pipeline delas é bem maior.
# * [DECISÃO, 15/10/2026] → A atualização ESPELHA o arquivo: o que está no arquivo entra (novas) ou é atualizado (mudaram), e o que o
#   sistema tem e o arquivo NÃO tem é REMOVIDO — para o banco ficar 100% síncrono com o arquivo (antes só criava e atualizava; decisão do
#   Matheus de 15/10/2026 depois de ver 224 linhas de sobra na Samvale). Tudo na mesma transação de cada tabela/empresa.
# * [DECISÃO, 15/10/2026] → Cada atualização bem-sucedida grava, no banco da empresa, "quando e com qual arquivo" (historico_da_atualizacao.py),
#   dentro da MESMA transação: a tela mostra a data da última atualização e se o sistema está em dia com o Drive.
# * [EXPLICAÇÃO] → Regras de segurança, nesta ordem:
#   1) Arquivo que o Drive não tem, ou que o Drive não deixou ler por inteiro (checksum), não segue.
#   2) A auditoria roda DE NOVO sobre o que veio do Drive (o arquivo pode ter sido trocado à mão lá): com erro, NADA é gravado.
#   3) Cada tabela de cada empresa é gravada "tudo ou nada" (transação): se o importador apontar qualquer erro de linha, ou se a conta
#      final não fechar (o banco precisa ficar com exatamente as linhas do arquivo), a gravação inteira daquela tabela naquela empresa
#      é desfeita — nunca fica meia tabela nova, nem tabela sem as linhas que o arquivo mandou remover.
#   4) As duas empresas são independentes: se uma falhar, a outra continua e o resultado diz qual atualizou e qual não.
# * [EXPLICAÇÃO] → Como se conta "novas / mudaram / iguais / removidas": tira-se uma fotografia da tabela antes e outra depois (valores
#   de cada linha, pela chave interna) e compara-se. Não se usa a conta "Atualizados" do importador, porque ele regrava TODA linha que
#   casa com o arquivo, tenha mudado ou não. "Removidas" = linhas que já existiam no banco e o arquivo não menciona.
# * [IMPORTANTE] → Os importadores (o mesmo código do "popular banco") só CRIAM e ATUALIZAM; quem REMOVE o que sobrou é este módulo, logo
#   depois do importador e DENTRO da mesma transação. O "popular banco" de terminal continua como sempre foi (não remove nada).
# * [IMPORTANTE] → Este passo ainda NÃO recalcula as grades de preço (calcular_grade_*). Enquanto isso, quando a tabela muda, o resultado
#   avisa que a grade daquele marketplace continua com os preços da tabela anterior (o recálculo automático é o próximo ciclo).
# * [EXPLICAÇÃO] → O importador escolhe o banco pela empresa ativa da requisição (EmpresaRouter). Por isso o laço troca a empresa
#   ativa para cada banco e SEMPRE devolve a original no fim (a requisição continua na empresa que a pessoa escolheu na tela).

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
from .catalogo_arquivos import ARQUIVOS
from .envio_ao_drive import ArquivoAusenteNoDrive, ErroDoEnvio, ler_do_drive
from .historico_da_atualizacao import registrar, tabela_existe
from .relatorio_auditoria import formatar_tamanho

logger = logging.getLogger(__name__)

PACOTE_DOS_IMPORTADORES = 'core.management.commands.popular_banco_suporte'
MAXIMO_DE_MOTIVOS_MOSTRADOS = 5
TAMANHO_DO_LOTE_DE_REMOCAO = 500   # chaves por DELETE (o MySQL aceita listas grandes, mas lotes pequenos são mais seguros)

# Resultado de 1 ARQUIVO (a tela mostra ícone + texto para cada um).
STATUS_ATUALIZADO = 'ok'                    # gravado nas duas empresas
STATUS_PARCIAL = 'parcial'                  # gravado só em uma das empresas
STATUS_NAO_ATUALIZOU = 'nao_atualizou'      # nada gravado (importador apontou erro ou o banco falhou) — banco intacto
STATUS_ARQUIVO_COM_ERROS = 'erro_no_arquivo'  # a auditoria do arquivo que está no Drive recusou
STATUS_SEM_ARQUIVO = 'sem_arquivo'          # o Drive ainda não tem o arquivo
STATUS_FALHA_DO_DRIVE = 'falha_drive'       # login vencido, sem internet, sem permissão...
STATUS_OCUPADO = 'ocupado'                  # já tem uma atualização deste arquivo em andamento
STATUS_FALHA_DO_SISTEMA = 'falha_sistema'   # bug nosso (o detalhe vai para o terminal do servidor)

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
    grade: str      # nome da grade de preços que usa esta tabela (só para o aviso "grade ainda não recalculada")


# id do cartão (catalogo_arquivos.py) -> como importar. É a lista FECHADA do que o botão atualiza hoje.
IMPORTACOES = {
    'frete-mercado-livre': ImportacaoDeTabela('importar_tabela_frete_ml', 'ImportadorFreteML', 'mercado_livre', 'FreteML', 'Mercado Livre'),
    'frete-magalu': ImportacaoDeTabela('importar_tabela_frete_magalu', 'ImportadorFreteMagalu', 'magalu', 'FreteMagalu', 'Magalu'),
    'frete-tiktok-shop': ImportacaoDeTabela('importar_tabela_frete_tiktok', 'ImportadorFreteTiktok', 'tiktok', 'FreteTiktok', 'TikTok Shop'),
    'frete-amazon': ImportacaoDeTabela('importar_tabela_frete_amazon', 'ImportadorFreteAmazon', 'precificacao', 'FreteAmazon', 'Amazon'),
}

# Cada arquivo tem a sua trava: dois cliques (ou duas abas) no mesmo arquivo não gravam ao mesmo tempo. A trava vale dentro de 1 processo
# do servidor; o que protege o banco de verdade é a transação de cada tabela.
_TRAVA_GERAL = threading.Lock()
_TRAVAS_POR_ARQUIVO = {}


def _trava_do_arquivo(id_do_arquivo):
    with _TRAVA_GERAL:
        return _TRAVAS_POR_ARQUIVO.setdefault(id_do_arquivo, threading.Lock())


# Função Objetivo: Os arquivos do catálogo que o botão "Atualizar o sistema com o Drive" atualiza hoje, na ordem da tela.
def arquivos_que_o_botao_atualiza():
    return [arquivo for arquivo in ARQUIVOS if arquivo.id in IMPORTACOES]


def o_botao_atualiza(id_do_arquivo):
    return id_do_arquivo in IMPORTACOES


# Função Objetivo: Onde os importadores escrevem "[FRETE ML] ... 10/40 linhas": aqui ninguém lê, então se descarta (o resultado vai para a tela).
class _SaidaSilenciosa:

    def write(self, *_, **__):
        return 0

    def flush(self):
        pass


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


# Função Objetivo: Grava 1 arquivo, na tabela de 1 empresa, "tudo ou nada": importa, remove o que o arquivo não tem, confere a conta e
# registra no histórico. Devolve o resultado dessa empresa para a tela. `lido` é o que ler_do_drive devolveu.
def _importar_para_a_empresa(arquivo, importacao, lido, empresa):
    alias = ALIAS_BANCO_POR_EMPRESA[empresa]
    resultado = {
        'empresa': empresa, 'nome': NOMES_CURTOS_DAS_EMPRESAS.get(empresa, empresa.title()), 'status': EMPRESA_ATUALIZADA,
        'criados': 0, 'mudaram': 0, 'iguais': 0, 'removidas': 0, 'motivos': [], 'motivos_ocultos': 0, 'mensagem': '',
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

        modulo = importlib.import_module(f'{PACOTE_DOS_IMPORTADORES}.{importacao.modulo}')
        classe_do_importador = getattr(modulo, importacao.classe)
        modelo = apps.get_model(importacao.app, importacao.modelo)

        with transaction.atomic(using=alias):
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
            registrar(
                alias, arquivo.id, lido['md5'], lido['modificado_em'],
                novas=criados, mudaram=mudaram, iguais=len(tocadas) - mudaram, removidas=len(a_remover),
            )

        resultado.update(criados=criados, mudaram=mudaram, iguais=len(tocadas) - mudaram, removidas=len(a_remover))
    except _ImportacaoRecusada as recusa:
        motivos, ocultos = _cortar_motivos(recusa.motivos)
        resultado.update(
            status=EMPRESA_RECUSADA, motivos=motivos, motivos_ocultos=ocultos,
            mensagem='O importador achou problema no arquivo. Nada foi gravado nesta empresa.',
        )
    except Exception:
        logger.exception('Atualização do sistema: falha ao gravar %s na empresa %s', importacao.modelo, empresa)
        resultado.update(
            status=EMPRESA_FALHOU,
            mensagem='Erro do próprio sistema ao gravar nesta empresa. Nada foi gravado aqui (a gravação é desfeita). Veja o terminal do servidor.',
        )
    finally:
        definir_empresa_ativa(empresa_da_requisicao)
    return resultado


def _resultado_base(arquivo, status, mensagem='', **extras):
    return {
        'arquivo_id': arquivo.id, 'nome': arquivo.nome, 'icone': arquivo.icone, 'nome_no_drive': arquivo.nome_no_drive, 'status': status,
        'mensagem': mensagem, 'drive': None, 'notas': [], 'motivos': [], 'motivos_ocultos': 0, 'empresas': [],
        'renovar_autorizacao': False, **extras,
    }


# Função Objetivo: Resultado para um erro do PRÓPRIO sistema (bug) que escapou: a view usa quando o resto quebrou.
def resultado_de_falha_do_sistema(arquivo):
    return _resultado_base(
        arquivo, STATUS_FALHA_DO_SISTEMA,
        'Erro do próprio sistema ao atualizar (não é problema do arquivo). Veja o terminal do servidor.',
    )


def _resumo_das_empresas(empresas):
    atualizadas = [e for e in empresas if e['status'] == EMPRESA_ATUALIZADA]
    if len(atualizadas) == len(empresas):
        if all(e['criados'] == 0 and e['mudaram'] == 0 and e['removidas'] == 0 for e in empresas):
            return STATUS_ATUALIZADO, 'Nada mudou: o sistema já tinha exatamente o que está no Drive.'
        return STATUS_ATUALIZADO, 'Atualizado nas duas empresas.'
    if atualizadas:
        so_em = ' e '.join(e['nome'] for e in atualizadas)
        return STATUS_PARCIAL, f'Atualizou só em {so_em}. Na outra empresa nada foi gravado — veja o motivo abaixo.'
    return STATUS_NAO_ATUALIZOU, 'Nada foi gravado em nenhuma das duas empresas — veja o motivo abaixo.'


# Função Objetivo: Atualiza o sistema com UM arquivo do Drive. `arquivo` é um ArquivoDeReferencia do catálogo (a view já conferiu que
# o botão o atualiza). Falha PREVISTA vira resultado (para a tela); bug do sistema sobe como exceção (a view registra e avisa).
def atualizar_arquivo(arquivo):
    importacao = IMPORTACOES[arquivo.id]

    trava = _trava_do_arquivo(arquivo.id)
    if not trava.acquire(blocking=False):
        return _resultado_base(
            arquivo, STATUS_OCUPADO,
            'Já tem uma atualização deste arquivo em andamento (outra pessoa ou outra aba). Espere terminar e tente de novo.',
        )
    try:
        try:
            lido = ler_do_drive(arquivo)
        except ArquivoAusenteNoDrive as problema:
            return _resultado_base(arquivo, STATUS_SEM_ARQUIVO, problema.mensagem)
        except ErroDoEnvio as problema:
            return _resultado_base(
                arquivo, STATUS_FALHA_DO_DRIVE, problema.resumo, renovar_autorizacao=problema.renovar_autorizacao,
            )

        conteudo = lido['conteudo']
        drive = {
            'tamanho_texto': formatar_tamanho(lido['tamanho_em_bytes']), 'modificado_em': lido['modificado_em'],
            'copias': lido['copias'], 'caminho': lido['caminho'],
        }
        notas = []
        if lido['copias'] > 1:
            notas.append(f'Há {lido["copias"]} cópias deste arquivo na pasta do Drive; foi lida a mais recente.')

        relatorio = auditar_arquivo(arquivo, conteudo, lido['nome'], tamanho_em_bytes=len(conteudo))
        if not relatorio.pode_enviar:
            motivos = [f'{achado.onde}: {achado.o_que}' for achado in relatorio.erros]
            mostrados, ocultos = _cortar_motivos(motivos)
            ocultos += relatorio.erros_ocultos
            return _resultado_base(
                arquivo, STATUS_ARQUIVO_COM_ERROS,
                f'O arquivo que está no Drive não passou na conferência ({relatorio.total_de_erros} '
                f'{"erro" if relatorio.total_de_erros == 1 else "erros"}). Nada foi gravado no sistema. '
                'Corrija o arquivo e envie de novo pelo cartão.',
                drive=drive, notas=notas, motivos=mostrados, motivos_ocultos=ocultos,
            )
        if relatorio.total_de_avisos:
            notas.append(
                f'A conferência achou {relatorio.total_de_avisos} {"aviso" if relatorio.total_de_avisos == 1 else "avisos"} neste arquivo '
                '(avisos não impedem a atualização).'
            )

        empresas = [_importar_para_a_empresa(arquivo, importacao, lido, empresa) for empresa in EMPRESAS_VALIDAS]
        status, mensagem = _resumo_das_empresas(empresas)
        # Tabela mudou, grade ainda não foi recalculada: o aviso existe para essa diferença nunca passar em silêncio.
        if any(e['status'] == EMPRESA_ATUALIZADA and (e['criados'] or e['mudaram'] or e['removidas']) for e in empresas):
            notas.append(
                f'A grade de precificação do {importacao.grade} ainda NÃO foi recalculada com esta mudança: ela continua com os '
                'preços calculados pela tabela anterior até ser recalculada.'
            )
        return _resultado_base(arquivo, status, mensagem, drive=drive, notas=notas, empresas=empresas)
    finally:
        trava.release()
