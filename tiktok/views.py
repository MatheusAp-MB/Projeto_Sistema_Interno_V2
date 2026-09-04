from django.shortcuts import render


def view_configuracoes_tiktok(request):
    from decimal import Decimal, InvalidOperation
    from django.urls import reverse
    from django.shortcuts import redirect
    from tiktok.models import ConfiguracaoTiktok
    from precificacao.models import TabelaComissaoTiktok

    def _dec(valor, atual):
        try:
            return Decimal(str(valor).replace(',', '.'))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return atual

    config = ConfiguracaoTiktok.obter()

    if request.method == 'POST':
        config.margem_afiliado_percentual = _dec(
            request.POST.get('margem_afiliado_percentual'), config.margem_afiliado_percentual
        )
        config.desconto_vitrine_percentual = _dec(
            request.POST.get('desconto_vitrine_percentual'), config.desconto_vitrine_percentual
        )
        config.save()
        return redirect(f"{reverse('tiktok_configuracoes')}?salvo=1")

    return render(request, 'tiktok/estrutura_configuracoes_tiktok.html', {
        'config': config,
        'faixas_comissao': TabelaComissaoTiktok.objects.all().order_by('preco_min'),
        'salvo': request.GET.get('salvo') == '1',
    })


def view_tabela_frete_tiktok(request):
    from tiktok.models import FreteTiktok

    faixas = FreteTiktok.objects.all().order_by('peso_min')
    return render(request, 'tiktok/estrutura_tabela_frete_tiktok.html', {'faixas': faixas})


def view_calcular_frete_tiktok(request):
    from decimal import Decimal, InvalidOperation
    from django.db.models import Q
    from tiktok.models import FreteTiktok

    try:
        peso = Decimal(request.POST.get('peso', '0'))

        faixa = FreteTiktok.objects.filter(
            peso_min__lte=peso,
        ).filter(
            Q(peso_max__gte=peso) | Q(peso_max__isnull=True)
        ).order_by('peso_min').last()

        if faixa:
            return render(request, 'tiktok/parciais/estrutura_parcial_resultado_frete_tiktok.html', {
                'valor': faixa.valor, 'peso_min': faixa.peso_min,
            })

        return render(request, 'tiktok/parciais/estrutura_parcial_resultado_frete_tiktok.html', {
            'valor': None,
        })

    except (InvalidOperation, ValueError) as e:
        return render(request, 'tiktok/parciais/estrutura_parcial_resultado_frete_tiktok.html', {
            'valor': None, 'erro': str(e),
        })
    

def view_gerar_promocao(request):
    from produtos.models import Produto

    marcas_disponiveis = Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca')
    return render(request, 'tiktok/estrutura_gerar_promocao.html', {'marcas_disponiveis': marcas_disponiveis})


