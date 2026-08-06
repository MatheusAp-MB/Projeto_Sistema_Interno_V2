# agenda_videos/funcoes_auxiliares/drive/verificador.py

# Função Objetivo: Verifica se o arquivo da ETAPA ATUAL da ocorrência de 1
# ciclo existe no Drive — se sim, marca a data de conclusão e confere a
# próxima etapa, repetindo até faltar arquivo ou chegar numa etapa que não
# depende de arquivo (postar/aguardando_aprovacao/etc.). Reativado (05/08)
# pro modelo novo (Base/Roteiro/Completo por OCORRÊNCIA) — estava desativado
# desde 30/07, quando o modelo antigo (13 pontos, pool por fase inteira) foi
# descartado sem redesenho próprio.
#
# 2 modos de entrada, MESMO loop de avanço por baixo (_avancar_etapas_com_estrutura):
#   - verificar_produto_no_drive(produto_id) — 1 produto, busca o Drive AO VIVO.
#   - verificar_todos_no_drive() — todo o catálogo; sincroniza o snapshot
#     (escaneador.sincronizar_snapshots_drive) e avança em cima dele, sem
#     bater no Drive de novo por produto.

from dataclasses import dataclass
from django.utils import timezone

from agenda_videos.models import Fase
from .constantes import PREFIXO_ARQUIVO_POR_FASE
from .localizador import LocalizadorArquivosProduto
from .parser import parsear_arquivos_produto, montar_produto_nao_encontrado

ETAPAS_QUE_DEPENDEM_DE_ARQUIVO = {'base', 'roteiro', 'completo'}
CAMPO_TIMESTAMP_POR_ETAPA = {
    'base': 'base_concluido_em', 'roteiro': 'roteiro_concluido_em', 'completo': 'completo_concluido_em',
}


@dataclass(frozen=True)
class DiagnosticoBloqueio:
    etapa: str
    mensagem: str


def _montar_nome_esperado(ciclo, etapa):
    prefixo = PREFIXO_ARQUIVO_POR_FASE[ciclo.fase]
    extensao = 'txt' if etapa == 'roteiro' else 'mp4'
    if ciclo.fase == Fase.SIMPLES:
        return f'{prefixo}_{etapa.capitalize()}.{extensao}'
    return f'{prefixo}_{ciclo.numero_ocorrencia:02d}_{etapa.capitalize()}.{extensao}'


# Função Objetivo: Avalia se o Drive (já navegado/parseado em
# ArquivosProdutoDrive) satisfaz a etapa atual da ocorrência de `ciclo` —
# devolve (satisfeito, diagnostico). Pura, sem chamada de rede nem escrita no
# banco — reutilizável por qualquer camada que só queira LER o estado, sem
# avançar nada.
def avaliar_etapa_no_drive(ciclo, estrutura_drive):
    etapa = ciclo.etapa_atual()
    if etapa not in ETAPAS_QUE_DEPENDEM_DE_ARQUIVO:
        return True, None

    arquivos_da_fase = estrutura_drive.obter_fase(ciclo.fase)
    ocorrencia = arquivos_da_fase.obter_ocorrencia(ciclo.numero_ocorrencia)
    arquivo = getattr(ocorrencia, etapa) if ocorrencia else None

    if arquivo is None:
        nome_esperado = _montar_nome_esperado(ciclo, etapa)
        return False, DiagnosticoBloqueio(etapa, f'Aguardando {etapa.capitalize()} — "{nome_esperado}" não encontrado.')
    return True, None


# Função Objetivo: O LOOP de avanço em si — reaproveitado tanto pela
# verificação individual quanto pela em massa. Recebe a estrutura do Drive JÁ
# PRONTA (nenhuma chamada de rede aqui dentro).
def _avancar_etapas_com_estrutura(produto_id, estrutura_drive):
    from produtos.models import Produto
    from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_indicadores_agenda_produto

    etapas_marcadas = []
    diagnostico = None
    produto = None

    while True:
        produto = Produto.objects.get(id=produto_id)
        ciclo = produto.ciclos_video.first()
        if ciclo is None:
            break

        etapa = ciclo.etapa_atual()
        if etapa not in ETAPAS_QUE_DEPENDEM_DE_ARQUIVO:
            break

        satisfeito, diagnostico_etapa = avaliar_etapa_no_drive(ciclo, estrutura_drive)
        if not satisfeito:
            diagnostico = diagnostico_etapa
            break

        campo_timestamp = CAMPO_TIMESTAMP_POR_ETAPA[etapa]
        setattr(ciclo, campo_timestamp, timezone.now())
        ciclo.save(update_fields=[campo_timestamp])
        etapas_marcadas.append(etapa)

    if etapas_marcadas and produto is not None:
        sincronizar_indicadores_agenda_produto(produto)

    return etapas_marcadas, diagnostico


def verificar_produto_no_drive(produto_id):
    from produtos.models import Produto

    produto = Produto.objects.get(id=produto_id)
    localizador = LocalizadorArquivosProduto()
    encontrado, arquivos_brutos, motivo, _ = localizador.localizar_arquivos(produto.marca, produto.ean)

    if not encontrado:
        estrutura_drive = montar_produto_nao_encontrado(produto.marca, produto.ean, motivo)
        return [], estrutura_drive, DiagnosticoBloqueio('pasta', motivo)

    estrutura_drive = parsear_arquivos_produto(produto.marca, produto.ean, arquivos_brutos)
    etapas_marcadas, diagnostico = _avancar_etapas_com_estrutura(produto_id, estrutura_drive)
    return etapas_marcadas, estrutura_drive, diagnostico


def verificar_todos_no_drive():
    from agenda_videos.models import SnapshotArquivosDrive
    from .escaneador import sincronizar_snapshots_drive

    _, sem_produto_no_banco, produto_ids_atualizados = sincronizar_snapshots_drive()

    resumo_por_produto = []
    for produto_id in produto_ids_atualizados:
        snapshot = SnapshotArquivosDrive.objects.select_related('produto').get(produto_id=produto_id)
        produto = snapshot.produto
        estrutura_drive = parsear_arquivos_produto(produto.marca, produto.ean, snapshot.arquivos_videos)
        etapas_marcadas, _ = _avancar_etapas_com_estrutura(produto_id, estrutura_drive)
        if etapas_marcadas:
            resumo_por_produto.append((produto_id, etapas_marcadas))

    return resumo_por_produto, sem_produto_no_banco