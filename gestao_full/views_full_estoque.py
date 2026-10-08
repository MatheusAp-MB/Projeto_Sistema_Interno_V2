# gestao_full/views_full_estoque.py
#
# Views da tela "Full — Estoque no Full" (Mercado Livre → Gestão de estoque Full → Estoque no Full): para cada
# PRODUTO, quanto estoque ele tem hoje no Full, somando os Códigos ML dele. É a tela de CONSULTA ("quanto temos?");
# a tela de Planejamento de envios responde "quanto enviar?".
#
# REGRA DO MATHEUS: esta tela NUNCA chama a API do ML SOZINHA. Abrir, buscar, filtrar, ordenar e paginar só LEEM o
# banco (os Códigos ML de cada produto e a consulta mais recente de cada Código). A API só é chamada por CLIQUE, em 3 botões:
#   - "Atualizar" (um Código ML) e "Atualizar produto" (todos os Códigos dele)  → view_full_estoque_atualizar
#     (e view_full_estoque_faixa, que só LÊ o banco para refazer a faixa de totais do topo depois)
#   - "Fazer varredura completa" (todos os Códigos da empresa, em segundo plano) → view_full_estoque_varredura_iniciar
#     (com _status para a barra de andamento e _parar para interromper)
# Todos usam a mesma consulta do botão "Consultar no Mercado Livre" do Planejamento (consultar_codigo), que grava o que o
# ML respondeu no banco; a tela volta a ler só do banco e redesenha o produto no lugar, sem recarregar a página.

from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.empresa import obter_empresa_ativa
from gestao_full.views_full import _ler_json
from mercado_livre.views_caracteristicas import _nome_usuario, _plural

MSG_VARREDURA_RODANDO = 'Há uma varredura completa em andamento. Espere terminar (ou clique em Parar) para atualizar um Código ou um produto.'


# Função Objetivo: A tela. LÊ SÓ DO BANCO. Os parâmetros da URL (q, filtro, ordem, p) são validados dentro de montar_estoque.
def view_full_estoque(request):
    from gestao_full.funcoes_auxiliares.full_estoque_ml import montar_estoque
    from gestao_full.funcoes_auxiliares.full_ml import carregar_validacoes
    from mercado_livre.models import CampoFullMercadoLivre

    rotulos_situacao = dict(CampoFullMercadoLivre.Situacao.choices)
    return render(request, 'gestao_full/estrutura_full_estoque.html', {
        'pagina': montar_estoque(request.GET, carregar_validacoes(), rotulos_situacao),
        'url_estoque': reverse('gestao_full_estoque'),
        'url_planejamento': reverse('gestao_full_planejamento'),
        'url_debug': reverse('gestao_full_debug'),
        # Endereços que o JS usa nos botões de atualização (só são chamados depois de um clique).
        'url_atualizar': reverse('gestao_full_estoque_atualizar'),
        'url_faixa': reverse('gestao_full_estoque_faixa'),
        'url_varredura_iniciar': reverse('gestao_full_estoque_varredura_iniciar'),
        'url_varredura_status': reverse('gestao_full_estoque_varredura_status'),
        'url_varredura_parar': reverse('gestao_full_estoque_varredura_parar'),
    })


