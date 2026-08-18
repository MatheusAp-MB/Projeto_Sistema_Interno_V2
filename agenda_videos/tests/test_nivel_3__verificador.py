# agenda_videos/tests/test_nivel_3__verificador.py

# SUT: agenda_videos/funcoes_auxiliares/drive/verificador.py
#      (_avancar_etapas_com_estrutura, verificar_produto_no_drive)
# DOC: banco real (Produto, CicloVideo, IndicadoresAgendaProduto) — Nível 3.
#      Drive é SIMULADO aqui: LocalizadorArquivosProduto.localizar_arquivos
#      é mockado via monkeypatch, resto da cadeia (parser real, avanço real,
#      banco real) roda de verdade. A versão com Drive REAL fica no arquivo
#      de Nível 4.

import pytest
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import CicloVideo, Fase, IndicadoresAgendaProduto
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from agenda_videos.funcoes_auxiliares.drive.verificador import (
    DiagnosticoBloqueio, _avancar_etapas_com_estrutura, verificar_produto_no_drive,
)
from agenda_videos.funcoes_auxiliares.drive.parser import ArquivoDrive, ArquivosOcorrencia, ArquivosFase, ArquivosProdutoDrive
from agenda_videos.funcoes_auxiliares.drive.localizador import LocalizadorArquivosProduto
from testes_apoio.apoio_visual import registrar_resultado
from agenda_videos.models import SnapshotArquivosDrive
from agenda_videos.funcoes_auxiliares.drive import escaneador
from agenda_videos.funcoes_auxiliares.drive.verificador import verificar_todos_no_drive


# * [EXPLICAÇÃO] → Desde a migração pra 2 bancos, todo teste deste arquivo
#                  seta a empresa ativa como MAGAZINE (fixture abaixo) —
#                  isso faz o EmpresaRouter mandar toda query pro alias
#                  explícito 'magazine', em vez do genérico 'default'. O
#                  pytest-django só libera 'default' por padrão; sem
#                  declarar os outros aliases aqui, qualquer .objects.create()
#                  neste arquivo quebra com DatabaseOperationForbidden.
pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])


# * [EXPLICAÇÃO] → Achado real (18/08/2026): mesmo com o Drive mockado
#                  (localizar_arquivos/listar_arquivos_usados), o
#                  LocalizadorArquivosProduto() real ainda é construído por
#                  dentro de verificar_produto_no_drive/verificar_todos_no_drive
#                  — e agora isso exige saber a empresa ativa (a pasta raiz
#                  do Drive virou por empresa). Este arquivo roda função
#                  direto, sem requisição Django, então precisa fixar a
#                  empresa manualmente.
@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


def _estrutura_generica(fase_chave, numero, base=None, roteiro=None, completo=None):
    ocorrencia = ArquivosOcorrencia(numero=numero, base=base, roteiro=roteiro, completo=completo)
    ocorrencias_por_fase = {'simples': [], 'video_mensal': [], 'video_trimestral': []}
    ocorrencias_por_fase[fase_chave] = [ocorrencia]
    return ArquivosProdutoDrive(
        marca='Marca X', ean='123', pasta_encontrada=True, motivo_pasta_nao_encontrada=None,
        simples=ArquivosFase(fase='simples', ocorrencias=ocorrencias_por_fase['simples']),
        video_mensal=ArquivosFase(fase='video_mensal', ocorrencias=ocorrencias_por_fase['video_mensal']),
        video_trimestral=ArquivosFase(fase='video_trimestral', ocorrencias=ocorrencias_por_fase['video_trimestral']),
        arquivos_nao_reconhecidos=[],
    )


