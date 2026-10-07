# gestao_full/views_full_planejamento.py
#
# View da tela FINAL "Full — Planejamento de envios" (Mercado Livre → Gestão de estoque Full →
# Planejamento de envios): a versão organizada, para apresentar. Parte do PRODUTO (SKU, EAN, Código ML
# ou MLB) e mostra, para cada Código ML do Full dele, o que fazer, o estoque, as vendas e os anúncios.
# A tela de debug (views_full.py) continua existindo: é nela que a equipe confere cada campo.
#
# REGRA DO MATHEUS: esta tela NUNCA chama a API do ML sozinha. Abrir a tela e buscar só LEEM o banco e
# o arquivo detalhes_mlbs.json. O único gatilho que consulta o ML é o botão "Consultar no Mercado Livre"
# de cada Código ML, que usa a MESMA view da ficha de debug (view_full_consultar) e guarda o resultado
# no banco; depois a tela recarrega lendo só do banco.

from django.shortcuts import render
from django.urls import reverse
from django.utils.http import urlencode

from core.empresa import obter_empresa_ativa


# Função Objetivo: A tela. LÊ SÓ DO BANCO E DO ARQUIVO. Sem busca, mostra o convite e os últimos Códigos ML
# consultados; com busca, o(s) produto(s) achado(s) e, dentro de cada um, os seus Códigos ML.
def view_full_planejamento(request):
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import formatar_data_hora
    from gestao_full.funcoes_auxiliares.full_ml import carregar_validacoes, listar_recentes
    from gestao_full.funcoes_auxiliares.full_planejamento_ml import montar_legenda, montar_planejamento
    from mercado_livre.models import CampoFullMercadoLivre

    texto = request.GET.get('q', '').strip()
    rotulos_situacao = dict(CampoFullMercadoLivre.Situacao.choices)
    pagina = montar_planejamento(obter_empresa_ativa(), texto, carregar_validacoes(), rotulos_situacao)

    recentes = []
    if pagina['estado'] == 'vazio':
        recentes = [{'codigo': c.codigo, 'quando': formatar_data_hora(c.consultado_em),
                     'url': reverse('gestao_full_planejamento') + '?' + urlencode({'q': c.codigo})}
                    for c in listar_recentes()]

    return render(request, 'gestao_full/estrutura_full_planejamento.html', {
        'texto': texto,
        'pagina': pagina,
        'recentes': recentes,
        'legenda': montar_legenda(rotulos_situacao),
        'url_debug': reverse('gestao_full_debug'),
        'url_planejamento': reverse('gestao_full_planejamento'),
    })
