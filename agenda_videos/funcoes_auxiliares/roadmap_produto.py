# agenda_videos/funcoes_auxiliares/roadmap_produto.py

# Função Objetivo: Calcula o "mapa de missão" (roadmap) de 1 produto — os 9 pontos do
# ciclo de vida de vídeo, qual está concluído/atual/futuro, e se é clicável.
# Explicação em detalhe: é o produto quem "possui" o roadmap (não é conceito de Diária,
# Semanal ou A Fazer) — por isso vira template tag, reaproveitável em QUALQUER tela que
# mostre produto, sem duplicar lógica. Ordem é travada (nunca fora de ordem, confirmado
# com o usuário) — só o ponto "atual" pode ser clicável, e só entre os 4 primeiros
# (preparação); os 5 seguintes são sempre só leitura (calculados pelo sistema).
#
# Refatorado (24/07) — cada ponto agora é 1 dataclass só (chave/editável/unidade de
# tempo/explicações tudo junto, nada em conjunto externo pra manter sincronizado à mão).
# "Próxima fase" não é mais dicionário separado — é simplesmente o próximo item desta
# mesma lista ordenada (elimina uma 2ª fonte de verdade pra um fato que a própria ordem
# da lista já contava).

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
    # * [EXPLICAÇÃO] → Presença deste campo (não-None) já DEFINE que o ponto é
    #                  cíclico — não precisa de um "CHAVES_FASES_CICLICAS" à parte.
    unidade_tempo: Optional[UnidadeTempoFase] = None
    # * [EXPLICAÇÃO] → None nos pontos cíclicos (o texto é sempre calculado com o
    #                  número real do produto, nunca fixo — ver _montar_explicacao_ciclica).
    explicacoes_por_estado: Optional[dict] = None

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


@dataclass
class RoadmapProduto:
    produto_id: int
    pontos: list = field(default_factory=list)


