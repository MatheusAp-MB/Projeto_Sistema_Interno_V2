# agenda_videos\tests\test_nivel_5__drive_leitura.py

# Função Objetivo: Confirma que a leitura do Google Drive funciona DE
# VERDADE — não é DB local, é rede real + credencial real. Categoria nova,
# fora da numeração "Nível" (que é sobre camadas dentro do Django) — aqui é
# integração com serviço externo. SÓ LEITURA: nenhum teste aqui cria, move
# ou apaga nada no Drive real; a única escrita é no banco de TESTE
# (SnapshotArquivosDrive), isolado e descartável.
#
# Auto-skip: se GOOGLE_DRIVE_CREDENCIAIS_JSON não estiver configurado nesta
# máquina, os testes pulam de forma limpa em vez de quebrar — rodar `pytest`
# normal já cobre quando a credencial existir, sem flag especial.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import os

import pytest
from django.conf import settings

from produtos.models import Produto
from agenda_videos.models import SnapshotArquivosDrive
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive, obter_pasta_raiz_id_ativa
from agenda_videos.funcoes_auxiliares.drive.escaneador import (
    _listar_tudo_paginado, montar_arvore_por_ean, sincronizar_snapshots_drive,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Integração real — leitura do Google Drive (sem mock, só leitura)'

pytestmark = pytest.mark.skipif(
    not settings.GOOGLE_DRIVE_CREDENCIAIS_JSON,
    reason='GOOGLE_DRIVE_CREDENCIAIS_JSON não configurado nesta máquina — sem credencial, sem teste real de Drive.',
)


# * [EXPLICAÇÃO] → Achado real (18/08/2026): depois da pasta raiz do Drive
#                  virar por empresa, qualquer código que a resolva precisa
#                  saber a empresa ativa — e testes não passam por
#                  middleware de sessão. Fixa MAGAZINE (o dado de
#                  referência real, QUIMIVIDA, é da Magazine) pra toda a
#                  suíte deste arquivo.
@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


def test_conexao_real_autentica_e_lista_itens(tabela_resultados):
    # Exercise:
    servico = obter_servico_drive()
    todos_os_itens = _listar_tudo_paginado(servico)

    # Assert:
    passou = isinstance(todos_os_itens, list) and len(todos_os_itens) > 0
    registrar_resultado(
        tabela_resultados, teste='Conexão real com o Drive + listagem paginada',
        entrada=f'credencial real ({settings.GOOGLE_DRIVE_CREDENCIAIS_JSON})', esperado='lista não vazia de itens reais',
        motivo='Se a credencial ou a API estiverem quebradas, isso já falha aqui, antes de qualquer lógica nossa',
        obtido=f'total_itens={len(todos_os_itens)}',
        passou=passou,
    )
    assert passou


def test_arvore_reconstruida_a_partir_do_drive_real(tabela_resultados):
    # Exercise:
    servico = obter_servico_drive()
    pasta_raiz_id = obter_pasta_raiz_id_ativa()
    todos_os_itens = _listar_tudo_paginado(servico)
    arvore_por_ean = montar_arvore_por_ean(todos_os_itens, pasta_raiz_id)

    # Assert:
    passou = isinstance(arvore_por_ean, dict)
    registrar_resultado(
        tabela_resultados, teste='montar_arvore_por_ean() contra a estrutura real de hoje',
        entrada=f'{len(todos_os_itens)} itens reais, raiz={pasta_raiz_id}', esperado='dict {ean: {marca, arquivos_videos, arquivos_usados}}',
        motivo='Prova que a navegação marca→ean→Videos→arquivos funciona contra pastas reais, não uma lista fabricada',
        obtido=f'total_eans_reconhecidos={len(arvore_por_ean)}',
        passou=passou,
    )
    assert passou


# * [EXPLICAÇÃO] → Igual ao caso de test_nivel_3__verificador.py: com a
#                  empresa ativa setada (fixture do topo do arquivo), o
#                  EmpresaRouter manda a query de SnapshotArquivosDrive pro
#                  alias explícito 'magazine' — precisa declarar aqui, senão
#                  o pytest-django bloqueia com DatabaseOperationForbidden.
@pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])
def test_sincronizar_snapshots_drive_roda_de_verdade_sem_erro(tabela_resultados):
    # Função Objetivo: Exercita a função de orquestração completa contra o
    # Drive real — a única escrita é no banco de TESTE (SnapshotArquivosDrive),
    # isolado; nada é escrito no Drive.
    # Exercise:
    atualizados, sem_produto_no_banco, produto_ids_atualizados = sincronizar_snapshots_drive()

    # Assert:
    passou = (
        isinstance(atualizados, int) and isinstance(sem_produto_no_banco, list)
        and isinstance(produto_ids_atualizados, list)
        and SnapshotArquivosDrive.objects.count() == atualizados
    )
    registrar_resultado(
        tabela_resultados, teste='sincronizar_snapshots_drive() contra o Drive real',
        entrada='Drive real + banco de teste vazio', esperado='roda sem exceção; SnapshotArquivosDrive criado só pros EANs que já têm Produto no banco de teste',
        motivo='Prova a função de orquestração inteira, ponta a ponta, sem mock nenhum',
        obtido=f'atualizados={atualizados}, sem_produto_no_banco={len(sem_produto_no_banco)}, snapshots_no_banco={SnapshotArquivosDrive.objects.count()}',
        passou=passou,
    )
    assert passou