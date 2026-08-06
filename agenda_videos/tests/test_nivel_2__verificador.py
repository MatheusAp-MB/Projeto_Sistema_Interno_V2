# agenda_videos/tests/test_nivel_2__verificador.py

# SUT: agenda_videos/funcoes_auxiliares/drive/verificador.py
#      (_montar_nome_esperado, avaliar_etapa_no_drive)
# DOC: CicloVideo em memória (sem .save()) + ArquivosProdutoDrive fabricado
#      na mão — nenhum dos dois toca banco nem Drive real. Nível 2.

from django.utils import timezone

from agenda_videos.models import CicloVideo, Fase
from agenda_videos.funcoes_auxiliares.drive.verificador import (
    DiagnosticoBloqueio, _montar_nome_esperado, avaliar_etapa_no_drive,
)
from agenda_videos.funcoes_auxiliares.drive.parser import ArquivoDrive, ArquivosOcorrencia, ArquivosFase, ArquivosProdutoDrive
from testes_apoio.apoio_visual import registrar_resultado


def _estrutura_com_ocorrencia_mensal_1(base=None, roteiro=None, completo=None):
    ocorrencia = ArquivosOcorrencia(numero=1, base=base, roteiro=roteiro, completo=completo)
    return ArquivosProdutoDrive(
        marca='Marca X', ean='123', pasta_encontrada=True, motivo_pasta_nao_encontrada=None,
        simples=ArquivosFase(fase='simples', ocorrencias=[]),
        video_mensal=ArquivosFase(fase='video_mensal', ocorrencias=[ocorrencia]),
        video_trimestral=ArquivosFase(fase='video_trimestral', ocorrencias=[]),
        arquivos_nao_reconhecidos=[],
    )


