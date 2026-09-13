from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import render, get_object_or_404
from .models import Produto
from produtos.funcoes_auxiliares.contexto_tela_produtos import ContextoTelaProdutos
from impostos.funcoes_auxiliares.exibicao_impostos_entrada import montar_detalhes_para_exibicao
from impostos.funcoes_auxiliares.motivo_impostos_saida import ClassificadorMotivoFiscal


def view_produtos(request):
    contexto = ContextoTelaProdutos(request).montar()
    return render(request, 'produtos/estrutura_produtos.html', contexto)


def view_painel_produto(request, produto_id):
    produto = get_object_or_404(Produto, pk=produto_id)

    # * [EXPLICAÇÃO] → Nem todo produto já tem impostos de entrada
    #                  sincronizados (Sysemp) — trata a ausência como caso
    #                  normal, não como erro.
    try:
        impostos_entrada = montar_detalhes_para_exibicao(produto.impostos_entrada)
    except ObjectDoesNotExist:
        impostos_entrada = None

    # * [EXPLICAÇÃO] → Camada C da auditoria fiscal (13/09/2026, ver
    #                  Descoberta no vault): só classifica motivo pro campo
    #                  que ESTÁ em branco agora — um campo preenchido nunca
    #                  precisa de motivo nenhum. icms_saida_sp e
    #                  icms_saida_media são classificados separadamente
    #                  (podem ter motivos diferentes — ver
    #                  ClassificadorMotivoFiscal.classificar_icms_media);
    #                  pis_percentual/cofins_percentual sempre vêm juntos
    #                  (1 classificação só cobre os 2, igual ao restante
    #                  do sistema).
    dados_fiscais = produto.obter_dados_fiscais()
    classificador = ClassificadorMotivoFiscal()

    # Origem do Cadastro — reaproveita o mesmo impostos_entrada já
    # resolvido acima (com o mesmo try/except pra ausência), nunca uma 2ª
    # consulta pra buscar de novo.
    origem_produto = impostos_entrada.origem_mercadoria_cadastro if impostos_entrada is not None else None

    motivo_icms_saida_sp = (
        classificador.classificar_icms_sp(produto.ncm, dados_fiscais.cst_saida, origem_produto)
        if dados_fiscais.icms_saida_sp is None else None
    )
    motivo_icms_saida_media = (
        classificador.classificar_icms_media(produto.ncm, dados_fiscais.cst_saida, origem_produto)
        if dados_fiscais.icms_saida_media is None else None
    )
    motivo_pis_cofins = (
        classificador.classificar_pis_cofins(produto.ncm, dados_fiscais.cst_saida)
        if dados_fiscais.pis_percentual is None else None
    )

    return render(request, 'produtos/parciais/estrutura_parcial_painel_produto.html', {
        'produto': produto,
        'impostos_entrada': impostos_entrada,
        'motivo_icms_saida_sp': motivo_icms_saida_sp,
        'motivo_icms_saida_media': motivo_icms_saida_media,
        'motivo_pis_cofins': motivo_pis_cofins,
    })