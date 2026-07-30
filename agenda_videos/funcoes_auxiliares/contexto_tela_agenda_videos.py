# agenda_videos/funcoes_auxiliares/contexto_tela_agenda_videos.py

# Função Objetivo: Monta todo o contexto da tela única "Agenda de Vídeos".
# Renomeado de contexto_tela_diarios.py (24/07). Estágio padrão ("Diário") só se
# aplica na 1ª visita (nenhum parâmetro na URL ainda) — depois disso, respeita
# exatamente o que o usuário escolheu, mesmo que seja "nenhum estágio marcado".

from datetime import datetime
from dataclasses import dataclass, field
from django.conf import settings
from django.core.paginator import Paginator
from produtos.models import Produto
from agenda_videos.models import EstagioAgenda
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import (
    listar_produtos_agenda_filtrados, CAMPOS_ORDENACAO, CAMPOS_FAIXA, OPCOES_PENDENTE_AGORA,
)
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import listar_a_fazer_hoje, calcular_indicadores_atraso
from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    calcular_indicador_pool_insuficiente, calcular_indicador_divergencia_fase_concluida,
)
from agenda_videos.funcoes_auxiliares.drive import calcular_diagnostico_preparo_drive
from agenda_videos.funcoes_auxiliares.postagem_ciclica import ja_postou_hoje
from agenda_videos.funcoes_auxiliares.badges_agenda import (
    BADGES_STATUS_MANUAL, BADGES_STATUS_POSTAGEM, BADGES_STATUS_VIDEO, opcoes_com_badge,
)
from core.funcoes_auxiliares.cabecalhos_ordenaveis import ConstrutorCabecalhosOrdenacao

LABELS_COLUNAS = {
    'titulo': 'Nome', 'marca': 'Marca', 'estoque': 'Estoque',
    'ocorrencia_atual': 'Ocorrência', 'inicio_fase': 'Início da Fase',
    'fim_fase': 'Fim da Fase', 'quantidade_roteiros': 'Qtd. Roteiros',
}

LABELS_CAMPOS_FAIXA = {
    'andamento_agenda__ocorrencia_atual': 'Ocorrência',
    'andamento_agenda__inicio_fase': 'Início da Fase',
    'andamento_agenda__fim_fase': 'Fim da Fase',
    'andamento_agenda__fim_ocorrencia_atual': 'Vencimento da Ocorrência',
    'progresso_producao_video__quantidade_roteiros': 'Qtd. Roteiros',
}

OPCOES_ESTAGIO = [{'valor': e.value, 'label': e.label} for e in EstagioAgenda]

OPCOES_SIM_NAO = [
    {'valor': 'sim', 'label': 'Sim', 'classe': None, 'icone': None},
    {'valor': 'nao', 'label': 'Não', 'classe': None, 'icone': None},
]


@dataclass
class ParametrosBuscaAgendaVideos:
    busca: str
    por_pagina: int
    ordenar: str
    numero_pagina: int
    filtros: dict = field(default_factory=dict)
    data_simulada: object = None

    @classmethod
    def a_partir_da_requisicao(cls, request):
        busca = request.GET.get('busca', '').strip()

        por_pagina_bruto = request.GET.get('por_pagina', '25')
        try:
            por_pagina = int(por_pagina_bruto)
        except ValueError:
            por_pagina = 25

        ordenar = request.GET.get('ordenar', 'titulo')
        if ordenar.lstrip('-') not in CAMPOS_ORDENACAO:
            ordenar = 'titulo'

        # * [EXPLICAÇÃO] → "1ª visita" = nenhum parâmetro na URL — nesse caso o
        #                  padrão passa a ser "A Fazer Hoje" (não mais "Diário").
        #                  "A Fazer Hoje" é um filtro à parte, não um EstagioAgenda —
        #                  quando ativo, ignora "estagio" por completo (são 2 caminhos
        #                  de query diferentes, nunca combinados).
        eh_primeira_visita = len(request.GET) == 0
        a_fazer_hoje = eh_primeira_visita or request.GET.get('a_fazer_hoje') is not None
        estagio = [] if a_fazer_hoje else request.GET.getlist('estagio')

        # * [EXPLICAÇÃO] → Só funciona com DEBUG=True — nunca em produção, mesmo que
        #                  alguém tente forjar o parâmetro na URL manualmente. Existe
        #                  só pra testar "A Fazer Hoje"/Atrasado/Risco com datas
        #                  diferentes direto na tela, sem precisar de teste.py.
        data_simulada = None
        if settings.DEBUG:
            valor_bruto = request.GET.get('simular_data', '').strip()
            if valor_bruto:
                try:
                    data_simulada = datetime.strptime(valor_bruto, '%Y-%m-%d').date()
                except ValueError:
                    data_simulada = None

        filtros = {
            'a_fazer_hoje': a_fazer_hoje,
            'estagio': estagio,
            'marcas': request.GET.getlist('marca'),
            'status_manual': request.GET.getlist('status_manual'),
            'urgente': request.GET.getlist('urgente'),
            'sem_video': request.GET.getlist('sem_video'),
            'reestruturacao_manual': request.GET.getlist('reestruturacao_manual'),
            'sincronizado_drive': request.GET.getlist('sincronizado_drive'),
            'atrasado': request.GET.getlist('atrasado'),
            'risco': request.GET.getlist('risco'),
            'pendente_agora': request.GET.getlist('pendente_agora'),
            'video_simples_status': request.GET.getlist('video_simples_status'),
            'video_base_status': request.GET.getlist('video_base_status'),
            'roteiros_gerados': request.GET.getlist('roteiros_gerados'),
            'completos_produzidos': request.GET.getlist('completos_produzidos'),
            'roteiros_insuficientes': request.GET.getlist('roteiros_insuficientes'),
            'status_postagem': request.GET.getlist('status_postagem'),
        }
        for campo in CAMPOS_FAIXA:
            filtros[f'{campo}_min'] = request.GET.get(f'{campo}_min', '')
            filtros[f'{campo}_max'] = request.GET.get(f'{campo}_max', '')

        return cls(
            busca=busca, por_pagina=por_pagina, ordenar=ordenar,
            numero_pagina=request.GET.get('pagina', 1), filtros=filtros,
            data_simulada=data_simulada,
        )


