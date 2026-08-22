# agenda_videos/tests/test_nivel_0__escaneador.py

# SUT: agenda_videos/funcoes_auxiliares/drive/escaneador.py
#      (_listar_tudo_paginado, montar_arvore_por_ean)
# DOC: as 2 funções são puras/sem banco — _listar_tudo_paginado só depende
#      de um objeto "serviço" com o mesmo formato da API do Drive (aqui,
#      um dublê fabricado à mão, sem rede nenhuma); montar_arvore_por_ean
#      é 100% pura (lista fabricada -> dict). Nível 0. O laço
#      Sistema→Drive (sincronizar_snapshots_drive) tem teste próprio em
#      test_nivel_3__escaneador.py, com estas 2 funções mockadas de lá.

from agenda_videos.funcoes_auxiliares.drive.escaneador import _listar_tudo_paginado, montar_arvore_por_ean
from agenda_videos.funcoes_auxiliares.drive.constantes import MIME_PASTA
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — escaneador.py: _listar_tudo_paginado / montar_arvore_por_ean (puras)'


def _pasta(id_, nome, pai_id):
    return {'id': id_, 'name': nome, 'mimeType': MIME_PASTA, 'parents': [pai_id]}


def _arquivo(id_, nome, pai_id):
    return {'id': id_, 'name': nome, 'mimeType': 'video/mp4', 'parents': [pai_id]}


# ---------- _listar_tudo_paginado ----------

class _RespostaFake:
    def __init__(self, dados):
        self._dados = dados

    def execute(self):
        return self._dados


class _ServicoFakePaginado:
    # Função Objetivo: dublê mínimo da cadeia servico.files().list(**kwargs).execute()
    # — devolve 1 página por chamada, escolhida pelo pageToken recebido.
    def __init__(self, paginas_por_token):
        self._paginas_por_token = paginas_por_token
        self.chamadas = []

    def files(self):
        return self

    def list(self, **kwargs):
        self.chamadas.append(kwargs.get('pageToken'))
        return _RespostaFake(self._paginas_por_token[kwargs.get('pageToken')])


def test_nivel_0__listar_tudo_paginado_1_pagina_sem_next_token(tabela_resultados):
    # Setup:
    servico = _ServicoFakePaginado({None: {'files': [{'id': '1'}, {'id': '2'}]}})

    # Exercise:
    itens = _listar_tudo_paginado(servico)

    # Assert:
    passou = itens == [{'id': '1'}, {'id': '2'}] and servico.chamadas == [None]
    registrar_resultado(
        tabela_resultados, teste='_listar_tudo_paginado — 1 página, sem nextPageToken',
        entrada='resposta única com 2 arquivos, sem nextPageToken',
        esperado='devolve os 2 arquivos, para depois de 1 chamada',
        motivo='Caso mais simples — precisa parar sozinho quando não há mais página',
        obtido=f'itens={itens}, chamadas={servico.chamadas}',
        passou=passou,
    )
    assert passou


def test_nivel_0__listar_tudo_paginado_2_paginas_concatena_e_para(tabela_resultados):
    # Setup:
    servico = _ServicoFakePaginado({
        None: {'files': [{'id': '1'}], 'nextPageToken': 'tok2'},
        'tok2': {'files': [{'id': '2'}]},
    })

    # Exercise:
    itens = _listar_tudo_paginado(servico)

    # Assert:
    passou = itens == [{'id': '1'}, {'id': '2'}] and servico.chamadas == [None, 'tok2']
    registrar_resultado(
        tabela_resultados, teste='_listar_tudo_paginado — 2 páginas, concatena tudo',
        entrada='1ª resposta com nextPageToken="tok2", 2ª sem',
        esperado='itens das 2 páginas concatenados, 2 chamadas na ordem certa',
        motivo='Catálogo real tem mais de 1000 itens (pageSize) — paginação precisa varrer até o fim',
        obtido=f'itens={itens}, chamadas={servico.chamadas}',
        passou=passou,
    )
    assert passou


# ---------- montar_arvore_por_ean ----------

