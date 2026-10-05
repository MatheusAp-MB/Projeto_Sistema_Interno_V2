# mercado_livre/views_caracteristicas.py
#
# Views da tela "Características dos anúncios" (Mercado Livre).
#
# REGRA DESTA TELA (Matheus): NUNCA chamar a API do ML sozinha. Abrir a tela,
# filtrar, expandir um produto, paginar — tudo lê SÓ do banco. A API só é
# chamada por 2 botões, sob clique explícito:
#   - "Fazer varredura completa" → view_caracteristicas_varredura_iniciar
#   - "Atualizar" (de 1 produto)  → view_caracteristicas_atualizar_produto
# Os dois guardam o que leram no banco; a tela volta a ler só do banco.

import threading
import time

from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core.empresa import definir_empresa_ativa, obter_empresa_ativa

# * [EXPLICAÇÃO] → O estado da varredura mora no cache (como no Portal do
#                  Drive), 1 chave por empresa — Magazine e Samvale podem
#                  varrer ao mesmo tempo sem se atrapalhar.
CHAVE_CACHE_VARREDURA = 'caracteristicas_ml_varredura_{empresa}'
CHAVE_CACHE_TRAVA_PRODUTO = 'caracteristicas_ml_atualizando_{empresa}_{sku}'
TIMEOUT_CACHE_SEGUNDOS = 900

# * [EXPLICAÇÃO] → Se uma varredura diz "rodando" mas não gravou progresso há
#                  mais que isso, a thread morreu (ex.: o servidor reiniciou
#                  com um cache que sobrevive ao reinício) — a tela deixa
#                  começar outra em vez de ficar travada para sempre.
SEGUNDOS_SEM_PROGRESSO_PARA_CONSIDERAR_PARADA = 300

# * [EXPLICAÇÃO] → Quantas vezes por segundo o progresso é gravado no cache.
#                  Cada anúncio lido dispara o callback; gravar em todos seria
#                  barulho à toa (o navegador só pergunta a cada ~2 s).
INTERVALO_GRAVACAO_PROGRESSO = 1.0

OPCOES_POR_PAGINA = (10, 25, 50, 100)
POR_PAGINA_PADRAO = 25

# * [EXPLICAÇÃO] → Os 4 blocos de resumo do topo (que também são os filtros
#                  da lista): valor do filtro, título, explicação curta e
#                  ícone. A chave (todos/nunca/parcial/completa) também dá a
#                  cor do bloco no CSS.
ROTULOS_FILTRO_LEITURA = (
    ('', 'todos', 'Todos os produtos', 'com anúncio ativo ou pausado', 'fa-boxes-stacked'),
    ('nunca', 'nunca', 'Nunca lidos', 'ainda sem dados do ML', 'fa-eye-slash'),
    ('parcial', 'parcial', 'Lidos em parte', 'faltam anúncios a ler', 'fa-circle-half-stroke'),
    ('completa', 'completa', 'Lidos', 'todos os anúncios lidos', 'fa-circle-check'),
)


def _plural(n, singular, plural):
    return singular if n == 1 else plural


def _chave_varredura(empresa):
    return CHAVE_CACHE_VARREDURA.format(empresa=empresa)


# Função Objetivo: Estado da varredura desta empresa que ainda vale (rodando
# e com progresso recente), ou None.
def _varredura_em_andamento(empresa):
    from django.core.cache import cache

    estado = cache.get(_chave_varredura(empresa))
    if not estado or estado.get('status') != 'rodando':
        return None
    if time.time() - estado.get('atualizado_em', 0) > SEGUNDOS_SEM_PROGRESSO_PARA_CONSIDERAR_PARADA:
        return None
    return estado


def _nome_usuario(request):
    usuario = getattr(request, 'user', None)
    if usuario is not None and getattr(usuario, 'is_authenticated', False):
        return usuario.get_username()
    return ''