# Função Objetivo: Botões "Atualizar" (1 Código ML) e "Atualizar produto" (a tela chama este endereço 1 vez por Código do produto, em fila).
# Consulta o Código no Mercado Livre, grava no banco e devolve o produto JÁ REDESENHADO com o número novo (html). A faixa de totais do topo
# é refeita à parte (view_full_estoque_faixa), uma vez no fim, para não refazer a soma da lista inteira a cada Código.
# Recusa se uma varredura completa está rodando e se o mesmo Código já está sendo consultado. Mesmos erros do botão do Planejamento; o acesso
# recusado (502) e a varredura rodando (409) vêm com "interromper": a tela para a fila de um produto.
@require_POST
def view_full_estoque_atualizar(request):
    import traceback

    from gestao_full.funcoes_auxiliares.full_estoque_ml import BADGE_A_CAMINHO, montar_um_produto
    from gestao_full.funcoes_auxiliares.full_estoque_varredura import CodigoOcupado, consultar_com_trava, varredura_em_andamento
    from gestao_full.funcoes_auxiliares.full_ml import interpretar_codigo
    from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
    from integracao_mercado_livre.servicos.consultar_full_ml import ErroConsultaFull

    corpo = _ler_json(request) or {}
    codigo, _, _ = interpretar_codigo(corpo.get('codigo'))
    if codigo is None:
        return JsonResponse({'ok': False, 'mensagem': 'Código ML inválido. Recarregue a página e tente de novo.'}, status=400)
    sku = str(corpo.get('sku') or '').strip()
    try:
        indice = int(corpo.get('indice') or 0)
    except (TypeError, ValueError):
        indice = 0

    empresa = obter_empresa_ativa()
    if varredura_em_andamento(empresa) is not None:
        return JsonResponse({'ok': False, 'mensagem': MSG_VARREDURA_RODANDO, 'interromper': True}, status=409)

    try:
        relatorio = consultar_com_trava(empresa, codigo, _nome_usuario(request))
    except CodigoOcupado:
        return JsonResponse({'ok': False, 'mensagem': f'O Código {codigo} já está sendo consultado (em outra aba ou pelo Planejamento). Espere um instante.'}, status=409)
    except ErroConsultaFull as erro:
        return JsonResponse({'ok': False, 'mensagem': str(erro)}, status=422)
    except ErroAutenticacaoAPI:
        traceback.print_exc()
        return JsonResponse({'ok': False, 'interromper': True,
                             'mensagem': 'O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi gravado.'}, status=502)
    except Exception:
        traceback.print_exc()
        return JsonResponse({'ok': False, 'mensagem': 'Falha inesperada ao consultar o Mercado Livre. O detalhe está no terminal do servidor.'}, status=500)

    n_falhas = len(relatorio.falhas)
    mensagem = f'Código {codigo} atualizado: {relatorio.chamadas} {_plural(relatorio.chamadas, "chamada feita", "chamadas feitas")} ao Mercado Livre'
    if n_falhas:
        mensagem += f'; {n_falhas} {_plural(n_falhas, "falhou", "falharam")} (o Mercado Livre não devolveu tudo)'
    mensagem += '.'

    # A consulta já está gravada. Se a remontagem do produto falhar, a pessoa ainda vê que o Código foi atualizado e pode recarregar a tela.
    resposta = {'ok': True, 'mensagem': mensagem, 'falhas': n_falhas, 'html': ''}
    try:
        produto = montar_um_produto(sku, indice)
        if produto is not None:
            resposta['html'] = render_to_string('gestao_full/parciais/estrutura_parcial_produto_estoque.html', {
                'produto': produto, 'aberto': True, 'badge_a_caminho': BADGE_A_CAMINHO}, request=request)
    except Exception:
        traceback.print_exc()
        resposta['mensagem'] += ' Não consegui redesenhar o produto: recarregue a página para ver o número novo.'
        resposta['html'] = ''
    return JsonResponse(resposta)


# Função Objetivo: A faixa de totais do topo refeita com o que o banco tem agora (a tela troca a faixa velha por esta depois de um "Atualizar").
# LÊ SÓ DO BANCO. Recebe a mesma query string da tela (q, filtro, marca...), para somar a MESMA lista que a pessoa está vendo.
@require_GET
def view_full_estoque_faixa(request):
    from gestao_full.funcoes_auxiliares.full_estoque_ml import montar_faixa_de_totais

    return JsonResponse({'html': render_to_string('gestao_full/parciais/estrutura_parcial_resumo_estoque.html', {
        'pagina': montar_faixa_de_totais(request.GET)}, request=request)})


# Função Objetivo: Botão "Fazer varredura completa" (depois da confirmação na janela): só dispara a varredura em segundo plano e responde na
# hora. Se já há uma rodando, devolve o estado dela em vez de começar outra.
@require_POST
def view_full_estoque_varredura_iniciar(request):
    from gestao_full.funcoes_auxiliares.full_estoque_varredura import iniciar_varredura

    estado, _ = iniciar_varredura(obter_empresa_ativa(), _nome_usuario(request))
    return JsonResponse(estado)


# Função Objetivo: Polling da barra de andamento (GET simples, só lê o cache). Terminou ou deu erro: entrega o resultado UMA vez.
@require_GET
def view_full_estoque_varredura_status(request):
    from gestao_full.funcoes_auxiliares.full_estoque_varredura import ler_estado_varredura

    return JsonResponse(ler_estado_varredura(obter_empresa_ativa()))


# Função Objetivo: Botão "Parar": a varredura termina o Código que está consultando e encerra (o que já foi consultado fica salvo).
@require_POST
def view_full_estoque_varredura_parar(request):
    from gestao_full.funcoes_auxiliares.full_estoque_varredura import pedir_parada

    estado = pedir_parada(obter_empresa_ativa())
    if estado is None:
        return JsonResponse({'status': 'ocioso', 'mensagem': 'Não há varredura em andamento.'})
    return JsonResponse(estado)
