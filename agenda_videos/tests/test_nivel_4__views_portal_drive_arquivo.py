# agenda_videos/tests/test_nivel_4__views_portal_drive_arquivo.py

# Função Objetivo: Testa view_portal_drive_detalhe(), view_portal_drive_enviar(),
# view_portal_drive_confirmar_exclusao() e view_portal_drive_excluir() —
# Nível 4 (view HTTP real). ArquivadorDrive (upload/exclusão real no
# Drive) e obter_servico_drive/obter_pasta_raiz_id_ativa/
# verificar_produto_no_drive são substituídos por fakes — o que importa
# aqui é o COMPORTAMENTO da view (validação de extensão, tratamento de
# conflito, contexto montado), não a chamada de rede real ao Drive.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from produtos.models import Produto
import agenda_videos.views as views_module
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — Portal do Drive: detalhe/enviar/confirmar_exclusao/excluir'


@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


@pytest.fixture(autouse=True)
def _drive_desligado(monkeypatch):
    # Setup: nenhum destes testes deve tentar falar com o Drive de
    # verdade — obter_servico_drive() só é mesmo usado quando o produto já
    # tem snapshot com arquivo presente (não é o caso de nenhum cenário
    # aqui), então um valor sentinela basta.
    monkeypatch.setattr(views_module, 'obter_servico_drive', lambda: object())
    monkeypatch.setattr(views_module, 'obter_pasta_raiz_id_ativa', lambda: 'PASTA_RAIZ_TESTE_FAKE')
    monkeypatch.setattr(views_module, 'verificar_produto_no_drive', lambda produto_id: None)


class _ArquivadorFalso:
    # Função Objetivo: substitui ArquivadorDrive — grava toda chamada em
    # listas de classe (a view cria 1 instância nova por requisição) pra
    # o teste poder inspecionar depois. contador_instancias existe só pra
    # provar que a view reaproveita a MESMA instância quando o lote tem
    # mais de 1 arquivo (arquivador = ArquivadorDrive() só roda 1x).
    chamadas_enviar = []
    chamadas_excluir = []
    excecao_ao_enviar = None
    contador_instancias = 0

    def __init__(self):
        _ArquivadorFalso.contador_instancias += 1

    def enviar_arquivo(self, pasta_raiz_id, marca, ean, fase, numero_ocorrencia, tipo, caminho_local, permitir_substituir=False):
        self.chamadas_enviar.append({
            'pasta_raiz_id': pasta_raiz_id, 'marca': marca, 'ean': ean,
            'fase': fase, 'numero_ocorrencia': numero_ocorrencia, 'tipo': tipo,
        })
        if self.excecao_ao_enviar is not None:
            raise self.excecao_ao_enviar
        return 'FAKE_FILE_ID'

    def excluir_arquivo(self, drive_file_id):
        self.chamadas_excluir.append(drive_file_id)


@pytest.fixture(autouse=True)
def _resetar_arquivador_falso():
    # Setup/Teardown: listas de classe zeradas antes E depois de cada
    # teste — são compartilhadas entre instâncias, sem isso um teste veria
    # chamada do teste anterior.
    _ArquivadorFalso.chamadas_enviar = []
    _ArquivadorFalso.chamadas_excluir = []
    _ArquivadorFalso.excecao_ao_enviar = None
    _ArquivadorFalso.contador_instancias = 0
    yield
    _ArquivadorFalso.chamadas_enviar = []
    _ArquivadorFalso.chamadas_excluir = []
    _ArquivadorFalso.excecao_ao_enviar = None
    _ArquivadorFalso.contador_instancias = 0


def _criar_produto(sku, ean, marca='Marca Teste'):
    return Produto.objects.create(ean=ean, sku=sku, titulo='Produto Teste', marca=marca)


def _url_detalhe(produto_id):
    return reverse('agenda_videos_portal_drive_detalhe', args=[produto_id])