def test_nivel_3__avancar_etapas_produto_sem_ciclo_e_sem_base_no_drive_nao_cria_nada(tabela_resultados):
    # Função Objetivo: produto nunca tocado (sem CicloVideo) e o Drive ainda
    # não tem o arquivo Base — não cria ciclo nenhum, só devolve o
    # diagnóstico apontando o que falta. Regressão do Bug 2 (ver "Botao de
    # Verificar Drive Individual Tinha 3 Bugs Reais" no vault) — antes desta
    # correção, esse caso saía do loop em silêncio, sem diagnóstico nenhum.
    # Setup:
    produto = _criar_produto('SKU-101')
    estrutura_drive = _estrutura_generica('simples', 1)  # sem Base

    # Exercise:
    etapas_marcadas, diagnostico = _avancar_etapas_com_estrutura(produto.id, estrutura_drive)

    # Assert:
    passou = (
        etapas_marcadas == []
        and diagnostico == DiagnosticoBloqueio('base', 'Aguardando Base — "Simples_Base.mp4" não encontrado.')
        and not CicloVideo.objects.filter(produto=produto).exists()
        and not IndicadoresAgendaProduto.objects.filter(produto=produto).exists()
    )
    registrar_resultado(
        tabela_resultados, teste='_avancar_etapas_com_estrutura — produto sem ciclo, Drive sem Base',
        entrada='produto sem nenhum CicloVideo, Drive sem Simples_Base.mp4',
        esperado='([], DiagnosticoBloqueio("base", ...)), nenhum CicloVideo criado',
        motivo='Nunca cria ciclo travado sem arquivo — só avisa o que falta',
        obtido=f'etapas_marcadas={etapas_marcadas}, diagnostico={diagnostico}, ciclo_existe={CicloVideo.objects.filter(produto=produto).exists()}',
        passou=passou,
    )
    assert passou


def test_nivel_3__avancar_etapas_produto_sem_ciclo_cria_o_1o_ciclo_quando_base_esta_pronta(tabela_resultados):
    # Função Objetivo: produto nunca tocado (sem CicloVideo) e o Drive já tem
    # o arquivo Base pronto — cria o 1º CicloVideo sozinho (mesmo caminho de
    # CicloVideo.iniciar_agenda) e já avança Base, sem esperar clique manual.
    # Regressão do Bug 2 (ver "Botao de Verificar Drive Individual Tinha 3
    # Bugs Reais" no vault).
    # Setup:
    produto = _criar_produto('SKU-105')
    estrutura_drive = _estrutura_generica('simples', 1, base=ArquivoDrive('Simples_Base.mp4', 'id_base'))

    # Exercise:
    etapas_marcadas, diagnostico = _avancar_etapas_com_estrutura(produto.id, estrutura_drive)

    # Assert:
    ciclo = CicloVideo.objects.filter(produto=produto).first()
    esperado_diagnostico = DiagnosticoBloqueio('roteiro', 'Aguardando Roteiro — "Simples_Roteiro.txt" não encontrado.')
    passou = (
        etapas_marcadas == ['base']
        and diagnostico == esperado_diagnostico
        and ciclo is not None
        and ciclo.fase == Fase.SIMPLES and ciclo.numero_ocorrencia == 1
        and ciclo.base_concluido_em is not None
        and ciclo.roteiro_concluido_em is None
    )
    registrar_resultado(
        tabela_resultados, teste='_avancar_etapas_com_estrutura — cria o 1º ciclo quando Base está pronta',
        entrada='produto sem nenhum CicloVideo, Drive com Simples_Base.mp4',
        esperado=f"(['base'], {esperado_diagnostico}), CicloVideo criado com Base marcada",
        motivo='Sincronização deve fazer o papel do clique manual quando o Drive já comprova',
        obtido=f'etapas_marcadas={etapas_marcadas}, diagnostico={diagnostico}, ciclo_criado={ciclo is not None}, base_concluido_em={ciclo.base_concluido_em if ciclo else None}',
        passou=passou,
    )
    assert passou