def view_processar_promocao(request):
    import uuid
    from django.core.cache import cache
    from django.http import HttpResponse
    from django.urls import reverse
    from tiktok.funcoes_auxiliares.promocao.processador_promocao_tiktok import ProcessadorPromocaoTiktok
    from tiktok.funcoes_auxiliares.promocao.gerador_excel_promocao_tiktok import gerar_excel_promocao, gerar_excel_detalhes

    from decimal import Decimal, InvalidOperation

    marcas = request.POST.getlist('marca')
    margem_sem_afiliado = request.POST.get('margem_sem_afiliado', 'padrao')
    margem_com_afiliado = request.POST.get('margem_com_afiliado', 'padrao')
    arquivo = request.FILES.get('arquivo_tiktok')

    # * [EXPLICAÇÃO] → 'grade' = comportamento padrão (Grade do sistema, intocado).
    #                  'arquivo' = usa o preço já correto na plataforma como referência
    #                  + desconto manual — sem Grade, sem checagem de estoque, sem trava.
    fonte_preco = request.POST.get('fonte_preco', 'grade')
    desconto_percentual = None

    erros = []
    if not marcas:
        erros.append('Selecione ao menos uma marca.')
    if not arquivo:
        erros.append('Envie o arquivo baixado do TikTok Shop.')

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
            cabecalho, linhas_arquivo = ler_linhas_planilha_robusta(arquivo, linha_cabecalho=3, primeira_linha_dado=6)

            colunas_esperadas = {
                'ID do produto', 'ID do SKU', 'Preço de varejo (moeda local)',
                'Quantidade', 'SKU do vendedor',
            }
            faltando = colunas_esperadas - set(cabecalho)
            if faltando:
                erros.append(f'O arquivo não tem as colunas esperadas do TikTok Shop: {", ".join(sorted(faltando))}.')
        except Exception as e:
            erros.append(f'Não foi possível abrir o arquivo — confirme que é um .xlsx válido, baixado direto do TikTok Shop. Erro técnico: {type(e).__name__}: {e}')

    if erros:
        return render(request, 'tiktok/parciais/estrutura_parcial_modal_erro_promocao.html', {'erros': erros})

    processador = ProcessadorPromocaoTiktok(marcas, margem_sem_afiliado, margem_com_afiliado, cabecalho, linhas_arquivo)

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
            cache.set(f'promocao_tiktok_{token}_{marca_chave}_promocao', gerar_excel_promocao(resultados_marca), timeout=3600)
            marcas_prontas.append({'marca': marca, 'total': n_prontos})

        if n_excecoes > 0:
            cache.set(f'promocao_tiktok_{token}_{marca_chave}_detalhes', gerar_excel_detalhes(resultados_marca), timeout=3600)
            marcas_com_divergencia.append({
                'marca': marca, 'total': n_excecoes,
                'divergente': n_divergente, 'novo': n_novo,
                'nao_encontrado': n_nao_encontrado, 'estoque_inconsistente': n_estoque_inconsistente,
                'preco_invalido': n_preco_invalido,
            })

    cache.set(f'promocao_tiktok_{token}_contexto', {
        'resumo': resumo, 'marcas_prontas': marcas_prontas, 'marcas_com_divergencia': marcas_com_divergencia,
    }, timeout=3600)

    resposta = HttpResponse(status=200)
    resposta['HX-Redirect'] = reverse('tiktok_resultado_promocao', args=[token])
    return resposta


def view_resultado_promocao(request, token):
    from django.core.cache import cache
    from django.shortcuts import redirect

    contexto = cache.get(f'promocao_tiktok_{token}_contexto')
    if contexto is None:
        return redirect('tiktok_gerar_promocao')

    return render(request, 'tiktok/estrutura_resultado_promocao.html', {'token': token, **contexto})


def view_baixar_promocao(request, token, marca, tipo):
    from datetime import date
    from django.core.cache import cache
    from django.http import HttpResponse
    from core.funcoes_auxiliares.chave_cache_segura import chave_cache_segura

    arquivo_bytes = cache.get(f'promocao_tiktok_{token}_{chave_cache_segura(marca)}_{tipo}')
    if arquivo_bytes is None:
        return HttpResponse('Arquivo expirado — gere a promoção de novo.', status=404)

    # * [EXPLICAÇÃO] → "/" na marca quebra nome de arquivo no Windows — troca só
    #                  a barra, mantém acento/espaço.
    marca_para_nome_arquivo = marca.replace('/', '-')
    data_hoje = date.today().strftime('%d_%m_%y')
    nome_arquivo = (
        f'Promoção_{marca_para_nome_arquivo}_TikTok_{data_hoje}.xlsx' if tipo == 'promocao'
        else f'Detalhes_divergencias_{marca_para_nome_arquivo}_TikTok_{data_hoje}.xlsx'
    )

    response = HttpResponse(
        arquivo_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    return response


def view_baixar_todas_promocao(request, token, categoria):
    import zipfile
    import io
    from datetime import date
    from django.core.cache import cache
    from django.http import HttpResponse

    contexto = cache.get(f'promocao_tiktok_{token}_contexto')
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
            arquivo_bytes = cache.get(f'promocao_tiktok_{token}_{chave_cache_segura(marca)}_{tipo_arquivo}')
            if arquivo_bytes is None:
                continue
            # * [EXPLICAÇÃO] → Mesmo motivo do view_baixar_promocao: "/" na marca
            #                  vira separador de pasta dentro do zip — troca só a barra.
            marca_para_nome_arquivo = marca.replace('/', '-')
            nome_arquivo = (
                f'Promoção_{marca_para_nome_arquivo}_TikTok_{data_hoje}.xlsx' if tipo_arquivo == 'promocao'
                else f'Detalhes_divergencias_{marca_para_nome_arquivo}_TikTok_{data_hoje}.xlsx'
            )
            zip_arquivo.writestr(nome_arquivo, arquivo_bytes)

    buffer.seek(0)
    nome_categoria = 'Prontas' if categoria == 'prontas' else 'Divergencias'
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="Promocoes_TikTok_{nome_categoria}_{data_hoje}.zip"'
    return response