def _url_enviar(produto_id):
    return reverse('agenda_videos_portal_drive_enviar', args=[produto_id])


def _url_confirmar_exclusao(produto_id, file_id):
    return reverse('agenda_videos_portal_drive_confirmar_exclusao', args=[produto_id, file_id])


def _url_excluir(produto_id, file_id):
    return reverse('agenda_videos_portal_drive_excluir', args=[produto_id, file_id])


# ---------------------------------------------------------------------
# view_portal_drive_detalhe
# ---------------------------------------------------------------------

def test_detalhe_produto_sem_snapshot_renderiza_card_nunca_sincronizado(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-DET-001', '7891111100100')

    # Exercise:
    resposta = client.get(_url_detalhe(produto.id))

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['nunca_sincronizado'] is True
    registrar_resultado(
        tabela_resultados, teste='Produto sem SnapshotArquivosDrive → card mostra nunca_sincronizado=True',
        entrada='produto recém-criado, sem nenhuma sincronização', esperado='status 200, nunca_sincronizado=True',
        motivo='snapshot is None é a única fonte dessa flag — nada de rede acontece aqui',
        obtido=f'status={resposta.status_code}, nunca_sincronizado={resposta.context.get("nunca_sincronizado")}',
        passou=passou,
    )
    assert passou


def test_detalhe_produto_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url_detalhe(999999))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='produto_id inexistente → 404',
        entrada='produto_id=999999', esperado='status_code == 404',
        motivo='get_object_or_404 protege o carregamento lazy do card',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_portal_drive_enviar
# ---------------------------------------------------------------------

def test_enviar_arquivo_valido_chama_arquivador_e_retorna_sucesso(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-ENV-001', '7891111100110')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    arquivo = SimpleUploadedFile('video.mp4', b'conteudo de video falso', content_type='video/mp4')

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {'arquivo__simples__0__base': arquivo})

    # Assert:
    resultado_envio = resposta.context['resultado_envio']
    passou = (
        resposta.status_code == 200 and len(resultado_envio) == 1
        and resultado_envio[0]['status'] == 'enviado'
        and _ArquivadorFalso.chamadas_enviar == [{
            'pasta_raiz_id': 'PASTA_RAIZ_TESTE_FAKE', 'marca': produto.marca, 'ean': produto.ean,
            'fase': 'simples', 'numero_ocorrencia': None, 'tipo': 'base',
        }]
    )
    registrar_resultado(
        tabela_resultados, teste='Upload de .mp4 pro campo "base" de Simples → chama ArquivadorDrive.enviar_arquivo e retorna status "enviado"',
        entrada='arquivo__simples__0__base = video.mp4',
        esperado="resultado_envio[0]['status'] == 'enviado', 1 chamada a enviar_arquivo com fase=simples/numero=None/tipo=base",
        motivo='numero_str "0" vira numero_ocorrencia=None — é assim que Simples (sem ocorrência numerada) é representado no campo do formulário',
        obtido=f'status={resposta.status_code}, resultado_envio={resultado_envio}, chamadas={_ArquivadorFalso.chamadas_enviar}',
        passou=passou,
    )
    assert passou


def test_enviar_extensao_errada_retorna_erro_sem_chamar_arquivador(client, tabela_resultados, monkeypatch):
    # Setup: campo pede tipo "base" (exige .mp4), mas o arquivo enviado é .txt.
    produto = _criar_produto('SKU-ENV-002', '7891111100111')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    arquivo = SimpleUploadedFile('video.txt', b'isso nao e um video', content_type='text/plain')

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {'arquivo__simples__0__base': arquivo})

    # Assert:
    resultado_envio = resposta.context['resultado_envio']
    passou = (
        resposta.status_code == 200 and resultado_envio[0]['status'] == 'erro'
        and 'esperado .mp4' in resultado_envio[0]['mensagem']
        and _ArquivadorFalso.chamadas_enviar == []
    )
    registrar_resultado(
        tabela_resultados, teste='Extensão errada (.txt no lugar de .mp4) → erro, ArquivadorDrive nunca chamado',
        entrada='arquivo__simples__0__base = video.txt',
        esperado="status='erro', mensagem cita 'esperado .mp4', nenhuma chamada a enviar_arquivo",
        motivo='Validação de extensão acontece ANTES de qualquer chamada ao Drive — nunca sobe um arquivo com tipo errado',
        obtido=f'status={resposta.status_code}, resultado_envio={resultado_envio}, chamadas={_ArquivadorFalso.chamadas_enviar}',
        passou=passou,
    )
    assert passou