def test_nivel_3__avancar_etapas_etapa_fora_do_escopo_nao_faz_nada(tabela_resultados):
    # Função Objetivo: ciclo já em "postar" (fora de ETAPAS_QUE_DEPENDEM_DE_ARQUIVO)
    # — quebra sem tocar no Drive nem no banco.
    # Setup:
    produto = _criar_produto('SKU-102')
    agora = timezone.now()
    ciclo = CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
    )
    estrutura_drive = _estrutura_generica('simples', 1)  # vazia de propósito — não deveria importar

    # Exercise:
    etapas_marcadas, diagnostico = _avancar_etapas_com_estrutura(produto.id, estrutura_drive)

    # Assert:
    ciclo.refresh_from_db()
    passou = (
        etapas_marcadas == [] and diagnostico is None
        and ciclo.base_concluido_em == agora
        and not IndicadoresAgendaProduto.objects.filter(produto=produto).exists()
    )
    registrar_resultado(
        tabela_resultados, teste='_avancar_etapas_com_estrutura — etapa fora do escopo (postar)',
        entrada='etapa_atual()=postar, estrutura do Drive vazia',
        esperado='([], None), timestamps intocados, sem cache criado',
        motivo='postar não depende de arquivo — loop quebra antes de olhar o Drive',
        obtido=f'etapas_marcadas={etapas_marcadas}, diagnostico={diagnostico}',
        passou=passou,
    )
    assert passou


def test_nivel_3__avancar_etapas_marca_uma_e_trava_na_proxima_que_falta(tabela_resultados):
    # Função Objetivo: Drive só tem Base — avança Base, trava em Roteiro com
    # diagnóstico preenchido.
    # Setup:
    produto = _criar_produto('SKU-103')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)  # etapa_atual() == 'base'
    estrutura_drive = _estrutura_generica('simples', 1, base=ArquivoDrive('Simples_Base.mp4', 'id_base'))

    # Exercise:
    etapas_marcadas, diagnostico = _avancar_etapas_com_estrutura(produto.id, estrutura_drive)

    # Assert:
    ciclo.refresh_from_db()
    esperado_diagnostico = DiagnosticoBloqueio('roteiro', 'Aguardando Roteiro — "Simples_Roteiro.txt" não encontrado.')
    passou = (
        etapas_marcadas == ['base']
        and diagnostico == esperado_diagnostico
        and ciclo.base_concluido_em is not None
        and ciclo.roteiro_concluido_em is None
    )
    registrar_resultado(
        tabela_resultados, teste='_avancar_etapas_com_estrutura — marca 1 e trava na próxima',
        entrada='Drive só tem Simples_Base.mp4',
        esperado=f"(['base'], {esperado_diagnostico})",
        motivo='Avança o que existe, trava exatamente no primeiro que falta',
        obtido=f'etapas_marcadas={etapas_marcadas}, diagnostico={diagnostico}, base_concluido_em={ciclo.base_concluido_em}, roteiro_concluido_em={ciclo.roteiro_concluido_em}',
        passou=passou,
    )
    assert passou


def test_nivel_3__avancar_etapas_avanca_base_roteiro_completo_em_sequencia(tabela_resultados):
    # Função Objetivo: Drive tem o trio completo — avança as 3 etapas numa
    # só chamada, sincroniza o cache no final pra etapa "postar".
    # Setup:
    produto = _criar_produto('SKU-104')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    estrutura_drive = _estrutura_generica(
        'simples', 1,
        base=ArquivoDrive('Simples_Base.mp4', 'id_base'),
        roteiro=ArquivoDrive('Simples_Roteiro.txt', 'id_roteiro'),
        completo=ArquivoDrive('Simples_Completo.mp4', 'id_completo'),
    )

    # Exercise:
    etapas_marcadas, diagnostico = _avancar_etapas_com_estrutura(produto.id, estrutura_drive)

    # Assert:
    ciclo.refresh_from_db()
    indicadores = IndicadoresAgendaProduto.objects.filter(produto=produto).first()
    passou = (
        etapas_marcadas == ['base', 'roteiro', 'completo']
        and diagnostico is None
        and ciclo.base_concluido_em is not None
        and ciclo.roteiro_concluido_em is not None
        and ciclo.completo_concluido_em is not None
        and indicadores is not None and indicadores.etapa_atual == 'postar'
    )
    registrar_resultado(
        tabela_resultados, teste='_avancar_etapas_com_estrutura — avança as 3 em sequência',
        entrada='Drive tem Base + Roteiro + Completo',
        esperado="(['base','roteiro','completo'], None), cache sincronizado pra 'postar'",
        motivo='Loop continua enquanto a etapa depender de arquivo e o arquivo existir',
        obtido=f'etapas_marcadas={etapas_marcadas}, diagnostico={diagnostico}, etapa_no_cache={indicadores.etapa_atual if indicadores else None}',
        passou=passou,
    )
    assert passou


