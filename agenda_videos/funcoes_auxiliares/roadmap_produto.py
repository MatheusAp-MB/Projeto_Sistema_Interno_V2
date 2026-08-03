# agenda_videos/funcoes_auxiliares/roadmap_produto.py

# Função Objetivo: Monta os dados da "esteira" de rodadas de 1 produto — pro
# template usar (agenda_videos/parciais/estrutura_parcial_roadmap_produto.html).
# Reestruturação (01/08, 2ª rodada) — esteira deixa de ser janela deslizante
# (2 anteriores + atual + 3 futuras) e passa a mostrar o CAMINHO FINITO
# INTEIRO, sempre: Simples, cada ocorrência de Vídeo Mensal, e 1 ponto único
# "Vídeo Trimestral contínua" no fim (Trimestral não tem fim, nunca lista
# ocorrência individual dele). O caminho é sempre construído a partir de
# ConfiguracaoFase (nunca hardcoded).
# Reestruturação (02/08, 3ª rodada) — todo produto mostra o roadmap completo
# desde sempre, mesmo sem nenhum CicloVideo no banco ainda (Simples aparece
# direto como "atual"). Ganha 1 ponto extra clicável ("Agendar"), só visível
# entre o Simples replicado e o Vídeo Mensal #1 ainda não criado.

from dataclasses import dataclass

from django.db import models

from produtos.models import Produto
from agenda_videos.models import Fase, ConfiguracaoFase, CicloVideo, StatusPostagem

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
#                  quando combinado com str). Ordem de declaração = ordem
#                  de exibição na legenda (validada no mockup, 01/08).
class EstadoVisualRoadmap(models.TextChoices):
    CONCLUIDO = 'concluido', 'Concluído'
    ATUAL = 'atual', 'Atual'
    FUTURO = 'futuro', 'Futuro'
    AGUARDANDO = 'aguardando', 'Aguardando aprovação'
    APROVADO_CLARO = 'aprovado-claro', 'Aprovado, aguardando replicar'
    RECUSADO = 'recusado', 'Recusado'


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
    clicavel: bool = False


# Objeto de domínio/processo — 1 dos 5 passos fixos da rodada em andamento.
@dataclass(frozen=True)
class EtapaRodadaAtual:
    nome: str
    chave_badge: str
    estado: EstadoVisualRoadmap
    chave_acao: str | None = None


# Objeto de domínio/processo — 1 item do caminho fixo de fases. numero=None
# marca o ponto único da fase contínua (nunca numera ocorrência dela).
@dataclass(frozen=True)
class _PontoCaminho:
    fase: str
    numero: int | None


# Objeto de domínio/processo — caminho fixo completo + aviso de transição.
@dataclass(frozen=True)
class CaminhoCompletoFases:
    pontos: list[_PontoCaminho]
    aviso_transicao_continua: str


# Objeto de domínio/processo — retorno único e padronizado de calcular_roadmap_produto.
@dataclass(frozen=True)
class RoadmapProduto:
    rodadas: list[RodadaEsteira]
    etapas_rodada_atual: list[EtapaRodadaAtual]
    rodada_atual_id: str | None = None
    rodada_atual_label: str | None = None
    rodada_atual_legenda: str | None = None
    aviso_transicao_continua: str = ''


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


# Função Objetivo: Monta o caminho fixo inteiro de fases (Simples + cada
# ocorrência de toda fase finita + 1 ponto pra fase contínua) e o aviso de
# transição pra ela — sempre a partir de ConfiguracaoFase, nunca hardcoded,
# pra nunca dessincronizar se a régua de fases mudar no admin.
def _montar_caminho_completo_fases() -> CaminhoCompletoFases:
    pontos: list[_PontoCaminho] = []
    aviso = ''
    config = ConfiguracaoFase.objects.select_related('proxima_fase').get(fase=Fase.SIMPLES)

    while True:
        if config.periodo_continuo:
            pontos.append(_PontoCaminho(fase=config.fase, numero=None))
            break

        pontos.extend(_PontoCaminho(fase=config.fase, numero=n) for n in range(1, config.periodo + 1))

        proxima = config.proxima_fase
        if proxima is None:
            break
        if proxima.periodo_continuo:
            aviso = (
                f'Depois da #{config.periodo}, entra a fase {Fase(proxima.fase).label} '
                f'(a cada {proxima.distancia_dias_corridos} dias, pra sempre) — nunca conclui.'
            )
        config = proxima

    return CaminhoCompletoFases(pontos=pontos, aviso_transicao_continua=aviso)