# Função Objetivo: Tela principal — lista de produtos (1 linha por SKU) com
# busca, filtro de marca e filtro de leitura. LÊ SÓ DO BANCO.
def view_caracteristicas_anuncios(request):
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import (
        estimar_varredura, formatar_data_hora, listar_produtos,
    )
    from mercado_livre.models import VarreduraCaracteristicasMercadoLivre

    busca = request.GET.get('busca', '').strip()
    marca = request.GET.get('marca', '').strip()
    leitura = request.GET.get('leitura', '').strip()
    if leitura not in ('nunca', 'parcial', 'completa'):
        leitura = ''

    try:
        por_pagina = int(request.GET.get('por_pagina', POR_PAGINA_PADRAO))
    except ValueError:
        por_pagina = POR_PAGINA_PADRAO
    if por_pagina not in OPCOES_POR_PAGINA:
        por_pagina = POR_PAGINA_PADRAO

    resultado = listar_produtos(busca=busca, marca=marca, leitura=leitura)
    paginador = Paginator(resultado['produtos'], por_pagina)
    pagina = paginador.get_page(request.GET.get('pagina', 1))
    for produto in pagina.object_list:
        produto['ultima_leitura_txt'] = formatar_data_hora(produto['ultima_leitura'])

    # Os botões de filtro de leitura mantêm busca, marca e por_pagina.
    base = request.GET.copy()
    base.pop('pagina', None)
    base.pop('leitura', None)
    filtros_leitura = []
    for valor, chave, rotulo, descricao, icone in ROTULOS_FILTRO_LEITURA:
        consulta = base.copy()
        if valor:
            consulta['leitura'] = valor
        filtros_leitura.append({
            'valor': valor,
            'chave': chave,
            'rotulo': rotulo,
            'descricao': descricao,
            'icone': icone,
            'n': resultado['contagens'][chave],
            'url': '?' + consulta.urlencode(),
            'ativo': valor == leitura,
        })

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    ultima_varredura = (
        VarreduraCaracteristicasMercadoLivre.objects
        .exclude(situacao=VarreduraCaracteristicasMercadoLivre.Situacao.RODANDO)
        .first()
    )
    if ultima_varredura is not None:
        ultima_varredura.iniciada_txt = formatar_data_hora(ultima_varredura.iniciada_em)
        ultima_varredura.falhas_lista = ultima_varredura.falhas or []

    return render(request, 'mercado_livre/estrutura_caracteristicas_anuncios.html', {
        'pagina': pagina,
        'busca': busca,
        'marca': marca,
        'leitura': leitura,
        'por_pagina': por_pagina,
        'opcoes_por_pagina': OPCOES_POR_PAGINA,
        'marcas': resultado['marcas'],
        'filtros_leitura': filtros_leitura,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'total_produtos': resultado['contagens']['todos'],
        'ultima_varredura': ultima_varredura,
        'estimativa': estimar_varredura(),
    })


# Função Objetivo: A "ficha" de 1 produto (tabela de anúncios + cards),
# devolvida como pedaço de HTML para o HTMX encaixar na linha do produto.
# LÊ SÓ DO BANCO — expandir a linha nunca chama a API.
@require_GET
def view_caracteristicas_ficha(request, sku):
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import formatar_data_hora, montar_ficha_produto

    ficha = montar_ficha_produto(sku)
    if ficha is None:
        raise Http404('Produto não encontrado.')

    ficha['resumo']['ultima_leitura_txt'] = formatar_data_hora(ficha['resumo']['ultima_leitura'])
    for linha in ficha['tabela']['linhas']:
        linha['lido_em_txt'] = formatar_data_hora(linha['lido_em'])
    return render(request, 'mercado_livre/parciais/estrutura_parcial_ficha_caracteristicas.html', {'ficha': ficha})