def test_nivel_3__verificar_produto_no_drive_simulado_pasta_nao_encontrada(tabela_resultados, monkeypatch):
    # Função Objetivo: Localizador (mockado) diz que a pasta não existe —
    # a função devolve estrutura "não encontrada" + diagnóstico de pasta,
    # sem nunca chegar a chamar o parser nem o avanço de etapa.
    # Setup:
    produto = _criar_produto('SKU-201')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    def _localizar_fake(self, marca, ean):
        return False, None, 'Pasta da marca não encontrada no Drive', None

    monkeypatch.setattr(LocalizadorArquivosProduto, 'localizar_arquivos', _localizar_fake)

    # Exercise:
    etapas_marcadas, estrutura_drive, diagnostico = verificar_produto_no_drive(produto.id)

    # Assert:
    passou = (
        etapas_marcadas == []
        and estrutura_drive.pasta_encontrada is False
        and diagnostico == DiagnosticoBloqueio('pasta', 'Pasta da marca não encontrada no Drive')
    )
    registrar_resultado(
        tabela_resultados, teste='verificar_produto_no_drive (simulado) — pasta não encontrada',
        entrada='Localizador mockado devolve encontrado=False',
        esperado='([], estrutura não encontrada, DiagnosticoBloqueio("pasta", motivo))',
        motivo='Pasta ausente é um bloqueio próprio, nem chega a parsear nem avançar',
        obtido=f'etapas_marcadas={etapas_marcadas}, pasta_encontrada={estrutura_drive.pasta_encontrada}, diagnostico={diagnostico}',
        passou=passou,
    )
    assert passou


def test_nivel_3__verificar_produto_no_drive_simulado_avanca_ponta_a_ponta(tabela_resultados, monkeypatch):
    # Função Objetivo: Localizador mockado devolve 1 arquivo bruto real —
    # prova a cadeia inteira (mock → parser real → avanço real → banco real)
    # funcionando junto, não só cada peça isolada.
    # Setup:
    produto = _criar_produto('SKU-202')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    arquivos_brutos_fabricados = [{'id': 'id_base', 'name': 'Simples_Base.mp4'}]

    def _localizar_fake(self, marca, ean):
        return True, arquivos_brutos_fabricados, None, None

    monkeypatch.setattr(LocalizadorArquivosProduto, 'localizar_arquivos', _localizar_fake)
    # * [EXPLICAÇÃO] → Desde a correção do Bug 3, verificar_produto_no_drive
    #                  também chama listar_arquivos_usados — sem mockar isso
    #                  aqui, o teste bateria de verdade no Drive real.
    monkeypatch.setattr(LocalizadorArquivosProduto, 'listar_arquivos_usados', lambda self, pasta_videos_id: [])

    # Exercise:
    etapas_marcadas, estrutura_drive, diagnostico = verificar_produto_no_drive(produto.id)

    # Assert:
    ciclo.refresh_from_db()
    passou = (
        etapas_marcadas == ['base']
        and estrutura_drive.pasta_encontrada is True
        and diagnostico == DiagnosticoBloqueio('roteiro', 'Aguardando Roteiro — "Simples_Roteiro.txt" não encontrado.')
        and ciclo.base_concluido_em is not None
    )
    registrar_resultado(
        tabela_resultados, teste='verificar_produto_no_drive (simulado) — avança ponta a ponta',
        entrada='Localizador mockado devolve [Simples_Base.mp4]',
        esperado="(['base'], pasta_encontrada=True, DiagnosticoBloqueio('roteiro', ...))",
        motivo='Mock só na borda de rede — parser, avanço e banco rodam de verdade',
        obtido=f'etapas_marcadas={etapas_marcadas}, pasta_encontrada={estrutura_drive.pasta_encontrada}, diagnostico={diagnostico}, base_concluido_em={ciclo.base_concluido_em}',
        passou=passou,
    )
    assert passou

