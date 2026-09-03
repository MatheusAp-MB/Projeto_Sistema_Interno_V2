from django.shortcuts import render


def view_configuracoes_shopee(request):
    from decimal import Decimal, InvalidOperation
    from django.urls import reverse
    from django.shortcuts import redirect
    from shopee.models import ConfiguracaoShopee
    from precificacao.models import TabelaComissaoShopee

    def _dec(valor, atual):
        try:
            return Decimal(str(valor).replace(',', '.'))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return atual

    config = ConfiguracaoShopee.obter()

    if request.method == 'POST':
        config.frete_padrao = _dec(request.POST.get('frete_padrao'), config.frete_padrao)
        config.desconto_vitrine_percentual = _dec(
            request.POST.get('desconto_vitrine_percentual'), config.desconto_vitrine_percentual
        )
        config.save()
        return redirect(f"{reverse('shopee_configuracoes')}?salvo=1")

    return render(request, 'shopee/estrutura_configuracoes_shopee.html', {
        'config': config,
        'faixas_comissao': TabelaComissaoShopee.objects.all().order_by('preco_min'),
        'salvo': request.GET.get('salvo') == '1',
    })

def view_gerar_promocao(request):
    from produtos.models import Produto

    marcas_disponiveis = Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca')
    return render(request, 'shopee/estrutura_gerar_promocao.html', {'marcas_disponiveis': marcas_disponiveis})


# Função Objetivo: Processa o envio (chamado via HTMX) — erro devolve só o modal
# (não recarrega a página, então o arquivo escolhido nunca é perdido); sucesso manda
# o navegador de verdade pra tela de resultado, via header HX-Redirect.
def view_processar_promocao(request):
    import uuid
    from decimal import Decimal, InvalidOperation
    from django.core.cache import cache
    from django.http import HttpResponse
    from django.urls import reverse
    from shopee.funcoes_auxiliares.promocao.processador_promocao_shopee import ProcessadorPromocaoShopee
    from shopee.funcoes_auxiliares.promocao.gerador_excel_promocao import gerar_excel_promocao, gerar_excel_detalhes, gerar_excel_linhas_orfas

    marcas = request.POST.getlist('marca')
    margem = request.POST.get('margem', 'padrao')
    arquivo = request.FILES.get('arquivo_shopee')

    # * [EXPLICAÇÃO] → 'grade' = comportamento padrão (Grade do sistema, intocado).
    #                  'arquivo' = usa o preço já correto na plataforma como referência
    #                  + desconto manual — sem Grade, sem checagem de estoque, sem trava.
    #                  Mesmo padrão do TikTok (tiktok/views.py::view_processar_promocao).
    fonte_preco = request.POST.get('fonte_preco', 'grade')
    desconto_percentual = None

    erros = []
    if not marcas:
        erros.append('Selecione ao menos uma marca.')
    if not arquivo:
        erros.append('Envie o arquivo baixado da Shopee.')

    if fonte_preco == 'arquivo':
        valor_desconto_bruto = request.POST.get('desconto_percentual', '').strip().replace(',', '.')
        try:
            desconto_percentual = Decimal(valor_desconto_bruto)
            if not (Decimal('0') < desconto_percentual < Decimal('100')):
                erros.append('O desconto (%) precisa ser maior que 0 e menor que 100.')
        except InvalidOperation:
            erros.append('Informe um desconto (%) válido pra usar o preço do arquivo como referência.')

    cabecalho, linhas_arquivo = [], []
    if not erros:
        try:
            from core.funcoes_auxiliares.leitor_planilha_robusto import ler_linhas_planilha_robusta
            cabecalho, linhas_arquivo = ler_linhas_planilha_robusta(arquivo, linha_cabecalho=3, primeira_linha_dado=7)

            colunas_esperadas = {'ID do Produto', 'SKU', 'Preço', 'Estoque do Vendedor', 'Variante Identificador', 'SKU de referência'}
            faltando = colunas_esperadas - set(cabecalho)
            if faltando:
                erros.append(f'O arquivo não tem as colunas esperadas da Shopee: {", ".join(sorted(faltando))}.')
        except Exception as e:
            erros.append(f'Não foi possível abrir o arquivo — confirme que é um .xlsx válido, baixado direto da Shopee. Erro técnico: {type(e).__name__}: {e}')

    if erros:
        return render(request, 'shopee/parciais/estrutura_parcial_modal_erro_promocao.html', {'erros': erros})

    processador = ProcessadorPromocaoShopee(marcas, margem, cabecalho, linhas_arquivo)

    if fonte_preco == 'arquivo':
        processador.processar_modo_arquivo(desconto_percentual)
    else:
        processador.processar()

    token = str(uuid.uuid4())
    resumo = processador.resumo_geral()

    marcas_prontas = []
    marcas_com_divergencia = []

    from core.funcoes_auxiliares.chave_cache_segura import chave_cache_segura

    for marca in processador.marcas_com_resultado():
        resultados_marca = processador.resultados_por_marca(marca)
        n_prontos = sum(1 for r in resultados_marca if r.categoria == 'pronto')

        n_divergente = sum(1 for r in resultados_marca if r.categoria == 'divergente')
        n_novo = sum(1 for r in resultados_marca if r.categoria == 'novo')
        n_nao_encontrado = sum(1 for r in resultados_marca if r.categoria == 'nao_encontrado')
        n_estoque_inconsistente = sum(1 for r in resultados_marca if r.categoria == 'estoque_inconsistente')
        n_preco_invalido = sum(1 for r in resultados_marca if r.categoria == 'preco_invalido')
        n_excecoes = n_divergente + n_novo + n_nao_encontrado + n_estoque_inconsistente + n_preco_invalido

        marca_chave = chave_cache_segura(marca)

        if n_prontos > 0:
            cache.set(f'promocao_shopee_{token}_{marca_chave}_promocao', gerar_excel_promocao(resultados_marca), timeout=3600)
            marcas_prontas.append({'marca': marca, 'total': n_prontos})

        if n_excecoes > 0:
            cache.set(f'promocao_shopee_{token}_{marca_chave}_detalhes', gerar_excel_detalhes(resultados_marca), timeout=3600)
            marcas_com_divergencia.append({
                'marca': marca, 'total': n_excecoes,
                'divergente': n_divergente, 'novo': n_novo,
                'nao_encontrado': n_nao_encontrado, 'estoque_inconsistente': n_estoque_inconsistente,
                'preco_invalido': n_preco_invalido,
            })

    total_linhas_orfas = len(processador.linhas_orfas)
    if total_linhas_orfas > 0:
        cache.set(f'promocao_shopee_{token}_orfas', gerar_excel_linhas_orfas(processador.linhas_orfas), timeout=3600)

    cache.set(f'promocao_shopee_{token}_contexto', {
        'resumo': resumo, 'marcas_prontas': marcas_prontas, 'marcas_com_divergencia': marcas_com_divergencia,
        'total_linhas_orfas': total_linhas_orfas,
    }, timeout=3600)

    resposta = HttpResponse(status=200)
    resposta['HX-Redirect'] = reverse('shopee_resultado_promocao', args=[token])
    return resposta


