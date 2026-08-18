# agenda_videos/tests/test_nivel_5__drive_escrita.py

# Função Objetivo: Confirma que a ESCRITA no Google Drive funciona DE
# VERDADE — rede real + credencial real, escopo de escrita
# (obter_servico_drive_escrita). Diferente de test_nivel_5__drive_leitura.py
# (que documenta explicitamente NUNCA criar/mover/apagar nada real), este
# arquivo é o 1º do projeto que ESCREVE de propósito no Drive real. Cobre
# buscar_ou_criar_subpasta (achar-ou-criar pasta) e enviar_arquivo (subir,
# recusar duplicado, substituir mantendo o mesmo ID) — os 2 pilares de
# escrita do Portal do Drive.
#
# Pra nunca sujar a estrutura real de produção, toda escrita deste arquivo
# acontece DENTRO de uma pasta fixa, "_teste_automatizado", criada
# manualmente 1x na raiz do Drive do Magazine (fora do que qualquer relatório
# de produto olha) — e o próprio teste desfaz no TearDown o que criou,
# apagando de verdade (files().delete(), nunca só lixeira), pra nunca
# acumular debris entre execuções.
#
# Auto-skip: se GOOGLE_DRIVE_CREDENCIAIS_JSON não estiver configurado nesta
# máquina, pula de forma limpa em vez de quebrar.
#
# A pasta-sandbox "_teste_automatizado" NÃO precisa ser criada manualmente:
# o próprio teste garante que ela existe (acha ou cria, 1x, via chamada
# crua à API — nunca através de buscar_ou_criar_subpasta, que é o SUT).
# Motivo: se o SUT tivesse um bug de idempotência, usá-lo pra criar a
# PRÓPRIA pasta-raiz do sandbox mascararia o bug — cada rodada criaria uma
# pasta raiz duplicada no Drive real, e nada aqui apaga a raiz (só a
# subpasta criada DENTRO dela, no TearDown). A raiz fica pra sempre, então
# só pode ser criada por um caminho independente, que sabemos ser idempotente.

import os
import tempfile

import pytest
from django.conf import settings

