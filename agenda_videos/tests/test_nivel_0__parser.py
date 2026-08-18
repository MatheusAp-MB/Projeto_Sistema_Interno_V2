# agenda_videos/tests/test_nivel_0__parser.py

# SUT: agenda_videos/funcoes_auxiliares/drive/parser.py
# DOC: nenhuma — funções puras, sem banco nem rede. Nível 0.

from agenda_videos.funcoes_auxiliares.drive.parser import (
    ArquivoDrive, ArquivosOcorrencia, ArquivosFase,
    parsear_arquivos_produto, montar_produto_nao_encontrado,
)
from testes_apoio.apoio_visual import registrar_resultado


def test_nivel_0__parsear_pasta_completa_valida(tabela_resultados):
    # Função Objetivo: caminho feliz completo — Simples + Vídeo Mensal 01-04
    # + Vídeo Trimestral 01, cada um com o trio Base/Roteiro/Completo, mesmo
    # formato da pasta de referência real (EAN 0789888395162, QUIMIVIDA).
    # Setup:
    arquivos_brutos = [
        {'id': 'id_simples_base', 'name': 'Simples_Base.mp4'},
        {'id': 'id_simples_roteiro', 'name': 'Simples_Roteiro.txt'},
        {'id': 'id_simples_completo', 'name': 'Simples_Completo.mp4'},
    ]
    for numero in range(1, 5):
        nn = f'{numero:02d}'
        arquivos_brutos += [
            {'id': f'id_mensal_{nn}_base', 'name': f'Mensal_{nn}_Base.mp4'},
            {'id': f'id_mensal_{nn}_roteiro', 'name': f'Mensal_{nn}_Roteiro.txt'},
            {'id': f'id_mensal_{nn}_completo', 'name': f'Mensal_{nn}_Completo.mp4'},
        ]
    arquivos_brutos += [
        {'id': 'id_trimestral_01_base', 'name': 'Trimestral_01_Base.mp4'},
        {'id': 'id_trimestral_01_roteiro', 'name': 'Trimestral_01_Roteiro.txt'},
        {'id': 'id_trimestral_01_completo', 'name': 'Trimestral_01_Completo.mp4'},
    ]

    # Exercise:
    resultado = parsear_arquivos_produto('QUIMIVIDA', '0789888395162', arquivos_brutos)

    # Assert:
    numeros_mensal = [o.numero for o in resultado.video_mensal.ocorrencias]
    simples_ok = (
        len(resultado.simples.ocorrencias) == 1
        and resultado.simples.ocorrencias[0].numero == 1
        and resultado.simples.ocorrencias[0].base == ArquivoDrive('Simples_Base.mp4', 'id_simples_base')
        and resultado.simples.ocorrencias[0].roteiro == ArquivoDrive('Simples_Roteiro.txt', 'id_simples_roteiro')
        and resultado.simples.ocorrencias[0].completo == ArquivoDrive('Simples_Completo.mp4', 'id_simples_completo')
    )
    mensal_completo_ok = all(o.base and o.roteiro and o.completo for o in resultado.video_mensal.ocorrencias)
    trimestral_ok = (
        len(resultado.video_trimestral.ocorrencias) == 1
        and resultado.video_trimestral.ocorrencias[0].numero == 1
    )
    passou = (
        resultado.pasta_encontrada is True
        and simples_ok
        and numeros_mensal == [1, 2, 3, 4]
        and mensal_completo_ok
        and trimestral_ok
        and resultado.arquivos_nao_reconhecidos == []
    )
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — pasta completa e válida',
        entrada='18 arquivos: Simples + Mensal 01-04 + Trimestral 01, trio completo em cada',
        esperado='simples=1 ocorrência completa, mensal=[1,2,3,4] completas, trimestral=1 ocorrência, 0 não reconhecidos',
        motivo='Caminho feliz — mesmo formato da pasta de referência real validada no Drive (QUIMIVIDA)',
        obtido=f'simples_ok={simples_ok}, numeros_mensal={numeros_mensal}, mensal_completo_ok={mensal_completo_ok}, trimestral_ok={trimestral_ok}, nao_reconhecidos={resultado.arquivos_nao_reconhecidos}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_ocorrencia_incompleta_so_base(tabela_resultados):
    # Função Objetivo: ocorrência com só 1 dos 3 arquivos ainda é reportada —
    # os campos que faltam ficam None, o parser nunca trava por incompletude.
    # Setup:
    arquivos_brutos = [{'id': 'id_base', 'name': 'Mensal_01_Base.mp4'}]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    ocorrencia = resultado.video_mensal.obter_ocorrencia(1)
    passou = (
        ocorrencia is not None
        and ocorrencia.base == ArquivoDrive('Mensal_01_Base.mp4', 'id_base')
        and ocorrencia.roteiro is None
        and ocorrencia.completo is None
    )
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — ocorrência incompleta (só Base)',
        entrada='1 arquivo: Mensal_01_Base.mp4',
        esperado='ocorrência #1 com base preenchido, roteiro=None, completo=None',
        motivo='Arquivo que falta nunca trava o parser nem inventa dado — só fica None',
        obtido=f'ocorrencia={ocorrencia}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_numeros_com_buraco_na_sequencia(tabela_resultados):
    # Função Objetivo: só Mensal_02 e Mensal_04 presentes — o parser reporta
    # fielmente o que existe, sem inventar #1/#3 nem travar por causa do buraco.
    # Setup:
    arquivos_brutos = [
        {'id': 'id_02', 'name': 'Mensal_02_Base.mp4'},
        {'id': 'id_04', 'name': 'Mensal_04_Base.mp4'},
    ]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    numeros = [o.numero for o in resultado.video_mensal.ocorrencias]
    passou = numeros == [2, 4]
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — números com buraco (só #2 e #4)',
        entrada='2 arquivos: Mensal_02_Base.mp4, Mensal_04_Base.mp4',
        esperado='ocorrências=[2, 4], sem #1 nem #3 inventados',
        motivo='Time pré-produz vídeos fora de ordem (pool) — parser precisa refletir isso fielmente',
        obtido=f'numeros={numeros}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_nome_certo_extensao_errada_nao_reconhecido(tabela_resultados):
    # Função Objetivo: nome bate no padrão de Base, mas extensão é .txt (só
    # Roteiro pode ser .txt) — precisa cair em não reconhecido, nunca ser
    # aceito por engano como Base.
    # Setup:
    arquivos_brutos = [{'id': 'id_x', 'name': 'Simples_Base.txt'}]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    passou = (
        resultado.simples.ocorrencias == []
        and resultado.arquivos_nao_reconhecidos == [ArquivoDrive('Simples_Base.txt', 'id_x')]
    )
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — nome certo, extensão errada',
        entrada='Simples_Base.txt (Base deveria ser .mp4)',
        esperado='simples.ocorrencias=[], vai pra não reconhecidos',
        motivo='Extensão errada nunca é aceita por engano, mesmo com nome certo',
        obtido=f'simples_ocorrencias={resultado.simples.ocorrencias}, nao_reconhecidos={resultado.arquivos_nao_reconhecidos}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_case_insensitive(tabela_resultados):
    # Função Objetivo: nome em CAIXA ALTA é reconhecido igual — reconhecimento
    # é insensível a maiúscula/minúscula, tanto no prefixo quanto no tipo.
    # Setup:
    arquivos_brutos = [{'id': 'id_z', 'name': 'MENSAL_01_BASE.MP4'}]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    ocorrencia = resultado.video_mensal.obter_ocorrencia(1)
    passou = ocorrencia is not None and ocorrencia.base == ArquivoDrive('MENSAL_01_BASE.MP4', 'id_z')
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — case-insensitive',
        entrada='MENSAL_01_BASE.MP4 (tudo caixa alta)',
        esperado='reconhecido igual a Mensal_01_Base.mp4',
        motivo='Reconhecimento insensível a maiúscula/minúscula, rígido só no formato',
        obtido=f'ocorrencia={ocorrencia}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_numero_sem_2_digitos_nao_reconhecido(tabela_resultados):
    # Função Objetivo: PADRAO_NUMERADO exige exatamente 2 dígitos (\d{2}) —
    # "Mensal_1_Base.mp4" (1 dígito) não bate em nenhum padrão, cai em não
    # reconhecido.
    # Setup:
    arquivos_brutos = [{'id': 'id_w', 'name': 'Mensal_1_Base.mp4'}]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    passou = (
        resultado.video_mensal.ocorrencias == []
        and resultado.arquivos_nao_reconhecidos == [ArquivoDrive('Mensal_1_Base.mp4', 'id_w')]
    )
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — número sem 2 dígitos',
        entrada='Mensal_1_Base.mp4 (1 dígito, não "01")',
        esperado='não reconhecido — regex exige 2 dígitos exatos',
        motivo='Formato rígido é intencional — evita ambiguidade de numeração',
        obtido=f'video_mensal_ocorrencias={resultado.video_mensal.ocorrencias}, nao_reconhecidos={resultado.arquivos_nao_reconhecidos}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_nome_totalmente_fora_do_padrao(tabela_resultados):
    # Função Objetivo: nome que não bate em nenhum dos 2 padrões (nem Simples
    # nem numerado) vai direto pra não reconhecido.
    # Setup:
    arquivos_brutos = [{'id': 'id_v', 'name': 'arquivo_qualquer.pdf'}]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    passou = resultado.arquivos_nao_reconhecidos == [ArquivoDrive('arquivo_qualquer.pdf', 'id_v')]
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — nome fora do padrão',
        entrada='arquivo_qualquer.pdf',
        esperado='vai pra não reconhecidos',
        motivo='Nenhum dos 2 padrões (Simples/numerado) bate',
        obtido=f'nao_reconhecidos={resultado.arquivos_nao_reconhecidos}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_pasta_vazia(tabela_resultados):
    # Função Objetivo: lista vazia de entrada nunca quebra — as 3 fases vêm
    # com ocorrencias=[], não reconhecidos vazio, pasta_encontrada=True (a
    # pasta EXISTE, só está vazia — diferente de não encontrada).
    # Setup:
    arquivos_brutos = []

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    passou = (
        resultado.pasta_encontrada is True
        and resultado.simples.ocorrencias == []
        and resultado.video_mensal.ocorrencias == []
        and resultado.video_trimestral.ocorrencias == []
        and resultado.arquivos_nao_reconhecidos == []
    )
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — pasta vazia',
        entrada='lista vazia de arquivos',
        esperado='3 fases vazias, não reconhecidos vazio, pasta_encontrada=True',
        motivo='Pasta existir vazia é diferente de pasta não encontrada — não deve travar',
        obtido=f'pasta_encontrada={resultado.pasta_encontrada}, simples={resultado.simples.ocorrencias}, mensal={resultado.video_mensal.ocorrencias}, trimestral={resultado.video_trimestral.ocorrencias}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_nao_reconhecidos_ordenados_por_nome(tabela_resultados):
    # Função Objetivo: arquivos_nao_reconhecidos sempre sai ordenado por nome
    # — determinístico, independente da ordem de chegada do Drive.
    # Setup:
    arquivos_brutos = [
        {'id': 'id_zzz', 'name': 'zzz_arquivo.pdf'},
        {'id': 'id_aaa', 'name': 'aaa_arquivo.pdf'},
    ]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    passou = resultado.arquivos_nao_reconhecidos == [
        ArquivoDrive('aaa_arquivo.pdf', 'id_aaa'), ArquivoDrive('zzz_arquivo.pdf', 'id_zzz'),
    ]
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — não reconhecidos ordenados por nome',
        entrada='zzz_arquivo.pdf chega antes de aaa_arquivo.pdf',
        esperado='saída ordenada: [aaa_arquivo.pdf, zzz_arquivo.pdf]',
        motivo='Ordem determinística, não depende da ordem de chegada do Drive',
        obtido=f'nao_reconhecidos={resultado.arquivos_nao_reconhecidos}',
        passou=passou,
    )
    assert passou


