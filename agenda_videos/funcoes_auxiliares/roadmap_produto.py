# agenda_videos/funcoes_auxiliares/roadmap_produto.py

# Função Objetivo: Calcula o "mapa de missão" (roadmap) de 1 produto — os 9 pontos do
# ciclo de vida de vídeo, qual está concluído/atual/futuro, e se é clicável.
# Explicação em detalhe: é o produto quem "possui" o roadmap (não é conceito de Diária,
# Semanal ou A Fazer) — por isso vira template tag, reaproveitável em QUALQUER tela que
# mostre produto, sem duplicar lógica. Ordem é travada (nunca fora de ordem, confirmado
# com o usuário) — só o ponto "atual" pode ser clicável, e só entre os 4 primeiros
# (preparação); os 5 seguintes são sempre só leitura (calculados pelo sistema).

from dataclasses import dataclass, field
from typing import Optional
from django.core.cache import cache


@dataclass
class PontoRoadmap:
    chave: str
    rotulo: str
    rotulo_completo: str
    explicacao: str
    estado: str  # 'concluido' | 'atual' | 'futuro'
    clicavel: bool
    contador: Optional[str] = None


@dataclass
class RoadmapProduto:
    produto_id: int
    pontos: list = field(default_factory=list)


# * [EXPLICAÇÃO] → Ordem travada — nunca reordenar esta lista sem revisar
#                  a lógica de "qual é o atual" logo abaixo, junto.
DEFINICOES_PONTOS = [
    ('simples', 'Simples', 'Vídeos Simples Gerados',
     'Vídeo só com imagens + música de fundo — a versão mínima, usada no 1º anúncio do produto.'),
    ('base', 'Base', 'Vídeos Base Gerados',
     'Vídeo-base pra gerar as versões narradas — pode ser o mesmo Simples ou um novo, mais elaborado.'),
    ('roteiros', 'Roteiros', 'Roteiros Gerados',
     'Textos de narração/legenda — 1 por dia da Fase Diária, escritos antes dos vídeos completos.'),
    ('completos', 'Completos', 'Vídeos Completos Gerados',
     'Vídeo-base + narração de cada roteiro — o conjunto pronto pra postar (o "pool") na Fase Diária.'),
    ('pronto_agendamento', 'Agendamento', 'Pronto para Agendamento',
     'Todos os vídeos estão prontos — falta só entrar formalmente na Agenda de Vídeos.'),
    ('diaria', 'Diária', 'Fase Diária',
     '10 dias seguidos, 1 vídeo obrigatório por dia útil — o ritmo mais intenso, logo no início.'),
    ('semanal', 'Semanal', 'Fase Semanal',
     '1 vídeo por semana — ritmo mais tranquilo, produzido sob demanda.'),
    ('mensal', 'Mensal', 'Fase Mensal',
     'Última fase do ciclo — 1 vídeo por mês, produzido sob demanda.'),
    ('otimizado', 'Otimizado', 'Anúncio Otimizado',
     'Ciclo de divulgação encerrado — não tem mais obrigação de vídeo na Agenda.'),
]

CHAVES_FASES_CICLICAS = {'diaria', 'semanal', 'mensal'}
CHAVES_EDITAVEIS = {'simples', 'base', 'roteiros', 'completos'}


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
def _calcular_chave_atual(progresso, andamento):
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


# Função Objetivo: Monta o contador ("2/10") de uma fase cíclica, ativa ou futura.
def _montar_contador(chave, andamento, mapa_periodos):
    # (sem mudança aqui — só o nome da função chamada por calcular_roadmap_produto abaixo)
    if andamento is not None and andamento.fase_atual and andamento.fase_atual.fase == chave:
        return f'{andamento.ocorrencia_atual}/{andamento.fase_atual.periodo}'
    periodo = mapa_periodos.get(chave)
    return f'0/{periodo}' if periodo else None


# Função Objetivo: Monta o roadmap completo (9 pontos) de 1 produto.
def calcular_roadmap_produto(produto):
    progresso = getattr(produto, 'progresso_producao_video', None)
    andamento = getattr(produto, 'andamento_agenda', None)

    chave_atual = _calcular_chave_atual(progresso, andamento)
    ordem_chaves = [definicao[0] for definicao in DEFINICOES_PONTOS]
    indice_atual = ordem_chaves.index(chave_atual)
    mapa_periodos = obter_mapa_periodos_por_fase()

    pontos = []
    for indice, (chave, rotulo, rotulo_completo, explicacao) in enumerate(DEFINICOES_PONTOS):
        if indice < indice_atual:
            estado = 'concluido'
        elif indice == indice_atual:
            estado = 'atual'
        else:
            estado = 'futuro'

        clicavel = estado == 'atual' and chave in CHAVES_EDITAVEIS

        contador = None
        if chave in CHAVES_FASES_CICLICAS:
            contador = _montar_contador(chave, andamento, mapa_periodos)

        pontos.append(PontoRoadmap(
            chave=chave, rotulo=rotulo, rotulo_completo=rotulo_completo,
            explicacao=explicacao, estado=estado, clicavel=clicavel, contador=contador,
        ))

    return RoadmapProduto(produto_id=produto.id, pontos=pontos)