# Função Objetivo: Botão "Atualizar" de 1 produto — lê da API os anúncios
# desse SKU (e só as categorias que o banco ainda não conhece) e grava no
# banco. Síncrono: são poucos anúncios por produto, então o navegador espera
# a resposta. Recusa se uma varredura completa está rodando (as duas
# gravariam nos mesmos anúncios) ou se este mesmo produto já está sendo
# atualizado (duplo clique).
@require_POST
def view_caracteristicas_atualizar_produto(request, sku):
    import traceback

    from django.core.cache import cache

    from api_mercado_livre.core.estrutura_api.cliente_api import ErroAutenticacaoAPI
    from integracao_mercado_livre.servicos.sincronizar_caracteristicas_ml import atualizar_produto
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import resumir_produto

    empresa = obter_empresa_ativa()

    if resumir_produto(sku)['n_anuncios'] == 0:
        return JsonResponse(
            {'ok': False, 'mensagem': 'Este produto não tem anúncios elegíveis para leitura.'}, status=404,
        )

    if _varredura_em_andamento(empresa) is not None:
        return JsonResponse(
            {'ok': False, 'mensagem': 'Há uma varredura completa em andamento. Espere terminar para atualizar um produto.'},
            status=409,
        )

    chave_trava = CHAVE_CACHE_TRAVA_PRODUTO.format(empresa=empresa, sku=sku)
    if not cache.add(chave_trava, True, timeout=TIMEOUT_CACHE_SEGUNDOS):
        return JsonResponse({'ok': False, 'mensagem': 'Este produto já está sendo atualizado.'}, status=409)

    try:
        relatorio = atualizar_produto(empresa, sku)
    except ErroAutenticacaoAPI:
        traceback.print_exc()
        return JsonResponse(
            {'ok': False, 'mensagem': 'O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi gravado.'},
            status=502,
        )
    except Exception:
        traceback.print_exc()
        return JsonResponse(
            {'ok': False, 'mensagem': 'Falha inesperada ao ler do Mercado Livre. O detalhe está no terminal do servidor.'},
            status=500,
        )
    finally:
        cache.delete(chave_trava)

    lidos_txt = (
        f'{relatorio.anuncios_lidos} de {relatorio.total_anuncios} '
        f'{_plural(relatorio.total_anuncios, "anúncio lido", "anúncios lidos")}'
    )
    if relatorio.falhas:
        n_falhas = len(relatorio.falhas)
        mensagem = f'{lidos_txt}; {n_falhas} {_plural(n_falhas, "falhou", "falharam")} (veja abaixo).'
    else:
        mensagem = f'{lidos_txt} do Mercado Livre.'

    return JsonResponse({
        'ok': True,
        'mensagem': mensagem,
        'falhas': relatorio.falhas[:10],
        'resumo': resumir_produto(sku),
    })


