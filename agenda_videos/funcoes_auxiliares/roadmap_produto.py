# agenda_videos/funcoes_auxiliares/roadmap_produto.py

# Função Objetivo: Calcula o "mapa de missão" (roadmap) de 1 produto — os 13 pontos do
# ciclo de vida de vídeo, qual está concluído/atual/futuro, e se é clicável.
#
# Refatorado (25/07) — de 9 pra 13 pontos. Roteiros/Completos deixaram de ser
# únicos pro produto inteiro e viraram POR FASE (Diária/Semanal/Mensal) — regra
# confirmada: só compensa preparar o pool de uma fase quando o produto CHEGA nela
# (nunca com antecedência), então cada fase precisa da sua própria checagem de
# "roteiros prontos / completos prontos" antes de liberar o ponto cíclico dela.

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from django.core.cache import cache


class EstadoPonto(str, Enum):
    CONCLUIDO = 'concluido'
    ATUAL = 'atual'
    FUTURO = 'futuro'


@dataclass(frozen=True)
class UnidadeTempoFase:
    singular: str
    plural: str
    preposicao: str


@dataclass(frozen=True)
class DefinicaoPonto:
    chave: str
    rotulo: str
    rotulo_completo: str
    eh_editavel: bool = False
    unidade_tempo: Optional[UnidadeTempoFase] = None
    explicacoes_por_estado: Optional[dict] = None
    texto_confirmacao: str = ''

    @property
    def eh_ciclico(self):
        return self.unidade_tempo is not None


@dataclass
class PontoRoadmap:
    chave: str
    rotulo: str
    rotulo_completo: str
    explicacao: str
    estado: EstadoPonto
    clicavel: bool
    contador: Optional[str] = None
    texto_confirmacao: str = ''
    # * [EXPLICAÇÃO] → Só preenchido nos 3 pontos cíclicos, quando ATIVOS — o sub-
    #                  estado da Postagem em andamento (None = ainda não postou,
    #                  'aguardando'/'recusado'/'aprovado' = já postou, aguardando
    #                  ou já resolvido). Muda a cor da bolinha, pra nunca parecer
    #                  "travado" sem o usuário entender que precisa clicar de novo.
    sub_estado_postagem: Optional[str] = None


@dataclass
class RoadmapProduto:
    produto_id: int
    pontos: list = field(default_factory=list)


# * [EXPLICAÇÃO] → "Roteiros"/"Completos" de preparação por fase (usados fora do
#                  ciclo, na checagem de "pronto pra entrar/avançar de fase").
CHAVES_PREPARACAO_POR_FASE = {
    'diaria': ('roteiros_diaria', 'completos_diaria'),
    'semanal': ('roteiros_semanal', 'completos_semanal'),
    'mensal': ('roteiros_mensal', 'completos_mensal'),
}

# * [EXPLICAÇÃO] → Mapeamento inverso — de qualquer chave de preparação por fase
#                  pra qual FASE ela pertence (usado pra buscar o período certo e o
#                  PreparacaoVideoFase certo, sem repetir esse "if" em cada função).
FASE_DA_CHAVE_PREPARACAO = {
    chave: fase
    for fase, (chave_roteiros, chave_completos) in CHAVES_PREPARACAO_POR_FASE.items()
    for chave in (chave_roteiros, chave_completos)
}

