# agenda_videos/funcoes_auxiliares/verificar_arquivos_drive.py

# Função Objetivo: Verifica os arquivos de 1 produto no Drive (AO VIVO, 1
# produto por vez) e avança o roadmap automaticamente — reaproveita
# calcular_chave_atual (a MESMA função que decide qual ponto é o atual pro
# clique manual), em loop: pergunta qual é o ponto atual, confere se o Drive
# tem o arquivo dele, marca como pronto, pergunta de novo, repete até faltar
# arquivo ou chegar num ponto que não depende de arquivo.
#
# avaliar_ponto_preparacao() é a peça COMPARTILHADA entre este arquivo
# (verificação ao vivo, escreve no banco) e diagnostico_preparo_drive.py
# (leitura só do snapshot já salvo, nunca escreve) — nunca duplicar a
# pergunta "esse ponto está satisfeito?" em 2 lugares.
#
# Sempre grava SnapshotArquivosDrive ao final — dado da API é caro, nunca
# descartado depois de usado 1 vez, mesmo sendo verificação individual.

from dataclasses import dataclass
from django.utils import timezone
from agenda_videos.models import (
    StatusVideo, ProgressoProducaoVideo, PreparacaoVideoFase, SnapshotArquivosDrive,
)
from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    calcular_chave_atual, montar_preparacoes_por_fase, obter_mapa_periodos_por_fase,
    FASE_DA_CHAVE_PREPARACAO,
)
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto
from agenda_videos.funcoes_auxiliares.drive_arquivos_produto import LocalizadorArquivosProduto
from agenda_videos.funcoes_auxiliares.parser_arquivos_drive import (
    parsear_arquivos_produto, montar_produto_nao_encontrado,
)

PREFIXO_CHAVE_PARA_FASE_TXT = {'diaria': 'Diario', 'semanal': 'Semanal', 'mensal': 'Mensal'}

# * [EXPLICAÇÃO] → Só estes pontos dependem de arquivo do Drive — pontos
#                  cíclicos (Diária/Semanal/Mensal em si), Agendamento e
#                  Otimizado nunca dependem, e não passam por aqui.
CHAVES_QUE_DEPENDEM_DE_ARQUIVO = {
    'simples', 'base',
    'roteiros_diaria', 'completos_diaria',
    'roteiros_semanal', 'completos_semanal',
    'roteiros_mensal', 'completos_mensal',
}


# Função Objetivo: Explica POR QUE a verificação está bloqueada num ponto que
# depende de arquivo — distingue "arquivo não existe ainda" de "existe, mas
# é insuficiente", pra o usuário nunca ficar sem entender o que falta.
@dataclass(frozen=True)
class DiagnosticoBloqueio:
    ponto: str
    mensagem: str


# Função Objetivo: Avalia se o Drive (já navegado/parseado em
# ArquivosProdutoDrive) satisfaz o ponto de preparação `chave` — devolve
# (satisfeito, diagnostico). Pura, sem chamada de rede nem escrita no banco —
# reutilizada tanto pela verificação que ESCREVE (este arquivo, ao vivo)
# quanto pelo diagnóstico que só LÊ (diagnostico_preparo_drive.py, a partir
# do snapshot salvo).
def avaliar_ponto_preparacao(chave, estrutura_drive):
    if chave == 'simples':
        if estrutura_drive.simples is None:
            return False, DiagnosticoBloqueio('simples', 'Aguardando Vídeo Simples — "Simples.mp4" não encontrado.')
        return True, None

    if chave == 'base':
        if estrutura_drive.base is None:
            return False, DiagnosticoBloqueio('base', 'Aguardando Vídeo Base — "Base.mp4" não encontrado.')
        return True, None

    if chave in ('roteiros_diaria', 'roteiros_semanal', 'roteiros_mensal'):
        fase = FASE_DA_CHAVE_PREPARACAO[chave]
        if estrutura_drive.fases[fase].roteiros is None:
            nome_esperado = f'Roteiros_{PREFIXO_CHAVE_PARA_FASE_TXT[fase]}.txt'
            return False, DiagnosticoBloqueio(
                chave, f'Aguardando Roteiros ({fase}) — "{nome_esperado}" não encontrado.',
            )
        return True, None

    if chave in ('completos_diaria', 'completos_semanal', 'completos_mensal'):
        fase = FASE_DA_CHAVE_PREPARACAO[chave]
        periodo_atual = obter_mapa_periodos_por_fase().get(fase)
        quantidade_no_drive = estrutura_drive.fases[fase].completos.quantidade
        if periodo_atual is None or quantidade_no_drive < periodo_atual:
            faltam = (periodo_atual - quantidade_no_drive) if periodo_atual else '?'
            return False, DiagnosticoBloqueio(
                chave,
                f'Completos ({fase}): {quantidade_no_drive} de {periodo_atual} vídeo(s) encontrado(s) — faltam {faltam}.',
            )
        return True, None

    return True, None  # ponto que não depende de arquivo — nunca bloqueado por isso


