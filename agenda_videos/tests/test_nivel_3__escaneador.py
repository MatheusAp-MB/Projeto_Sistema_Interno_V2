# agenda_videos/tests/test_nivel_3__escaneador.py

# SUT: agenda_videos/funcoes_auxiliares/drive/escaneador.py::sincronizar_snapshots_drive()
# DOC: banco real (Produto, IndicadoresAgendaProduto, SnapshotArquivosDrive) — Nível 3.
#      Drive é SIMULADO aqui: obter_servico_drive/obter_pasta_raiz_id_ativa/
#      _listar_tudo_paginado são trocados por dublês fixos, e montar_arvore_por_ean()
#      (já testada isolada em Nível 0) é trocada por um valor configurável por
#      teste — o que se exercita de verdade é o LAÇO que decide, pra cada
#      produto ATIVO do catálogo, se foi achado ou não achado no Drive (a
#      correção de 20/08/2026 — ver "Bug Real - Sincronizacao em Massa..."
#      no Obsidian). A versão com Drive REAL fica em test_nivel_5__drive_leitura.py.

import pytest

from produtos.models import Produto
from agenda_videos.models import IndicadoresAgendaProduto, SnapshotArquivosDrive, StatusManualAgenda
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from agenda_videos.funcoes_auxiliares.drive import escaneador
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 3 — sincronizar_snapshots_drive(): direção Sistema→Drive'


@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


@pytest.fixture(autouse=True)
def _drive_simulado(monkeypatch):
    monkeypatch.setattr(escaneador, 'obter_servico_drive', lambda: object())
    monkeypatch.setattr(escaneador, 'obter_pasta_raiz_id_ativa', lambda: 'raiz-teste')
    monkeypatch.setattr(escaneador, '_listar_tudo_paginado', lambda servico: [])


def _configurar_arvore(monkeypatch, arvore):
    monkeypatch.setattr(escaneador, 'montar_arvore_por_ean', lambda itens, raiz: arvore)


def _criar_produto(sku, ean, status_manual=None):
    produto = Produto.objects.create(ean=ean, sku=sku, titulo='Produto Teste')
    if status_manual:
        IndicadoresAgendaProduto.objects.create(produto=produto, status_manual=status_manual)
    return produto


def _dados_pasta(marca='Marca X'):
    return {
        'marca': marca,
        'arquivos_videos': [{'id': 'id_base', 'name': 'Simples_Base.mp4'}],
        'arquivos_usados': [],
        'pasta_videos_id': 'pasta-videos-id',
        'pasta_usados_id': '',
    }