DEFINICOES_PONTOS = [
    DefinicaoPonto(
        chave='simples', rotulo='Simples', rotulo_completo='Vídeos Simples Gerados',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.ATUAL: 'Vídeo simples (imagens + música de fundo) ainda não foi gerado — é a versão mínima usada no 1º anúncio do produto.',
            EstadoPonto.CONCLUIDO: 'Vídeo simples (imagens + música de fundo) já foi gerado — usado no 1º anúncio do produto.',
        },
        texto_confirmacao='Ao marcar o vídeo simples como gerado, você assume que já foi produzido um vídeo com imagens do produto e música de fundo — a versão mínima, usada no 1º anúncio.',
    ),
    DefinicaoPonto(
        chave='base', rotulo='Base', rotulo_completo='Vídeos Base Gerados',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Vídeo-base ainda não pode ser gerado — depende do Vídeo Simples estar pronto primeiro.',
            EstadoPonto.ATUAL: 'Vídeo-base ainda não foi gerado — vira a base das versões narradas (pode ser o mesmo Simples ou um novo, mais elaborado).',
            EstadoPonto.CONCLUIDO: 'Vídeo-base já foi gerado — pronto pra virar as versões narradas.',
        },
        texto_confirmacao='Ao marcar o vídeo base como gerado, você assume que já existe o vídeo que vai servir de base pras versões narradas (pode ser o mesmo Simples ou um novo, mais elaborado).',
    ),
    DefinicaoPonto(
        chave='roteiros_diaria', rotulo='Roteiros', rotulo_completo='Roteiros Gerados (Diária)',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Roteiros da Diária ainda não podem ser escritos — depende do Vídeo Base estar pronto primeiro.',
            EstadoPonto.ATUAL: 'Roteiros da Fase Diária ainda não foram escritos — 1 por dia.',
            EstadoPonto.CONCLUIDO: 'Roteiros da Fase Diária já foram escritos — prontos pra virar os vídeos completos.',
        },
        texto_confirmacao='Ao marcar os roteiros da Diária como gerados, você assume que já foram escritos',
    ),
    DefinicaoPonto(
        chave='completos_diaria', rotulo='Completos', rotulo_completo='Vídeos Completos Gerados (Diária)',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Vídeos completos da Diária ainda não podem ser produzidos — depende dos Roteiros estarem prontos primeiro.',
            EstadoPonto.ATUAL: 'Vídeos completos da Fase Diária ainda não foram produzidos — é o pool pronto pra postar.',
            EstadoPonto.CONCLUIDO: 'Vídeos completos da Fase Diária já foram produzidos — pool pronto.',
        },
        texto_confirmacao='Ao marcar os vídeos completos da Diária como gerados, você assume que já foi produzido o pool inteiro, pronto pra postar.',
    ),
    DefinicaoPonto(
        chave='pronto_agendamento', rotulo='Agendamento', rotulo_completo='Pronto para Agendamento',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Ainda não chegou a vez de agendar — depende de terminar a produção de vídeo primeiro.',
            EstadoPonto.ATUAL: 'Tudo pronto! Escolha em qual fase esse produto deve começar.',
            EstadoPonto.CONCLUIDO: 'Já entrou na Agenda — seguiu pro ciclo de postagem.',
        },
    ),
    DefinicaoPonto(
        chave='diaria', rotulo='Diária', rotulo_completo='Fase Diária',
        eh_editavel=True, unidade_tempo=UnidadeTempoFase('Dia', 'dias', 'no'),
    ),
    DefinicaoPonto(
        chave='roteiros_semanal', rotulo='Roteiros', rotulo_completo='Roteiros Gerados (Semanal)',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Ainda não chegou a vez — só é preciso preparar a Semanal quando o produto chegar nela.',
            EstadoPonto.ATUAL: 'Roteiros da Fase Semanal ainda não foram escritos — 1 por semana.',
            EstadoPonto.CONCLUIDO: 'Roteiros da Fase Semanal já foram escritos.',
        },
        texto_confirmacao='Ao marcar os roteiros da Semanal como gerados, você assume que já foram escritos',
    ),
    DefinicaoPonto(
        chave='completos_semanal', rotulo='Completos', rotulo_completo='Vídeos Completos Gerados (Semanal)',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Vídeos completos da Semanal ainda não podem ser produzidos — depende dos Roteiros estarem prontos primeiro.',
            EstadoPonto.ATUAL: 'Vídeos completos da Fase Semanal ainda não foram produzidos.',
            EstadoPonto.CONCLUIDO: 'Vídeos completos da Fase Semanal já foram produzidos.',
        },
        texto_confirmacao='Ao marcar os vídeos completos da Semanal como gerados, você assume que já foi produzido o pool inteiro dessa fase.',
    ),
    DefinicaoPonto(
        chave='semanal', rotulo='Semanal', rotulo_completo='Fase Semanal',
        eh_editavel=True, unidade_tempo=UnidadeTempoFase('Semana', 'semanas', 'na'),
    ),
    DefinicaoPonto(
        chave='roteiros_mensal', rotulo='Roteiros', rotulo_completo='Roteiros Gerados (Mensal)',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Ainda não chegou a vez — só é preciso preparar a Mensal quando o produto chegar nela.',
            EstadoPonto.ATUAL: 'Roteiros da Fase Mensal ainda não foram escritos — 1 por mês.',
            EstadoPonto.CONCLUIDO: 'Roteiros da Fase Mensal já foram escritos.',
        },
        texto_confirmacao='Ao marcar os roteiros da Mensal como gerados, você assume que já foram escritos',
    ),
    DefinicaoPonto(
        chave='completos_mensal', rotulo='Completos', rotulo_completo='Vídeos Completos Gerados (Mensal)',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Vídeos completos da Mensal ainda não podem ser produzidos — depende dos Roteiros estarem prontos primeiro.',
            EstadoPonto.ATUAL: 'Vídeos completos da Fase Mensal ainda não foram produzidos.',
            EstadoPonto.CONCLUIDO: 'Vídeos completos da Fase Mensal já foram produzidos.',
        },
        texto_confirmacao='Ao marcar os vídeos completos da Mensal como gerados, você assume que já foi produzido o pool inteiro dessa fase.',
    ),
    DefinicaoPonto(
        chave='mensal', rotulo='Mensal', rotulo_completo='Fase Mensal',
        eh_editavel=True, unidade_tempo=UnidadeTempoFase('Mês', 'meses', 'no'),
    ),
    DefinicaoPonto(
        chave='otimizado', rotulo='Otimizado', rotulo_completo='Anúncio Otimizado',
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Ainda não otimizado — o produto ainda está no ciclo de divulgação (Diária/Semanal/Mensal).',
            EstadoPonto.ATUAL: 'Ciclo de divulgação encerrado — o produto não tem mais obrigação de vídeo na Agenda.',
        },
    ),
]