def view_resultado_promocao(request, token):
    from django.core.cache import cache
    from django.shortcuts import redirect

    contexto = cache.get(f'promocao_shopee_{token}_contexto')
    if contexto is None:
        return redirect('shopee_gerar_promocao')

    return render(request, 'shopee/estrutura_resultado_promocao.html', {'token': token, **contexto})


def view_baixar_promocao(request, token, marca, tipo):
    from datetime import date
    from django.core.cache import cache
    from django.http import HttpResponse
    from core.funcoes_auxiliares.chave_cache_segura import chave_cache_segura

    arquivo_bytes = cache.get(f'promocao_shopee_{token}_{chave_cache_segura(marca)}_{tipo}')
    if arquivo_bytes is None:
        return HttpResponse('Arquivo expirado — gere a promoção de novo.', status=404)

    # * [EXPLICAÇÃO] → "/" na marca (ex: "DELLAMED/SUPERMEDY") quebra nome de
    #                  arquivo no Windows — troca só a barra, mantém acento/espaço
    #                  (o nome ainda precisa ser legível pro usuário).
    marca_para_nome_arquivo = marca.replace('/', '-')
    data_hoje = date.today().strftime('%d_%m_%y')
    nome_arquivo = (
        f'Promoção_{marca_para_nome_arquivo}_Shopee_{data_hoje}.xlsx' if tipo == 'promocao'
        else f'Detalhes_divergencias_{marca_para_nome_arquivo}_Shopee_{data_hoje}.xlsx'
    )

    response = HttpResponse(
        arquivo_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    return response


# Função Objetivo: Baixa a planilha de linhas órfãs (achado 3) — 1 arquivo só por
# envio inteiro, sem marca no caminho da URL (essas linhas não têm marca conhecida).
def view_baixar_linhas_orfas(request, token):
    from datetime import date
    from django.core.cache import cache
    from django.http import HttpResponse

    arquivo_bytes = cache.get(f'promocao_shopee_{token}_orfas')
    if arquivo_bytes is None:
        return HttpResponse('Arquivo expirado — gere a promoção de novo.', status=404)

    data_hoje = date.today().strftime('%d_%m_%y')
    response = HttpResponse(
        arquivo_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="Linhas_orfas_Shopee_{data_hoje}.xlsx"'
    return response

def view_baixar_todas_promocao(request, token, categoria):
    import zipfile
    import io
    from datetime import date
    from django.core.cache import cache
    from django.http import HttpResponse

    contexto = cache.get(f'promocao_shopee_{token}_contexto')
    if contexto is None:
        return HttpResponse('Resultado expirado — gere a promoção de novo.', status=404)

    if categoria == 'prontas':
        marcas = [item['marca'] for item in contexto['marcas_prontas']]
        tipo_arquivo = 'promocao'
    else:
        marcas = [item['marca'] for item in contexto['marcas_com_divergencia']]
        tipo_arquivo = 'detalhes'

    data_hoje = date.today().strftime('%d_%m_%y')
    buffer = io.BytesIO()

    from core.funcoes_auxiliares.chave_cache_segura import chave_cache_segura

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_arquivo:
        for marca in marcas:
            arquivo_bytes = cache.get(f'promocao_shopee_{token}_{chave_cache_segura(marca)}_{tipo_arquivo}')
            if arquivo_bytes is None:
                continue
            # * [EXPLICAÇÃO] → Mesmo motivo do view_baixar_promocao: "/" na marca
            #                  vira separador de pasta dentro do zip (cria uma
            #                  subpasta silenciosamente) — troca só a barra.
            marca_para_nome_arquivo = marca.replace('/', '-')
            nome_arquivo = (
                f'Promoção_{marca_para_nome_arquivo}_Shopee_{data_hoje}.xlsx' if tipo_arquivo == 'promocao'
                else f'Detalhes_divergencias_{marca_para_nome_arquivo}_Shopee_{data_hoje}.xlsx'
            )
            zip_arquivo.writestr(nome_arquivo, arquivo_bytes)

    buffer.seek(0)
    nome_categoria = 'Prontas' if categoria == 'prontas' else 'Divergencias'
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="Promocoes_Shopee_{nome_categoria}_{data_hoje}.zip"'
    return response