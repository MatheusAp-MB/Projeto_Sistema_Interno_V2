# arquivos_referencia/views_arquivos_referencia.py

# Função Objetivo: Views da tela "Arquivos de referência" — onde se confere (e, nas próximas etapas, se envia ao
# Drive) os arquivos que o "popular banco" lê: 4 tabelas de frete e 2 planilhas do Busca Legal.
#
# * [DECISÃO, 15/10/2026] → 1º ciclo = só a tela + a AUDITORIA das tabelas de frete. Nada vai ao Drive, nada é
#   gravado em disco ou no banco e nada muda no sistema: o arquivo escolhido existe só na memória durante a
#   conferência. Por isso não há model, migração nem rota de envio ainda.
# * [DECISÃO, 15/10/2026] → Mesma proteção da Gestão de APIs: a tela não usa decorador de login (o middleware global de
#   autenticação já protege as rotas); o envio é POST com CSRF (o token vai no cabeçalho, posto pelo base global).
# * [EXPLICAÇÃO] → Dois jeitos de responder, de propósito:
#   - problema NO ARQUIVO (não é planilha, coluna fora do lugar...): resposta normal (200) com o cartão novo mostrando
#     o relatório — a pessoa lê o que corrigir na própria tela;
#   - problema DO SISTEMA (arquivo desconhecido, bug): resposta com erro + JSON {"mensagem": ...}, que o JS mostra num
#     aviso na tela. O detalhe técnico vai para o terminal do servidor, nunca para o navegador.

import traceback

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .funcoes_auxiliares.auditor_de_arquivos import auditar_arquivo
from .funcoes_auxiliares.catalogo_arquivos import buscar_arquivo
from .funcoes_auxiliares.leitura_planilha import TAMANHO_MAXIMO_DO_ARQUIVO
from .funcoes_auxiliares.montagem_da_tela import montar_cartao, montar_grupos

TAMANHO_MAXIMO_DO_NOME_EXIBIDO = 150


def _erro_do_sistema(mensagem, status):
    return JsonResponse({'mensagem': mensagem}, status=status)


@require_GET
def view_arquivos_referencia(request):
    # * [EXPLICAÇÃO] → Abrir a página não lê nenhum arquivo: todos os cartões começam em "Sem arquivo".
    return render(request, 'arquivos_referencia/estrutura_arquivos_referencia.html', {
        'grupos': montar_grupos(),
        'limite_do_arquivo_em_bytes': TAMANHO_MAXIMO_DO_ARQUIVO,
        'limite_do_arquivo_em_mb': TAMANHO_MAXIMO_DO_ARQUIVO // (1024 * 1024),
    })


@require_POST
def view_auditar_arquivo(request, arquivo_id):
    # * [IMPORTANTE] → O arquivo é escolhido pelo ID da lista fechada do catálogo; nada vindo do navegador (nome do
    #   arquivo, por exemplo) entra em caminho de disco. O nome enviado só é mostrado na tela (já escapado).
    arquivo = buscar_arquivo(arquivo_id)
    if arquivo is None:
        return _erro_do_sistema('Arquivo de referência desconhecido. Recarregue a página.', 404)
    if not arquivo.auditoria_pronta:
        return _erro_do_sistema('Este arquivo ainda não tem auditoria (ela chega na próxima etapa).', 409)

    enviado = request.FILES.get('arquivo')
    if enviado is None:
        return _erro_do_sistema('Nenhum arquivo chegou ao servidor. Escolha o arquivo de novo.', 400)

    try:
        # Lê 1 byte a mais que o limite: se vier, o arquivo é grande demais e a auditoria explica na tela.
        conteudo = enviado.read(TAMANHO_MAXIMO_DO_ARQUIVO + 1)
        relatorio = auditar_arquivo(
            arquivo, conteudo, (enviado.name or 'arquivo')[:TAMANHO_MAXIMO_DO_NOME_EXIBIDO], tamanho_em_bytes=enviado.size,
        )
    except Exception:
        traceback.print_exc()
        return _erro_do_sistema(
            'A conferência quebrou por um erro do próprio sistema (não é problema do arquivo). Veja o terminal do servidor.',
            500,
        )

    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_cartao.html', {
        'cartao': montar_cartao(arquivo, relatorio, timezone.now()),
    })
    resposta['Cache-Control'] = 'no-store'
    return resposta
