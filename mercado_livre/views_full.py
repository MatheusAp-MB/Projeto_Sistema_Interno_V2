# mercado_livre/views_full.py
#
# Views da tela "Full — ficha do código" (Mercado Livre → Gestão de estoque Full →
# Planejamento de envios). A tela organiza, para 1 código por vez e em 3 níveis
# (Produto, Código ML do Full e 1 bloco por anúncio/MLB), os dados que o ML devolve
# (REPOS, ESTOQUE, ARQUIVO) ao lado do que está no nosso banco (BANCO) e do que só
# existe na tela (TELA), para a equipe dar nome a cada informação e registrar o que
# já foi conferido (A validar / Hipótese / Válido / Inválido). Não é a tela final:
# o layout vai mudando conforme o sistema cresce.
#
# REGRA DESTA TELA (Matheus): NUNCA chamar a API do ML sozinha. Abrir a tela,
# trocar de código, editar nome interno, situação ou observação — tudo lê/grava
# SÓ no banco. A API só é chamada por 1 botão, sob clique explícito:
#   - "Consultar no Mercado Livre" → view_full_consultar
# que guarda o que o ML respondeu em ConsultaFullMercadoLivre; a tela volta a ler
# só do banco.

import json

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from core.empresa import obter_empresa_ativa
from mercado_livre.views_caracteristicas import _nome_usuario, _plural

CHAVE_CACHE_TRAVA_CONSULTA = 'full_ml_consultando_{empresa}_{codigo}'
TIMEOUT_TRAVA_SEGUNDOS = 120

MAX_NOME_INTERNO = 120
MAX_OBSERVACAO = 2000


# Função Objetivo: Corpo JSON da requisição como dict, ou None se não for um objeto JSON.
def _ler_json(request):
    try:
        corpo = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None
    return corpo if isinstance(corpo, dict) else None


# Função Objetivo: A tela. LÊ SÓ DO BANCO — mostra a consulta mais recente do código
# pedido em ?codigo= (ou o estado vazio, com atalhos para os códigos já consultados).
def view_full_ficha(request):
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import formatar_data_hora
    from mercado_livre.funcoes_auxiliares.full_ml import (
        FONTES_FULL, ROTULO_PROJETO, buscar_ultima_consulta, carregar_validacoes, contar_situacoes,
        interpretar_codigo, ler_banco, listar_recentes, montar_pagina,
    )
    from mercado_livre.models import CampoFullMercadoLivre

    digitado = request.GET.get('codigo', '').strip()
    codigo, _, _ = interpretar_codigo(digitado) if digitado else (None, None, None)
    rotulos_situacao = dict(CampoFullMercadoLivre.Situacao.choices)
    validacoes = carregar_validacoes()

    consulta = buscar_ultima_consulta(codigo) if codigo else None
    # * [EXPLICAÇÃO] → ler_banco só LÊ as tabelas Produto, Anúncio e Variação (nada de ML, nada gravado).
    banco = ler_banco(consulta) if consulta else None
    pagina = montar_pagina(consulta, validacoes, rotulos_situacao, banco) if consulta else None

    recentes = [{'codigo': c.codigo, 'quando': formatar_data_hora(c.consultado_em)} for c in listar_recentes()]

    return render(request, 'mercado_livre/estrutura_full_ficha.html', {
        'digitado': digitado,
        'codigo': codigo,
        'codigo_invalido': bool(digitado) and codigo is None,
        'consulta': consulta,
        'consulta_quando': formatar_data_hora(consulta.consultado_em) if consulta else '',
        'pagina': pagina,
        'recentes': recentes,
        'placar': contar_situacoes(validacoes, rotulos_situacao),
        'situacoes': list(CampoFullMercadoLivre.Situacao.choices),
        'legenda_fontes': [
            {'chave': chave, 'nome': info['nome'], 'projeto': info['projeto'],
             'projeto_rotulo': ROTULO_PROJETO[info['projeto']]}
            for chave, info in FONTES_FULL.items()
        ],
    })


