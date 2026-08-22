# agenda_videos/tests/test_nivel_4__views_portal_drive_midia.py

# Função Objetivo: Testa view_portal_drive_video() e
# view_portal_drive_thumbnail() — Nível 4 (view HTTP real). São proxies
# puros pro Google Drive (streaming de vídeo via requests, thumbnail via
# googleapiclient) — nenhuma chamada de rede de verdade acontece aqui,
# tudo substituído por fakes. Nenhuma destas 2 views toca banco, por isso
# este arquivo não precisa de pytest.mark.django_db.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

import agenda_videos.views as views_module
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 4 — view_portal_drive_video()/view_portal_drive_thumbnail(): proxy de mídia do Drive'


def _url_video(file_id):
    return reverse('agenda_videos_portal_drive_video', args=[file_id])


def _url_thumbnail(file_id):
    return reverse('agenda_videos_portal_drive_thumbnail', args=[file_id])


class _RespostaRequestsFalsa:
    def __init__(self, status_code, headers=None, content=b'', pedacos=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self._pedacos = pedacos if pedacos is not None else [content]

    def iter_content(self, chunk_size=None):
        return iter(self._pedacos)


class _CredenciaisFalsas:
    token = 'TOKEN-FALSO-DE-TESTE'


# ---------------------------------------------------------------------
# view_portal_drive_video
# ---------------------------------------------------------------------

def test_video_stream_com_sucesso_devolve_streaming_response_com_cabecalhos(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'obter_credenciais_drive_escrita', lambda: _CredenciaisFalsas())
    resposta_falsa = _RespostaRequestsFalsa(
        status_code=200,
        headers={'Content-Type': 'video/mp4', 'Content-Length': '1024'},
        pedacos=[b'parte1', b'parte2'],
    )
    monkeypatch.setattr(views_module.requests, 'get', lambda *args, **kwargs: resposta_falsa)

    # Exercise:
    resposta = client.get(_url_video('FILE_VIDEO_1'))

    # Assert:
    conteudo = b''.join(resposta.streaming_content)
    passou = (
        resposta.status_code == 200 and conteudo == b'parte1parte2'
        and resposta['Content-Type'] == 'video/mp4' and resposta['Content-Length'] == '1024'
        and resposta['Accept-Ranges'] == 'bytes'
    )
    registrar_resultado(
        tabela_resultados, teste='Drive responde 200 com vídeo → StreamingHttpResponse repassa conteúdo e cabeçalhos',
        entrada='resposta fake do Drive: status=200, Content-Type=video/mp4, Content-Length=1024, 2 pedaços de bytes',
        esperado="status 200, conteúdo == b'parte1parte2', Content-Type/Content-Length repassados, Accept-Ranges=bytes",
        motivo='O navegador precisa desses cabeçalhos pra permitir seek/scrubbing no player de vídeo',
        obtido=f'status={resposta.status_code}, conteudo={conteudo!r}, content_type={resposta.get("Content-Type")}, content_length={resposta.get("Content-Length")}, accept_ranges={resposta.get("Accept-Ranges")}',
        passou=passou,
    )
    assert passou


def test_video_repassa_o_cabecalho_range_da_requisicao_pro_drive(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'obter_credenciais_drive_escrita', lambda: _CredenciaisFalsas())
    chamadas = []

    def _get_falso(url, params=None, headers=None, stream=None):
        chamadas.append({'url': url, 'headers': headers})
        return _RespostaRequestsFalsa(status_code=206, headers={'Content-Type': 'video/mp4'}, content=b'trecho')
    monkeypatch.setattr(views_module.requests, 'get', _get_falso)

    # Exercise:
    resposta = client.get(_url_video('FILE_VIDEO_2'), HTTP_RANGE='bytes=100-200')

    # Assert:
    passou = (
        resposta.status_code == 206
        and len(chamadas) == 1 and chamadas[0]['headers'].get('Range') == 'bytes=100-200'
        and chamadas[0]['headers'].get('Authorization') == 'Bearer TOKEN-FALSO-DE-TESTE'
    )
    registrar_resultado(
        tabela_resultados, teste='Requisição do navegador com cabeçalho Range → repassado pro Drive junto com o Bearer token',
        entrada='HTTP_RANGE=bytes=100-200',
        esperado="chamada ao Drive com headers Range='bytes=100-200' e Authorization='Bearer TOKEN-FALSO-DE-TESTE'",
        motivo='É esse repasse que permite ao usuário pular pra qualquer ponto do vídeo (scrubbing), não só tocar do início',
        obtido=f'status={resposta.status_code}, chamadas={chamadas}',
        passou=passou,
    )
    assert passou


def test_video_nao_encontrado_no_drive_devolve_404(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'obter_credenciais_drive_escrita', lambda: _CredenciaisFalsas())
    monkeypatch.setattr(views_module.requests, 'get', lambda *args, **kwargs: _RespostaRequestsFalsa(status_code=404))

    # Exercise:
    resposta = client.get(_url_video('FILE_INEXISTENTE'))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='Drive devolve status fora de (200, 206) → HttpResponseNotFound, sem tentar montar streaming',
        entrada='resposta fake do Drive: status=404', esperado='status_code == 404',
        motivo='Arquivo pode ter sido excluído/sem permissão desde a última sincronização — precisa de 404 claro, não um stream vazio',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_portal_drive_thumbnail
# ---------------------------------------------------------------------

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


def test_thumbnail_com_sucesso_devolve_a_imagem(client, tabela_resultados, monkeypatch):
    # Setup:
    servico_falso = _ServicoDriveFalso(resultado={'thumbnailLink': 'https://drive.example/thumb.jpg'})
    monkeypatch.setattr(views_module, 'obter_servico_drive', lambda: servico_falso)
    monkeypatch.setattr(
        views_module.requests, 'get',
        lambda url, stream=None: _RespostaRequestsFalsa(status_code=200, headers={'Content-Type': 'image/jpeg'}, content=b'BYTES_DA_IMAGEM'),
    )

    # Exercise:
    resposta = client.get(_url_thumbnail('FILE_THUMB_1'))

    # Assert:
    passou = resposta.status_code == 200 and resposta.content == b'BYTES_DA_IMAGEM' and resposta['Content-Type'] == 'image/jpeg'
    registrar_resultado(
        tabela_resultados, teste='Drive tem thumbnailLink e a imagem baixa com sucesso → devolve a imagem com o Content-Type certo',
        entrada="metadados={'thumbnailLink': 'https://drive.example/thumb.jpg'}, download com status 200",
        esperado="status 200, content == b'BYTES_DA_IMAGEM', Content-Type=image/jpeg",
        motivo='2 passos: 1º pega o link no Drive, 2º baixa a imagem de fato — os 2 precisam dar certo',
        obtido=f'status={resposta.status_code}, content={resposta.content!r}, content_type={resposta.get("Content-Type")}',
        passou=passou,
    )
    assert passou


def test_thumbnail_sem_thumbnail_link_devolve_404(client, tabela_resultados, monkeypatch):
    # Setup:
    servico_falso = _ServicoDriveFalso(resultado={})
    monkeypatch.setattr(views_module, 'obter_servico_drive', lambda: servico_falso)

    # Exercise:
    resposta = client.get(_url_thumbnail('FILE_THUMB_2'))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='Metadados sem "thumbnailLink" (Drive ainda não gerou miniatura) → 404',
        entrada='metadados={} (sem a chave thumbnailLink)', esperado='status_code == 404',
        motivo='Arquivo recém-enviado pode não ter miniatura gerada ainda pelo Drive',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_thumbnail_erro_ao_consultar_metadados_no_drive_devolve_404(client, tabela_resultados, monkeypatch):
    # Setup:
    servico_falso = _ServicoDriveFalso(excecao=ConnectionError('Falha simulada de rede com o Drive'))
    monkeypatch.setattr(views_module, 'obter_servico_drive', lambda: servico_falso)

    # Exercise:
    resposta = client.get(_url_thumbnail('FILE_THUMB_3'))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='Exceção ao consultar metadados no Drive (arquivo excluído, sem permissão, rede fora) → 404, nunca 500',
        entrada='servico.files().get(...).execute() lançando ConnectionError', esperado='status_code == 404',
        motivo='try/except genérico de propósito — qualquer falha aqui vira 404, nunca erro de servidor',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_thumbnail_falha_ao_baixar_a_imagem_devolve_404(client, tabela_resultados, monkeypatch):
    # Setup:
    servico_falso = _ServicoDriveFalso(resultado={'thumbnailLink': 'https://drive.example/thumb.jpg'})
    monkeypatch.setattr(views_module, 'obter_servico_drive', lambda: servico_falso)
    monkeypatch.setattr(views_module.requests, 'get', lambda url, stream=None: _RespostaRequestsFalsa(status_code=500))

    # Exercise:
    resposta = client.get(_url_thumbnail('FILE_THUMB_4'))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='Link de thumbnail existe, mas o download da imagem falha (status != 200) → 404',
        entrada='thumbnailLink válido, download respondendo status=500', esperado='status_code == 404',
        motivo='Ter o link não garante que o download funcione — precisa checar o status da 2ª chamada também',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou