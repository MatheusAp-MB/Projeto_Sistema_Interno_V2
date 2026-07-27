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


# * [EXPLICAÇÃO] → Sem cache de propósito (26/07) — tinha cache de 5min antes,
#                  mas ConfiguracaoFase são só 3 linhas (indexadas), a query é
#                  tão barata quanto o próprio cache, e cache em memória por
#                  processo (LocMemCache, padrão do projeto) não invalida entre
#                  workers — arriscava ler periodo velho mesmo depois de salvar.
def obter_mapa_periodos_por_fase():
    from agenda_videos.models import ConfiguracaoFase
    return {c.fase: c.periodo for c in ConfiguracaoFase.objects.all()}


# Função Objetivo: Carrega as preparações (Diária/Semanal/Mensal) de 1 produto
# numa query só, monta um dict {fase: PreparacaoVideoFase} — nunca 1 query por
# fase depois. Única fonte desse dict (26/07, pente fino — antes essa mesma
# expressão estava escrita 3 vezes: aqui, em sincronizar_roadmap_agenda.py e
# em popular_banco_suporte/sincronizar_roadmap_agenda.py). Mora aqui (não em
# sincronizar_roadmap_agenda.py) porque esse módulo JÁ é importado por eles —
# o caminho contrário criaria import circular.
def montar_preparacoes_por_fase(produto):
    if not produto.pk:
        return {}
    return {p.fase: p for p in produto.preparacoes_video.all()}


# Função Objetivo: Busca (num dict já carregado, sem query nova) a preparação de 1 fase.
def _obter_preparacao(preparacoes_por_fase, fase):
    return preparacoes_por_fase.get(fase) if preparacoes_por_fase else None


# Função Objetivo: Compara a quantidade capturada no clique contra o periodo
# ATUAL da config — None (nunca clicado com esse recurso ativo) nunca é suficiente.
def _quantidade_suficiente(quantidade_no_clique, periodo_atual):
    return quantidade_no_clique is not None and quantidade_no_clique >= periodo_atual


# Função Objetivo: Existe Postagem aberta (não Replicada) na ocorrência atual?
# Explicação em detalhe: só usada quando a suficiência do pool falha — regra
# "deixar o ciclo rodar" (26/07): nunca interrompe uma ação já em andamento, só
# bloqueia a PRÓXIMA ocorrência de começar sem antes repor o pool.
def _existe_postagem_aberta(produto, andamento):
    from agenda_videos.models import Postagem, StatusPostagem
    return Postagem.objects.filter(
        produto=produto, fase=andamento.fase_atual.fase, numero_ocorrencia=andamento.ocorrencia_atual,
    ).exclude(status=StatusPostagem.REPLICADO).exists()


# Função Objetivo: Decide qual chave é "o atual", seguindo a ordem travada (13 pontos).
# Explicação em detalhe: "preparacoes_por_fase" é um dict {fase: PreparacaoVideoFase},
# carregado 1 vez por quem chama (nunca 1 query por fase aqui dentro).
# "produto" (26/07, opcional) habilita a checagem de suficiência de pool
# (Roteiros/Completos insuficientes pra fase ATUAL) — os 2 lugares que
# sincronizam RoadmapAgenda em lote (sincronizar_roadmap_agenda.py e o
# equivalente em popular_banco_suporte) não precisam passar isso: a distinção
# roteiros_X/completos_X vs a própria fase cíclica colapsa no MESMO
# EstagioAgenda (ver MAPA_COLAPSO), então essa checagem ali só custaria query
# extra sem mudar nada visível no Estágio salvo.
def calcular_chave_atual(progresso, preparacoes_por_fase, andamento, produto=None):
    if progresso is None or progresso.video_simples_status != 'gerado':
        return 'simples'
    if progresso.video_base_status != 'gerado':
        return 'base'

    mapa_periodos = obter_mapa_periodos_por_fase() if produto is not None else {}
    fase_atual = andamento.fase_atual.fase if andamento else None

    # * [EXPLICAÇÃO] → "relevante" = o produto ainda ESTÁ nessa fase agora (ou
    #                  nem começou nenhuma, no caso da Diária). Fase já
    #                  concluída fica de fora da checagem — o pool dela já
    #                  cumpriu o papel, reabrir isso voltaria o produto pra uma
    #                  etapa que não existe mais pra ele.
    def _insuficiente_e_bloqueia(quantidade_no_clique, fase, relevante):
        if produto is None or not relevante:
            return False
        periodo_atual = mapa_periodos.get(fase)
        if periodo_atual is None or _quantidade_suficiente(quantidade_no_clique, periodo_atual):
            return False
        if andamento is None:
            return True  # nunca postou nada nessa fase — nada "aberto" a proteger
        return not _existe_postagem_aberta(produto, andamento)

    prep_diaria = _obter_preparacao(preparacoes_por_fase, 'diaria')
    diaria_relevante = andamento is None or fase_atual == 'diaria'
    if prep_diaria is None or not prep_diaria.roteiros_gerados:
        return 'roteiros_diaria'
    if _insuficiente_e_bloqueia(prep_diaria.roteiros_quantidade_no_clique, 'diaria', diaria_relevante):
        return 'roteiros_diaria'
    if not prep_diaria.completos_produzidos:
        return 'completos_diaria'
    if _insuficiente_e_bloqueia(prep_diaria.completos_quantidade_no_clique, 'diaria', diaria_relevante):
        return 'completos_diaria'

    if andamento is None:
        return 'pronto_agendamento'
    if andamento.concluido:
        return 'otimizado'

    if fase_atual == 'diaria':
        return 'diaria'

    prep_semanal = _obter_preparacao(preparacoes_por_fase, 'semanal')
    semanal_relevante = fase_atual == 'semanal'
    if prep_semanal is None or not prep_semanal.roteiros_gerados:
        return 'roteiros_semanal'
    if _insuficiente_e_bloqueia(prep_semanal.roteiros_quantidade_no_clique, 'semanal', semanal_relevante):
        return 'roteiros_semanal'
    if not prep_semanal.completos_produzidos:
        return 'completos_semanal'
    if _insuficiente_e_bloqueia(prep_semanal.completos_quantidade_no_clique, 'semanal', semanal_relevante):
        return 'completos_semanal'
    if fase_atual == 'semanal':
        return 'semanal'

    prep_mensal = _obter_preparacao(preparacoes_por_fase, 'mensal')
    mensal_relevante = fase_atual == 'mensal'
    if prep_mensal is None or not prep_mensal.roteiros_gerados:
        return 'roteiros_mensal'
    if _insuficiente_e_bloqueia(prep_mensal.roteiros_quantidade_no_clique, 'mensal', mensal_relevante):
        return 'roteiros_mensal'
    if not prep_mensal.completos_produzidos:
        return 'completos_mensal'
    if _insuficiente_e_bloqueia(prep_mensal.completos_quantidade_no_clique, 'mensal', mensal_relevante):
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
        if atual == periodo:
            return f'Concluída — foram publicados os {periodo} {unidade.plural}.'
        # * [EXPLICAÇÃO] → periodo mudou DEPOIS que essa fase já tinha terminado —
        #                  "atual" aqui é a contagem REAL (Postagem Replicada),
        #                  nunca mais o periodo atual (correção reaplicada 26/07 —
        #                  ficou faltando numa aplicação anterior, junto com a
        #                  mudança de "atual" em calcular_roadmap_produto).
        return (
            f'Concluída com {atual} {unidade.plural} — regra vigente na época. '
            f'A configuração atual pede {periodo} {unidade.plural}.'
        )

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