# * [EXPLICAÇÃO] → Ordem travada — nunca reordenar sem revisar _calcular_chave_atual
#                  logo abaixo, junto. "Próxima fase" (usada só nos 3 pontos cíclicos)
#                  é sempre o item seguinte desta mesma lista — por isso "Otimizado"
#                  precisa continuar logo depois de "Mensal", e "Semanal" logo depois
#                  de "Diária": a ordem da lista É a fonte de verdade da sequência.
DEFINICOES_PONTOS = [
    DefinicaoPonto(
        chave='simples', rotulo='Simples', rotulo_completo='Vídeos Simples Gerados',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.ATUAL: 'Vídeo simples (imagens + música de fundo) ainda não foi gerado — é a versão mínima usada no 1º anúncio do produto.',
            EstadoPonto.CONCLUIDO: 'Vídeo simples (imagens + música de fundo) já foi gerado — usado no 1º anúncio do produto.',
        },
    ),
    DefinicaoPonto(
        chave='base', rotulo='Base', rotulo_completo='Vídeos Base Gerados',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Vídeo-base ainda não pode ser gerado — depende do Vídeo Simples estar pronto primeiro.',
            EstadoPonto.ATUAL: 'Vídeo-base ainda não foi gerado — vira a base das versões narradas (pode ser o mesmo Simples ou um novo, mais elaborado).',
            EstadoPonto.CONCLUIDO: 'Vídeo-base já foi gerado — pronto pra virar as versões narradas.',
        },
    ),
    DefinicaoPonto(
        chave='roteiros', rotulo='Roteiros', rotulo_completo='Roteiros Gerados',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Roteiros ainda não podem ser escritos — depende do Vídeo Base estar pronto primeiro.',
            EstadoPonto.ATUAL: 'Roteiros (texto de narração/legenda) ainda não foram escritos — 1 por dia da Fase Diária.',
            EstadoPonto.CONCLUIDO: 'Roteiros já foram escritos — prontos pra virar os vídeos completos.',
        },
    ),
    DefinicaoPonto(
        chave='completos', rotulo='Completos', rotulo_completo='Vídeos Completos Gerados',
        eh_editavel=True,
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Vídeos completos ainda não podem ser produzidos — depende dos Roteiros estarem prontos primeiro.',
            EstadoPonto.ATUAL: 'Vídeos completos (vídeo-base + narração de cada roteiro) ainda não foram produzidos — é o pool pronto pra postar na Fase Diária.',
            EstadoPonto.CONCLUIDO: 'Vídeos completos já foram produzidos — pool pronto, só falta entrar na Agenda.',
        },
    ),
    DefinicaoPonto(
        chave='pronto_agendamento', rotulo='Agendamento', rotulo_completo='Pronto para Agendamento',
        explicacoes_por_estado={
            EstadoPonto.FUTURO: 'Ainda não chegou a vez de agendar — depende de terminar a produção de vídeo primeiro.',
            EstadoPonto.ATUAL: 'Tudo pronto! Só falta alguém decidir formalmente colocar esse produto na Agenda de Vídeos.',
            EstadoPonto.CONCLUIDO: 'Já entrou na Agenda — seguiu pro ciclo de postagem.',
        },
    ),
    DefinicaoPonto(
        chave='diaria', rotulo='Diária', rotulo_completo='Fase Diária',
        eh_editavel=True, unidade_tempo=UnidadeTempoFase('Dia', 'dias', 'no'),
    ),
    DefinicaoPonto(
        chave='semanal', rotulo='Semanal', rotulo_completo='Fase Semanal',
        eh_editavel=True, unidade_tempo=UnidadeTempoFase('Semana', 'semanas', 'na'),
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


# Função Objetivo: Busca (com cache de 5min) o período configurado de cada fase.
# Explicação em detalhe: evita 1 query por produto por fase futura — numa lista de N
# produtos, sem isso viraria N+1 de verdade. Muda raríssimo (é config, não dado por
# produto), então 5min de cache é seguro.
def obter_mapa_periodos_por_fase():
    mapa = cache.get('agenda_videos_mapa_periodos_fase')
    if mapa is None:
        from agenda_videos.models import ConfiguracaoFase
        mapa = {c.fase: c.periodo for c in ConfiguracaoFase.objects.all()}
        cache.set('agenda_videos_mapa_periodos_fase', mapa, 300)
    return mapa


# Função Objetivo: Decide qual chave é "o atual", seguindo a ordem travada.
# Explicação em detalhe: pública (24/07) — deixou de ser uso interno único desta função
# quando RoadmapAgenda passou a precisar da mesma decisão (nunca duplicar a lógica).
def calcular_chave_atual(progresso, andamento):
    if progresso is None or progresso.video_simples_status != 'gerado':
        return 'simples'
    if progresso.video_base_status != 'gerado':
        return 'base'
    if not progresso.roteiros_gerados:
        return 'roteiros'
    if not progresso.completos_produzidos:
        return 'completos'
    if andamento is None:
        return 'pronto_agendamento'
    if andamento.concluido:
        return 'otimizado'
    return andamento.fase_atual.fase


# Função Objetivo: Monta o rótulo compacto ("Dia 03 de 10") de uma fase cíclica.
# Explicação em detalhe: zero à esquerda só quando o período tem 2+ dígitos (a
# Diária, com período 10, fica "03" pra alinhar com "10" — Semanal/Mensal, com
# período de 1 dígito, não precisam disso).
def _montar_rotulo_ciclico(unidade, atual, periodo):
    largura = len(str(periodo))
    return f'{unidade.singular} {str(atual).zfill(largura)} de {periodo}'


# Função Objetivo: Monta a frase do hover de uma fase cíclica, nos 3 estados possíveis.
# Explicação em detalhe: sempre explica o que já foi feito, o que está em andamento,
# e o que falta — nunca o número puro. "definicao_seguinte" é o próximo item de
# DEFINICOES_PONTOS (não um dicionário separado) — usado só quando a última ocorrência
# da fase é atingida, pra dizer "avança para: {próximo ponto}".
def _montar_explicacao_ciclica(unidade, estado, atual, periodo, definicao_seguinte):
    if estado == EstadoPonto.FUTURO:
        return (
            f'Ainda não começou. Serão {periodo} {unidade.plural}, '
            f'1 vídeo por {unidade.singular.lower()}, quando chegar a vez.'
        )

    if estado == EstadoPonto.CONCLUIDO:
        return f'Concluída — foram publicados os {periodo} {unidade.plural}.'

    # estado == EstadoPonto.ATUAL
    ja_publicados = atual - 1
    if atual < periodo:
        proximo = f'o {unidade.singular.lower()} {atual + 1}'
    else:
        proximo = definicao_seguinte.rotulo_completo

    return (
        f'Você está {unidade.preposicao} {unidade.singular.lower()} {atual} de {periodo}. '
        f'Já foram publicados {ja_publicados}. Ao concluir e replicar, avança para: {proximo}.'
    )


# Função Objetivo: Monta o roadmap completo (9 pontos) de 1 produto.
def calcular_roadmap_produto(produto):
    progresso = getattr(produto, 'progresso_producao_video', None)
    andamento = getattr(produto, 'andamento_agenda', None)

    chave_atual = calcular_chave_atual(progresso, andamento)
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
                explicacao = ''  # sem ConfiguracaoFase pra essa fase ainda
        else:
            explicacao = definicao.explicacoes_por_estado.get(
                estado, definicao.explicacoes_por_estado.get(EstadoPonto.ATUAL, ''),
            )

        pontos.append(PontoRoadmap(
            chave=definicao.chave, rotulo=definicao.rotulo, rotulo_completo=definicao.rotulo_completo,
            explicacao=explicacao, estado=estado, clicavel=clicavel, contador=contador,
        ))

    return RoadmapProduto(produto_id=produto.id, pontos=pontos)