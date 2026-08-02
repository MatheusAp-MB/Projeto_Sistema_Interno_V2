# agenda_videos/funcoes_auxiliares/roadmap_produto.py

# Função Objetivo: Monta os dados da "esteira" de rodadas de 1 produto — pro
# template usar (agenda_videos/parciais/estrutura_parcial_roadmap_produto.html,
# ainda pendente de reescrita própria — Frente 4).
# Reestruturação completa (30/07): antes eram 13 pontos fixos (calculados
# cruzando 3 tabelas). Agora é só o histórico real de CicloVideo do produto —
# rodadas PASSADAS + a ATUAL vêm do banco; rodadas FUTURAS são só PREVISTAS
# (calculadas a partir de ConfiguracaoFase, nunca criadas no banco antes da
# hora).
#
# * [EXPLICAÇÃO] → Janela: mostra só as últimas anteriores + a atual + um
# número limitado de futuras — nunca a lista inteira (Vídeo Trimestral não
# tem fim, não dá pra listar "todas as futuras"). Rodadas antigas continuam
# disponíveis no Histórico (historico_roadmap.py), só saem da esteira
# compacta — mesmo comportamento validado no mockup com o usuário e a equipe.

from dataclasses import dataclass

from django.db import models

from produtos.models import Produto
from agenda_videos.models import Fase, ConfiguracaoFase, CicloVideo, StatusPostagem

QUANTIDADE_ANTERIORES_NA_ESTEIRA = 2
QUANTIDADE_FUTURAS_NA_ESTEIRA = 3

ORDEM_ETAPAS = ['base', 'roteiro', 'completo', 'postar', 'replicar']
INDICE_DA_ETAPA = {
    'base': 0, 'roteiro': 1, 'completo': 2, 'postar': 3,
    'aguardando_aprovacao': 3, 'replicar': 4, 'concluido': 5,
}


# * [EXPLICAÇÃO] → Valor fixo repetido (cor da bolinha na esteira e no
#                  detalhe) — nunca string solta espalhada pelo código.
#                  TextChoices mesmo sem campo de banco nenhum usar isso:
#                  é só reaproveitar a mesma classe-base do projeto (Fase,
#                  StatusPostagem já usam), em vez de reinventar com Enum
#                  puro (que tem uma pegadinha conhecida de __str__ errado
#                  quando combinado com str).
class EstadoVisualRoadmap(models.TextChoices):
    CONCLUIDO = 'concluido', 'Concluído'
    ATUAL = 'atual', 'Atual'
    FUTURO = 'futuro', 'Futuro'
    AGUARDANDO = 'aguardando', 'Aguardando aprovação'
    RECUSADO = 'recusado', 'Recusado'
    APROVADO_CLARO = 'aprovado-claro', 'Aprovado, aguardando replicar'


# * [EXPLICAÇÃO] → Traduz o status bruto da postagem pro estado visual —
#                  único lugar do sistema que faz essa tradução, nunca deve
#                  ser reimplementada no template.
MAPA_ESTADO_VISUAL_POR_STATUS = {
    None: EstadoVisualRoadmap.ATUAL,
    StatusPostagem.AGUARDANDO_APROVACAO: EstadoVisualRoadmap.AGUARDANDO,
    StatusPostagem.RECUSADO: EstadoVisualRoadmap.RECUSADO,
    StatusPostagem.APROVADO: EstadoVisualRoadmap.APROVADO_CLARO,
    StatusPostagem.REPLICADO: EstadoVisualRoadmap.CONCLUIDO,
}

LEGENDAS_POR_ESTADO_VISUAL = {
    EstadoVisualRoadmap.RECUSADO: 'recusado',
    EstadoVisualRoadmap.AGUARDANDO: 'aguardando aprovação',
    EstadoVisualRoadmap.APROVADO_CLARO: 'aprovado, aguardando replicar',
}


# Objeto de domínio/processo (nunca salvo no banco) — 1 bolinha da esteira.
@dataclass(frozen=True)
class RodadaEsteira:
    id: str
    label: str
    ciclica: bool
    estado: EstadoVisualRoadmap
    legenda: str = ''


# Objeto de domínio/processo — 1 dos 5 passos fixos da rodada em andamento.
@dataclass(frozen=True)
class EtapaRodadaAtual:
    nome: str
    chave_badge: str
    estado: EstadoVisualRoadmap
    chave_acao: str | None = None


# Objeto de domínio/processo — retorno único e padronizado de calcular_roadmap_produto.
@dataclass(frozen=True)
class RoadmapProduto:
    rodadas: list[RodadaEsteira]
    etapas_rodada_atual: list[EtapaRodadaAtual]
    tem_rodada_atual: bool
    rodada_atual_id: str | None = None
    rodada_atual_label: str | None = None
    rodada_atual_legenda: str | None = None


# Função Objetivo: Monta o rótulo legível de 1 rodada (ex: "Vídeo Mensal #2");
# Simples nunca numera, porque só existe 1 ocorrência dela.
def montar_rotulo_rodada(fase: str, numero_ocorrencia: int) -> str:
    if fase == Fase.SIMPLES:
        return Fase(fase).label
    return f'{Fase(fase).label} #{numero_ocorrencia}'


