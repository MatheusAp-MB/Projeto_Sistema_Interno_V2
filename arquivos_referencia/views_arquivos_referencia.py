# arquivos_referencia/views_arquivos_referencia.py

# Função Objetivo: Views da tela "Arquivos de referência" — onde se confere e se ENVIA ao Drive os arquivos que o
# "popular banco" lê: 4 tabelas de frete e 2 planilhas do Busca Legal.
#
# * [DECISÃO, 14/10/2026] → O fluxo final tem 2 passos SEPARADOS: (1) conferir e enviar ao Drive (esta tela); (2) atualizar o
#   sistema com o que está no Drive (outro clique, próximo ciclo). Por isso nenhuma view aqui toca no banco do sistema.
# * [DECISÃO, 15/10/2026] → 1º e 2º ciclos = só a tela + a AUDITORIA (nada gravado em lugar nenhum). 3º ciclo = o ENVIO ao
#   Drive: o arquivo continua sem ser gravado em disco ou no banco — vai da memória do servidor direto para o Drive.
# * [DECISÃO, 15/10/2026] → Mesma proteção da Gestão de APIs: a tela não usa decorador de login (o middleware global de
#   autenticação já protege as rotas); conferir/enviar são POST com CSRF (o token vai no cabeçalho, posto pelo base global).
# * [IMPORTANTE] → O envio NUNCA confia na conferência que a tela mostrou: o navegador manda o arquivo de novo e o servidor
#   audita DE NOVO antes de mexer no Drive (o banco pode ter mudado desde a conferência, e a tela poderia estar velha).
#   Arquivo que agora tem erro não é enviado: volta o cartão com o relatório novo e um aviso.
# * [EXPLICAÇÃO] → Dois jeitos de responder, de propósito:
#   - problema NO ARQUIVO (não é planilha, coluna fora do lugar...): resposta normal (200) com o cartão novo mostrando
#     o relatório — a pessoa lê o que corrigir na própria tela;
#   - problema DO SISTEMA ou do DRIVE (arquivo desconhecido, login do Drive vencido, bug): resposta com erro + JSON
#     {"mensagem": ..., "link": {"texto", "url"} (opcional)}, que o JS mostra num aviso na tela. O detalhe técnico vai para
#     o terminal do servidor, nunca para o navegador.

import json
import traceback

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .funcoes_auxiliares.auditor_de_arquivos import auditar_arquivo
from .funcoes_auxiliares.catalogo_arquivos import buscar_arquivo
from .funcoes_auxiliares.envio_ao_drive import ErroDoEnvio, consultar_no_drive, enviar_para_o_drive
from .funcoes_auxiliares.leitura_planilha import TAMANHO_MAXIMO_DO_ARQUIVO
from .funcoes_auxiliares.montagem_da_tela import montar_cartao, montar_grupos, montar_linha_do_drive

TAMANHO_MAXIMO_DO_NOME_EXIBIDO = 150


def _erro_do_sistema(mensagem, status, link=None):
    corpo = {'mensagem': mensagem}
    if link:
        corpo['link'] = link
    return JsonResponse(corpo, status=status)


# Função Objetivo: Atalho para a Gestão de APIs (onde fica o botão "Renovar autorização" do Drive). Sem a rota, sem atalho.
def _link_da_gestao_de_apis():
    try:
        return {'texto': 'Abrir Gestão de APIs', 'url': reverse('gestao_apis_painel')}
    except NoReverseMatch:
        return None


def _erro_do_drive(erro):
    return _erro_do_sistema(erro.mensagem, erro.status, _link_da_gestao_de_apis() if erro.renovar_autorizacao else None)


# Função Objetivo: Aviso na tela vindo do servidor: o cabeçalho HX-Trigger do HTMX vira o evento "arqAviso" no navegador.
# (json.dumps escapa os acentos: cabeçalho HTTP só leva ASCII com segurança.)
def _com_aviso(resposta, mensagem, tipo):
    resposta['HX-Trigger'] = json.dumps({'arqAviso': {'mensagem': mensagem, 'tipo': tipo}})
    return resposta


@require_GET
def view_arquivos_referencia(request):
    # * [EXPLICAÇÃO] → Abrir a página não lê nenhum arquivo: todos os cartões começam em "Consultando o Drive". (Em seguida cada
    #   cartão pergunta ao Drive, só leitura, e vira "No Drive" ou "Sem arquivo no Drive" — ver view_situacao_no_drive.)
    return render(request, 'arquivos_referencia/estrutura_arquivos_referencia.html', {
        'grupos': montar_grupos(),
        'limite_do_arquivo_em_bytes': TAMANHO_MAXIMO_DO_ARQUIVO,
        'limite_do_arquivo_em_mb': TAMANHO_MAXIMO_DO_ARQUIVO // (1024 * 1024),
    })


# Função Objetivo: Lê o arquivo enviado pelo formulário e audita. Devolve (conteudo, relatorio, enviado) ou uma resposta de erro.
def _receber_e_auditar(request, arquivo):
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
    return conteudo, relatorio, enviado


