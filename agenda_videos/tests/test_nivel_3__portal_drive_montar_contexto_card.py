# agenda_videos/tests/test_nivel_3__portal_drive_montar_contexto_card.py

# Função Objetivo: Testa _montar_contexto_card() — Nível 3 (banco real,
# Drive simulado). Só _obter_detalhes_arquivo é substituída por uma fake —
# o resto (banco, mutação do item, decisão de salvar) roda de verdade.
# Confirma a otimização central do cache: 1 único save por render do card,
# nunca 1 por arquivo, e zero saves quando tudo já está cacheado.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest

from produtos.models import Produto
from agenda_videos.models import SnapshotArquivosDrive
from agenda_videos.funcoes_auxiliares.drive.arquivador import montar_nome_arquivo
import agenda_videos.views as views_module
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 3 — _montar_contexto_card(): salva o snapshot só 1 vez por render'


@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


@pytest.fixture(autouse=True)
def _drive_desligado(monkeypatch):
    # Setup: obter_servico_drive() é chamado incondicionalmente no topo de
    # _montar_contexto_card — um sentinela basta, já que _obter_detalhes_arquivo
    # (quem de fato usaria o servico) é substituída em cada teste.
    monkeypatch.setattr(views_module, 'obter_servico_drive', lambda: object())


def _criar_produto(sku, ean, marca='Marca Teste'):
    return Produto.objects.create(ean=ean, sku=sku, titulo='Produto Teste', marca=marca)


def _criar_snapshot(produto, arquivos_videos):
    return SnapshotArquivosDrive.objects.create(
        produto=produto, pasta_encontrada=True, arquivos_videos=arquivos_videos, arquivos_usados=[],
        pasta_videos_id='id_pasta_videos', pasta_usados_id='',
    )


@pytest.fixture
def _contador_de_saves(monkeypatch):
    # Setup: substitui SnapshotArquivosDrive.save por uma versão que conta
    # as chamadas E delega pro save de verdade — assim as gravações reais
    # continuam acontecendo, só ganham uma contagem observável.
    chamadas = []
    save_original = SnapshotArquivosDrive.save

    def _save_contando(self, *args, **kwargs):
        chamadas.append(kwargs.get('update_fields'))
        return save_original(self, *args, **kwargs)

    monkeypatch.setattr(SnapshotArquivosDrive, 'save', _save_contando)
    return chamadas


def test_1_arquivo_sem_cache_causa_exatamente_1_save(tabela_resultados, monkeypatch, _contador_de_saves):
    # Setup:
    produto = _criar_produto('SKU-CACHE-001', '7891111100200')
    nome_arquivo = montar_nome_arquivo('simples', None, 'base')
    snapshot = _criar_snapshot(produto, [{'id': 'FILE_1', 'name': nome_arquivo}])
    monkeypatch.setattr(
        views_module, '_obter_detalhes_arquivo',
        lambda servico, drive_file_id: {'link_visualizacao': 'https://drive.example/1', 'tamanho_bytes': 1000, 'duracao_segundos': 10.0},
    )
    _contador_de_saves.clear()  # o create() do snapshot acima também chama save() — zera antes de exercitar

    # Exercise:
    views_module._montar_contexto_card(produto)

    # Assert:
    snapshot.refresh_from_db()
    item_persistido = snapshot.arquivos_videos[0]
    passou = (
        len(_contador_de_saves) == 1
        and _contador_de_saves[0] == ['arquivos_videos', 'arquivos_usados']
        and item_persistido.get('tamanho_bytes') == 1000
    )
    registrar_resultado(
        tabela_resultados, teste='1 arquivo sem cache → exatamente 1 save, campos gravados de verdade no banco',
        entrada='snapshot com 1 arquivo presente, sem os campos de cache',
        esperado="1 save com update_fields=['arquivos_videos', 'arquivos_usados']; item recarregado do banco já com tamanho_bytes=1000",
        motivo='snapshot.save() só roda 1 vez no final de _montar_contexto_card, não durante o loop de linhas',
        obtido=f'saves={_contador_de_saves}, item_persistido={item_persistido}',
        passou=passou,
    )
    assert passou