from agenda_videos.funcoes_auxiliares.drive.arquivador import ArquivadorDrive, montar_nome_arquivo
from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive_escrita
from agenda_videos.funcoes_auxiliares.drive.constantes import MIME_PASTA, NOME_PASTA_VIDEOS
from agenda_videos.funcoes_auxiliares.drive.utilitarios_pasta import (
    buscar_subpasta, buscar_ou_criar_subpasta, buscar_arquivo,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Integração real — escrita no Google Drive (buscar_ou_criar_subpasta + enviar_arquivo, dentro de _teste_automatizado)'

NOME_PASTA_TESTE_FIXA = '_teste_automatizado'
NOME_SUBPASTA_CRIADA_PELO_TESTE = 'subpasta_criada_pelo_teste_nivel_5'
MARCA_TESTE_ESCRITA = 'marca_teste_nivel_5'
EAN_TESTE_ESCRITA = '0000000000001'

pytestmark = pytest.mark.skipif(
    not settings.GOOGLE_DRIVE_CREDENCIAIS_JSON
    or not settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON
    or not os.path.exists(settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON),
    reason='Credencial de leitura (Service Account) ou token OAuth de escrita não configurados nesta máquina — sem os 2, sem teste real de escrita no Drive.',
)


def _garantir_pasta_teste_fixa(servico):
    # Função Objetivo: acha ou cria (1x) a pasta-raiz do sandbox — NUNCA via
    # buscar_ou_criar_subpasta (o SUT), só via chamada crua à API, pelo
    # motivo explicado no topo do arquivo.
    pasta_id = buscar_subpasta(servico, settings.GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE, NOME_PASTA_TESTE_FIXA)
    if pasta_id is not None:
        return pasta_id
    pasta_nova = servico.files().create(
        body={
            'name': NOME_PASTA_TESTE_FIXA,
            'mimeType': MIME_PASTA,
            'parents': [settings.GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE],
        },
        fields='id',
        supportsAllDrives=True,
    ).execute()
    return pasta_nova['id']


def _apagar_cadeia_de_teste_se_existir(servico, pasta_teste_id):
    # Limpa, de dentro pra fora (Videos -> EAN -> marca), toda a estrutura
    # que os testes de enviar_arquivo criam dentro do sandbox — usada tanto
    # no Setup (limpar debris de uma rodada anterior que falhou no meio)
    # quanto no TearDown (desfazer o que o próprio teste acabou de criar).
    # Apagar a pasta Videos já cascade-apaga o arquivo lá dentro (delete
    # permanente do Drive não deixa "pasta não-vazia" travar nada).
    pasta_marca_id = buscar_subpasta(servico, pasta_teste_id, MARCA_TESTE_ESCRITA)
    if pasta_marca_id is None:
        return
    pasta_ean_id = buscar_subpasta(servico, pasta_marca_id, EAN_TESTE_ESCRITA)
    if pasta_ean_id is not None:
        pasta_videos_id = buscar_subpasta(servico, pasta_ean_id, NOME_PASTA_VIDEOS)
        if pasta_videos_id is not None:
            servico.files().delete(fileId=pasta_videos_id, supportsAllDrives=True).execute()
        servico.files().delete(fileId=pasta_ean_id, supportsAllDrives=True).execute()
    servico.files().delete(fileId=pasta_marca_id, supportsAllDrives=True).execute()


def _criar_arquivo_local_temporario(conteudo_bytes):
    caminho = tempfile.mktemp(suffix='.mp4')
    with open(caminho, 'wb') as arquivo:
        arquivo.write(conteudo_bytes)
    return caminho


def test_buscar_ou_criar_subpasta_e_idempotente_de_verdade(tabela_resultados):
    # Função Objetivo: 1ª chamada, sem a subpasta existir ainda, precisa
    # CRIAR e devolver um ID novo; 2ª chamada, com o mesmo nome e mesmo pai,
    # precisa ACHAR a que já existe, devolver o MESMO ID, e nunca duplicar.
    # Essa é a regra de negócio por trás do Portal do Drive: cada
    # "sincronizar" pode chamar essa função de novo pro mesmo produto, sem
    # nunca criar uma 2ª pasta com o mesmo nome.

    # Setup: garante que a pasta-raiz do sandbox existe (self-provisiona, 1x,
    # sem pré-requisito manual) e garante que não sobrou debris de uma
    # rodada anterior que tenha falhado entre criar e apagar — sempre parte
    # de um estado limpo e conhecido.
    servico = obter_servico_drive_escrita()
    pasta_teste_id = _garantir_pasta_teste_fixa(servico)
    debris_id = buscar_subpasta(servico, pasta_teste_id, NOME_SUBPASTA_CRIADA_PELO_TESTE)
    if debris_id is not None:
        servico.files().delete(fileId=debris_id, supportsAllDrives=True).execute()

    subpasta_id_criada = None
    try:
        # Exercise: chama o SUT 2 vezes de propósito, pra provar os 2 lados
        # da idempotência na mesma execução.
        subpasta_id_criada = buscar_ou_criar_subpasta(servico, pasta_teste_id, NOME_SUBPASTA_CRIADA_PELO_TESTE)
        subpasta_id_reaproveitada = buscar_ou_criar_subpasta(servico, pasta_teste_id, NOME_SUBPASTA_CRIADA_PELO_TESTE)

        resultado_bruto = servico.files().list(
            q=(
                f"'{pasta_teste_id}' in parents and name = '{NOME_SUBPASTA_CRIADA_PELO_TESTE}' "
                f"and trashed = false"
            ),
            fields='files(id)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        total_pastas_com_esse_nome = len(resultado_bruto.get('files', []))

        # Assert: registra ANTES de comparar, pra linha aparecer mesmo se falhar.
        passou = (
            subpasta_id_criada is not None
            and subpasta_id_reaproveitada == subpasta_id_criada
            and total_pastas_com_esse_nome == 1
        )
        registrar_resultado(
            tabela_resultados, teste='buscar_ou_criar_subpasta() — cria na 1ª vez, reaproveita na 2ª, nunca duplica',
            entrada=f"pasta_pai='{NOME_PASTA_TESTE_FIXA}' (real), subpasta='{NOME_SUBPASTA_CRIADA_PELO_TESTE}'",
            esperado='1ª chamada cria e devolve um ID; 2ª chamada devolve o MESMO ID; só 1 pasta com esse nome no Drive real',
            motivo='Sem idempotência, cada "Sincronizar" no Portal do Drive criaria uma pasta duplicada pro mesmo produto',
            obtido=f'id_1={subpasta_id_criada}, id_2={subpasta_id_reaproveitada}, total_no_drive={total_pastas_com_esse_nome}',
            passou=passou,
        )
        assert passou
    finally:
        # TearDown: apaga de verdade a subpasta criada pelo teste (nunca só
        # lixeira) — este teste ESCREVE no Drive real, então precisa desfazer
        # a própria escrita, sempre, mesmo se o assert acima tiver falhado.
        if subpasta_id_criada is not None:
            servico.files().delete(fileId=subpasta_id_criada, supportsAllDrives=True).execute()


def test_enviar_arquivo_cria_cadeia_de_pastas_e_sobe_arquivo_de_verdade(tabela_resultados):
    # Função Objetivo: cenário "tudo novo" — marca/EAN/Videos ainda não
    # existem dentro do sandbox; enviar_arquivo precisa criar a cadeia
    # inteira e subir o arquivo, com o nome canônico certo.
    # Setup:
    servico = obter_servico_drive_escrita()
    pasta_teste_id = _garantir_pasta_teste_fixa(servico)
    _apagar_cadeia_de_teste_se_existir(servico, pasta_teste_id)

    arquivador = ArquivadorDrive()
    nome_esperado = montar_nome_arquivo('simples', 1, 'base')
    caminho_local = _criar_arquivo_local_temporario(b'conteudo de teste - video simulado')

    arquivo_id = None
    try:
        # Exercise:
        arquivo_id = arquivador.enviar_arquivo(
            pasta_teste_id, MARCA_TESTE_ESCRITA, EAN_TESTE_ESCRITA, 'simples', 1, 'base', caminho_local,
        )

        pasta_marca_id = buscar_subpasta(servico, pasta_teste_id, MARCA_TESTE_ESCRITA)
        pasta_ean_id = buscar_subpasta(servico, pasta_marca_id, EAN_TESTE_ESCRITA) if pasta_marca_id else None
        pasta_videos_id = buscar_subpasta(servico, pasta_ean_id, NOME_PASTA_VIDEOS) if pasta_ean_id else None
        arquivo_encontrado_id = buscar_arquivo(servico, pasta_videos_id, nome_esperado) if pasta_videos_id else None

        # Assert:
        passou = (
            arquivo_id is not None
            and pasta_marca_id is not None
            and pasta_ean_id is not None
            and pasta_videos_id is not None
            and arquivo_encontrado_id == arquivo_id
        )
        registrar_resultado(
            tabela_resultados, teste='enviar_arquivo() — cria cadeia marca/EAN/Videos do zero e sobe o arquivo',
            entrada=f"marca='{MARCA_TESTE_ESCRITA}', ean='{EAN_TESTE_ESCRITA}', fase='simples', tipo='base'",
            esperado=f"cadeia de pastas criada, arquivo '{nome_esperado}' presente em Videos/",
            motivo='Prova o caminho "tudo novo" do Portal do Drive — 1º envio de um produto que nunca teve pasta',
            obtido=f'arquivo_id={arquivo_id}, pasta_marca={pasta_marca_id}, pasta_ean={pasta_ean_id}, pasta_videos={pasta_videos_id}, achado_por_nome={arquivo_encontrado_id}',
            passou=passou,
        )
        assert passou
    finally:
        # TearDown:
        _apagar_cadeia_de_teste_se_existir(servico, pasta_teste_id)
        os.remove(caminho_local)


def test_enviar_arquivo_recusa_sobrescrever_sem_permissao_explicita(tabela_resultados):
    # Função Objetivo: já existe um arquivo com o nome canônico em Videos/ —
    # sem permitir_substituir=True, precisa recusar (FileExistsError) e não
    # tocar em NADA no Drive.
    # Setup: sobe o arquivo original 1x (fica "já existente" pro Exercise).
    servico = obter_servico_drive_escrita()
    pasta_teste_id = _garantir_pasta_teste_fixa(servico)
    _apagar_cadeia_de_teste_se_existir(servico, pasta_teste_id)

    arquivador = ArquivadorDrive()
    nome_esperado = montar_nome_arquivo('simples', 1, 'base')
    caminho_original = _criar_arquivo_local_temporario(b'conteudo original')
    caminho_tentativa = _criar_arquivo_local_temporario(b'conteudo tentando sobrescrever sem permissao')

    try:
        arquivador.enviar_arquivo(
            pasta_teste_id, MARCA_TESTE_ESCRITA, EAN_TESTE_ESCRITA, 'simples', 1, 'base', caminho_original,
        )

        # Exercise:
        levantou_file_exists_error = False
        try:
            arquivador.enviar_arquivo(
                pasta_teste_id, MARCA_TESTE_ESCRITA, EAN_TESTE_ESCRITA, 'simples', 1, 'base', caminho_tentativa,
            )
        except FileExistsError:
            levantou_file_exists_error = True

        pasta_marca_id = buscar_subpasta(servico, pasta_teste_id, MARCA_TESTE_ESCRITA)
        pasta_ean_id = buscar_subpasta(servico, pasta_marca_id, EAN_TESTE_ESCRITA)
        pasta_videos_id = buscar_subpasta(servico, pasta_ean_id, NOME_PASTA_VIDEOS)
        resultado_bruto = servico.files().list(
            q=f"'{pasta_videos_id}' in parents and name = '{nome_esperado}' and trashed = false",
            fields='files(id)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        total_arquivos_com_esse_nome = len(resultado_bruto.get('files', []))

        # Assert:
        passou = levantou_file_exists_error and total_arquivos_com_esse_nome == 1
        registrar_resultado(
            tabela_resultados, teste='enviar_arquivo() — recusa sobrescrever sem permitir_substituir=True',
            entrada=f"arquivo '{nome_esperado}' já existente, 2ª chamada sem permitir_substituir",
            esperado='FileExistsError levantado; continua existindo só 1 arquivo com esse nome (o original, intocado)',
            motivo='Sobrescrever é decisão do usuário via modal de confirmação — nunca automático',
            obtido=f'levantou_file_exists_error={levantou_file_exists_error}, total_no_drive={total_arquivos_com_esse_nome}',
            passou=passou,
        )
        assert passou
    finally:
        # TearDown:
        _apagar_cadeia_de_teste_se_existir(servico, pasta_teste_id)
        os.remove(caminho_original)
        os.remove(caminho_tentativa)


def test_enviar_arquivo_substitui_mantendo_mesmo_id_quando_permitido(tabela_resultados):
    # Função Objetivo: com permitir_substituir=True, o CONTEÚDO muda de
    # verdade (baixa de novo e compara bytes) mas o ID continua o MESMO —
    # nunca cria um 2º arquivo duplicado.
    servico = obter_servico_drive_escrita()
    pasta_teste_id = _garantir_pasta_teste_fixa(servico)
    _apagar_cadeia_de_teste_se_existir(servico, pasta_teste_id)

    arquivador = ArquivadorDrive()
    nome_esperado = montar_nome_arquivo('simples', 1, 'base')
    conteudo_original = b'conteudo original'
    conteudo_substituto = b'conteudo NOVO depois da substituicao confirmada'
    caminho_original = _criar_arquivo_local_temporario(conteudo_original)
    caminho_substituto = _criar_arquivo_local_temporario(conteudo_substituto)
    caminho_baixado = None

    try:
        arquivo_id_original = arquivador.enviar_arquivo(
            pasta_teste_id, MARCA_TESTE_ESCRITA, EAN_TESTE_ESCRITA, 'simples', 1, 'base', caminho_original,
        )

        # Exercise:
        arquivo_id_substituto = arquivador.enviar_arquivo(
            pasta_teste_id, MARCA_TESTE_ESCRITA, EAN_TESTE_ESCRITA, 'simples', 1, 'base', caminho_substituto,
            permitir_substituir=True,
        )

        caminho_baixado = tempfile.mktemp(suffix='.mp4')
        arquivador.baixar_arquivo(arquivo_id_substituto, caminho_baixado)
        with open(caminho_baixado, 'rb') as arquivo_baixado_handle:
            conteudo_baixado = arquivo_baixado_handle.read()

        pasta_marca_id = buscar_subpasta(servico, pasta_teste_id, MARCA_TESTE_ESCRITA)
        pasta_ean_id = buscar_subpasta(servico, pasta_marca_id, EAN_TESTE_ESCRITA)
        pasta_videos_id = buscar_subpasta(servico, pasta_ean_id, NOME_PASTA_VIDEOS)
        resultado_bruto = servico.files().list(
            q=f"'{pasta_videos_id}' in parents and name = '{nome_esperado}' and trashed = false",
            fields='files(id)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        total_arquivos_com_esse_nome = len(resultado_bruto.get('files', []))

        # Assert:
        passou = (
            arquivo_id_substituto == arquivo_id_original
            and conteudo_baixado == conteudo_substituto
            and total_arquivos_com_esse_nome == 1
        )
        registrar_resultado(
            tabela_resultados, teste='enviar_arquivo() — substitui conteúdo mantendo o mesmo ID (permitir_substituir=True)',
            entrada=f"arquivo '{nome_esperado}' já existente, 2ª chamada com permitir_substituir=True",
            esperado='mesmo ID de volta; conteúdo baixado bate com o NOVO arquivo; só 1 arquivo com esse nome no Drive',
            motivo='"Substituir" precisa ser o mesmo arquivo com conteúdo novo, nunca um 2º arquivo duplicado',
            obtido=f'id_original={arquivo_id_original}, id_substituto={arquivo_id_substituto}, conteudo_bate={conteudo_baixado == conteudo_substituto}, total_no_drive={total_arquivos_com_esse_nome}',
            passou=passou,
        )
        assert passou
    finally:
        # TearDown:
        _apagar_cadeia_de_teste_se_existir(servico, pasta_teste_id)
        os.remove(caminho_original)
        os.remove(caminho_substituto)
        if caminho_baixado is not None and os.path.exists(caminho_baixado):
            os.remove(caminho_baixado)