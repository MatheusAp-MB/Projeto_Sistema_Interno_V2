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
# * [IMPORTANTE] → Este passo ainda NÃO recalcula as grades de preço (calcular_grade_*). Enquanto isso, quando a tabela muda, o resultado
#   avisa que a grade daquele marketplace continua com os preços da tabela anterior (o recálculo automático é o próximo ciclo).
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
from .catalogo_arquivos import ARQUIVOS, arquivo_e_da_empresa
from .envio_ao_drive import ArquivoAusenteNoDrive, ErroDoEnvio, ler_do_drive
from .historico_da_atualizacao import registrar, tabela_existe
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
    return [arquivo for arquivo in ARQUIVOS if arquivo.id in IMPORTACOES and arquivo_e_da_empresa(arquivo, empresa)]


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
        'empresa': empresa, 'nome': _nome_da_empresa(empresa), 'status': EMPRESA_ATUALIZADA,
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


def _nome_da_empresa(empresa):
    return NOMES_CURTOS_DAS_EMPRESAS.get(empresa, empresa.title())


# `empresas` = lista com 1 item (a empresa atualizada): a tela mostra a tabela "Novas / Mudaram / Iguais / Removidas" dessa empresa.
def _resultado_base(arquivo, empresa, status, mensagem='', **extras):
    return {
        'arquivo_id': arquivo.id, 'nome': arquivo.nome, 'icone': arquivo.icone, 'nome_no_drive': arquivo.nome_no_drive, 'status': status,
        'empresa': empresa, 'empresa_nome': _nome_da_empresa(empresa),
        'mensagem': mensagem, 'drive': None, 'notas': [], 'motivos': [], 'motivos_ocultos': 0, 'empresas': [],
        'renovar_autorizacao': False, **extras,
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
        if not (resultado_da_empresa['criados'] or resultado_da_empresa['mudaram'] or resultado_da_empresa['removidas']):
            return STATUS_ATUALIZADO, f'Nada mudou: o sistema da {nome} já tinha exatamente o que está no Drive.'
        return STATUS_ATUALIZADO, f'Sistema da {nome} atualizado com o arquivo do Drive.'
    return STATUS_NAO_ATUALIZOU, f'Nada foi gravado no sistema da {nome} — veja o motivo abaixo.'


# Função Objetivo: Atualiza o sistema de UMA empresa com UM arquivo do Drive. `arquivo` é um ArquivoDeReferencia do catálogo (a view já
# conferiu que o botão o atualiza e que ele é visível para esta empresa); `empresa` é a empresa selecionada na tela. Falha PREVISTA vira
# resultado (para a tela); bug do sistema sobe como exceção (a view registra e avisa).
def atualizar_arquivo(arquivo, empresa):
    # Proteção de quem chama: empresa desconhecida ou arquivo de outra empresa nunca chega a tocar em banco nenhum.
    if empresa not in EMPRESAS_VALIDAS:
        raise ValueError(f'Empresa desconhecida: {empresa!r}')
    if not arquivo_e_da_empresa(arquivo, empresa):
        raise ValueError(f'O arquivo {arquivo.id} não é da empresa {empresa}.')
    importacao = IMPORTACOES[arquivo.id]
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

        da_empresa = _importar_para_a_empresa(arquivo, importacao, lido, empresa)
        status, mensagem = _resumo_da_empresa(da_empresa)
        # Tabela mudou, grade ainda não foi recalculada: o aviso existe para essa diferença nunca passar em silêncio.
        if da_empresa['status'] == EMPRESA_ATUALIZADA and (da_empresa['criados'] or da_empresa['mudaram'] or da_empresa['removidas']):
            notas.append(
                f'A grade de precificação do {importacao.grade} da {nome} ainda NÃO foi recalculada com esta mudança: ela continua com os '
                'preços calculados pela tabela anterior até ser recalculada.'
            )
        return _resultado_base(arquivo, empresa, status, mensagem, drive=drive, notas=notas, empresas=[da_empresa])
    finally:
        trava.release()
