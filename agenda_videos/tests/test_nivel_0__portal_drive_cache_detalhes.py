# agenda_videos/tests/test_nivel_0__portal_drive_cache_detalhes.py

# Função Objetivo: Testa _obter_detalhes_arquivo(), _obter_detalhes_com_cache()
# e os formatadores _formatar_tamanho_arquivo()/_formatar_duracao() — Nível 0
# (funções puras/quase-puras, sem banco). O "servico" do Drive é sempre um
# fake local — nunca bate em rede de verdade.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest

from agenda_videos.views import (
    _obter_detalhes_arquivo, _obter_detalhes_com_cache, _formatar_tamanho_arquivo, _formatar_duracao,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — cache de detalhes de arquivo do Portal do Drive'


class _ExecutavelFalso:
    def __init__(self, resultado=None, excecao=None):
        self._resultado = resultado
        self._excecao = excecao

    def execute(self):
        if self._excecao is not None:
            raise self._excecao
        return self._resultado


class _ArquivosFalso:
    def __init__(self, resultado=None, excecao=None):
        self._resultado = resultado
        self._excecao = excecao

    def get(self, fileId, fields, supportsAllDrives):
        return _ExecutavelFalso(resultado=self._resultado, excecao=self._excecao)


class _ServicoDriveFalso:
    def __init__(self, resultado=None, excecao=None):
        self._resultado = resultado
        self._excecao = excecao

    def files(self):
        return _ArquivosFalso(resultado=self._resultado, excecao=self._excecao)


# ---------------------------------------------------------------------
# _obter_detalhes_arquivo
# ---------------------------------------------------------------------

def test_obter_detalhes_arquivo_sucesso_com_duracao(tabela_resultados):
    # Setup:
    servico = _ServicoDriveFalso(resultado={
        'webViewLink': 'https://drive.example/view/abc',
        'size': '2097152',
        'videoMediaMetadata': {'durationMillis': '125000'},
    })

    # Exercise:
    resultado = _obter_detalhes_arquivo(servico, 'FILE_ABC')

    # Assert:
    esperado = {'link_visualizacao': 'https://drive.example/view/abc', 'tamanho_bytes': 2097152, 'duracao_segundos': 125.0}
    passou = resultado == esperado
    registrar_resultado(
        tabela_resultados, teste='Metadados completos (com duração de vídeo) → dict com os 3 campos certos',
        entrada="webViewLink + size='2097152' + durationMillis='125000'", esperado=f'{esperado}',
        motivo='durationMillis vem em milissegundos — precisa dividir por 1000 pra virar segundos',
        obtido=f'{resultado}',
        passou=passou,
    )
    assert passou


def test_obter_detalhes_arquivo_sucesso_sem_duracao(tabela_resultados):
    # Setup: arquivo de Roteiro (.txt) não tem videoMediaMetadata nenhum.
    servico = _ServicoDriveFalso(resultado={'webViewLink': 'https://drive.example/view/roteiro', 'size': '1024'})

    # Exercise:
    resultado = _obter_detalhes_arquivo(servico, 'FILE_ROTEIRO')

    # Assert:
    passou = resultado == {'link_visualizacao': 'https://drive.example/view/roteiro', 'tamanho_bytes': 1024, 'duracao_segundos': 0}
    registrar_resultado(
        tabela_resultados, teste='Metadados sem videoMediaMetadata (arquivo não é vídeo) → duracao_segundos=0',
        entrada='metadados sem a chave videoMediaMetadata', esperado='duracao_segundos == 0',
        motivo='Roteiro é .txt — nunca vai ter duração de vídeo',
        obtido=f'{resultado}',
        passou=passou,
    )
    assert passou


def test_obter_detalhes_arquivo_sucesso_sem_size(tabela_resultados):
    # Setup:
    servico = _ServicoDriveFalso(resultado={'webViewLink': 'https://drive.example/view/xyz'})

    # Exercise:
    resultado = _obter_detalhes_arquivo(servico, 'FILE_XYZ')

    # Assert:
    passou = resultado['tamanho_bytes'] == 0
    registrar_resultado(
        tabela_resultados, teste='Metadados sem "size" → tamanho_bytes=0, sem quebrar',
        entrada="metadados sem a chave 'size'", esperado='tamanho_bytes == 0',
        motivo="int(metadados.get('size', 0) or 0) protege contra ausência e contra string vazia",
        obtido=f'{resultado}',
        passou=passou,
    )
    assert passou


def test_obter_detalhes_arquivo_com_excecao_devolve_none(tabela_resultados):
    # Setup:
    servico = _ServicoDriveFalso(excecao=ConnectionError('Falha simulada de rede com o Drive'))

    # Exercise:
    resultado = _obter_detalhes_arquivo(servico, 'FILE_QUALQUER')

    # Assert:
    passou = resultado is None
    registrar_resultado(
        tabela_resultados, teste='Exceção ao consultar o Drive → devolve None (não um dict zerado)',
        entrada='servico.files().get(...).execute() lançando ConnectionError', esperado='resultado is None',
        motivo='None sinaliza "erro passageiro, tenta de novo depois" pra _obter_detalhes_com_cache — um dict zerado seria cacheado por engano',
        obtido=f'{resultado!r}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# _obter_detalhes_com_cache
# ---------------------------------------------------------------------

def test_obter_detalhes_com_cache_ja_preenchido_nao_bate_no_drive(tabela_resultados):
    # Setup: item já tem os 3 campos de cache — servico é um sentinela sem
    # nenhum método, pra provar que _obter_detalhes_arquivo nem é chamado
    # (se fosse, o teste quebraria com AttributeError, não com assert).
    item = {
        'id': 'FILE_1', 'name': 'Simples_Base.mp4',
        'link_visualizacao': 'https://drive.example/ja-cacheado', 'tamanho_bytes': 500, 'duracao_segundos': 12.0,
    }
    servico_sentinela = object()

    # Exercise:
    detalhes, novo = _obter_detalhes_com_cache(servico_sentinela, item)

    # Assert:
    passou = (
        detalhes == {'link_visualizacao': 'https://drive.example/ja-cacheado', 'tamanho_bytes': 500, 'duracao_segundos': 12.0}
        and novo is False
    )
    registrar_resultado(
        tabela_resultados, teste='Item já com os 3 campos de cache → devolve eles mesmos, novo=False, Drive nunca chamado',
        entrada='item já com link_visualizacao/tamanho_bytes/duracao_segundos preenchidos',
        esperado='detalhes == os 3 campos do item, novo=False',
        motivo='servico é um sentinela sem métodos — se _obter_detalhes_arquivo fosse chamado, o teste quebraria com AttributeError',
        obtido=f'detalhes={detalhes}, novo={novo}',
        passou=passou,
    )
    assert passou


def test_obter_detalhes_com_cache_vazio_com_sucesso_muta_o_item(tabela_resultados):
    # Setup:
    item = {'id': 'FILE_2', 'name': 'Simples_Base.mp4'}
    servico = _ServicoDriveFalso(resultado={
        'webViewLink': 'https://drive.example/view/novo', 'size': '3000', 'videoMediaMetadata': {'durationMillis': '4000'},
    })

    # Exercise:
    detalhes, novo = _obter_detalhes_com_cache(servico, item)

    # Assert:
    esperado_detalhes = {'link_visualizacao': 'https://drive.example/view/novo', 'tamanho_bytes': 3000, 'duracao_segundos': 4.0}
    passou = (
        detalhes == esperado_detalhes and novo is True
        and item['link_visualizacao'] == esperado_detalhes['link_visualizacao']
        and item['tamanho_bytes'] == esperado_detalhes['tamanho_bytes']
        and item['duracao_segundos'] == esperado_detalhes['duracao_segundos']
    )
    registrar_resultado(
        tabela_resultados, teste='Item sem cache + Drive responde com sucesso → busca, MUTA o item in-place, novo=True',
        entrada='item sem os 3 campos de cache',
        esperado='detalhes == valores buscados, novo=True, item mutado com os mesmos valores',
        motivo='item.update(detalhes) precisa mudar o MESMO dict (não uma cópia) — é esse dict que está dentro de arquivos_videos/arquivos_usados do snapshot',
        obtido=f'detalhes={detalhes}, novo={novo}, item={item}',
        passou=passou,
    )
    assert passou


def test_obter_detalhes_com_cache_vazio_com_falha_nao_muta_o_item(tabela_resultados):
    # Setup:
    item = {'id': 'FILE_3', 'name': 'Simples_Base.mp4'}
    servico = _ServicoDriveFalso(excecao=ConnectionError('Falha simulada de rede com o Drive'))

    # Exercise:
    detalhes, novo = _obter_detalhes_com_cache(servico, item)

    # Assert:
    passou = (
        detalhes == {'link_visualizacao': '', 'tamanho_bytes': 0, 'duracao_segundos': 0}
        and novo is False
        and 'link_visualizacao' not in item and 'tamanho_bytes' not in item and 'duracao_segundos' not in item
    )
    registrar_resultado(
        tabela_resultados, teste='Item sem cache + Drive falha → devolve zerado, novo=False, item NÃO é mutado',
        entrada='_obter_detalhes_arquivo devolvendo None (erro simulado)',
        esperado='detalhes zerado, novo=False, item continua sem os campos de cache',
        motivo='Não mutar o item é o que garante nova tentativa no próximo open — se mutasse com zeros, ficaria "cacheado" errado pra sempre',
        obtido=f'detalhes={detalhes}, novo={novo}, item={item}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# _formatar_tamanho_arquivo
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    'tamanho_bytes, esperado',
    [
        (0, '0 KB'),
        (None, '0 KB'),
        (500, '1 KB'),
        (2048, '2 KB'),
        (1048576, '1.0 MB'),
        (5242880, '5.0 MB'),
    ],
    ids=[
        'zero_bytes', 'none_vira_zero', 'menos_de_1kb_arredonda_pra_1', 'exato_2kb',
        'exato_1mb', 'exato_5mb',
    ],
)
def test_formatar_tamanho_arquivo(tamanho_bytes, esperado, tabela_resultados):
    # Setup: nada a montar — vem pronto do parametrize.

    # Exercise:
    resultado = _formatar_tamanho_arquivo(tamanho_bytes)

    # Assert:
    passou = resultado == esperado
    registrar_resultado(
        tabela_resultados, teste=f'_formatar_tamanho_arquivo({tamanho_bytes})',
        entrada=f'{tamanho_bytes}', esperado=esperado,
        motivo='Abaixo de 1KB nunca mostra "0 KB" pra arquivo que existe — arredonda pra cima, mínimo 1 KB',
        obtido=resultado,
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# _formatar_duracao
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    'duracao_segundos, esperado',
    [
        (0, '0:00'),
        (5, '0:05'),
        (65, '1:05'),
        (125, '2:05'),
        (3661, '61:01'),
    ],
    ids=['zero', 'so_segundos', 'passa_de_1_minuto', 'dois_minutos_e_pouco', 'mais_de_1_hora_vira_minutos_grandes'],
)
def test_formatar_duracao(duracao_segundos, esperado, tabela_resultados):
    # Setup: nada a montar — vem pronto do parametrize.

    # Exercise:
    resultado = _formatar_duracao(duracao_segundos)

    # Assert:
    passou = resultado == esperado
    registrar_resultado(
        tabela_resultados, teste=f'_formatar_duracao({duracao_segundos})',
        entrada=f'{duracao_segundos}', esperado=esperado,
        motivo='Sem componente de hora separado — vídeo de +1h mostra minutos de 2 dígitos ou mais, não HH:MM',
        obtido=resultado,
        passou=passou,
    )
    assert passou