def _obter_estrutura_drive(produto):
    localizador = LocalizadorArquivosProduto()
    encontrado, arquivos_brutos, motivo, pasta_videos_id = localizador.localizar_arquivos(produto.marca, produto.ean)

    if not encontrado:
        SnapshotArquivosDrive.objects.update_or_create(
            produto=produto,
            defaults={
                'pasta_encontrada': False, 'motivo_nao_encontrado': motivo,
                'arquivos_videos': [], 'arquivos_usados': [],
            },
        )
        return montar_produto_nao_encontrado(produto.marca, produto.ean, motivo)

    arquivos_usados = localizador.listar_arquivos_usados(pasta_videos_id)

    # * [EXPLICAÇÃO] → Dado da API é caro, sempre grava — mesmo sendo
    #                  verificação individual (não a varredura completa),
    #                  nunca descarta o resultado depois de usado 1 vez.
    SnapshotArquivosDrive.objects.update_or_create(
        produto=produto,
        defaults={
            'pasta_encontrada': True, 'motivo_nao_encontrado': None,
            'arquivos_videos': arquivos_brutos, 'arquivos_usados': arquivos_usados,
        },
    )

    return parsear_arquivos_produto(produto.marca, produto.ean, arquivos_brutos + arquivos_usados)


# Função Objetivo: Verifica 1 produto — avança quantos pontos os arquivos do
# Drive permitirem, numa passada só. Devolve (pontos_marcados,
# motivo_pasta_nao_encontrada, diagnostico_do_ponto_onde_travou).
def verificar_produto_no_drive(produto_id):
    from produtos.models import Produto

    produto_inicial = Produto.objects.get(id=produto_id)
    estrutura_drive = _obter_estrutura_drive(produto_inicial)

    if not estrutura_drive.pasta_encontrada:
        return [], estrutura_drive.motivo_pasta_nao_encontrada, None

    pontos_marcados = []
    diagnostico = None

    while True:
        # * [EXPLICAÇÃO] → Sempre busca fresco — Django guarda em cache a 1ª
        #                  versão de progresso_producao_video/andamento_agenda
        #                  que acessar; salvar um objeto separado
        #                  (get_or_create) não atualiza esse cache.
        produto = Produto.objects.get(id=produto_id)
        progresso = getattr(produto, 'progresso_producao_video', None)
        andamento = getattr(produto, 'andamento_agenda', None)
        preparacoes_por_fase = montar_preparacoes_por_fase(produto)
        chave_atual = calcular_chave_atual(progresso, preparacoes_por_fase, andamento, produto=produto)

        if chave_atual not in CHAVES_QUE_DEPENDEM_DE_ARQUIVO:
            break

        satisfeito, diagnostico_local = avaliar_ponto_preparacao(chave_atual, estrutura_drive)
        if not satisfeito:
            diagnostico = diagnostico_local
            break

        if chave_atual == 'simples':
            progresso, _ = ProgressoProducaoVideo.objects.get_or_create(produto=produto)
            progresso.video_simples_status = StatusVideo.GERADO
            progresso.video_simples_marcado_em = timezone.now()
            progresso.save()
            pontos_marcados.append('Vídeo Simples')

        elif chave_atual == 'base':
            progresso, _ = ProgressoProducaoVideo.objects.get_or_create(produto=produto)
            progresso.video_base_status = StatusVideo.GERADO
            progresso.video_base_marcado_em = timezone.now()
            progresso.save()
            pontos_marcados.append('Vídeo Base')

        elif chave_atual in ('roteiros_diaria', 'roteiros_semanal', 'roteiros_mensal'):
            fase = FASE_DA_CHAVE_PREPARACAO[chave_atual]
            periodo_atual = obter_mapa_periodos_por_fase().get(fase)
            preparacao, _ = PreparacaoVideoFase.objects.get_or_create(produto=produto, fase=fase)
            preparacao.roteiros_gerados = True
            preparacao.roteiros_quantidade_no_clique = periodo_atual
            preparacao.roteiros_marcado_em = timezone.now()
            preparacao.save()
            pontos_marcados.append(f'Roteiros ({fase})')

        elif chave_atual in ('completos_diaria', 'completos_semanal', 'completos_mensal'):
            fase = FASE_DA_CHAVE_PREPARACAO[chave_atual]
            periodo_atual = obter_mapa_periodos_por_fase().get(fase)
            preparacao, _ = PreparacaoVideoFase.objects.get_or_create(produto=produto, fase=fase)
            preparacao.completos_produzidos = True
            preparacao.completos_quantidade_no_clique = periodo_atual
            preparacao.completos_marcado_em = timezone.now()
            preparacao.save()
            pontos_marcados.append(f'Completos ({fase})')

    if pontos_marcados:
        produto = Produto.objects.get(id=produto_id)
        sincronizar_roadmap_agenda_produto(produto)

    return pontos_marcados, None, diagnostico