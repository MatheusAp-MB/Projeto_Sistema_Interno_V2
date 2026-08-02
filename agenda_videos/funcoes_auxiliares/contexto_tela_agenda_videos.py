# agenda_videos/funcoes_auxiliares/contexto_tela_agenda_videos.py

# Função Objetivo: Monta todo o contexto da tela única "Agenda de Vídeos".
# Estágio padrão ("A Fazer Hoje") só se aplica na 1ª visita — depois disso,
# respeita exatamente o que o usuário escolheu.
# Reestruturação completa (30/07) — filtros de vídeo simples/base/roteiros/
# completos soltos e reestruturação_manual saem (conceitos retirados).

from dataclasses import dataclass, field
from datetime import date, datetime

from django.conf import settings
from django.core.paginator import Page, Paginator

from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import (
    listar_produtos_agenda_filtrados, CAMPOS_ORDENACAO, CAMPOS_FAIXA, OPCOES_PENDENTE_AGORA, OPCOES_ESTAGIO,
)
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import listar_a_fazer_hoje, calcular_indicadores_ciclo
from agenda_videos.funcoes_auxiliares.drive import calcular_diagnostico_preparo_drive
from agenda_videos.funcoes_auxiliares.postagem_ciclica import ja_postou_hoje
from agenda_videos.funcoes_auxiliares.badges_agenda import (
    Badge, OpcaoComBadge, BADGES_STATUS_MANUAL, BADGES_STATUS_POSTAGEM, BADGES_ETAPA, montar_opcoes_com_badge,
)
from core.funcoes_auxiliares.cabecalhos_ordenaveis import ConstrutorCabecalhosOrdenacao

LABELS_COLUNAS = {
    'titulo': 'Nome', 'marca': 'Marca', 'estoque': 'Estoque',
    'numero_ocorrencia': 'Ocorrência', 'data_devida': 'Vencimento',
}

LABELS_CAMPOS_FAIXA = {
    'numero_ocorrencia_ciclo_atual': 'Ocorrência',
    'data_devida_ciclo_atual': 'Vencimento',
}

OPCOES_SIM_NAO = [
    OpcaoComBadge(valor='sim', label='Sim', classe=None, icone=None),
    OpcaoComBadge(valor='nao', label='Não', classe=None, icone=None),
]


@dataclass
class ParametrosBuscaAgendaVideos:
    busca: str
    por_pagina: int
    ordenar: str
    numero_pagina: int
    filtros: dict = field(default_factory=dict)
    data_simulada: date | None = None

    @classmethod
    def a_partir_da_requisicao(cls, request) -> 'ParametrosBuscaAgendaVideos':
        busca = request.GET.get('busca', '').strip()

        por_pagina_bruto = request.GET.get('por_pagina', '25')
        try:
            por_pagina = int(por_pagina_bruto)
        except ValueError:
            por_pagina = 25

        ordenar = request.GET.get('ordenar', 'titulo')
        if ordenar.lstrip('-') not in CAMPOS_ORDENACAO:
            ordenar = 'titulo'

        eh_primeira_visita = len(request.GET) == 0
        a_fazer_hoje = eh_primeira_visita or request.GET.get('a_fazer_hoje') is not None
        estagio = [] if a_fazer_hoje else request.GET.getlist('estagio')

        # * [EXPLICAÇÃO] → Só funciona com DEBUG=True — existe só pra testar
        #                  "A Fazer Hoje"/Atrasado/Risco com datas diferentes
        #                  direto na tela.
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
            'sincronizado_drive': request.GET.getlist('sincronizado_drive'),
            'atrasado': request.GET.getlist('atrasado'),
            'risco': request.GET.getlist('risco'),
            'pendente_agora': request.GET.getlist('pendente_agora'),
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

    def __init__(self, filtros: dict) -> None:
        self.filtros = filtros

    def _montar_chip_simples(self, label: str) -> Badge:
        return Badge(label=label, classe=None, icone=None)

    def _montar_chips_checkbox(self) -> list[Badge]:
        mapa_labels_estagio = dict(OPCOES_ESTAGIO)
        mapa_labels_pendencia = dict(OPCOES_PENDENTE_AGORA)
        chips = [self._montar_chip_simples(mapa_labels_estagio.get(v, v)) for v in self.filtros['estagio']]
        chips += [self._montar_chip_simples(m) for m in self.filtros['marcas']]
        chips += [BADGES_STATUS_MANUAL[v] for v in self.filtros['status_manual'] if v in BADGES_STATUS_MANUAL]
        chips += [self._montar_chip_simples('Urgente' if v == 'sim' else 'Não urgente') for v in self.filtros['urgente']]
        chips += [self._montar_chip_simples('Sem vídeo' if v == 'sim' else 'Com vídeo') for v in self.filtros['sem_video']]
        chips += [self._montar_chip_simples('Sincronizado com o Drive' if v == 'sim' else 'Não sincronizado com o Drive') for v in self.filtros['sincronizado_drive']]
        chips += [self._montar_chip_simples('Atrasado' if v == 'sim' else 'Não atrasado') for v in self.filtros['atrasado']]
        chips += [self._montar_chip_simples('Risco de atraso' if v == 'sim' else 'Sem risco') for v in self.filtros['risco']]
        chips += [self._montar_chip_simples(mapa_labels_pendencia.get(v, v)) for v in self.filtros['pendente_agora']]
        chips += [BADGES_STATUS_POSTAGEM[v] for v in self.filtros['status_postagem'] if v in BADGES_STATUS_POSTAGEM]
        return chips

    def _montar_chips_faixa(self) -> list[Badge]:
        chips = []
        for campo in CAMPOS_FAIXA:
            minimo = self.filtros.get(f'{campo}_min')
            maximo = self.filtros.get(f'{campo}_max')
            if not (minimo or maximo):
                continue
            label = LABELS_CAMPOS_FAIXA.get(campo, campo)
            if minimo and maximo:
                chips.append(self._montar_chip_simples(f'{label}: {minimo} até {maximo}'))
            elif minimo:
                chips.append(self._montar_chip_simples(f'{label}: a partir de {minimo}'))
            else:
                chips.append(self._montar_chip_simples(f'{label}: até {maximo}'))
        return chips

    def montar(self) -> list[Badge]:
        return self._montar_chips_checkbox() + self._montar_chips_faixa()


