# agenda_videos/funcoes_auxiliares/contexto_tela_agenda_videos.py

# Função Objetivo: Monta todo o contexto das 6 telas da Agenda de Vídeos.
# Tela padrão ("A Fazer Hoje") só se aplica na 1ª visita — depois disso,
# respeita exatamente o que o usuário escolheu.
# Reestruturação completa (12/08) — pendente_agora/motivo_a_fazer_hoje saem
# (sistema antigo de 6 telas); entram periodo/etapa/aba, e contadores de
# navegação (1 por tela, sempre calculados — decisão explícita do usuário,
# mesmo sabendo do custo de 6 consultas extras por carga de página).

from dataclasses import dataclass, field
from datetime import date, datetime

from django.conf import settings
from django.core.paginator import Page, Paginator

from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import (
    Tela, OPCOES_TELA, Periodo, OPCOES_PERIODO, OPCOES_ETAPA, OPCOES_ABA, ETAPAS_FABRICA,
    listar_produtos_agenda_filtrados, construir_queryset_tela, contar_por_condicoes, condicao_etapa,
    CAMPOS_ORDENACAO, CAMPOS_FAIXA,
)
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import calcular_indicadores_ciclo
from agenda_videos.funcoes_auxiliares.drive import calcular_diagnostico_preparo_drive
from agenda_videos.funcoes_auxiliares.postagem_ciclica import ja_postou_hoje
from agenda_videos.funcoes_auxiliares.badges_agenda import (
    Badge, OpcaoComBadge, BADGES_STATUS_MANUAL, BADGES_STATUS_POSTAGEM, BADGES_ETAPA, montar_opcoes_com_badge,
)
from agenda_videos.funcoes_auxiliares.roadmap_produto import EstadoVisualRoadmap
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
    tela: str
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
        tela_bruta = Tela.A_FAZER_HOJE if eh_primeira_visita else request.GET.get('tela', Tela.A_FAZER_HOJE)
        tela = tela_bruta if tela_bruta in Tela.values else Tela.A_FAZER_HOJE

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

        periodo = request.GET.get('periodo', Periodo.TODOS)
        if periodo not in Periodo.values:
            periodo = Periodo.TODOS

        aba = request.GET.get('aba', 'postar')
        if aba not in ('postar', 'replicar'):
            aba = 'postar'

        filtros = {
            'periodo': periodo,
            'etapa': request.GET.getlist('etapa'),
            'aba': aba,
            'marcas': request.GET.getlist('marca'),
            'status_manual': request.GET.getlist('status_manual'),
            'urgente': request.GET.getlist('urgente'),
            'sem_video': request.GET.getlist('sem_video'),
            'sincronizado_drive': request.GET.getlist('sincronizado_drive'),
            'atrasado': request.GET.getlist('atrasado'),
            'risco': request.GET.getlist('risco'),
            'status_postagem': request.GET.getlist('status_postagem'),
        }
        for campo in CAMPOS_FAIXA:
            filtros[f'{campo}_min'] = request.GET.get(f'{campo}_min', '')
            filtros[f'{campo}_max'] = request.GET.get(f'{campo}_max', '')

        return cls(
            busca=busca, por_pagina=por_pagina, ordenar=ordenar,
            numero_pagina=request.GET.get('pagina', 1), tela=tela, filtros=filtros,
            data_simulada=data_simulada,
        )