def test_nivel_3__verificar_produto_no_drive_simulado_grava_snapshot_quando_encontra(tabela_resultados, monkeypatch):
    # Função Objetivo: verificação individual também precisa manter o
    # snapshot fresco (SnapshotArquivosDrive) — regressão do Bug 3 (ver
    # "Botao de Verificar Drive Individual Tinha 3 Bugs Reais" no vault).
    # Antes desta correção, só o "Verificar Todos" gravava o snapshot.
    # Setup:
    produto = _criar_produto('SKU-401')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    arquivos_brutos_fabricados = [{'id': 'id_base', 'name': 'Simples_Base.mp4'}]
    arquivos_usados_fabricados = [{'id': 'id_antigo', 'name': 'Simples_Base_antigo.mp4'}]

    def _localizar_fake(self, marca, ean):
        return True, arquivos_brutos_fabricados, None, 'id_pasta_videos'

    monkeypatch.setattr(LocalizadorArquivosProduto, 'localizar_arquivos', _localizar_fake)
    monkeypatch.setattr(
        LocalizadorArquivosProduto, 'listar_arquivos_usados',
        lambda self, pasta_videos_id: arquivos_usados_fabricados if pasta_videos_id == 'id_pasta_videos' else [],
    )

    # Exercise:
    verificar_produto_no_drive(produto.id)

    # Assert:
    snapshot = SnapshotArquivosDrive.objects.filter(produto=produto).first()
    passou = (
        snapshot is not None and snapshot.pasta_encontrada is True
        and snapshot.motivo_nao_encontrado is None
        and snapshot.arquivos_videos == arquivos_brutos_fabricados
        and snapshot.arquivos_usados == arquivos_usados_fabricados
    )
    registrar_resultado(
        tabela_resultados, teste='verificar_produto_no_drive (simulado) — grava snapshot quando encontra',
        entrada='Localizador mockado devolve pasta encontrada + arquivos',
        esperado='SnapshotArquivosDrive criado com pasta_encontrada=True e os arquivos certos',
        motivo='Verificação individual também é 1 dos 2 caminhos que mantêm o snapshot fresco',
        obtido=f'snapshot_existe={snapshot is not None}, pasta_encontrada={snapshot.pasta_encontrada if snapshot else None}, arquivos_videos={snapshot.arquivos_videos if snapshot else None}, arquivos_usados={snapshot.arquivos_usados if snapshot else None}',
        passou=passou,
    )
    assert passou


def test_nivel_3__verificar_produto_no_drive_simulado_grava_snapshot_quando_nao_encontra(tabela_resultados, monkeypatch):
    # Função Objetivo: mesma garantia do teste anterior, agora pro desfecho
    # "pasta não encontrada" — snapshot grava pasta_encontrada=False e o
    # motivo, em vez de ficar sem nenhum registro/desatualizado.
    # Setup:
    produto = _criar_produto('SKU-402')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    def _localizar_fake(self, marca, ean):
        return False, None, 'Pasta da marca não encontrada no Drive', None

    monkeypatch.setattr(LocalizadorArquivosProduto, 'localizar_arquivos', _localizar_fake)

    # Exercise:
    verificar_produto_no_drive(produto.id)

    # Assert:
    snapshot = SnapshotArquivosDrive.objects.filter(produto=produto).first()
    passou = (
        snapshot is not None and snapshot.pasta_encontrada is False
        and snapshot.motivo_nao_encontrado == 'Pasta da marca não encontrada no Drive'
        and snapshot.arquivos_videos == [] and snapshot.arquivos_usados == []
    )
    registrar_resultado(
        tabela_resultados, teste='verificar_produto_no_drive (simulado) — grava snapshot quando não encontra',
        entrada='Localizador mockado devolve encontrado=False',
        esperado='SnapshotArquivosDrive criado com pasta_encontrada=False e o motivo',
        motivo='Não encontrar também precisa atualizar o snapshot, não só o caso de sucesso',
        obtido=f'snapshot_existe={snapshot is not None}, pasta_encontrada={snapshot.pasta_encontrada if snapshot else None}, motivo_nao_encontrado={snapshot.motivo_nao_encontrado if snapshot else None}',
        passou=passou,
    )
    assert passou