class ContextoTelaAgendaVideos:

    def __init__(self, request) -> None:
        self.request = request
        self.parametros = ParametrosBuscaAgendaVideos.a_partir_da_requisicao(request)

    def _montar_querystring_base(self) -> str:
        qs = self.request.GET.copy()
        qs.pop('ordenar', None)
        qs.pop('pagina', None)
        return qs.urlencode()

    def _montar_querystring_sem_pagina(self) -> str:
        qs = self.request.GET.copy()
        qs.pop('pagina', None)
        return qs.urlencode()

    def _enriquecer_pagina(self, pagina: Page) -> None:
        for produto in pagina:
            ciclo = produto.ciclos_video.first()
            if ciclo is not None:
                calcular_indicadores_ciclo(produto, ciclo, data_referencia=self.parametros.data_simulada)
                produto.ja_postou_hoje = ja_postou_hoje(produto, data_referencia=self.parametros.data_simulada)
            produto.diagnostico_drive = calcular_diagnostico_preparo_drive(produto)

    def _montar_pagina(self) -> Page:
        if self.parametros.filtros.get('a_fazer_hoje'):
            produtos = listar_a_fazer_hoje(
                busca=self.parametros.busca or None, filtros=self.parametros.filtros,
                data_referencia=self.parametros.data_simulada,
            )
        else:
            produtos = listar_produtos_agenda_filtrados(
                busca=self.parametros.busca or None, filtros=self.parametros.filtros,
                ordenar=self.parametros.ordenar, data_referencia=self.parametros.data_simulada,
            )

        paginator = Paginator(produtos, self.parametros.por_pagina)
        pagina = paginator.get_page(self.parametros.numero_pagina)
        self._enriquecer_pagina(pagina)
        return pagina

    def montar(self) -> dict:
        cabecalhos = ConstrutorCabecalhosOrdenacao(
            self.parametros.ordenar, self._montar_querystring_base(),
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
            'opcoes_estagio': [OpcaoComBadge(valor=v, label=l, classe=None, icone=None) for v, l in OPCOES_ESTAGIO],
            'opcoes_status_manual': montar_opcoes_com_badge(BADGES_STATUS_MANUAL),
            'opcoes_etapa': montar_opcoes_com_badge(BADGES_ETAPA),
            'opcoes_status_postagem': montar_opcoes_com_badge(BADGES_STATUS_POSTAGEM),
            'opcoes_sim_nao': OPCOES_SIM_NAO,
            'opcoes_pendente_agora': OPCOES_PENDENTE_AGORA,
            'querystring_sem_pagina': self._montar_querystring_sem_pagina(),
        }