class ConstrutorChipsAtivosAgendaVideos:

    def __init__(self, filtros: dict) -> None:
        self.filtros = filtros

    def _montar_chip_simples(self, label: str) -> Badge:
        return Badge(label=label, classe=None, icone=None)

    def _montar_chips_checkbox(self) -> list[Badge]:
        mapa_labels_etapa = dict(OPCOES_ETAPA)
        mapa_labels_periodo = dict(OPCOES_PERIODO)
        chips = [self._montar_chip_simples(m) for m in self.filtros['marcas']]
        chips += [BADGES_STATUS_MANUAL[v] for v in self.filtros['status_manual'] if v in BADGES_STATUS_MANUAL]
        chips += [self._montar_chip_simples('Urgente' if v == 'sim' else 'Não urgente') for v in self.filtros['urgente']]
        chips += [self._montar_chip_simples('Sem vídeo' if v == 'sim' else 'Com vídeo') for v in self.filtros['sem_video']]
        chips += [self._montar_chip_simples('Sincronizado com o Drive' if v == 'sim' else 'Não sincronizado com o Drive') for v in self.filtros['sincronizado_drive']]
        chips += [self._montar_chip_simples('Atrasado' if v == 'sim' else 'Não atrasado') for v in self.filtros['atrasado']]
        chips += [self._montar_chip_simples('Risco de atraso' if v == 'sim' else 'Sem risco') for v in self.filtros['risco']]
        chips += [self._montar_chip_simples(mapa_labels_etapa.get(v, v)) for v in self.filtros['etapa']]
        chips += [BADGES_STATUS_POSTAGEM[v] for v in self.filtros['status_postagem'] if v in BADGES_STATUS_POSTAGEM]
        if self.filtros.get('periodo') and self.filtros['periodo'] != Periodo.TODOS:
            chips.append(self._montar_chip_simples(mapa_labels_periodo.get(self.filtros['periodo'], self.filtros['periodo'])))
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

    def _montar_querystring_sem_tela_nem_pagina(self) -> str:
        # Função Objetivo: base do link de navegação entre as 6 telas —
        # preserva busca (única coisa que faz sentido cruzar de 1 tela pra
        # outra); período/etapa/aba são específicos de cada tela e nunca
        # devem "vazar" pra outra ao trocar de aba.
        qs = self.request.GET.copy()
        qs.pop('tela', None)
        qs.pop('pagina', None)
        qs.pop('periodo', None)
        qs.pop('etapa', None)
        qs.pop('aba', None)
        return qs.urlencode()

    def _montar_querystring_sem_periodo_nem_pagina(self) -> str:
        # Função Objetivo: base do link de Período (Geral/A Fazer Hoje) —
        # troca só o período, preserva tela/etapa/busca.
        qs = self.request.GET.copy()
        qs.pop('periodo', None)
        qs.pop('pagina', None)
        return qs.urlencode()

    def _montar_querystring_sem_aba_nem_pagina(self) -> str:
        # Função Objetivo: base do link de aba (Aguardando Postar/Replicar)
        # — troca só a aba, preserva tela/busca.
        qs = self.request.GET.copy()
        qs.pop('aba', None)
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
        produtos = listar_produtos_agenda_filtrados(
            tela=self.parametros.tela, busca=self.parametros.busca or None,
            filtros=self.parametros.filtros, ordenar=self.parametros.ordenar,
            data_referencia=self.parametros.data_simulada,
        )
        paginator = Paginator(produtos, self.parametros.por_pagina)
        pagina = paginator.get_page(self.parametros.numero_pagina)
        self._enriquecer_pagina(pagina)
        return pagina

    def _montar_contadores_chips(self) -> dict[str, int]:
        # Função Objetivo: 1 contagem por chip da tela atual — Etapa (Geral/
        # A Fazer Hoje) ou aba (Aguardando Postar/Replicar) — sobre o
        # queryset SEM esse filtro aplicado, senão o chip clicado zeraria a
        # própria contagem. As outras 3 telas não têm chip nenhum.
        if self.parametros.tela not in (Tela.GERAL, Tela.A_FAZER_HOJE, Tela.AGUARDANDO_POSTAR_REPLICAR):
            return {}

        filtros_sem_chip = {
            chave: valor for chave, valor in self.parametros.filtros.items()
            if chave not in ('etapa', 'aba')
        }
        qs_base, _ = construir_queryset_tela(
            self.parametros.tela, busca=self.parametros.busca or None,
            filtros=filtros_sem_chip, data_referencia=self.parametros.data_simulada,
        )

        if self.parametros.tela == Tela.AGUARDANDO_POSTAR_REPLICAR:
            condicoes = {chave: condicao_etapa(chave) for chave, _ in OPCOES_ABA}
        elif self.parametros.tela == Tela.A_FAZER_HOJE:
            condicoes = {chave: condicao_etapa(chave) for chave in ETAPAS_FABRICA}
        else:
            condicoes = {chave: condicao_etapa(chave) for chave, _ in OPCOES_ETAPA}
        return contar_por_condicoes(qs_base, condicoes)

    def _montar_contadores_navegacao(self) -> dict[str, int]:
        # Função Objetivo: 1 contagem por tela, pro número ao lado de cada
        # aba do menu principal. Ignora período/etapa/aba de propósito (é a
        # contagem "se eu limpasse os sub-filtros dessa tela") — só respeita
        # a busca, que cruza qualquer tela.
        return {
            valor: construir_queryset_tela(valor, busca=self.parametros.busca or None)[0].count()
            for valor, _ in OPCOES_TELA
        }

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
            'tela_atual': self.parametros.tela,
            'filtros': self.parametros.filtros,
            'cabecalhos': cabecalhos,
            'chips_ativos': chips_ativos,
            'marcas_disponiveis': marcas_disponiveis,
            'opcoes_tela': [OpcaoComBadge(valor=v, label=l, classe=None, icone=None) for v, l in OPCOES_TELA],
            'opcoes_periodo': [OpcaoComBadge(valor=v, label=l, classe=None, icone=None) for v, l in OPCOES_PERIODO],
            'opcoes_filtro_etapa': OPCOES_ETAPA,
            'opcoes_filtro_etapa_fabrica': [(c, l) for c, l in OPCOES_ETAPA if c in ETAPAS_FABRICA],
            'opcoes_aba': OPCOES_ABA,
            'opcoes_etapa': montar_opcoes_com_badge(BADGES_ETAPA),
            'opcoes_status_manual': montar_opcoes_com_badge(BADGES_STATUS_MANUAL),
            'opcoes_status_postagem': montar_opcoes_com_badge(BADGES_STATUS_POSTAGEM),
            'opcoes_sim_nao': OPCOES_SIM_NAO,
            'contadores_chips': self._montar_contadores_chips(),
            'contadores_navegacao': self._montar_contadores_navegacao(),
            'querystring_sem_pagina': self._montar_querystring_sem_pagina(),
            'querystring_sem_tela_nem_pagina': self._montar_querystring_sem_tela_nem_pagina(),
            'legenda_estados': EstadoVisualRoadmap.choices,
            'querystring_sem_periodo_nem_pagina': self._montar_querystring_sem_periodo_nem_pagina(),
            'querystring_sem_aba_nem_pagina': self._montar_querystring_sem_aba_nem_pagina(),
        }