def _arquivo_do_catalogo(arquivo_id):
    # * [IMPORTANTE] → O arquivo é escolhido pelo ID da lista fechada do catálogo; nada vindo do navegador (nome do
    #   arquivo, por exemplo) entra em caminho de disco nem em nome no Drive. O nome enviado só é mostrado na tela (já escapado).
    arquivo = buscar_arquivo(arquivo_id)
    if arquivo is None:
        return None, _erro_do_sistema('Arquivo de referência desconhecido. Recarregue a página.', 404)
    if not arquivo.auditoria_pronta:
        return None, _erro_do_sistema('Este arquivo ainda não tem auditoria (ela chega na próxima etapa).', 409)
    return arquivo, None


@require_POST
def view_auditar_arquivo(request, arquivo_id):
    arquivo, erro = _arquivo_do_catalogo(arquivo_id)
    if erro:
        return erro
    recebido = _receber_e_auditar(request, arquivo)
    if isinstance(recebido, JsonResponse):
        return recebido
    _, relatorio, _ = recebido

    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_cartao.html', {
        'cartao': montar_cartao(arquivo, relatorio, timezone.now()),
    })
    resposta['Cache-Control'] = 'no-store'
    return resposta


@require_POST
def view_enviar_arquivo(request, arquivo_id):
    arquivo, erro = _arquivo_do_catalogo(arquivo_id)
    if erro:
        return erro
    recebido = _receber_e_auditar(request, arquivo)
    if isinstance(recebido, JsonResponse):
        return recebido
    conteudo, relatorio, enviado = recebido
    agora = timezone.now()

    # Trava de segurança: só envia o que foi lido por inteiro e passou na conferência feita AGORA, no servidor.
    if not relatorio.pode_enviar or len(conteudo) != enviado.size:
        resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_cartao.html', {
            'cartao': montar_cartao(arquivo, relatorio, agora),
        })
        resposta['Cache-Control'] = 'no-store'
        return _com_aviso(
            resposta, 'Este arquivo não passou na conferência feita agora, então NÃO foi enviado ao Drive. Veja a auditoria.', 'info',
        )

    try:
        envio = enviar_para_o_drive(arquivo, conteudo)
    except ErroDoEnvio as problema:
        return _erro_do_drive(problema)
    except Exception:
        traceback.print_exc()
        return _erro_do_sistema(
            'O envio quebrou por um erro do próprio sistema (não é problema do arquivo). O Drive pode não ter sido alterado — '
            'veja o terminal do servidor.',
            500,
        )

    mensagem = f'Enviado ao Drive: {envio["nome"]}. ' + (
        'O arquivo que estava lá foi trocado.' if envio['substituiu'] else 'Era um arquivo novo na pasta.'
    )
    tipo = 'ok'
    if envio['copias_removidas'] == 1:
        mensagem += ' 1 cópia repetida foi para a lixeira do Drive.'
    elif envio['copias_removidas'] > 1:
        mensagem += f' {envio["copias_removidas"]} cópias repetidas foram para a lixeira do Drive.'
    if envio['copias_que_ficaram']:
        tipo = 'info'
        mensagem += (
            f' Atenção: {envio["copias_que_ficaram"]} cópia(s) repetida(s) continua(m) na pasta (o Drive não deixou removê-las) — '
            'apague à mão.'
        )

    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_cartao.html', {
        'cartao': montar_cartao(arquivo, relatorio, agora, envio=envio),
    })
    resposta['Cache-Control'] = 'no-store'
    return _com_aviso(resposta, mensagem, tipo)


@require_GET
def view_situacao_no_drive(request, arquivo_id):
    # * [EXPLICAÇÃO] → Só leitura (não cria pasta nem arquivo). Responde SEMPRE 200 com a linha pronta: se o Drive não
    #   puder ser consultado (login vencido, sem internet...), o motivo aparece na própria linha do cartão — um problema do
    #   Drive nunca derruba nem esconde o resto da tela.
    # * [EXPLICAÇÃO] → Com `?cartao_vazio=1` (o cartão ainda não tem arquivo conferido) a resposta leva, além da linha, o selo e a
    #   área de soltar do cartão já no estado certo ("No Drive", "Sem arquivo no Drive" ou "Drive sem resposta"): o HTMX troca
    #   os 3 de uma vez (hx-swap-oob). Só esses dois pedaços mudam — o formulário e o seletor de arquivo do cartão ficam
    #   intactos, então a pessoa pode estar escolhendo um arquivo enquanto o Drive responde.
    arquivo = buscar_arquivo(arquivo_id)
    if arquivo is None:
        return _erro_do_sistema('Arquivo de referência desconhecido. Recarregue a página.', 404)

    situacao = erro = erro_completo = link = None
    try:
        situacao = consultar_no_drive(arquivo)
    except ErroDoEnvio as problema:
        erro, erro_completo = problema.resumo, problema.mensagem
        link = _link_da_gestao_de_apis() if problema.renovar_autorizacao else None
    except Exception:
        traceback.print_exc()
        erro = 'Erro do próprio sistema ao consultar o Drive. Veja o terminal do servidor.'

    atualizar_cartao = request.GET.get('cartao_vazio') == '1' and arquivo.auditoria_pronta
    linha = montar_linha_do_drive(
        arquivo.id, situacao, erro, link, erro_completo=erro_completo, sem_arquivo_local=atualizar_cartao,
    )
    contexto = {'linha': linha}
    if atualizar_cartao:
        contexto.update(oob_cartao=True, cartao=montar_cartao(arquivo, linha_drive=linha))

    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_drive.html', contexto)
    resposta['Cache-Control'] = 'no-store'
    return resposta