def test_nivel_0__montar_produto_nao_encontrado(tabela_resultados):
    # Função Objetivo: monta a versão "pasta não encontrada" — mesma
    # dataclass, 3 fases vazias, motivo preenchido.
    # Setup + Exercise:
    resultado = montar_produto_nao_encontrado('Marca X', '123', 'Pasta da marca não encontrada')

    # Assert:
    passou = (
        resultado.pasta_encontrada is False
        and resultado.motivo_pasta_nao_encontrada == 'Pasta da marca não encontrada'
        and resultado.simples.ocorrencias == []
        and resultado.video_mensal.ocorrencias == []
        and resultado.video_trimestral.ocorrencias == []
        and resultado.arquivos_nao_reconhecidos == []
    )
    registrar_resultado(
        tabela_resultados, teste='montar_produto_nao_encontrado',
        entrada="marca='Marca X', ean='123', motivo='Pasta da marca não encontrada'",
        esperado='pasta_encontrada=False, motivo preenchido, 3 fases vazias',
        motivo='Placeholder seguro pra quando a pasta não existe no Drive',
        obtido=f'pasta_encontrada={resultado.pasta_encontrada}, motivo={resultado.motivo_pasta_nao_encontrada!r}',
        passou=passou,
    )
    assert passou


def test_nivel_0__obter_ocorrencia_numero_existente(tabela_resultados):
    # Função Objetivo: obter_ocorrencia() acha a ocorrência certa pelo número.
    # Setup:
    ocorrencia_2 = ArquivosOcorrencia(numero=2, base=None, roteiro=None, completo=None)
    fase = ArquivosFase(fase='video_mensal', ocorrencias=[
        ArquivosOcorrencia(numero=1, base=None, roteiro=None, completo=None), ocorrencia_2,
    ])

    # Exercise:
    encontrada = fase.obter_ocorrencia(2)

    # Assert:
    passou = encontrada is ocorrencia_2
    registrar_resultado(
        tabela_resultados, teste='obter_ocorrencia — número existente',
        entrada='ocorrencias=[#1, #2], busca #2',
        esperado='devolve a ocorrência #2',
        motivo='Busca direta pelo número, sem depender de índice de lista',
        obtido=f'encontrada={encontrada}',
        passou=passou,
    )
    assert passou