def test_todos_os_arquivos_ja_com_cache_nao_causa_nenhum_save(tabela_resultados, monkeypatch, _contador_de_saves):
    # Setup:
    produto = _criar_produto('SKU-CACHE-002', '7891111100201')
    nome_arquivo = montar_nome_arquivo('simples', None, 'base')
    _criar_snapshot(produto, [{
        'id': 'FILE_2', 'name': nome_arquivo,
        'link_visualizacao': 'https://drive.example/ja-cacheado', 'tamanho_bytes': 2000, 'duracao_segundos': 20.0,
    }])

    def _nao_deveria_ser_chamada(servico, drive_file_id):
        raise AssertionError('_obter_detalhes_arquivo não deveria ser chamado quando o item já está cacheado')
    monkeypatch.setattr(views_module, '_obter_detalhes_arquivo', _nao_deveria_ser_chamada)
    _contador_de_saves.clear()  # o create() do snapshot acima também chama save() — zera antes de exercitar

    # Exercise:
    views_module._montar_contexto_card(produto)

    # Assert:
    passou = len(_contador_de_saves) == 0
    registrar_resultado(
        tabela_resultados, teste='Arquivo já com cache completo → zero saves, Drive nunca chamado',
        entrada='snapshot com 1 arquivo já com os 3 campos de cache preenchidos',
        esperado='nenhum save, _obter_detalhes_arquivo nunca chamado',
        motivo='Reabrir um produto já visto não pode custar nem chamada ao Drive nem escrita no banco',
        obtido=f'saves={_contador_de_saves}',
        passou=passou,
    )
    assert passou


def test_2_arquivos_sem_cache_ainda_assim_causa_so_1_save(tabela_resultados, monkeypatch, _contador_de_saves):
    # Setup: 2 arquivos de linhas DIFERENTES, os 2 sem cache — prova que o
    # save é agregado (1 só no final), não 1 por arquivo novo.
    produto = _criar_produto('SKU-CACHE-003', '7891111100202')
    nome_base_simples = montar_nome_arquivo('simples', None, 'base')
    nome_base_mensal_1 = montar_nome_arquivo('video_mensal', 1, 'base')
    snapshot = _criar_snapshot(produto, [
        {'id': 'FILE_3', 'name': nome_base_simples},
        {'id': 'FILE_4', 'name': nome_base_mensal_1},
    ])
    monkeypatch.setattr(
        views_module, '_obter_detalhes_arquivo',
        lambda servico, drive_file_id: {'link_visualizacao': f'https://drive.example/{drive_file_id}', 'tamanho_bytes': 1500, 'duracao_segundos': 15.0},
    )
    _contador_de_saves.clear()  # o create() do snapshot acima também chama save() — zera antes de exercitar

    # Exercise:
    views_module._montar_contexto_card(produto)

    # Assert:
    snapshot.refresh_from_db()
    ambos_cacheados = all('tamanho_bytes' in item for item in snapshot.arquivos_videos)
    passou = len(_contador_de_saves) == 1 and ambos_cacheados
    registrar_resultado(
        tabela_resultados, teste='2 arquivos sem cache no mesmo render → só 1 save (agregado), não 1 por arquivo',
        entrada='snapshot com 2 arquivos presentes, nenhum com cache',
        esperado='1 save só, os 2 itens persistidos com os campos de cache',
        motivo='houve_cache_novo é um OR acumulado pelas linhas — o save só roda 1 vez, depois do loop inteiro',
        obtido=f'saves={_contador_de_saves}, arquivos_videos={snapshot.arquivos_videos}',
        passou=passou,
    )
    assert passou


def test_produto_sem_snapshot_nunca_tenta_salvar(tabela_resultados, _contador_de_saves):
    # Setup:
    produto = _criar_produto('SKU-CACHE-004', '7891111100203')

    # Exercise:
    contexto = views_module._montar_contexto_card(produto)

    # Assert:
    passou = len(_contador_de_saves) == 0 and contexto['nunca_sincronizado'] is True
    registrar_resultado(
        tabela_resultados, teste='Produto sem snapshot nenhum → nenhum save, sem quebrar',
        entrada='produto sem SnapshotArquivosDrive', esperado='nenhum save; nunca_sincronizado=True',
        motivo='Sem snapshot não tem nada pra cachear nem pra salvar — houve_cache_novo nunca vira True nesse caso',
        obtido=f'saves={_contador_de_saves}, nunca_sincronizado={contexto.get("nunca_sincronizado")}',
        passou=passou,
    )
    assert passou