# Função Objetivo: Traduz o status bruto (ou a ausência dele) no estado
# visual correspondente.
def _traduzir_status_em_estado_visual(status: str | None) -> EstadoVisualRoadmap:
    return MAPA_ESTADO_VISUAL_POR_STATUS.get(status, EstadoVisualRoadmap.ATUAL)


# Função Objetivo: Prevê as próximas N rodadas SEM criar nada no banco — só
# consulta ConfiguracaoFase pra saber quantas ocorrências cada fase tem e
# qual é a próxima. Vídeo Trimestral nunca lista instância individual — só 1
# placeholder ("contínua"), já que não tem fim.
def _prever_proximas_rodadas(fase_atual: str, numero_atual: int, quantidade_maxima: int) -> list[RodadaEsteira]:
    futuras: list[RodadaEsteira] = []
    config = ConfiguracaoFase.objects.select_related('proxima_fase').get(fase=fase_atual)
    fase, numero = fase_atual, numero_atual

    while len(futuras) < quantidade_maxima:
        if config.dentro_do_periodo(numero + 1):
            numero += 1
        else:
            config = config.proxima_fase
            if config is None:
                break
            fase, numero = config.fase, 1

        if config.periodo_continuo:
            futuras.append(RodadaEsteira(
                id=f'{fase}_continua', label=f'{Fase(fase).label} contínua',
                ciclica=True, estado=EstadoVisualRoadmap.FUTURO,
            ))
            break

        futuras.append(RodadaEsteira(
            id=f'{fase}_{numero}', label=montar_rotulo_rodada(fase, numero),
            ciclica=True, estado=EstadoVisualRoadmap.FUTURO,
        ))

    return futuras


# Função Objetivo: Monta os 5 passos fixos (Base/Roteiro/Completo/Postar/
# Replicar) da rodada em andamento, cada um com seu estado visual.
def _montar_etapas_rodada_atual(ciclo: CicloVideo) -> list[EtapaRodadaAtual]:
    etapa_real = ciclo.etapa_atual()
    indice_atual = INDICE_DA_ETAPA[etapa_real]
    estado_atual = _traduzir_status_em_estado_visual(ciclo.status)

    etapas = []
    for indice, nome in enumerate(ORDEM_ETAPAS):
        if indice < indice_atual:
            estado, chave_acao = EstadoVisualRoadmap.CONCLUIDO, None
        elif indice == indice_atual:
            estado, chave_acao = estado_atual, etapa_real
        else:
            estado, chave_acao = EstadoVisualRoadmap.FUTURO, None
        etapas.append(EtapaRodadaAtual(nome=nome.capitalize(), chave_badge=nome, estado=estado, chave_acao=chave_acao))
    return etapas


# Função Objetivo: Monta a esteira completa (anteriores + atual + previstas)
# e o detalhe da rodada em andamento de 1 produto — ponto único que o
# template tag "roadmap_produto" consome.
def calcular_roadmap_produto(produto: Produto) -> RoadmapProduto:
    ciclos = list(produto.ciclos_video.order_by('criado_em'))
    if not ciclos:
        return RoadmapProduto(rodadas=[], etapas_rodada_atual=[], tem_rodada_atual=False)

    ciclo_atual = ciclos[-1]  # o mais recente é sempre o "em andamento"
    anteriores = ciclos[:-1][-QUANTIDADE_ANTERIORES_NA_ESTEIRA:]

    rodadas = [
        RodadaEsteira(
            id=f'{ciclo.fase}_{ciclo.numero_ocorrencia}',
            label=montar_rotulo_rodada(ciclo.fase, ciclo.numero_ocorrencia),
            ciclica=ciclo.fase != Fase.SIMPLES,
            estado=EstadoVisualRoadmap.CONCLUIDO,
        )
        for ciclo in anteriores
    ]

    estado_atual = _traduzir_status_em_estado_visual(ciclo_atual.status)
    rodadas.append(RodadaEsteira(
        id=f'{ciclo_atual.fase}_{ciclo_atual.numero_ocorrencia}',
        label=montar_rotulo_rodada(ciclo_atual.fase, ciclo_atual.numero_ocorrencia),
        ciclica=ciclo_atual.fase != Fase.SIMPLES,
        estado=estado_atual,
        legenda=LEGENDAS_POR_ESTADO_VISUAL.get(estado_atual, f'vence {ciclo_atual.data_devida:%d/%m}'),
    ))

    rodadas.extend(_prever_proximas_rodadas(
        ciclo_atual.fase, ciclo_atual.numero_ocorrencia, QUANTIDADE_FUTURAS_NA_ESTEIRA,
    ))

    rodada_atual = rodadas[len(anteriores)]

    return RoadmapProduto(
        rodadas=rodadas,
        etapas_rodada_atual=_montar_etapas_rodada_atual(ciclo_atual),
        tem_rodada_atual=True,
        rodada_atual_id=rodada_atual.id,
        rodada_atual_label=rodada_atual.label,
        rodada_atual_legenda=rodada_atual.legenda,
    )