def obter_mapa_periodos_por_fase():
    mapa = cache.get('agenda_videos_mapa_periodos_fase')
    if mapa is None:
        from agenda_videos.models import ConfiguracaoFase
        mapa = {c.fase: c.periodo for c in ConfiguracaoFase.objects.all()}
        cache.set('agenda_videos_mapa_periodos_fase', mapa, 300)
    return mapa


# Função Objetivo: Busca (num dict já carregado, sem query nova) a preparação de 1 fase.
def _obter_preparacao(preparacoes_por_fase, fase):
    return preparacoes_por_fase.get(fase) if preparacoes_por_fase else None


# Função Objetivo: Decide qual chave é "o atual", seguindo a ordem travada (13 pontos).
# Explicação em detalhe: "preparacoes_por_fase" é um dict {fase: PreparacaoVideoFase},
# carregado 1 vez por quem chama (nunca 1 query por fase aqui dentro).
def calcular_chave_atual(progresso, preparacoes_por_fase, andamento):
    if progresso is None or progresso.video_simples_status != 'gerado':
        return 'simples'
    if progresso.video_base_status != 'gerado':
        return 'base'

    prep_diaria = _obter_preparacao(preparacoes_por_fase, 'diaria')
    if prep_diaria is None or not prep_diaria.roteiros_gerados:
        return 'roteiros_diaria'
    if not prep_diaria.completos_produzidos:
        return 'completos_diaria'

    if andamento is None:
        return 'pronto_agendamento'
    if andamento.concluido:
        return 'otimizado'

    fase_atual = andamento.fase_atual.fase
    if fase_atual == 'diaria':
        return 'diaria'

    prep_semanal = _obter_preparacao(preparacoes_por_fase, 'semanal')
    if prep_semanal is None or not prep_semanal.roteiros_gerados:
        return 'roteiros_semanal'
    if not prep_semanal.completos_produzidos:
        return 'completos_semanal'
    if fase_atual == 'semanal':
        return 'semanal'

    prep_mensal = _obter_preparacao(preparacoes_por_fase, 'mensal')
    if prep_mensal is None or not prep_mensal.roteiros_gerados:
        return 'roteiros_mensal'
    if not prep_mensal.completos_produzidos:
        return 'completos_mensal'
    return 'mensal'


def _montar_rotulo_ciclico(unidade, atual, periodo):
    largura = len(str(periodo))
    return f'{unidade.singular} {str(atual).zfill(largura)} de {periodo}'


def _montar_explicacao_ciclica(unidade, estado, atual, periodo, definicao_seguinte):
    if estado == EstadoPonto.FUTURO:
        return (
            f'Ainda não começou. Serão {periodo} {unidade.plural}, '
            f'1 vídeo por {unidade.singular.lower()}, quando chegar a vez.'
        )
    if estado == EstadoPonto.CONCLUIDO:
        return f'Concluída — foram publicados os {periodo} {unidade.plural}.'

    ja_publicados = atual - 1
    if atual < periodo:
        proximo = f'o {unidade.singular.lower()} {atual + 1}'
    else:
        proximo = definicao_seguinte.rotulo_completo

    return (
        f'Você está {unidade.preposicao} {unidade.singular.lower()} {atual} de {periodo}. '
        f'Já foram publicados {ja_publicados}. Ao concluir e replicar, avança para: {proximo}.'
    )