def test_nivel_2__montar_nome_esperado_simples_base(tabela_resultados):
    # Função Objetivo: Simples nunca numera, mesmo tendo numero_ocorrencia=1.
    # Setup:
    ciclo = CicloVideo(fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    nome = _montar_nome_esperado(ciclo, 'base')

    # Assert:
    passou = nome == 'Simples_Base.mp4'
    registrar_resultado(
        tabela_resultados, teste='_montar_nome_esperado — Simples/base',
        entrada='fase=Simples, numero_ocorrencia=1, etapa=base',
        esperado='Simples_Base.mp4',
        motivo='Simples nunca numera — sem número no nome, mesmo recebendo numero_ocorrencia',
        obtido=f'nome={nome!r}',
        passou=passou,
    )
    assert passou


def test_nivel_2__montar_nome_esperado_simples_roteiro_extensao_txt(tabela_resultados):
    # Função Objetivo: Roteiro sempre .txt, mesmo fase Simples.
    # Setup:
    ciclo = CicloVideo(fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    nome = _montar_nome_esperado(ciclo, 'roteiro')

    # Assert:
    passou = nome == 'Simples_Roteiro.txt'
    registrar_resultado(
        tabela_resultados, teste='_montar_nome_esperado — Simples/roteiro',
        entrada='fase=Simples, etapa=roteiro',
        esperado='Simples_Roteiro.txt',
        motivo='Roteiro é a única etapa com extensão .txt — Base/Completo são .mp4',
        obtido=f'nome={nome!r}',
        passou=passou,
    )
    assert passou


def test_nivel_2__montar_nome_esperado_mensal_numera_com_2_digitos(tabela_resultados):
    # Função Objetivo: Vídeo Mensal numera com 2 dígitos fixos (01, não 1).
    # Setup:
    ciclo = CicloVideo(fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1)

    # Exercise:
    nome = _montar_nome_esperado(ciclo, 'base')

    # Assert:
    passou = nome == 'Mensal_01_Base.mp4'
    registrar_resultado(
        tabela_resultados, teste='_montar_nome_esperado — Mensal/base',
        entrada='fase=Vídeo Mensal, numero_ocorrencia=1, etapa=base',
        esperado='Mensal_01_Base.mp4',
        motivo='Mensal numera com 2 dígitos fixos — bate com o padrão real do parser',
        obtido=f'nome={nome!r}',
        passou=passou,
    )
    assert passou


def test_nivel_2__montar_nome_esperado_trimestral_numero_alto_sem_teto(tabela_resultados):
    # Função Objetivo: Trimestral não tem teto — número #7 formata igual a
    # qualquer outro, sem tratamento especial.
    # Setup:
    ciclo = CicloVideo(fase=Fase.VIDEO_TRIMESTRAL, numero_ocorrencia=7)

    # Exercise:
    nome = _montar_nome_esperado(ciclo, 'completo')

    # Assert:
    passou = nome == 'Trimestral_07_Completo.mp4'
    registrar_resultado(
        tabela_resultados, teste='_montar_nome_esperado — Trimestral/completo, número alto',
        entrada='fase=Vídeo Trimestral, numero_ocorrencia=7, etapa=completo',
        esperado='Trimestral_07_Completo.mp4',
        motivo='Fase contínua — função não limita a numeração, só formata o que recebe',
        obtido=f'nome={nome!r}',
        passou=passou,
    )
    assert passou


def test_nivel_2__avaliar_etapa_sem_depender_de_arquivo_libera_sem_olhar_drive(tabela_resultados):
    # Função Objetivo: etapas fora de {base, roteiro, completo} (aqui, postar)
    # liberam direto — nem chega a olhar a estrutura do Drive.
    # Setup:
    agora = timezone.now()
    ciclo = CicloVideo(
        fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
    )
    estrutura_drive = _estrutura_com_ocorrencia_mensal_1()  # vazia de propósito — não deveria importar

    # Exercise:
    satisfeito, diagnostico = avaliar_etapa_no_drive(ciclo, estrutura_drive)

    # Assert:
    passou = satisfeito is True and diagnostico is None
    registrar_resultado(
        tabela_resultados, teste='avaliar_etapa_no_drive — etapa sem depender de arquivo (postar)',
        entrada='etapa_atual()=postar, estrutura do Drive vazia',
        esperado='(True, None) — libera mesmo sem arquivo nenhum no Drive',
        motivo='postar/aguardando_aprovacao/etc. nunca dependem de arquivo — fora de ETAPAS_QUE_DEPENDEM_DE_ARQUIVO',
        obtido=f'satisfeito={satisfeito}, diagnostico={diagnostico}',
        passou=passou,
        dado_bruto=f'etapa_atual()={ciclo.etapa_atual()!r}',
    )
    assert passou


def test_nivel_2__avaliar_etapa_arquivo_existe_libera(tabela_resultados):
    # Função Objetivo: etapa=base, arquivo esperado existe no Drive → libera.
    # Setup:
    ciclo = CicloVideo(fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1)  # etapa_atual() == 'base'
    arquivo_base = ArquivoDrive(nome_arquivo='Mensal_01_Base.mp4', drive_file_id='id1')
    estrutura_drive = _estrutura_com_ocorrencia_mensal_1(base=arquivo_base)

    # Exercise:
    satisfeito, diagnostico = avaliar_etapa_no_drive(ciclo, estrutura_drive)

    # Assert:
    passou = satisfeito is True and diagnostico is None
    registrar_resultado(
        tabela_resultados, teste='avaliar_etapa_no_drive — arquivo existe',
        entrada='etapa_atual()=base, Mensal_01_Base.mp4 presente na estrutura',
        esperado='(True, None)',
        motivo='Arquivo esperado está lá — etapa liberada',
        obtido=f'satisfeito={satisfeito}, diagnostico={diagnostico}',
        passou=passou,
    )
    assert passou


def test_nivel_2__avaliar_etapa_ocorrencia_existe_mas_arquivo_none_bloqueia(tabela_resultados):
    # Função Objetivo: ocorrência existe na estrutura, mas o campo da etapa
    # (base) está None → bloqueia com diagnóstico e nome esperado corretos.
    # Setup:
    ciclo = CicloVideo(fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1)  # etapa_atual() == 'base'
    estrutura_drive = _estrutura_com_ocorrencia_mensal_1()  # ocorrência #1 existe, mas base=None

    # Exercise:
    satisfeito, diagnostico = avaliar_etapa_no_drive(ciclo, estrutura_drive)

    # Assert:
    esperado = DiagnosticoBloqueio('base', 'Aguardando Base — "Mensal_01_Base.mp4" não encontrado.')
    passou = satisfeito is False and diagnostico == esperado
    registrar_resultado(
        tabela_resultados, teste='avaliar_etapa_no_drive — ocorrência existe, arquivo None',
        entrada='etapa_atual()=base, ocorrência #1 existe mas campo base=None',
        esperado=f'(False, {esperado})',
        motivo='Arquivo esperado não está lá — bloqueia com mensagem e nome corretos',
        obtido=f'satisfeito={satisfeito}, diagnostico={diagnostico}',
        passou=passou,
    )
    assert passou


def test_nivel_2__avaliar_etapa_ocorrencia_nao_existe_na_lista_bloqueia(tabela_resultados):
    # Função Objetivo: ocorrência pedida nem existe na lista da fase (número
    # diferente do que está na estrutura) → mesmo bloqueio, via o ramo
    # "ocorrencia is None" do ternário.
    # Setup:
    agora = timezone.now()
    ciclo = CicloVideo(fase=Fase.VIDEO_MENSAL, numero_ocorrencia=2, base_concluido_em=agora)  # etapa_atual() == 'roteiro'
    estrutura_drive = _estrutura_com_ocorrencia_mensal_1()  # só tem ocorrência #1, não #2

    # Exercise:
    satisfeito, diagnostico = avaliar_etapa_no_drive(ciclo, estrutura_drive)

    # Assert:
    esperado = DiagnosticoBloqueio('roteiro', 'Aguardando Roteiro — "Mensal_02_Roteiro.txt" não encontrado.')
    passou = satisfeito is False and diagnostico == esperado
    registrar_resultado(
        tabela_resultados, teste='avaliar_etapa_no_drive — ocorrência nem existe na lista',
        entrada='etapa_atual()=roteiro, numero_ocorrencia=2, estrutura só tem a ocorrência #1',
        esperado=f'(False, {esperado})',
        motivo='obter_ocorrencia() devolve None — arquivo vira None do mesmo jeito, bloqueio idêntico',
        obtido=f'satisfeito={satisfeito}, diagnostico={diagnostico}',
        passou=passou,
    )
    assert passou