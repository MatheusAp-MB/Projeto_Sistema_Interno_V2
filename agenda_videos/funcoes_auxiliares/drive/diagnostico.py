# agenda_videos/funcoes_auxiliares/drive/diagnostico.py

# Função Objetivo: Devolve o diagnóstico de preparação (badge) de 1 produto,
# SEMPRE lendo do snapshot já salvo (SnapshotArquivosDrive) — nunca chama o
# Drive ao vivo. Por isso pode ser calculado em toda visita à tela, de graça,
# sem repetir o erro de performance já corrigido antes nesta sessão
# (tem_video_reprovado, que rodava consulta cara toda vez).
#
# Só retorna diagnóstico quando o ponto ATUAL do roadmap depende de arquivo
# (Simples/Base/Roteiros/Completos de qualquer fase) — pontos cíclicos,
# Agendamento e Otimizado nunca mostram esse badge.

from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_chave_atual, montar_preparacoes_por_fase
from .verificador import CHAVES_QUE_DEPENDEM_DE_ARQUIVO, avaliar_ponto_preparacao, DiagnosticoBloqueio
from .parser import parsear_arquivos_produto


def calcular_diagnostico_preparo_drive(produto):
    andamento = getattr(produto, 'andamento_agenda', None)
    progresso = getattr(produto, 'progresso_producao_video', None)
    preparacoes_por_fase = montar_preparacoes_por_fase(produto)
    chave_atual = calcular_chave_atual(progresso, preparacoes_por_fase, andamento, produto=produto)

    if chave_atual not in CHAVES_QUE_DEPENDEM_DE_ARQUIVO:
        return None

    snapshot = getattr(produto, 'snapshot_drive', None)
    if snapshot is None or snapshot.expirado:
        return DiagnosticoBloqueio(chave_atual, 'Não sincronizado com o Drive.')

    if not snapshot.pasta_encontrada:
        return DiagnosticoBloqueio(chave_atual, snapshot.motivo_nao_encontrado or 'Pasta não encontrada no Drive.')

    estrutura_drive = parsear_arquivos_produto(
        produto.marca, produto.ean, snapshot.arquivos_videos + snapshot.arquivos_usados,
    )
    satisfeito, diagnostico = avaliar_ponto_preparacao(chave_atual, estrutura_drive)
    return None if satisfeito else diagnostico