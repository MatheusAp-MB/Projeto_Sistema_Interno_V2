# gestao_full/views_full_estoque.py
#
# View da tela "Full — Estoque no Full" (Mercado Livre → Gestão de estoque Full → Estoque no Full): para cada
# PRODUTO, quanto estoque ele tem hoje no Full, somando os Códigos ML dele. É a tela de CONSULTA ("quanto temos?");
# a tela de Planejamento de envios responde "quanto enviar?".
#
# REGRA DO MATHEUS: esta tela NUNCA chama a API do ML. Abrir, buscar, filtrar, ordenar e paginar só LEEM o banco
# (os Códigos ML de cada produto e a consulta mais recente de cada Código). Para atualizar um número, a pessoa usa o
# botão "Consultar no Mercado Livre" do Planejamento — esta tela só leva até lá.

from django.shortcuts import render
from django.urls import reverse


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
    })