def test_produto_ativo_achado_na_arvore_grava_pasta_encontrada_true(monkeypatch, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-501', 'EAN-501')
    _configurar_arvore(monkeypatch, {'EAN-501': _dados_pasta()})

    # Exercise:
    atualizados, sem_produto_no_banco, encontrados = escaneador.sincronizar_snapshots_drive()

    # Assert:
    snapshot = SnapshotArquivosDrive.objects.get(produto=produto)
    passou = (
        snapshot.pasta_encontrada is True
        and snapshot.arquivos_videos == [{'id': 'id_base', 'name': 'Simples_Base.mp4'}]
        and produto.id in encontrados
        and atualizados == 1
        and sem_produto_no_banco == []
    )
    registrar_resultado(
        tabela_resultados, teste='Produto ativo com EAN presente na árvore do Drive',
        entrada='árvore = {EAN-501: pasta com 1 arquivo}',
        esperado='snapshot pasta_encontrada=True, produto na lista de encontrados',
        motivo='Caminho feliz da direção Sistema→Drive — precisa continuar funcionando depois da inversão',
        obtido=f'pasta_encontrada={snapshot.pasta_encontrada}, encontrados={encontrados}, atualizados={atualizados}',
        passou=passou,
    )
    assert passou


def test_produto_ativo_sem_pasta_no_drive_grava_pasta_encontrada_false(monkeypatch, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-502', 'EAN-502')
    _configurar_arvore(monkeypatch, {})

    # Exercise:
    atualizados, sem_produto_no_banco, encontrados = escaneador.sincronizar_snapshots_drive()

    # Assert:
    snapshot = SnapshotArquivosDrive.objects.get(produto=produto)
    passou = (
        snapshot.pasta_encontrada is False
        and snapshot.arquivos_videos == [] and snapshot.arquivos_usados == []
        and snapshot.motivo_nao_encontrado not in (None, '')
        and produto.id not in encontrados
        and atualizados == 1
    )
    registrar_resultado(
        tabela_resultados, teste='Produto ativo SEM pasta no Drive — bug real corrigido',
        entrada='árvore vazia (nenhum EAN encontrado)',
        esperado='snapshot pasta_encontrada=False, gravado mesmo sem achar nada (nunca fica None)',
        motivo='Cenário exato do bug relatado: antes da correção, este produto ficava com snapshot_drive=None pra sempre, mesmo após "sincronizar tudo"',
        obtido=f'pasta_encontrada={snapshot.pasta_encontrada}, motivo={snapshot.motivo_nao_encontrado!r}, encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_produto_pausado_nao_recebe_snapshot(monkeypatch, tabela_resultados):
    # Setup:
    produto_pausado = _criar_produto('SKU-503', 'EAN-503', status_manual=StatusManualAgenda.PAUSADO)
    _configurar_arvore(monkeypatch, {'EAN-503': _dados_pasta()})

    # Exercise:
    escaneador.sincronizar_snapshots_drive()

    # Assert:
    passou = not SnapshotArquivosDrive.objects.filter(produto=produto_pausado).exists()
    registrar_resultado(
        tabela_resultados, teste='Produto Pausado fica fora da sincronização em massa',
        entrada='produto com status_manual=Pausado, EAN presente na árvore do Drive',
        esperado='nenhum SnapshotArquivosDrive criado — sincronização respeita o mesmo recorte da tela',
        motivo='listar_produtos_agenda_filtrados(tela=Tela.GERAL) já exclui Pausado/Descontinuado',
        obtido=f'snapshot_existe={SnapshotArquivosDrive.objects.filter(produto=produto_pausado).exists()}',
        passou=passou,
    )
    assert passou


def test_ean_orfao_no_drive_sem_produto_ativo_vira_sem_produto_no_banco(monkeypatch, tabela_resultados):
    # Setup: nenhum produto criado com este EAN
    _configurar_arvore(monkeypatch, {'EAN-ORFAO-999': _dados_pasta()})

    # Exercise:
    atualizados, sem_produto_no_banco, encontrados = escaneador.sincronizar_snapshots_drive()

    # Assert:
    passou = sem_produto_no_banco == ['EAN-ORFAO-999'] and atualizados == 0 and encontrados == []
    registrar_resultado(
        tabela_resultados, teste='Pasta no Drive sem produto ativo correspondente',
        entrada='árvore = {EAN-ORFAO-999: ...}, nenhum Produto com esse EAN',
        esperado='sem_produto_no_banco lista o EAN órfão; nada gravado',
        motivo='Resíduo do Drive precisa continuar visível como aviso, não sumir silenciosamente',
        obtido=f'sem_produto_no_banco={sem_produto_no_banco}, atualizados={atualizados}',
        passou=passou,
    )
    assert passou


def test_snapshot_antigo_e_sobrescrito_quando_pasta_some_do_drive(monkeypatch, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-504', 'EAN-504')
    SnapshotArquivosDrive.objects.create(
        produto=produto, pasta_encontrada=True,
        arquivos_videos=[{'id': 'id_velho', 'name': 'Simples_Base.mp4'}],
        pasta_videos_id='pasta-antiga',
    )
    _configurar_arvore(monkeypatch, {})

    # Exercise:
    escaneador.sincronizar_snapshots_drive()

    # Assert:
    snapshot = SnapshotArquivosDrive.objects.get(produto=produto)
    passou = snapshot.pasta_encontrada is False and snapshot.arquivos_videos == []
    registrar_resultado(
        tabela_resultados, teste='Snapshot antigo é sobrescrito quando a pasta some do Drive',
        entrada='snapshot anterior com 1 arquivo; nova varredura não acha mais a pasta',
        esperado='snapshot atualizado pra pasta_encontrada=False, arquivos_videos esvaziado',
        motivo='update_or_create precisa sobrescrever por completo, nunca deixar dado obsoleto',
        obtido=f'pasta_encontrada={snapshot.pasta_encontrada}, arquivos_videos={snapshot.arquivos_videos}',
        passou=passou,
    )
    assert passou


def test_callback_progresso_e_chamado_por_produto_processado(monkeypatch, tabela_resultados):
    # Setup:
    _criar_produto('SKU-505', 'EAN-505')
    _criar_produto('SKU-506', 'EAN-506')
    _configurar_arvore(monkeypatch, {'EAN-505': _dados_pasta()})
    chamadas = []

    # Exercise:
    escaneador.sincronizar_snapshots_drive(callback_progresso=lambda *args: chamadas.append(args))

    # Assert:
    chamadas_atualizando = [c for c in chamadas if c[0] == 'atualizando_produtos']
    passou = (
        chamadas[0] == ('lendo_drive', 0, None)
        and len(chamadas_atualizando) == 2
        and chamadas_atualizando[-1] == ('atualizando_produtos', 2, 2)
    )
    registrar_resultado(
        tabela_resultados, teste='callback_progresso chamado nas fases certas',
        entrada='2 produtos ativos, callback capturando cada chamada',
        esperado="1ª chamada ('lendo_drive', 0, None); depois 1 'atualizando_produtos' por produto, terminando em (2, 2)",
        motivo='É o que alimenta a barra de progresso real do botão — sem isso a barra trava ou nunca chega a 100%',
        obtido=f'chamadas={chamadas}',
        passou=passou,
    )
    assert passou