def test_nivel_0__montar_arvore_caminho_completo_com_usados(tabela_resultados):
    # Setup: raiz -> Marca X -> EAN-1 -> Videos -> (1 arquivo solto + pasta usados -> 1 arquivo)
    itens = [
        _pasta('marca1', 'Marca X', 'raiz'),
        _pasta('ean1', 'EAN-1', 'marca1'),
        _pasta('videos1', 'Videos', 'ean1'),
        _arquivo('arq1', 'Simples_Base.mp4', 'videos1'),
        _pasta('usados1', 'usados', 'videos1'),
        _arquivo('arq2', 'Simples_Base.mp4', 'usados1'),
    ]

    # Exercise:
    arvore = montar_arvore_por_ean(itens, 'raiz')

    # Assert:
    passou = arvore == {
        'EAN-1': {
            'marca': 'Marca X',
            'arquivos_videos': [{'id': 'arq1', 'name': 'Simples_Base.mp4'}],
            'arquivos_usados': [{'id': 'arq2', 'name': 'Simples_Base.mp4'}],
            'pasta_videos_id': 'videos1',
            'pasta_usados_id': 'usados1',
        }
    }
    registrar_resultado(
        tabela_resultados, teste='montar_arvore_por_ean — caminho completo, com pasta usados',
        entrada='raiz→Marca X→EAN-1→Videos→(1 arquivo + usados→1 arquivo)',
        esperado='1 entrada no dict, arquivos_videos e arquivos_usados corretos, ids de pasta corretos',
        motivo='Caminho feliz — a estrutura real que a maioria dos produtos tem',
        obtido=f'arvore={arvore}',
        passou=passou,
    )
    assert passou


def test_nivel_0__montar_arvore_case_insensitive_videos_e_usados(tabela_resultados):
    # Setup: nomes de pasta em minúsculo/maiúsculo misturado — regressão do
    # bug real de 05/08/2026 (Drive é case-insensitive, o código antigo não era).
    itens = [
        _pasta('marca1', 'Marca X', 'raiz'),
        _pasta('ean1', 'EAN-2', 'marca1'),
        _pasta('videos1', 'videos', 'ean1'),  # minúsculo
        _arquivo('arq1', 'Simples_Base.mp4', 'videos1'),
        _pasta('usados1', 'USADOS', 'videos1'),  # maiúsculo
    ]

    # Exercise:
    arvore = montar_arvore_por_ean(itens, 'raiz')

    # Assert:
    passou = (
        'EAN-2' in arvore
        and arvore['EAN-2']['pasta_videos_id'] == 'videos1'
        and arvore['EAN-2']['pasta_usados_id'] == 'usados1'
    )
    registrar_resultado(
        tabela_resultados, teste='montar_arvore_por_ean — nomes de pasta case-insensitive',
        entrada='pasta "videos" (minúsculo) e "USADOS" (maiúsculo)',
        esperado='reconhece as 2 pastas mesmo assim (Drive real é case-insensitive)',
        motivo='Regressão do bug real corrigido em 05/08/2026 — 4 de 5 pastas de EAN eram descartadas silenciosamente por comparação case-sensitive',
        obtido=f'arvore={arvore}',
        passou=passou,
    )
    assert passou


def test_nivel_0__montar_arvore_ean_sem_pasta_videos_e_ignorado(tabela_resultados):
    # Setup: EAN existe, mas não tem subpasta "Videos" dentro dele
    itens = [
        _pasta('marca1', 'Marca X', 'raiz'),
        _pasta('ean1', 'EAN-3', 'marca1'),
        _arquivo('arq_solto', 'arquivo_solto.txt', 'ean1'),
    ]

    # Exercise:
    arvore = montar_arvore_por_ean(itens, 'raiz')

    # Assert:
    passou = arvore == {}
    registrar_resultado(
        tabela_resultados, teste='montar_arvore_por_ean — EAN sem pasta Videos é ignorado',
        entrada='pasta de EAN sem nenhuma subpasta "Videos"',
        esperado='dict vazio — não quebra, só não inclui esse EAN',
        motivo='Estrutura incompleta/errada no Drive não pode derrubar a varredura inteira',
        obtido=f'arvore={arvore}',
        passou=passou,
    )
    assert passou


