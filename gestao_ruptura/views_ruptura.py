# gestao_ruptura/views_ruptura.py
#
# View da tela "Previsão de Ruptura de estoque" (Mercado Livre → Estoque → Previsão de Ruptura de estoque), PROVA DE CONCEITO de 12/10/2026: projeta quantos dias o estoque dura no ritmo
# de vendas escolhido, em que dia ele acaba, até quando preparar o envio e o nível do estoque.
#
# REGRA DO MATHEUS: esta tela NUNCA chama a API do ML (nem a do ERP) sozinha. Abrir, filtrar, ordenar e trocar de referência só LÊEM o banco (as vendas que a tela de Vendas já coletou e a última consulta salva de cada
# Código ML). A API do Mercado Livre só é chamada por CLIQUE, no botão "Consultar" da tabela "Estoque no Full por Código ML" do detalhe (view_ruptura_consultar). O estoque e o lead time digitados não são guardados
# e valem só para aquela consulta (ficam no endereço da página).

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from gestao_ruptura.funcoes_auxiliares.ruptura_pagina import montar_pagina


# Função Objetivo: A tela, em dois modos. SEM "sku" na URL: a LISTA por urgência, com o seletor "Ver por" (gran = produto | mlb | codigo), busca (q), filtro de nível
# (nivel), ordenação (ord), itens por página (por) e página (pag). COM "sku": o DETALHE com a curva (do próprio SKU, ou de um MLB / Código ML dele: gran = mlb | codigo + item;
# mais visao, dias, estoque). O lead time é um só (lead; vazio = padrão provisório de 7 dias). Todos os parâmetros são validados dentro de montar_pagina.
@require_GET
def view_ruptura(request):
    base = reverse('gestao_ruptura_principal')
    return render(request, 'gestao_ruptura/estrutura_ruptura.html', {'pagina': montar_pagina(request.GET, base), 'url_ruptura': base})


# Função Objetivo: O botão "Consultar no Mercado Livre" da tabela de estoque do detalhe (um Código ML por chamada; "Consultar todos" chama este endereço uma vez por Código, em fila, pelo JS). Consulta o Código no
# Mercado Livre e grava no banco (a MESMA consulta da tela "Estoque no Full" e do Planejamento: consultar_com_trava); a tela recarrega e volta a ler só do banco. Recusa se uma varredura completa está rodando e se o
# mesmo Código já está sendo consultado. Erros iguais aos da tela "Estoque no Full"; acesso recusado (502) e varredura rodando (409) vêm com "interromper": o JS para a fila.
@require_POST
def view_ruptura_consultar(request):
    import traceback

    from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
    from core.empresa import obter_empresa_ativa
    from gestao_full.funcoes_auxiliares.full_estoque_varredura import CodigoOcupado, consultar_com_trava, varredura_em_andamento
    from gestao_full.funcoes_auxiliares.full_ml import interpretar_codigo
    from gestao_full.views_full import _ler_json
    from gestao_full.views_full_estoque import MSG_VARREDURA_RODANDO
    from integracao_mercado_livre.servicos.consultar_full_ml import ErroConsultaFull
    from mercado_livre.views_caracteristicas import _nome_usuario, _plural

    codigo, _, _ = interpretar_codigo((_ler_json(request) or {}).get('codigo'))
    if codigo is None:
        return JsonResponse({'ok': False, 'mensagem': 'Código ML inválido. Recarregue a página e tente de novo.'}, status=400)

    empresa = obter_empresa_ativa()
    if varredura_em_andamento(empresa) is not None:
        return JsonResponse({'ok': False, 'mensagem': MSG_VARREDURA_RODANDO, 'interromper': True}, status=409)
    try:
        relatorio = consultar_com_trava(empresa, codigo, _nome_usuario(request))
    except CodigoOcupado:
        return JsonResponse({'ok': False, 'mensagem': f'O Código {codigo} já está sendo consultado (em outra aba ou em outra tela). Espere um instante.'}, status=409)
    except ErroConsultaFull as erro:
        return JsonResponse({'ok': False, 'mensagem': str(erro)}, status=422)
    except ErroAutenticacaoAPI:
        traceback.print_exc()
        return JsonResponse({'ok': False, 'interromper': True, 'mensagem': 'O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi gravado.'}, status=502)
    except Exception:
        traceback.print_exc()
        return JsonResponse({'ok': False, 'mensagem': 'Falha inesperada ao consultar o Mercado Livre. O detalhe está no terminal do servidor.'}, status=500)

    n_falhas = len(relatorio.falhas)
    mensagem = f'Código {codigo} atualizado: {relatorio.chamadas} {_plural(relatorio.chamadas, "chamada feita", "chamadas feitas")} ao Mercado Livre'
    if n_falhas:
        mensagem += f'; {n_falhas} {_plural(n_falhas, "falhou", "falharam")} (o Mercado Livre não devolveu tudo)'
    return JsonResponse({'ok': True, 'mensagem': mensagem + '.', 'falhas': n_falhas})
