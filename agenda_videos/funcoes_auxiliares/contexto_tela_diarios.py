# agenda_videos/funcoes_auxiliares/contexto_tela_diarios.py

# Função Objetivo: Monta todo o contexto da tela "Diários" — mesma arquitetura já validada
# em Produtos e no Hub de Anúncios (busca/filtro/ordenação/paginação no servidor).

from dataclasses import dataclass, field
from django.core.paginator import Paginator
from produtos.models import Produto
from agenda_videos.models import Fase
from agenda_videos.funcoes_auxiliares.filtros_diarios import (
    listar_produtos_diarios_filtrados, CAMPOS_ORDENACAO, CAMPOS_FAIXA,
)
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
    'progresso_producao_video__quantidade_roteiros': 'Qtd. Roteiros',
}

SECOES_FILTRO_FAIXA = [
    {'titulo': 'Andamento', 'campos': [
        ('andamento_agenda__ocorrencia_atual', 'Ocorrência'),
        ('andamento_agenda__inicio_fase', 'Início da Fase'),
        ('andamento_agenda__fim_fase', 'Fim da Fase'),
    ]},
    {'titulo': 'Produção de Vídeo', 'campos': [
        ('progresso_producao_video__quantidade_roteiros', 'Qtd. Roteiros'),
    ]},
]

OPCOES_SIM_NAO = [
    {'valor': 'sim', 'label': 'Sim', 'classe': None, 'icone': None},
    {'valor': 'nao', 'label': 'Não', 'classe': None, 'icone': None},
]


# Função Objetivo: Representa os parâmetros de busca/filtro/ordenação já validados.
@dataclass
class ParametrosBuscaDiarios:
    busca: str
    por_pagina: int
    ordenar: str
    numero_pagina: int
    filtros: dict = field(default_factory=dict)

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

        filtros = {
            'marcas': request.GET.getlist('marca'),
            'status_manual': request.GET.getlist('status_manual'),
            'urgente': request.GET.getlist('urgente'),
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
        )


# Função Objetivo: Monta os chips de "filtro ativo" exibidos acima da lista.
class ConstrutorChipsAtivosDiarios:

    def __init__(self, filtros):
        self.filtros = filtros

    def _chip_simples(self, label):
        return {'label': label, 'classe': None, 'icone': None}

    def _chips_checkbox(self):
        chips = [self._chip_simples(m) for m in self.filtros['marcas']]
        chips += [BADGES_STATUS_MANUAL[v] for v in self.filtros['status_manual'] if v in BADGES_STATUS_MANUAL]
        chips += [self._chip_simples('Urgente' if v == 'sim' else 'Não urgente') for v in self.filtros['urgente']]
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


# Função Objetivo: Orquestra a montagem inteira do contexto da tela "Diários".
class ContextoTelaDiarios:

    def __init__(self, request):
        self.request = request
        self.parametros = ParametrosBuscaDiarios.a_partir_da_requisicao(request)

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
        produtos = listar_produtos_diarios_filtrados(
            busca=self.parametros.busca or None,
            filtros=self.parametros.filtros,
            ordenar=self.parametros.ordenar,
        )
        paginator = Paginator(produtos, self.parametros.por_pagina)
        return paginator.get_page(self.parametros.numero_pagina)

    def montar(self):
        cabecalhos = ConstrutorCabecalhosOrdenacao(
            self.parametros.ordenar, self._querystring_base(),
        ).montar(LABELS_COLUNAS)

        chips_ativos = ConstrutorChipsAtivosDiarios(self.parametros.filtros).montar()

        marcas_disponiveis = (
            Produto.objects
            .filter(andamento_agenda__fase_atual__fase=Fase.DIARIA, andamento_agenda__concluido=False)
            .exclude(marca__isnull=True).exclude(marca='')
            .values_list('marca', flat=True).distinct().order_by('marca')
        )

        return {
            'pagina': self._montar_pagina(),
            'busca': self.parametros.busca,
            'por_pagina': self.parametros.por_pagina,
            'filtros': self.parametros.filtros,
            'cabecalhos': cabecalhos,
            'chips_ativos': chips_ativos,
            'secoes_filtro_faixa': SECOES_FILTRO_FAIXA,
            'marcas_disponiveis': marcas_disponiveis,
            'opcoes_status_manual': opcoes_com_badge(BADGES_STATUS_MANUAL),
            'opcoes_status_video': opcoes_com_badge(BADGES_STATUS_VIDEO),
            'opcoes_status_postagem': opcoes_com_badge(BADGES_STATUS_POSTAGEM),
            'opcoes_sim_nao': OPCOES_SIM_NAO,
            # * [EXPLICAÇÃO] → Passado pro contexto pra resolver o badge do
            #                  status_postagem_recente (vem de Subquery, é só
            #                  uma string crua) — usa o get_item genérico que
            #                  já existe em core/templatetags/filtros.py, sem
            #                  precisar de nenhum filtro de template novo.
            'badges_status_postagem': BADGES_STATUS_POSTAGEM,
            'querystring_sem_pagina': self._querystring_sem_pagina(),
        }