# gestao_full/views_full_comparativo.py
#
# Views da tela "Full — Comparativo de estoque (debug)" (Mercado Livre → Gestão de estoque Full → Comparativo de estoque): o estoque de cada SKU
# lado a lado nas 3 fontes — Arquivo do ERP | API Sysemp | API Mercado Livre. É uma tela de debug, sem ligação com nenhum outro módulo do sistema:
# serve para o Matheus entender se os dados da API Sysemp são confiáveis e o que pedir à Sysemp.
#
# REGRA DO MATHEUS: esta tela NUNCA chama nenhuma API SOZINHA. Abrir, buscar, filtrar, ordenar e paginar só LEEM o arquivo do ERP, a última coleta da
# Sysemp (guardada na memória do servidor) e o banco (as consultas do Mercado Livre já gravadas). A API Sysemp só é chamada por CLIQUE, no botão
# "Coletar do Sysemp" (que roda em segundo plano, com andamento e botão Parar). O Mercado Livre NÃO é consultado aqui: as consultas dele são feitas na
# tela "Estoque no Full" (Atualizar / varredura completa).
# O botão "Exportar Excel" também só LÊ (a mesma montagem da tela): baixa a lista inteira num .xlsx para analisar fora do sistema.

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.empresa import obter_empresa_ativa


# Função Objetivo: A tela. LÊ SÓ o arquivo, a coleta guardada e o banco. Os parâmetros da URL (q, filtro, ordem, por_pagina, p) são validados em montar_comparativo.
def view_full_comparativo(request):
    from gestao_full.funcoes_auxiliares.comparativo_estoque import montar_comparativo

    return render(request, 'gestao_full/estrutura_full_comparativo.html', {
        'pagina': montar_comparativo(request.GET, obter_empresa_ativa()),
        'url_comparativo': reverse('gestao_full_comparativo_estoque'),
        'url_estoque': reverse('gestao_full_estoque'),
        # Endereços que o JS usa (só são chamados depois de um clique, exceto o status, que só lê o cache do servidor).
        'url_coletar': reverse('gestao_full_comparativo_coletar'),
        'url_coletar_status': reverse('gestao_full_comparativo_coletar_status'),
        'url_coletar_parar': reverse('gestao_full_comparativo_coletar_parar'),
    })


# Função Objetivo: Botão "Exportar Excel": baixa um .xlsx com a MESMA lista da tela (busca, filtro e ordem de agora), mas INTEIRA — todos os SKUs, não só a página.
# Só LÊ o arquivo, a coleta guardada e o banco, como a tela: não chama API nenhuma. Serve para analisar os números fora do sistema.
@require_GET
def view_full_comparativo_exportar(request):
    from django.http import HttpResponse
    from django.utils import timezone
    from gestao_full.funcoes_auxiliares.comparativo_estoque import montar_comparativo
    from gestao_full.funcoes_auxiliares.comparativo_estoque_exportacao import gerar_excel_comparativo, nome_do_arquivo

    empresa = obter_empresa_ativa()
    agora = timezone.now()
    arquivo_bytes = gerar_excel_comparativo(montar_comparativo(request.GET, empresa, todas_as_linhas=True), agora)
    resposta = HttpResponse(arquivo_bytes, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resposta['Content-Disposition'] = f'attachment; filename="{nome_do_arquivo(empresa, agora)}"'
    return resposta


# Função Objetivo: Botão "Coletar do Sysemp": só dispara a coleta em segundo plano e responde na hora. Se já há uma rodando, devolve o estado dela
# em vez de começar outra. Recusa (409) se a Sysemp ainda não liberou o método para a empresa ativa.
@require_POST
def view_full_comparativo_coletar_iniciar(request):
    from gestao_full.funcoes_auxiliares.comparativo_estoque_locais import api_sysemp_disponivel
    from gestao_full.funcoes_auxiliares.comparativo_estoque_sysemp import iniciar_coleta

    empresa = obter_empresa_ativa()
    if not api_sysemp_disponivel(empresa):
        return JsonResponse({'status': 'erro', 'mensagem': 'A Sysemp ainda não liberou este método para esta empresa.'}, status=409)
    estado, _ = iniciar_coleta(empresa)
    return JsonResponse(estado)


# Função Objetivo: Polling da barra de andamento (GET simples, só lê o cache). Terminou ou deu erro: entrega o resultado UMA vez.
@require_GET
def view_full_comparativo_coletar_status(request):
    from gestao_full.funcoes_auxiliares.comparativo_estoque_sysemp import ler_estado

    return JsonResponse(ler_estado(obter_empresa_ativa()))


# Função Objetivo: Botão "Parar": a coleta termina a página que está buscando e encerra (a coleta anterior continua valendo).
@require_POST
def view_full_comparativo_coletar_parar(request):
    from gestao_full.funcoes_auxiliares.comparativo_estoque_sysemp import pedir_parada

    estado = pedir_parada(obter_empresa_ativa())
    if estado is None:
        return JsonResponse({'status': 'ocioso', 'mensagem': 'Não há coleta em andamento.'})
    return JsonResponse(estado)