def test_nivel_0__montar_arvore_sem_pasta_usados_arquivos_usados_vazio(tabela_resultados):
    # Setup: tem Videos, mas nenhuma subpasta "usados"
    itens = [
        _pasta('marca1', 'Marca X', 'raiz'),
        _pasta('ean1', 'EAN-4', 'marca1'),
        _pasta('videos1', 'Videos', 'ean1'),
        _arquivo('arq1', 'Simples_Base.mp4', 'videos1'),
    ]

    # Exercise:
    arvore = montar_arvore_por_ean(itens, 'raiz')

    # Assert:
    passou = arvore['EAN-4']['arquivos_usados'] == [] and arvore['EAN-4']['pasta_usados_id'] == ''
    registrar_resultado(
        tabela_resultados, teste='montar_arvore_por_ean — sem pasta "usados", arquivos_usados fica vazio',
        entrada='Videos com 1 arquivo, sem subpasta usados',
        esperado='arquivos_usados=[], pasta_usados_id="" (nunca None nem erro)',
        motivo='A maioria dos produtos ainda não tem nenhum arquivo "usado" — precisa ser o caminho comum, não exceção',
        obtido=f"arquivos_usados={arvore['EAN-4']['arquivos_usados']!r}, pasta_usados_id={arvore['EAN-4']['pasta_usados_id']!r}",
        passou=passou,
    )
    assert passou


def test_nivel_0__montar_arvore_ignora_item_que_nao_e_pasta_no_nivel_marca_e_ean(tabela_resultados):
    # Setup: 1 arquivo solto direto na raiz (não é pasta de marca) e 1
    # arquivo solto direto na marca (não é pasta de EAN).
    itens = [
        _arquivo('lixo_raiz', 'nao_e_pasta.txt', 'raiz'),
        _pasta('marca1', 'Marca X', 'raiz'),
        _arquivo('lixo_marca', 'tambem_nao_e_pasta.txt', 'marca1'),
        _pasta('ean1', 'EAN-5', 'marca1'),
        _pasta('videos1', 'Videos', 'ean1'),
        _arquivo('arq1', 'Simples_Base.mp4', 'videos1'),
    ]

    # Exercise:
    arvore = montar_arvore_por_ean(itens, 'raiz')

    # Assert:
    passou = list(arvore.keys()) == ['EAN-5']
    registrar_resultado(
        tabela_resultados, teste='montar_arvore_por_ean — item que não é pasta é ignorado (nível marca e nível EAN)',
        entrada='1 arquivo solto na raiz + 1 arquivo solto na marca, ao lado das pastas reais',
        esperado='só EAN-5 aparece no resultado — os 2 arquivos soltos não geram entrada nem erro',
        motivo='O Drive pode ter lixo solto em qualquer nível — a varredura não pode quebrar nem confundir arquivo com pasta',
        obtido=f'chaves={list(arvore.keys())}',
        passou=passou,
    )
    assert passou


def test_nivel_0__montar_arvore_multiplas_marcas_e_eans(tabela_resultados):
    # Setup: 2 marcas, cada 1 com 1 EAN — confirma que o laço não mistura dado entre elas
    itens = [
        _pasta('marca1', 'Marca A', 'raiz'),
        _pasta('ean1', 'EAN-A1', 'marca1'),
        _pasta('videos1', 'Videos', 'ean1'),
        _arquivo('arq1', 'Simples_Base.mp4', 'videos1'),
        _pasta('marca2', 'Marca B', 'raiz'),
        _pasta('ean2', 'EAN-B1', 'marca2'),
        _pasta('videos2', 'Videos', 'ean2'),
        _arquivo('arq2', 'Simples_Base.mp4', 'videos2'),
    ]

    # Exercise:
    arvore = montar_arvore_por_ean(itens, 'raiz')

    # Assert:
    passou = (
        set(arvore.keys()) == {'EAN-A1', 'EAN-B1'}
        and arvore['EAN-A1']['marca'] == 'Marca A'
        and arvore['EAN-B1']['marca'] == 'Marca B'
    )
    registrar_resultado(
        tabela_resultados, teste='montar_arvore_por_ean — múltiplas marcas e EANs não se misturam',
        entrada='2 marcas, 1 EAN cada, cada 1 com seu próprio arquivo',
        esperado='2 entradas no dict, cada 1 com a marca certa',
        motivo='Catálogo real tem dezenas de marcas — precisa escalar sem confundir dado de 1 marca com outra',
        obtido=f'arvore={arvore}',
        passou=passou,
    )
    assert passou