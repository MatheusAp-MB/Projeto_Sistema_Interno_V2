# agenda_videos/tests/test_nivel_5__drive_escrita.py

# Função Objetivo: Confirma que a ESCRITA no Google Drive funciona DE
# VERDADE — rede real + credencial real, escopo de escrita
# (obter_servico_drive_escrita). Diferente de test_nivel_5__drive_leitura.py
# (que documenta explicitamente NUNCA criar/mover/apagar nada real), este
# arquivo é o 1º do projeto que ESCREVE de propósito no Drive real —
# arquivador.py segue com 0% de cobertura até aqui, então este é o primeiro
# caso.
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

import pytest
from django.conf import settings

from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive_escrita
from agenda_videos.funcoes_auxiliares.drive.constantes import MIME_PASTA
from agenda_videos.funcoes_auxiliares.drive.utilitarios_pasta import buscar_subpasta, buscar_ou_criar_subpasta
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Integração real — escrita no Google Drive (buscar_ou_criar_subpasta, dentro de _teste_automatizado)'

NOME_PASTA_TESTE_FIXA = '_teste_automatizado'
NOME_SUBPASTA_CRIADA_PELO_TESTE = 'subpasta_criada_pelo_teste_nivel_5'

pytestmark = pytest.mark.skipif(
    not settings.GOOGLE_DRIVE_CREDENCIAIS_JSON,
    reason='GOOGLE_DRIVE_CREDENCIAIS_JSON não configurado nesta máquina — sem credencial, sem teste real de Drive.',
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
    ).execute()
    return pasta_nova['id']


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
        servico.files().delete(fileId=debris_id).execute()

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
            servico.files().delete(fileId=subpasta_id_criada).execute()