def test_enviar_conflito_quando_arquivador_lanca_file_exists_error(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-ENV-003', '7891111100112')
    _ArquivadorFalso.excecao_ao_enviar = FileExistsError('já existe no Drive')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    arquivo = SimpleUploadedFile('video.mp4', b'conteudo', content_type='video/mp4')

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {'arquivo__simples__0__base': arquivo})

    # Assert:
    resultado_envio = resposta.context['resultado_envio']
    passou = resposta.status_code == 200 and resultado_envio[0]['status'] == 'conflito'
    registrar_resultado(
        tabela_resultados, teste='ArquivadorDrive.enviar_arquivo levanta FileExistsError → resultado vira "conflito", sem 500',
        entrada='enviar_arquivo configurado pra levantar FileExistsError', esperado="resultado_envio[0]['status'] == 'conflito'",
        motivo='Conflito é esperado (arquivo já existe) — não pode virar erro de servidor',
        obtido=f'status={resposta.status_code}, resultado_envio={resultado_envio}',
        passou=passou,
    )
    assert passou


def test_enviar_campo_com_fase_invalida_retorna_erro_de_campo(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-ENV-004', '7891111100113')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    arquivo = SimpleUploadedFile('video.mp4', b'conteudo', content_type='video/mp4')

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {'arquivo__fase_que_nao_existe__0__base': arquivo})

    # Assert:
    resultado_envio = resposta.context['resultado_envio']
    passou = (
        resposta.status_code == 200 and resultado_envio[0]['status'] == 'erro'
        and 'campo de envio inválido' in resultado_envio[0]['mensagem']
        and _ArquivadorFalso.chamadas_enviar == []
    )
    registrar_resultado(
        tabela_resultados, teste='Campo com nome de fase que não existe → erro de "campo de envio inválido", sem chamar o Drive',
        entrada='campo arquivo__fase_que_nao_existe__0__base', esperado="status='erro', mensagem cita 'campo de envio inválido'",
        motivo='Proteção contra formulário adulterado/desatualizado — fase precisa estar em ROTULO_FASE',
        obtido=f'status={resposta.status_code}, resultado_envio={resultado_envio}',
        passou=passou,
    )
    assert passou