def test_nivel_0__obter_ocorrencia_numero_inexistente(tabela_resultados):
    # Função Objetivo: número que não existe na lista devolve None, nunca
    # levanta erro.
    # Setup:
    fase = ArquivosFase(fase='video_mensal', ocorrencias=[
        ArquivosOcorrencia(numero=1, base=None, roteiro=None, completo=None),
    ])

    # Exercise:
    encontrada = fase.obter_ocorrencia(99)

    # Assert:
    passou = encontrada is None
    registrar_resultado(
        tabela_resultados, teste='obter_ocorrencia — número inexistente',
        entrada='ocorrencias=[#1], busca #99',
        esperado='None',
        motivo='Número fora da lista nunca levanta erro — só não acha',
        obtido=f'encontrada={encontrada}',
        passou=passou,
    )
    assert passou


def test_nivel_0__obter_fase_chave_valida(tabela_resultados):
    # Função Objetivo: obter_fase() com uma das 3 chaves reais devolve o
    # atributo certo.
    # Setup:
    produto_drive = montar_produto_nao_encontrado('Marca X', '123', 'motivo qualquer')

    # Exercise:
    fase = produto_drive.obter_fase('video_trimestral')

    # Assert:
    passou = fase is produto_drive.video_trimestral
    registrar_resultado(
        tabela_resultados, teste='obter_fase — chave válida',
        entrada="chave_fase='video_trimestral'",
        esperado='devolve o mesmo objeto de produto_drive.video_trimestral',
        motivo='getattr correto — 3 chaves reais mapeiam 1:1 pros 3 campos da dataclass',
        obtido=f'fase_e_o_mesmo_objeto={passou}',
        passou=passou,
    )
    assert passou