class ConstrutorChipsAtivosAgendaVideos:

    def __init__(self, filtros):
        self.filtros = filtros

    def _chip_simples(self, label):
        return {'label': label, 'classe': None, 'icone': None}

    def _chips_checkbox(self):
        mapa_labels_estagio = dict(EstagioAgenda.choices)
        mapa_labels_pendencia = dict(OPCOES_PENDENTE_AGORA)
        chips = [self._chip_simples(mapa_labels_estagio.get(v, v)) for v in self.filtros['estagio']]
        chips += [self._chip_simples(m) for m in self.filtros['marcas']]
        chips += [BADGES_STATUS_MANUAL[v] for v in self.filtros['status_manual'] if v in BADGES_STATUS_MANUAL]
        chips += [self._chip_simples('Urgente' if v == 'sim' else 'Não urgente') for v in self.filtros['urgente']]
        chips += [self._chip_simples('Sem vídeo' if v == 'sim' else 'Com vídeo') for v in self.filtros['sem_video']]
        chips += [self._chip_simples('Reestruturação Manual' if v == 'sim' else 'Sem reestruturação manual') for v in self.filtros['reestruturacao_manual']]
        chips += [self._chip_simples('Sincronizado com o Drive' if v == 'sim' else 'Não sincronizado com o Drive') for v in self.filtros['sincronizado_drive']]
        chips += [self._chip_simples('Atrasado' if v == 'sim' else 'Não atrasado') for v in self.filtros['atrasado']]
        chips += [self._chip_simples('Risco de atraso' if v == 'sim' else 'Sem risco') for v in self.filtros['risco']]
        chips += [self._chip_simples(mapa_labels_pendencia.get(v, v)) for v in self.filtros['pendente_agora']]
        chips += [self._chip_simples(f'Simples: {BADGES_STATUS_VIDEO[v]["label"]}') for v in self.filtros['video_simples_status'] if v in BADGES_STATUS_VIDEO]
        chips += [self._chip_simples(f'Base: {BADGES_STATUS_VIDEO[v]["label"]}') for v in self.filtros['video_base_status'] if v in BADGES_STATUS_VIDEO]
        chips += [self._chip_simples(f'Roteiros gerados: {"Sim" if v == "sim" else "Não"}') for v in self.filtros['roteiros_gerados']]
        chips += [self._chip_simples(f'Completos: {"Sim" if v == "sim" else "Não"}') for v in self.filtros['completos_produzidos']]
        chips += [self._chip_simples(f'Roteiros insuficientes: {"Sim" if v == "sim" else "Não"}') for v in self.filtros['roteiros_insuficientes']]
        chips += [BADGES_STATUS_POSTAGEM[v] for v in self.filtros['status_postagem'] if v in BADGES_STATUS_POSTAGEM]
        return chips

    def _chips_faixa(self):
        chips = []
        for campo in CAMPOS_FAIXA:
            minimo = self.filtros.get(f'{campo}_min')
            maximo = self.filtros.get(f'{campo}_max')
            if not (minimo or maximo):
                continue
            label = LABELS_CAMPOS_FAIXA.get(campo, campo)
            if minimo and maximo:
                chips.append(self._chip_simples(f'{label}: {minimo} até {maximo}'))
            elif minimo:
                chips.append(self._chip_simples(f'{label}: a partir de {minimo}'))
            else:
                chips.append(self._chip_simples(f'{label}: até {maximo}'))
        return chips

    def montar(self):
        return self._chips_checkbox() + self._chips_faixa()