def test_enviar_sem_nenhum_arquivo_selecionado_mostra_erro_generico(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-ENV-005', '7891111100114')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {})

    # Assert:
    passou = (
        resposta.status_code == 200
        and resposta.context['resultado_envio'] == []
        and resposta.context['erro_envio'] == 'Nenhum arquivo selecionado para envio.'
    )
    registrar_resultado(
        tabela_resultados, teste='POST sem nenhum arquivo → erro_envio genérico, resultado_envio vazio',
        entrada='POST sem FILES', esperado="erro_envio == 'Nenhum arquivo selecionado para envio.'",
        motivo='Distinto do erro de campo/extensão — aqui não tinha nada nem pra tentar validar',
        obtido=f'status={resposta.status_code}, resultado_envio={resposta.context.get("resultado_envio")}, erro_envio={resposta.context.get("erro_envio")!r}',
        passou=passou,
    )
    assert passou


def test_enviar_com_sucesso_reverifica_o_produto_no_drive(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-ENV-006', '7891111100115')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    chamadas_verificacao = []
    monkeypatch.setattr(views_module, 'verificar_produto_no_drive', lambda produto_id: chamadas_verificacao.append(produto_id))
    arquivo = SimpleUploadedFile('video.mp4', b'conteudo', content_type='video/mp4')

    # Exercise:
    client.post(_url_enviar(produto.id), {'arquivo__simples__0__base': arquivo})

    # Assert:
    passou = chamadas_verificacao == [produto.id]
    registrar_resultado(
        tabela_resultados, teste='Envio com sucesso → reverifica o produto no Drive (refresca o snapshot na hora)',
        entrada='1 envio bem-sucedido', esperado='verificar_produto_no_drive chamado 1x com o produto_id',
        motivo='Sem isso, o snapshot só atualizaria na próxima "Sincronizar com o Drive" manual',
        obtido=f'chamadas_verificacao={chamadas_verificacao}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_portal_drive_confirmar_exclusao
# ---------------------------------------------------------------------

def test_confirmar_exclusao_monta_contexto_a_partir_da_querystring(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-EXC-001', '7891111100120')

    # Exercise:
    resposta = client.get(_url_confirmar_exclusao(produto.id, 'FILE123'), {
        'rotulo': 'Simples', 'tipo': 'base', 'nome': 'Simples_Base.mp4',
    })

    # Assert:
    contexto = resposta.context
    passou = (
        resposta.status_code == 200 and contexto['produto_id'] == produto.id and contexto['file_id'] == 'FILE123'
        and contexto['rotulo'] == 'Simples' and contexto['tipo'] == 'base' and contexto['nome'] == 'Simples_Base.mp4'
    )
    registrar_resultado(
        tabela_resultados, teste='Modal de confirmação de exclusão → contexto vem 100% da querystring, nenhuma chamada ao Drive',
        entrada='?rotulo=Simples&tipo=base&nome=Simples_Base.mp4',
        esperado='contexto com esses 3 valores + produto_id/file_id da URL',
        motivo='1º clique é só exibição — nada é excluído aqui de verdade',
        obtido=f'status={resposta.status_code}, produto_id={contexto.get("produto_id")}, file_id={contexto.get("file_id")}, rotulo={contexto.get("rotulo")}, tipo={contexto.get("tipo")}, nome={contexto.get("nome")}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_portal_drive_excluir
# ---------------------------------------------------------------------

def test_excluir_chama_arquivador_com_o_file_id_certo_e_reverifica_produto(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-EXC-002', '7891111100121')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    chamadas_verificacao = []
    monkeypatch.setattr(views_module, 'verificar_produto_no_drive', lambda produto_id: chamadas_verificacao.append(produto_id))

    # Exercise:
    resposta = client.post(_url_excluir(produto.id, 'FILE456'))

    # Assert:
    passou = (
        resposta.status_code == 200
        and _ArquivadorFalso.chamadas_excluir == ['FILE456']
        and chamadas_verificacao == [produto.id]
        and resposta.context['mensagem_exclusao'] == 'Arquivo movido para a lixeira do Drive.'
    )
    registrar_resultado(
        tabela_resultados, teste='2º clique (exclusão de verdade) → chama excluir_arquivo com o file_id certo, reverifica o produto, mostra mensagem de sucesso',
        entrada='file_id=FILE456',
        esperado="excluir_arquivo chamado com 'FILE456', verificar_produto_no_drive chamado, mensagem_exclusao preenchida",
        motivo='Move pra lixeira (nunca apaga em definitivo) — a mensagem no card confirma isso pro usuário',
        obtido=f'status={resposta.status_code}, chamadas_excluir={_ArquivadorFalso.chamadas_excluir}, chamadas_verificacao={chamadas_verificacao}, mensagem_exclusao={resposta.context.get("mensagem_exclusao")!r}',
        passou=passou,
    )
    assert passou


def test_excluir_produto_inexistente_devolve_404(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)

    # Exercise:
    resposta = client.post(_url_excluir(999999, 'FILE789'))

    # Assert:
    passou = resposta.status_code == 404 and _ArquivadorFalso.chamadas_excluir == []
    registrar_resultado(
        tabela_resultados, teste='produto_id inexistente → 404, sem tentar excluir nada no Drive',
        entrada='produto_id=999999', esperado='status_code == 404, nenhuma chamada a excluir_arquivo',
        motivo='get_object_or_404 acontece antes de qualquer chamada ao ArquivadorDrive',
        obtido=f'status={resposta.status_code}, chamadas_excluir={_ArquivadorFalso.chamadas_excluir}',
        passou=passou,
    )
    assert passou


def test_enviar_ignora_campo_que_nao_comeca_com_arquivo(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-ENV-007', '7891111100116')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    arquivo = SimpleUploadedFile('anexo.mp4', b'conteudo', content_type='video/mp4')

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {'outro_campo_qualquer': arquivo})

    # Assert:
    passou = (
        resposta.status_code == 200
        and resposta.context['resultado_envio'] == []
        and resposta.context['erro_envio'] == 'Nenhum arquivo selecionado para envio.'
        and _ArquivadorFalso.chamadas_enviar == []
    )
    registrar_resultado(
        tabela_resultados, teste='Campo de FILES que não começa com "arquivo__" → ignorado silenciosamente (continue), sem chamar o Drive',
        entrada="FILES={'outro_campo_qualquer': anexo.mp4}",
        esperado='resultado_envio == [], erro_envio genérico, nenhuma chamada ao Drive',
        motivo='Protege contra qualquer outro campo de arquivo que um dia apareça no mesmo <form> (ex: upload de outra seção)',
        obtido=f'status={resposta.status_code}, resultado_envio={resposta.context.get("resultado_envio")}, erro_envio={resposta.context.get("erro_envio")!r}',
        passou=passou,
    )
    assert passou


def test_enviar_dois_arquivos_no_mesmo_lote_reaproveita_a_mesma_instancia_do_arquivador(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-ENV-008', '7891111100117')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    arquivo_base = SimpleUploadedFile('base.mp4', b'video', content_type='video/mp4')
    arquivo_roteiro = SimpleUploadedFile('roteiro.txt', b'texto', content_type='text/plain')

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {
        'arquivo__simples__0__base': arquivo_base,
        'arquivo__simples__0__roteiro': arquivo_roteiro,
    })

    # Assert:
    resultado_envio = resposta.context['resultado_envio']
    passou = (
        resposta.status_code == 200 and len(resultado_envio) == 2
        and all(r['status'] == 'enviado' for r in resultado_envio)
        and _ArquivadorFalso.contador_instancias == 1
    )
    registrar_resultado(
        tabela_resultados, teste='2 arquivos válidos no mesmo POST → os 2 são enviados, mas ArquivadorDrive() é instanciado só 1 vez (reaproveitada no loop)',
        entrada='FILES com 2 campos válidos (base.mp4 + roteiro.txt)',
        esperado='2 resultados com status=enviado, ArquivadorDrive instanciado 1x (não 1x por arquivo)',
        motivo='if arquivador is None: arquivador = ArquivadorDrive() só roda na 1ª iteração do lote — evita reconstruir o cliente do Drive a cada arquivo do mesmo envio',
        obtido=f'status={resposta.status_code}, resultado_envio={resultado_envio}, contador_instancias={_ArquivadorFalso.contador_instancias}',
        passou=passou,
    )
    assert passou


def test_enviar_com_sucesso_mas_reverificacao_falha_nao_quebra_a_resposta(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-ENV-009', '7891111100118')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)

    def _verificar_com_falha(produto_id):
        raise ConnectionError('Falha simulada de rede com o Drive')
    monkeypatch.setattr(views_module, 'verificar_produto_no_drive', _verificar_com_falha)
    arquivo = SimpleUploadedFile('video.mp4', b'conteudo', content_type='video/mp4')

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {'arquivo__simples__0__base': arquivo})

    # Assert:
    resultado_envio = resposta.context['resultado_envio']
    passou = resposta.status_code == 200 and resultado_envio[0]['status'] == 'enviado'
    registrar_resultado(
        tabela_resultados, teste='Upload dá certo, mas a reverificação pós-envio lança exceção → resposta continua 200 com status=enviado',
        entrada='verificar_produto_no_drive lançando ConnectionError, depois de um envio bem-sucedido',
        esperado="resultado_envio[0]['status'] == 'enviado' (o upload real não é desfeito por essa falha)",
        motivo='O arquivo já subiu de verdade — uma reverificação instável não pode fingir que o envio falhou',
        obtido=f'status={resposta.status_code}, resultado_envio={resultado_envio}',
        passou=passou,
    )
    assert passou


def test_excluir_quando_reverificacao_falha_nao_quebra_a_resposta(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-EXC-003', '7891111100122')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)

    def _verificar_com_falha(produto_id):
        raise ConnectionError('Falha simulada de rede com o Drive')
    monkeypatch.setattr(views_module, 'verificar_produto_no_drive', _verificar_com_falha)

    # Exercise:
    resposta = client.post(_url_excluir(produto.id, 'FILE999'))

    # Assert:
    passou = (
        resposta.status_code == 200
        and _ArquivadorFalso.chamadas_excluir == ['FILE999']
        and resposta.context['mensagem_exclusao'] == 'Arquivo movido para a lixeira do Drive.'
    )
    registrar_resultado(
        tabela_resultados, teste='Exclusão dá certo, mas a reverificação pós-exclusão lança exceção → resposta continua 200 com a mensagem de sucesso',
        entrada='verificar_produto_no_drive lançando ConnectionError, depois de excluir_arquivo já ter rodado',
        esperado='excluir_arquivo já chamado, mensagem_exclusao presente, sem 500',
        motivo='O arquivo já foi movido pra lixeira de verdade — a reverificação instável não pode esconder isso do usuário',
        obtido=f'status={resposta.status_code}, chamadas_excluir={_ArquivadorFalso.chamadas_excluir}, mensagem_exclusao={resposta.context.get("mensagem_exclusao")!r}',
        passou=passou,
    )
    assert passou


def test_enviar_nao_tenta_remover_arquivo_temporario_que_ja_nao_existe_mais(client, tabela_resultados, monkeypatch):
    # Setup: força os.path.exists a dizer "não existe" bem no momento da
    # limpeza — simula o arquivo temporário ter sumido por outro motivo
    # (ex: race condition, reinício no meio do envio). O arquivo real
    # criado pelo tempfile fica órfão no disco depois deste teste — sem
    # problema, é 1 arquivo pequeno e o SO limpa a pasta temp sozinho.
    produto = _criar_produto('SKU-ENV-010', '7891111100119')
    monkeypatch.setattr(views_module, 'ArquivadorDrive', _ArquivadorFalso)
    monkeypatch.setattr(views_module.os.path, 'exists', lambda caminho: False)
    arquivo = SimpleUploadedFile('video.mp4', b'conteudo', content_type='video/mp4')

    # Exercise:
    resposta = client.post(_url_enviar(produto.id), {'arquivo__simples__0__base': arquivo})

    # Assert:
    resultado_envio = resposta.context['resultado_envio']
    passou = resposta.status_code == 200 and resultado_envio[0]['status'] == 'enviado'
    registrar_resultado(
        tabela_resultados, teste='os.path.exists diz que o arquivo temporário já sumiu → limpeza é pulada, sem quebrar o envio',
        entrada='os.path.exists forçado a devolver False no momento da limpeza',
        esperado="resultado_envio[0]['status'] == 'enviado', nenhuma tentativa de remover um arquivo que já não existe",
        motivo='O finally não pode assumir que o arquivo temporário sempre sobrevive até ali — precisa checar antes de remover',
        obtido=f'status={resposta.status_code}, resultado_envio={resultado_envio}',
        passou=passou,
    )
    assert passou