def test_nivel_0__obter_fase_chave_invalida_levanta_value_error(tabela_resultados):
    # Função Objetivo: trava contra uso indevido — chave fora das 3 válidas
    # levanta ValueError com mensagem clara, nunca AttributeError cru. Fix
    # aplicado nesta sessão (05/08) especificamente pra isso.
    # Setup:
    produto_drive = montar_produto_nao_encontrado('Marca X', '123', 'motivo qualquer')

    # Exercise:
    levantou_value_error = False
    try:
        produto_drive.obter_fase('fase_que_nao_existe')
    except ValueError:
        levantou_value_error = True

    # Assert:
    passou = levantou_value_error
    registrar_resultado(
        tabela_resultados, teste='obter_fase — chave inválida levanta ValueError',
        entrada="chave_fase='fase_que_nao_existe'",
        esperado='levanta ValueError',
        motivo='Fix de 05/08: getattr sem guard levantava AttributeError cru — trocado por validação explícita',
        obtido=f'levantou_value_error={levantou_value_error}',
        passou=passou,
    )
    assert passou

def test_nivel_0__parsear_numerado_extensao_errada_nao_reconhecido(tabela_resultados):
    # Função Objetivo: mesmo caso do teste de extensão errada, mas no ramo
    # NUMERADO (Mensal/Trimestral) — nome bate certinho no formato (prefixo +
    # 2 dígitos + tipo), mas extensão errada ainda cai em não reconhecido.
    # Fecha o branch que faltava (linha 110 de parser.py).
    # Setup:
    arquivos_brutos = [{'id': 'id_y', 'name': 'Mensal_01_Base.txt'}]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    passou = (
        resultado.video_mensal.ocorrencias == []
        and resultado.arquivos_nao_reconhecidos == [ArquivoDrive('Mensal_01_Base.txt', 'id_y')]
    )
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — numerado, extensão errada',
        entrada='Mensal_01_Base.txt (Base deveria ser .mp4)',
        esperado='vai pra não reconhecidos, nenhuma ocorrência criada',
        motivo='Mesma regra do Simples, aplicada ao ramo Numerado (Mensal/Trimestral)',
        obtido=f'video_mensal_ocorrencias={resultado.video_mensal.ocorrencias}, nao_reconhecidos={resultado.arquivos_nao_reconhecidos}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_roteiro_simples_no_plural_reconhecido_igual_ao_singular(tabela_resultados):
    # Função Objetivo: achado real (Ortho Pauher/Samvale, 18/08/2026) — a
    # equipe vem salvando o Roteiro no plural ("Simples_Roteiros.txt"), não
    # no singular do padrão original. Precisa ser reconhecido exatamente
    # igual ao singular, nunca cair em "não reconhecido" por isso.
    # Setup:
    arquivos_brutos = [{'id': 'id_roteiro_plural', 'name': 'Simples_Roteiros.txt'}]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    ocorrencia = resultado.simples.obter_ocorrencia(1)
    passou = (
        ocorrencia is not None
        and ocorrencia.roteiro == ArquivoDrive('Simples_Roteiros.txt', 'id_roteiro_plural')
        and resultado.arquivos_nao_reconhecidos == []
    )
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — Roteiro no plural (Simples) reconhecido',
        entrada='Simples_Roteiros.txt (plural, achado real da equipe)',
        esperado='ocorrência #1 com roteiro preenchido, 0 não reconhecidos',
        motivo='Roteiro é só existência — variação singular/plural do nome não pode travar a etapa',
        obtido=f'ocorrencia={ocorrencia}, nao_reconhecidos={resultado.arquivos_nao_reconhecidos}',
        passou=passou,
    )
    assert passou