# Função Objetivo: Busca o sub-estado da Postagem mais recente da ocorrência ativa.
# Explicação em detalhe: só chamada quando o ponto ativo é cíclico (poucos produtos
# de verdade — os que já estão agendados), então o custo de 1 query a mais aqui é
# aceitável, sem virar N+1 numa lista de milhares de "Não Agendado".
def _buscar_sub_estado_postagem(produto, chave, andamento):
    from agenda_videos.models import Postagem, StatusPostagem

    postagem_atual = Postagem.objects.filter(
        produto=produto, fase=chave, numero_ocorrencia=andamento.ocorrencia_atual,
    ).order_by('-criado_em').first()

    if postagem_atual is None:
        return None
    return {
        StatusPostagem.AGUARDANDO_APROVACAO: 'aguardando',
        StatusPostagem.RECUSADO: 'recusado',
        StatusPostagem.APROVADO: 'aprovado',
    }.get(postagem_atual.status)


# Função Objetivo: Monta o roadmap completo (13 pontos) de 1 produto.
def calcular_roadmap_produto(produto):
    progresso = getattr(produto, 'progresso_producao_video', None)
    andamento = getattr(produto, 'andamento_agenda', None)

    # * [EXPLICAÇÃO] → Carrega as 3 preparações (Diária/Semanal/Mensal) numa query
    #                  só, monta um dict — nunca 1 query por fase depois.
    preparacoes_por_fase = {
        p.fase: p for p in produto.preparacoes_video.all()
    } if produto.pk else {}

    chave_atual = calcular_chave_atual(progresso, preparacoes_por_fase, andamento)
    ordem_chaves = [definicao.chave for definicao in DEFINICOES_PONTOS]
    indice_atual = ordem_chaves.index(chave_atual)
    mapa_periodos = obter_mapa_periodos_por_fase()

    pontos = []
    for indice, definicao in enumerate(DEFINICOES_PONTOS):
        if indice < indice_atual:
            estado = EstadoPonto.CONCLUIDO
        elif indice == indice_atual:
            estado = EstadoPonto.ATUAL
        else:
            estado = EstadoPonto.FUTURO

        clicavel = estado == EstadoPonto.ATUAL and definicao.eh_editavel
        contador = None
        texto_confirmacao = definicao.texto_confirmacao

        if definicao.eh_ciclico:
            periodo = mapa_periodos.get(definicao.chave)
            if periodo:
                if estado == EstadoPonto.ATUAL:
                    atual = andamento.ocorrencia_atual
                elif estado == EstadoPonto.CONCLUIDO:
                    atual = periodo
                else:
                    atual = 0

                definicao_seguinte = DEFINICOES_PONTOS[indice + 1]
                contador = _montar_rotulo_ciclico(definicao.unidade_tempo, atual, periodo)
                explicacao = _montar_explicacao_ciclica(
                    definicao.unidade_tempo, estado, atual, periodo, definicao_seguinte,
                )
            else:
                explicacao = ''
        elif definicao.chave in FASE_DA_CHAVE_PREPARACAO and 'roteiros' in definicao.chave:
            # * [EXPLICAÇÃO] → "Roteiros de X" tem número dinâmico (o período
            #                  daquela fase) — injeta no contador, igual "Dia 3 de 10".
            fase = FASE_DA_CHAVE_PREPARACAO[definicao.chave]
            periodo = mapa_periodos.get(fase)
            if periodo:
                contador = f'{periodo} necessários'
            explicacao = definicao.explicacoes_por_estado.get(
                estado, definicao.explicacoes_por_estado.get(EstadoPonto.ATUAL, ''),
            )
        else:
            explicacao = definicao.explicacoes_por_estado.get(
                estado, definicao.explicacoes_por_estado.get(EstadoPonto.ATUAL, ''),
            )

        sub_estado_postagem = None
        if definicao.eh_ciclico and estado == EstadoPonto.ATUAL:
            sub_estado_postagem = _buscar_sub_estado_postagem(produto, definicao.chave, andamento)

        pontos.append(PontoRoadmap(
            chave=definicao.chave, rotulo=definicao.rotulo, rotulo_completo=definicao.rotulo_completo,
            explicacao=explicacao, estado=estado, clicavel=clicavel, contador=contador,
            texto_confirmacao=texto_confirmacao, sub_estado_postagem=sub_estado_postagem,
        ))

    return RoadmapProduto(produto_id=produto.id, pontos=pontos)