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

from agenda_videos.models import Fase, ConfiguracaoFase

QUANTIDADE_ANTERIORES_NA_ESTEIRA = 2
QUANTIDADE_FUTURAS_NA_ESTEIRA = 3

ORDEM_ETAPAS = ['base', 'roteiro', 'completo', 'postar', 'replicar']
INDICE_DA_ETAPA = {
    'base': 0, 'roteiro': 1, 'completo': 2, 'postar': 3,
    'aguardando_aprovacao': 3, 'replicar': 4, 'concluido': 5,
}


def rotulo_rodada(fase, numero_ocorrencia):
    if fase == Fase.SIMPLES:
        return Fase(fase).label
    return f'{Fase(fase).label} #{numero_ocorrencia}'


# Função Objetivo: Prevê as próximas N rodadas SEM criar nada no banco — só
# consulta ConfiguracaoFase pra saber quantas ocorrências cada fase tem e
# qual é a próxima. Vídeo Trimestral nunca lista instância individual — só 1
# placeholder ("contínua"), já que não tem fim.
def _prever_proximas_rodadas(fase_atual, numero_atual, quantidade_maxima):
    futuras = []
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
            futuras.append({
                'id': f'{fase}_continua', 'label': f'{Fase(fase).label} contínua',
                'ciclica': True, 'estado': 'futuro', 'legenda': '',
            })
            break

        futuras.append({
            'id': f'{fase}_{numero}', 'label': _rotulo_rodada(fase, numero),
            'ciclica': True, 'estado': 'futuro', 'legenda': '',
        })

    return futuras


def _montar_etapas_rodada_atual(ciclo):
    etapa_real = ciclo.etapa_atual()
    indice_atual = INDICE_DA_ETAPA[etapa_real]

    etapas = []
    for indice, nome in enumerate(ORDEM_ETAPAS):
        if indice < indice_atual:
            estado = 'concluido'
        elif indice == indice_atual:
            estado = 'aguardando_aprovacao' if etapa_real == 'aguardando_aprovacao' else 'atual'
        else:
            estado = 'futuro'
        etapas.append({'nome': nome.capitalize(), 'estado': estado})
    return etapas


def calcular_roadmap_produto(produto):
    ciclos = list(produto.ciclos_video.order_by('criado_em'))
    if not ciclos:
        return {'rodadas': [], 'etapas_rodada_atual': [], 'tem_rodada_atual': False}

    ciclo_atual = ciclos[-1]  # o mais recente é sempre o "em andamento"
    anteriores = ciclos[:-1][-QUANTIDADE_ANTERIORES_NA_ESTEIRA:]

    rodadas = []
    for ciclo in anteriores:
        rodadas.append({
            'id': f'{ciclo.fase}_{ciclo.numero_ocorrencia}',
            'label': _rotulo_rodada(ciclo.fase, ciclo.numero_ocorrencia),
            'ciclica': ciclo.fase != Fase.SIMPLES,
            'estado': 'concluido',
            'legenda': '',
        })

    rodadas.append({
        'id': f'{ciclo_atual.fase}_{ciclo_atual.numero_ocorrencia}',
        'label': _rotulo_rodada(ciclo_atual.fase, ciclo_atual.numero_ocorrencia),
        'ciclica': ciclo_atual.fase != Fase.SIMPLES,
        'estado': 'atual',
        'legenda': f'vence {ciclo_atual.data_devida:%d/%m}',
    })

    rodadas.extend(_prever_proximas_rodadas(
        ciclo_atual.fase, ciclo_atual.numero_ocorrencia, QUANTIDADE_FUTURAS_NA_ESTEIRA,
    ))

    return {
        'rodadas': rodadas,
        'etapas_rodada_atual': _montar_etapas_rodada_atual(ciclo_atual),
        'tem_rodada_atual': True,
        'rodada_atual_id': f'{ciclo_atual.fase}_{ciclo_atual.numero_ocorrencia}',
    }