# Função Objetivo: Botão "Consultar no Mercado Livre" — lê da API os dados de Full do
# código e grava no banco. Síncrono: são ~2 chamadas, o navegador espera a resposta.
# Recusa clique duplo no mesmo código. A resposta traz a URL da tela já com o código,
# para o navegador recarregar lendo do banco.
@require_POST
def view_full_consultar(request):
    import traceback

    from django.core.cache import cache

    from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
    from integracao_mercado_livre.servicos.consultar_full_ml import ErroConsultaFull, consultar_codigo
    from mercado_livre.funcoes_auxiliares.full_ml import interpretar_codigo

    corpo = _ler_json(request)
    codigo, _, _ = interpretar_codigo((corpo or {}).get('codigo'))
    if codigo is None:
        return JsonResponse({'ok': False, 'mensagem': 'Digite um código válido antes de consultar.'}, status=400)

    empresa = obter_empresa_ativa()

    chave_trava = CHAVE_CACHE_TRAVA_CONSULTA.format(empresa=empresa, codigo=codigo)
    if not cache.add(chave_trava, True, timeout=TIMEOUT_TRAVA_SEGUNDOS):
        return JsonResponse({'ok': False, 'mensagem': 'Este código já está sendo consultado.'}, status=409)

    try:
        relatorio = consultar_codigo(empresa, codigo, _nome_usuario(request))
    except ErroConsultaFull as erro:
        return JsonResponse({'ok': False, 'mensagem': str(erro)}, status=422)
    except ErroAutenticacaoAPI:
        traceback.print_exc()
        return JsonResponse(
            {'ok': False, 'mensagem': 'O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi gravado.'},
            status=502,
        )
    except Exception:
        traceback.print_exc()
        return JsonResponse(
            {'ok': False, 'mensagem': 'Falha inesperada ao consultar o Mercado Livre. O detalhe está no terminal do servidor.'},
            status=500,
        )
    finally:
        cache.delete(chave_trava)

    mensagem = f'{relatorio.chamadas} {_plural(relatorio.chamadas, "chamada feita", "chamadas feitas")} ao Mercado Livre'
    if relatorio.falhas:
        n_falhas = len(relatorio.falhas)
        mensagem += f'; {n_falhas} {_plural(n_falhas, "falhou", "falharam")} (o motivo aparece em "De onde vêm os dados")'
    mensagem += '.'

    return JsonResponse({
        'ok': True,
        'mensagem': mensagem,
        'url': reverse('mercado_livre_full') + '?' + urlencode({'codigo': relatorio.codigo}),
    })


# Função Objetivo: Grava o que a equipe registrou de 1 campo da ficha — nome interno,
# situação e observação. Não chama a API. O campo é identificado por fonte + caminho e
# tem que existir no catálogo da ficha (assim ninguém grava lixo por uma requisição à mão).
@require_POST
def view_full_salvar_campo(request):
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import formatar_data_hora
    from mercado_livre.funcoes_auxiliares.full_ml import CHAVES_VALIDAS, chave_campo
    from mercado_livre.models import CampoFullMercadoLivre

    corpo = _ler_json(request)
    if corpo is None:
        return JsonResponse({'ok': False, 'mensagem': 'Não entendi o que a tela enviou. Recarregue a página e tente de novo.'}, status=400)

    fonte = str(corpo.get('fonte') or '')
    caminho = str(corpo.get('caminho') or '')
    nome_interno = str(corpo.get('nome_interno') or '').strip()
    situacao = str(corpo.get('situacao') or '')
    observacao = str(corpo.get('observacao') or '').strip()

    if chave_campo(fonte, caminho) not in CHAVES_VALIDAS:
        return JsonResponse({'ok': False, 'mensagem': 'Este campo não existe na ficha. Recarregue a página.'}, status=404)
    if situacao not in CampoFullMercadoLivre.Situacao.values:
        return JsonResponse({'ok': False, 'mensagem': 'Situação inválida.'}, status=400)
    if len(nome_interno) > MAX_NOME_INTERNO:
        return JsonResponse({'ok': False, 'mensagem': f'O nome interno aceita até {MAX_NOME_INTERNO} caracteres.'}, status=400)
    if len(observacao) > MAX_OBSERVACAO:
        return JsonResponse({'ok': False, 'mensagem': f'A observação aceita até {MAX_OBSERVACAO} caracteres.'}, status=400)

    campo, _ = CampoFullMercadoLivre.objects.update_or_create(
        fonte=fonte, caminho=caminho,
        defaults={
            'nome_interno': nome_interno,
            'situacao': situacao,
            'observacao': observacao,
            'atualizado_por': _nome_usuario(request),
        },
    )
    return JsonResponse({
        'ok': True,
        'mensagem': 'Salvo',
        'situacao': campo.situacao,
        'situacao_rotulo': campo.get_situacao_display(),
        'atualizado_em': formatar_data_hora(campo.atualizado_em),
    })