def test_nivel_3__verificar_todos_no_drive_simulado_1_produto_avanca(tabela_resultados, monkeypatch):
    # Função Objetivo: sincronizar_snapshots_drive (mockado) devolve 1 produto
    # atualizado — o resto (leitura do snapshot real, parser real, avanço
    # real) roda de verdade, e o produto aparece no resumo.
    # Setup:
    produto = _criar_produto('SKU-301')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    SnapshotArquivosDrive.objects.create(
        produto=produto, pasta_encontrada=True,
        arquivos_videos=[{'id': 'id_base', 'name': 'Simples_Base.mp4'}],
    )

    def _sincronizar_fake():
        return None, ['EAN-inexistente-no-banco'], [produto.id]

    monkeypatch.setattr(escaneador, 'sincronizar_snapshots_drive', _sincronizar_fake)

    # Exercise:
    resumo_por_produto, sem_produto_no_banco = verificar_todos_no_drive()

    # Assert:
    ciclo.refresh_from_db()
    passou = (
        resumo_por_produto == [(produto.id, ['base'])]
        and sem_produto_no_banco == ['EAN-inexistente-no-banco']
        and ciclo.base_concluido_em is not None
    )
    registrar_resultado(
        tabela_resultados, teste='verificar_todos_no_drive (simulado) — 1 produto avança',
        entrada='sincronizar_snapshots_drive mockado devolve 1 produto_id, snapshot real com Simples_Base.mp4',
        esperado="resumo=[(produto_id, ['base'])], sem_produto_no_banco repassado igual",
        motivo='Mock só na borda de rede — leitura do snapshot, parser e avanço rodam de verdade',
        obtido=f'resumo={resumo_por_produto}, sem_produto_no_banco={sem_produto_no_banco}, base_concluido_em={ciclo.base_concluido_em}',
        passou=passou,
    )
    assert passou


def test_nivel_3__verificar_todos_no_drive_simulado_produto_sem_avanco_fica_fora_do_resumo(tabela_resultados, monkeypatch):
    # Função Objetivo: produto sincronizado mas sem nenhum arquivo no Drive —
    # etapas_marcadas fica vazio, o produto some do resumo (o filtro
    # "if etapas_marcadas:" é o que garante isso).
    # Setup:
    produto = _criar_produto('SKU-302')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    SnapshotArquivosDrive.objects.create(produto=produto, pasta_encontrada=True, arquivos_videos=[])

    def _sincronizar_fake():
        return None, [], [produto.id]

    monkeypatch.setattr(escaneador, 'sincronizar_snapshots_drive', _sincronizar_fake)

    # Exercise:
    resumo_por_produto, sem_produto_no_banco = verificar_todos_no_drive()

    # Assert:
    passou = resumo_por_produto == [] and sem_produto_no_banco == []
    registrar_resultado(
        tabela_resultados, teste='verificar_todos_no_drive (simulado) — produto sem avanço fica fora do resumo',
        entrada='snapshot com arquivos_videos=[] (Drive vazio)',
        esperado='resumo=[] — produto não aparece',
        motivo='Filtro "if etapas_marcadas:" exclui quem não avançou nada',
        obtido=f'resumo={resumo_por_produto}, sem_produto_no_banco={sem_produto_no_banco}',
        passou=passou,
    )
    assert passou