# Função Objetivo: Conta quantas ocorrências dessa fase realmente viraram
# Postagem Replicada — número REAL, nunca afetado por mudança de config depois
# que a fase já tinha terminado.
def _contar_ocorrencias_replicadas(produto, fase):
    from agenda_videos.models import Postagem, StatusPostagem
    return Postagem.objects.filter(produto=produto, fase=fase, status=StatusPostagem.REPLICADO).count()


# Função Objetivo: Indicador pro badge do card — quais fases JÁ CONCLUÍDAS
# (Diária/Semanal/Mensal) têm contagem real diferente do periodo ATUAL da
# config? Acontece quando o periodo muda depois que a fase já tinha
# terminado — não afeta o andamento do produto (ele já passou dela), só a
# comparação/exibição fica desatualizada sem esse aviso. Devolve TODAS as
# divergências encontradas (26/07 — antes só a primeira; um produto pode
# ter mais de uma fase concluída divergindo ao mesmo tempo), lista vazia
# se nenhuma.
def calcular_indicador_divergencia_fase_concluida(produto, andamento):
    if andamento is None:
        return []

    fase_atual = andamento.fase_atual.fase
    concluidas = []
    if fase_atual in ('semanal', 'mensal') or andamento.concluido:
        concluidas.append('diaria')
    if fase_atual == 'mensal' or andamento.concluido:
        concluidas.append('semanal')
    if andamento.concluido:
        concluidas.append('mensal')

    if not concluidas:
        return []

    mapa_periodos = obter_mapa_periodos_por_fase()
    divergencias = []
    for fase in concluidas:
        periodo_atual = mapa_periodos.get(fase)
        if periodo_atual is None:
            continue
        real = _contar_ocorrencias_replicadas(produto, fase)
        if real != periodo_atual:
            divergencias.append({'fase': fase, 'real': real, 'atual': periodo_atual})
    return divergencias


# Função Objetivo: Indicador pro badge do card — a fase ATUAL do produto tem
# Roteiros ou Completos insuficientes (marcado como pronto, mas a quantidade
# capturada no clique não cobre mais o periodo de agora)? Devolve None/'roteiros'/
# 'completos'. Não decide clicabilidade (isso é calcular_chave_atual) — aparece
# mesmo com uma ação pendente em aberto, como aviso antecipado do que vai
# bloquear a PRÓXIMA ocorrência de começar.
def calcular_indicador_pool_insuficiente(produto, andamento):
    if andamento is None or andamento.concluido:
        return None

    fase = andamento.fase_atual.fase
    preparacao = next((p for p in produto.preparacoes_video.all() if p.fase == fase), None)
    if preparacao is None:
        return None

    periodo_atual = obter_mapa_periodos_por_fase().get(fase)
    if periodo_atual is None:
        return None

    if preparacao.roteiros_gerados and not _quantidade_suficiente(preparacao.roteiros_quantidade_no_clique, periodo_atual):
        return 'roteiros'
    if preparacao.completos_produzidos and not _quantidade_suficiente(preparacao.completos_quantidade_no_clique, periodo_atual):
        return 'completos'
    return None


# Função Objetivo: Monta o roadmap completo (13 pontos) de 1 produto.
def calcular_roadmap_produto(produto):
    progresso = getattr(produto, 'progresso_producao_video', None)
    andamento = getattr(produto, 'andamento_agenda', None)
    preparacoes_por_fase = montar_preparacoes_por_fase(produto)

    chave_atual = calcular_chave_atual(progresso, preparacoes_por_fase, andamento, produto=produto)
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
                    atual = _contar_ocorrencias_replicadas(produto, definicao.chave)
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