def test_nivel_0__parsear_roteiro_numerado_no_plural_reconhecido_igual_ao_singular(tabela_resultados):
    # Função Objetivo: mesmo achado real, agora no ramo NUMERADO (Mensal/
    # Trimestral) — "Mensal_01_Roteiros.txt" (plural) precisa ser reconhecido
    # igual a "Mensal_01_Roteiro.txt".
    # Setup:
    arquivos_brutos = [{'id': 'id_roteiro_plural_numerado', 'name': 'Mensal_01_Roteiros.txt'}]

    # Exercise:
    resultado = parsear_arquivos_produto('Marca X', '123', arquivos_brutos)

    # Assert:
    ocorrencia = resultado.video_mensal.obter_ocorrencia(1)
    passou = (
        ocorrencia is not None
        and ocorrencia.roteiro == ArquivoDrive('Mensal_01_Roteiros.txt', 'id_roteiro_plural_numerado')
        and resultado.arquivos_nao_reconhecidos == []
    )
    registrar_resultado(
        tabela_resultados, teste='parsear_arquivos_produto — Roteiro no plural (Numerado) reconhecido',
        entrada='Mensal_01_Roteiros.txt (plural, achado real da equipe)',
        esperado='ocorrência #1 com roteiro preenchido, 0 não reconhecidos',
        motivo='Mesma regra do Simples, aplicada ao ramo Numerado (Mensal/Trimestral)',
        obtido=f'ocorrencia={ocorrencia}, nao_reconhecidos={resultado.arquivos_nao_reconhecidos}',
        passou=passou,
    )
    assert passou