# Função Objetivo: Localiza a posição do ciclo atual dentro do caminho fixo —
# ponto de fase contínua casa por FASE só (nunca por número, já que não
# numera ocorrência individual dela).
def _localizar_indice_atual(pontos: list[_PontoCaminho], ciclo_atual: CicloVideo) -> int:
    for indice, ponto in enumerate(pontos):
        if ponto.numero is None:
            if ciclo_atual.fase == ponto.fase:
                return indice
        elif ponto.fase == ciclo_atual.fase and ponto.numero == ciclo_atual.numero_ocorrencia:
            return indice
    return len(pontos) - 1


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


# Função Objetivo: Monta a esteira completa (caminho fixo inteiro, do começo
# ao fim) e o detalhe da rodada em andamento de 1 produto — ponto único que
# o template tag "roadmap_produto" consome.
def calcular_roadmap_produto(produto: Produto) -> RoadmapProduto:
    # * [EXPLICAÇÃO] → Sem nenhum CicloVideo ainda, o produto já mostra o
    #                  roadmap completo mesmo assim (02/08) — Simples aparece
    #                  direto como "atual", Base clicável, SEM criar nada no
    #                  banco só de exibir a tela (instância não salva, só de
    #                  leitura — a criação real acontece no 1º clique real,
    #                  em view_marcar_ponto_roadmap).
    # Desempate por 'id' — 2 CicloVideo criados muito próximos podem
    # empatar no timestamp de criado_em (comum no Windows); id sempre
    # cresce na ordem de criação, nunca empata.
    ciclos = list(produto.ciclos_video.order_by('criado_em', 'id'))
    ciclo_atual = ciclos[-1] if ciclos else CicloVideo(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    caminho = _montar_caminho_completo_fases()
    indice_atual = _localizar_indice_atual(caminho.pontos, ciclo_atual)
    estado_atual = _traduzir_status_em_estado_visual(ciclo_atual.status)

    rodadas = []
    for indice, ponto in enumerate(caminho.pontos):
        if ponto.numero is None:
            identificador = f'{ponto.fase}_continua'
            rotulo = f'{Fase(ponto.fase).label} contínua'
        else:
            identificador = f'{ponto.fase}_{ponto.numero}'
            rotulo = montar_rotulo_rodada(ponto.fase, ponto.numero)

        if indice < indice_atual:
            estado, legenda = EstadoVisualRoadmap.CONCLUIDO, ''
        elif indice == indice_atual:
            estado = estado_atual
            if estado_atual in LEGENDAS_POR_ESTADO_VISUAL:
                legenda = LEGENDAS_POR_ESTADO_VISUAL[estado_atual]
            elif ciclo_atual.data_devida is not None:
                legenda = f'vence {ciclo_atual.data_devida:%d/%m}'
            else:
                legenda = ''  # Simples nunca vence — sem legenda de data
        else:
            estado, legenda = EstadoVisualRoadmap.FUTURO, ''

        rodadas.append(RodadaEsteira(
            id=identificador, label=rotulo,
            ciclica=(ponto.fase != Fase.SIMPLES), estado=estado, legenda=legenda,
        ))

    rodada_atual = rodadas[indice_atual]

    # * [EXPLICAÇÃO] → Ponto extra, só existe nesta janela específica: Simples
    #                  já replicado, Vídeo Mensal #1 ainda não criado (clique
    #                  manual de "Agendar" pendente). Depois de agendado, esse
    #                  ponto some — a esteira volta a ser só o caminho fixo.
    if ciclo_atual.fase == Fase.SIMPLES and ciclo_atual.etapa_atual() == 'concluido':
        rodadas.insert(1, RodadaEsteira(
            id='agendar', label='Agendar', ciclica=False,
            estado=EstadoVisualRoadmap.ATUAL, clicavel=True,
        ))

    return RoadmapProduto(
        rodadas=rodadas,
        etapas_rodada_atual=_montar_etapas_rodada_atual(ciclo_atual),
        rodada_atual_id=rodada_atual.id,
        rodada_atual_label=rodada_atual.label,
        rodada_atual_legenda=rodada_atual.legenda,
        aviso_transicao_continua=caminho.aviso_transicao_continua,
    )