class ContextoTelaAgendaVideos:

    def __init__(self, request):
        self.request = request
        self.parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    def _querystring_base(self):
        qs = self.request.GET.copy()
        qs.pop('ordenar', None)
        qs.pop('pagina', None)
        return qs.urlencode()

    def _querystring_sem_pagina(self):
        qs = self.request.GET.copy()
        qs.pop('pagina', None)
        return qs.urlencode()

    def _montar_pagina(self):
        if self.parametros.filtros.get('a_fazer_hoje'):
            produtos = listar_a_fazer_hoje(
                busca=self.parametros.busca or None,
                filtros=self.parametros.filtros,
                data_referencia=self.parametros.data_simulada,
            )
            paginator = Paginator(produtos, self.parametros.por_pagina)
            return paginator.get_page(self.parametros.numero_pagina)

        produtos = listar_produtos_agenda_filtrados(
            busca=self.parametros.busca or None,
            filtros=self.parametros.filtros,
            ordenar=self.parametros.ordenar,
            data_referencia=self.parametros.data_simulada,
        )
        paginator = Paginator(produtos, self.parametros.por_pagina)
        pagina = paginator.get_page(self.parametros.numero_pagina)

        # * [EXPLICAÇÃO] → Aplica o cálculo de Atrasado/Risco SÓ na página atual
        #                  (25 produtos, não a lista inteira) — antes, esses badges
        #                  só apareciam filtrando por "A Fazer Hoje", nunca nas
        #                  outras abas (Diário/Semanal/Mensal/etc.), mesmo quando o
        #                  produto realmente estava atrasado. Reaproveita a mesma
        #                  função, sem duplicar a conta em 2 lugares.
        for produto in pagina:
            andamento = getattr(produto, 'andamento_agenda', None)
            if andamento is not None and not andamento.concluido:
                calcular_indicadores_atraso(produto, andamento, data_referencia=self.parametros.data_simulada)
                produto.pool_insuficiente_tipo = calcular_indicador_pool_insuficiente(produto, andamento)
                produto.ja_postou_hoje = ja_postou_hoje(produto, data_referencia=self.parametros.data_simulada)
            if andamento is not None:
                produto.divergencia_fase_concluida = calcular_indicador_divergencia_fase_concluida(produto, andamento)
            # * [EXPLICAÇÃO] → Sem guarda de "andamento existe" — importa
            #                  justamente pros pontos ANTES do agendamento.
            produto.diagnostico_drive = calcular_diagnostico_preparo_drive(produto)

        return pagina

    def montar(self):
        cabecalhos = ConstrutorCabecalhosOrdenacao(
            self.parametros.ordenar, self._querystring_base(),
        ).montar(LABELS_COLUNAS)

        chips_ativos = ConstrutorChipsAtivosAgendaVideos(self.parametros.filtros).montar()

        marcas_disponiveis = (
            Produto.objects
            .exclude(marca__isnull=True).exclude(marca='')
            .values_list('marca', flat=True).distinct().order_by('marca')
        )

        return {
            'pagina': self._montar_pagina(),
            'busca': self.parametros.busca,
            'debug_ativo': settings.DEBUG,
            'data_simulada': self.parametros.data_simulada,
            'por_pagina': self.parametros.por_pagina,
            'filtros': self.parametros.filtros,
            'cabecalhos': cabecalhos,
            'chips_ativos': chips_ativos,
            'marcas_disponiveis': marcas_disponiveis,
            'opcoes_estagio': OPCOES_ESTAGIO,
            'opcoes_status_manual': opcoes_com_badge(BADGES_STATUS_MANUAL),
            'opcoes_status_video': opcoes_com_badge(BADGES_STATUS_VIDEO),
            'opcoes_status_postagem': opcoes_com_badge(BADGES_STATUS_POSTAGEM),
            'opcoes_sim_nao': OPCOES_SIM_NAO,
            'opcoes_pendente_agora': OPCOES_PENDENTE_AGORA,
            'querystring_sem_pagina': self._querystring_sem_pagina(),
        }