# Função Objetivo: Roda a varredura de verdade numa thread separada,
# publicando o progresso no cache — quem lê é a view de status (polling do
# navegador). Mesmo padrão do Portal do Drive.
def _rodar_varredura_em_thread(empresa, usuario):
    import traceback

    from django.core.cache import cache
    from django.db import connections

    from api_mercado_livre.core.estrutura_api.cliente_api import ErroAutenticacaoAPI
    from integracao_mercado_livre.servicos.sincronizar_caracteristicas_ml import (
        FASE_ANUNCIOS, FASE_CATEGORIAS, varredura_completa,
    )

    # * [EXPLICAÇÃO] → A empresa ativa vive num threading.local() que só a
    #                  thread da requisição tem preenchido; esta é uma thread
    #                  nova, então precisa receber a empresa e definir de novo
    #                  (mesmo motivo do Portal do Drive).
    definir_empresa_ativa(empresa)
    chave = _chave_varredura(empresa)
    ultimo = {'gravado_em': 0.0}

    def gravar(estado):
        estado['atualizado_em'] = time.time()
        cache.set(chave, estado, timeout=TIMEOUT_CACHE_SEGUNDOS)

    def ao_progredir(fase, atual, total):
        agora = time.time()
        terminou_fase = bool(total) and atual >= total
        if not terminou_fase and agora - ultimo['gravado_em'] < INTERVALO_GRAVACAO_PROGRESSO:
            return
        ultimo['gravado_em'] = agora
        gravar({
            'status': 'rodando',
            'fase': fase,
            'rotulo': 'Lendo os anúncios' if fase == FASE_ANUNCIOS else 'Lendo as categorias',
            'atual': atual,
            'total': total,
        })

    try:
        relatorio = varredura_completa(empresa, usuario=usuario, ao_progredir=ao_progredir)
    except ErroAutenticacaoAPI:
        traceback.print_exc()
        gravar({
            'status': 'erro',
            'mensagem': 'O Mercado Livre recusou o acesso (token inválido ou vencido). A varredura foi interrompida.',
        })
        return
    except Exception:
        # * [EXPLICAÇÃO] → Mantido de propósito: thread em background que
        #                  falha em silêncio é impossível de investigar depois.
        traceback.print_exc()
        gravar({
            'status': 'erro',
            'mensagem': 'A varredura parou por um erro inesperado. O detalhe está no terminal do servidor.',
        })
        return
    finally:
        connections.close_all()

    n_falhas = len(relatorio.falhas)
    gravar({
        'status': 'concluido',
        'mensagem': (
            f'Varredura concluída: {relatorio.anuncios_lidos} de {relatorio.total_anuncios} '
            f'{_plural(relatorio.total_anuncios, "anúncio", "anúncios")} e '
            f'{relatorio.categorias_lidas} {_plural(relatorio.categorias_lidas, "categoria", "categorias")} '
            f'lidos em {int(relatorio.duracao_segundos)} s'
            + (f', com {n_falhas} {_plural(n_falhas, "falha", "falhas")}.' if n_falhas else '.')
        ),
        'com_falhas': bool(n_falhas),
    })


# Função Objetivo: Botão "Fazer varredura completa" (depois da confirmação
# na janela) — só dispara a thread e responde na hora. Se já há uma varredura
# desta empresa rodando, devolve o estado dela em vez de começar outra.
@require_POST
def view_caracteristicas_varredura_iniciar(request):
    from django.core.cache import cache

    empresa = obter_empresa_ativa()
    em_andamento = _varredura_em_andamento(empresa)
    if em_andamento is not None:
        return JsonResponse(em_andamento)

    estado_inicial = {
        'status': 'rodando', 'fase': 'iniciando', 'rotulo': 'Preparando a leitura',
        'atual': 0, 'total': None, 'atualizado_em': time.time(),
    }
    cache.set(_chave_varredura(empresa), estado_inicial, timeout=TIMEOUT_CACHE_SEGUNDOS)

    # * [EXPLICAÇÃO] → A empresa é capturada AQUI (thread da requisição, onde
    #                  o EmpresaMiddleware já a resolveu) e repassada à thread.
    threading.Thread(
        target=_rodar_varredura_em_thread,
        args=(empresa, _nome_usuario(request)),
        daemon=True,
    ).start()

    return JsonResponse(estado_inicial)


# Função Objetivo: Polling da barra de progresso (GET simples; só lê o
# cache). Quando a varredura terminou ou deu erro, o resultado é entregue
# UMA vez e sai do cache — assim ele não reaparece a cada recarga da página.
@require_GET
def view_caracteristicas_varredura_status(request):
    from django.core.cache import cache

    empresa = obter_empresa_ativa()
    chave = _chave_varredura(empresa)
    estado = cache.get(chave)
    if not estado:
        return JsonResponse({'status': 'ocioso'})

    if estado.get('status') == 'rodando':
        if _varredura_em_andamento(empresa) is None:
            cache.delete(chave)
            return JsonResponse({
                'status': 'erro',
                'mensagem': 'A varredura anterior parou sem terminar (provavelmente o servidor foi reiniciado). Você pode começar outra.',
            })
        return JsonResponse(estado)

    cache.delete(chave)
    return JsonResponse(estado)
