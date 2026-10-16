# arquivos_referencia/views_arquivos_referencia.py

# Função Objetivo: Views da tela "Arquivos de referência" — onde se confere e se ENVIA ao Drive os arquivos que o
# "popular banco" lê: 4 tabelas de frete e 2 planilhas do Busca Legal.
#
# * [DECISÃO, 14/10/2026] → O fluxo final tem 2 passos SEPARADOS: (1) conferir e enviar ao Drive; (2) atualizar o sistema com o
#   que está no Drive (outro clique). Só a view de atualizar (view_atualizar_arquivo) toca no banco do sistema; conferir e enviar
#   nunca tocam.
# * [DECISÃO, 15/10/2026] → Passo 2, 1º ciclo (só as 4 tabelas de frete): o botão "Atualizar o sistema com o Drive" faz 1 pedido
#   POR ARQUIVO, um depois do outro (o JS). Assim a janela mostra o andamento de cada tabela, um arquivo com problema não derruba os
#   outros, e nenhum pedido fica longo demais. Toda falha PREVISTA volta como resultado do arquivo (resposta 200, linha pronta);
#   só pedido inválido (arquivo desconhecido, arquivo que o botão não atualiza) volta com erro + JSON.
# * [DECISÃO, 15/10/2026] → A atualização ESPELHA o arquivo: o que o sistema tem e o arquivo não tem é apagado ("100% síncrono"), e cada
#   atualização grava, por empresa, quando foi feita e com qual arquivo (model AtualizacaoDoSistema). Quem lê esse histórico é a consulta
#   ao Drive (view_situacao_no_drive → montar_linha_do_drive): o cartão mostra "Data do envio do arquivo" e "Data da última atualização
#   do sistema com este arquivo", com o selo "Em dia" quando o sistema leu exatamente o arquivo que o Drive tem agora.
# * [DECISÃO, 16/10/2026] → INDEPENDÊNCIA entre as empresas (igual à Gestão de APIs): a tela trabalha SEMPRE com a empresa selecionada
#   (a mesma que o resto do sistema usa: obter_empresa_ativa). Mostra só os cartões e as datas dessa empresa, e "Atualizar o sistema com o
#   Drive" grava SÓ nela. Como a empresa pode ser trocada em outra aba enquanto esta tela fica aberta, cada pedido que mexe no banco leva a
#   empresa que a tela mostrava e o servidor RECUSA (409, nada gravado) se ela não for mais a selecionada. Arquivo que é só da outra
#   empresa (a planilha Busca Legal dela) responde como se não existisse.
# * [DECISÃO, 16/10/2026] → "Ver arquivo" (visualizador): mostra o .xlsx como o Excel mostraria, numa janela (só leitura, nada é gravado).
#   Dois jeitos: o arquivo que ESTÁ no Drive (GET, lido do Drive na hora) e o arquivo que a pessoa acabou de ESCOLHER (POST; o navegador
#   manda o arquivo de novo, o servidor só abre na memória). Aqui o problema previsto (Drive fora do ar, arquivo ilegível, empresa trocada
#   em outra aba) volta SEMPRE como resposta 200 com a explicação dentro da própria janela — assim ela nunca fica "carregando" para sempre.
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

from core.empresa import EMPRESAS_VALIDAS, obter_empresa_ativa

from .funcoes_auxiliares.atualizacao_do_sistema import (
    arquivos_que_o_botao_atualiza, atualizar_arquivo, o_botao_atualiza, resultado_de_falha_do_sistema,
)
from .funcoes_auxiliares.auditor_de_arquivos import auditar_arquivo
from .funcoes_auxiliares.catalogo_arquivos import arquivo_e_da_empresa, buscar_arquivo
from .funcoes_auxiliares.envio_ao_drive import ArquivoAusenteNoDrive, ErroDoEnvio, consultar_no_drive, enviar_para_o_drive, ler_do_drive
from .funcoes_auxiliares.leitura_planilha import TAMANHO_MAXIMO_DO_ARQUIVO, ErroDeLeitura
from .funcoes_auxiliares.visualizacao_do_arquivo import ORIGEM_DRIVE, ORIGEM_ESCOLHIDO, montar_visualizacao
from .funcoes_auxiliares.montagem_da_tela import (
    montar_cartao, montar_grupos, montar_item_da_atualizacao, montar_linha_do_drive, nome_curto_da_empresa,
)

TAMANHO_MAXIMO_DO_NOME_EXIBIDO = 150

TEXTO_EMPRESA_MUDOU = (
    'A empresa selecionada mudou (em outra aba ou janela). Recarregue a página para trabalhar com a empresa certa.'
)


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


# Função Objetivo: A empresa selecionada AGORA (a do EmpresaMiddleware, pela sessão). Devolve (empresa, None) ou (None, resposta de erro).
def _empresa_da_requisicao():
    empresa = obter_empresa_ativa()
    if empresa in EMPRESAS_VALIDAS:
        return empresa, None
    return None, _erro_do_sistema('Nenhuma empresa está selecionada. Escolha a empresa no topo da tela e recarregue a página.', 409)


# Função Objetivo: A tela que fez o pedido estava mostrando a MESMA empresa que está selecionada agora? (`informada` = o que a tela mandou.)
def _tela_na_empresa_certa(informada, empresa):
    return informada == empresa


@require_GET
def view_arquivos_referencia(request):
    # * [EXPLICAÇÃO] → Abrir a página não lê nenhum arquivo: todos os cartões começam em "Consultando o Drive". (Em seguida cada
    #   cartão pergunta ao Drive, só leitura, e vira "No Drive" ou "Sem arquivo no Drive" — ver view_situacao_no_drive.)
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    return render(request, 'arquivos_referencia/estrutura_arquivos_referencia.html', {
        'empresa_da_tela': empresa,
        'empresa_da_tela_nome': nome_curto_da_empresa(empresa),
        'grupos': montar_grupos(empresa),
        'arquivos_para_atualizar': arquivos_que_o_botao_atualiza(empresa),
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


# Função Objetivo: O arquivo do catálogo que esta empresa pode usar. Desconhecido, ou da OUTRA empresa: 404 (como se não existisse).
def _arquivo_visivel(arquivo_id, empresa):
    arquivo = buscar_arquivo(arquivo_id)
    if arquivo is None or not arquivo_e_da_empresa(arquivo, empresa):
        return None, _erro_do_sistema('Arquivo de referência desconhecido para a empresa selecionada. Recarregue a página.', 404)
    return arquivo, None


def _arquivo_do_catalogo(arquivo_id, empresa):
    # * [IMPORTANTE] → O arquivo é escolhido pelo ID da lista fechada do catálogo; nada vindo do navegador (nome do
    #   arquivo, por exemplo) entra em caminho de disco nem em nome no Drive. O nome enviado só é mostrado na tela (já escapado).
    arquivo, erro = _arquivo_visivel(arquivo_id, empresa)
    if erro:
        return None, erro
    if not arquivo.auditoria_pronta:
        return None, _erro_do_sistema('Este arquivo ainda não tem auditoria (ela chega na próxima etapa).', 409)
    return arquivo, None


@require_POST
def view_auditar_arquivo(request, arquivo_id):
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    arquivo, erro = _arquivo_do_catalogo(arquivo_id, empresa)
    if erro:
        return erro
    recebido = _receber_e_auditar(request, arquivo)
    if isinstance(recebido, JsonResponse):
        return recebido
    _, relatorio, _ = recebido

    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_cartao.html', {
        'cartao': montar_cartao(arquivo, empresa, relatorio, timezone.now()),
    })
    resposta['Cache-Control'] = 'no-store'
    return resposta


@require_POST
def view_enviar_arquivo(request, arquivo_id):
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    arquivo, erro = _arquivo_do_catalogo(arquivo_id, empresa)
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
            'cartao': montar_cartao(arquivo, empresa, relatorio, agora),
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
        'cartao': montar_cartao(arquivo, empresa, relatorio, agora, envio=envio),
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
    # * [EXPLICAÇÃO] → A tela manda `?empresa=` (a empresa que ela mostra). Se a selecionada mudou em outra aba, a linha vira um aviso
    #   "recarregue a página" (e sem dados de empresa nenhuma) em vez de mostrar a data de uma empresa numa tela de outra.
    empresa, erro_da_empresa = _empresa_da_requisicao()
    if erro_da_empresa:
        return erro_da_empresa
    arquivo, erro_do_arquivo = _arquivo_visivel(arquivo_id, empresa)
    if erro_do_arquivo:
        return erro_do_arquivo

    if not _tela_na_empresa_certa(request.GET.get('empresa', empresa), empresa):
        linha = montar_linha_do_drive(arquivo.id, empresa, erro=TEXTO_EMPRESA_MUDOU)
        linha['sistema'] = None
        resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_drive.html', {'linha': linha})
        resposta['Cache-Control'] = 'no-store'
        return resposta

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
        arquivo.id, empresa, situacao, erro, link, erro_completo=erro_completo, sem_arquivo_local=atualizar_cartao,
    )
    contexto = {'linha': linha}
    if atualizar_cartao:
        contexto.update(oob_cartao=True, cartao=montar_cartao(arquivo, empresa, linha_drive=linha))

    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_drive.html', contexto)
    resposta['Cache-Control'] = 'no-store'
    return resposta


@require_POST
def view_atualizar_arquivo(request, arquivo_id):
    # * [EXPLICAÇÃO] → Passo 2: lê ESTE arquivo do Drive (só na memória), confere, e grava nas tabelas da empresa SELECIONADA (tudo ou nada).
    #   O arquivo é escolhido pelo ID da lista fechada do catálogo (nada vindo do navegador entra em caminho ou em consulta).
    #   O que sobe do navegador é só o pedido: o conteúdo vem do Drive, nunca do computador de quem clicou.
    # * [IMPORTANTE] → O pedido OBRIGATORIAMENTE diz em qual empresa a tela estava (`empresa`). Se faltar, ou se a empresa selecionada agora
    #   for outra (trocada em outra aba), o servidor recusa com 409 e NÃO grava nada: ninguém atualiza a empresa errada por uma tela velha.
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    if not _tela_na_empresa_certa(request.POST.get('empresa'), empresa):
        return _erro_do_sistema(f'{TEXTO_EMPRESA_MUDOU} Nada foi gravado.', 409)
    arquivo, erro = _arquivo_visivel(arquivo_id, empresa)
    if erro:
        return erro
    if not o_botao_atualiza(arquivo.id):
        return _erro_do_sistema('Este arquivo ainda não é atualizado por este botão.', 409)

    try:
        resultado = atualizar_arquivo(arquivo, empresa)
    except Exception:
        traceback.print_exc()
        resultado = resultado_de_falha_do_sistema(arquivo, empresa)

    link = _link_da_gestao_de_apis() if resultado['renovar_autorizacao'] else None
    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_resultado_atualizacao.html', {
        'resultado': montar_item_da_atualizacao(resultado, link),
    })
    resposta['Cache-Control'] = 'no-store'
    return resposta


# Função Objetivo: A resposta da janela "Ver arquivo" (sempre 200 e sem cache): ou o arquivo desenhado, ou a explicação do problema.
def _janela_do_visualizador(request, visualizacao=None, erro=None):
    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_visualizador.html', {
        'visualizacao': visualizacao, 'erro': erro,
    })
    resposta['Cache-Control'] = 'no-store'
    return resposta


def _erro_da_janela(titulo, texto, como_corrigir='', link=None):
    return {'titulo': titulo, 'texto': texto, 'como_corrigir': como_corrigir, 'link': link}


@require_GET
def view_ver_arquivo_do_drive(request, arquivo_id):
    # * [EXPLICAÇÃO] → Lê o arquivo do Drive (só na memória) e desenha. Cada empresa só vê os arquivos que são dela (o Busca Legal da outra
    #   empresa responde como se não existisse). A tela manda `?empresa=`: se a empresa selecionada mudou em outra aba, a janela avisa.
    empresa = obter_empresa_ativa()
    if empresa not in EMPRESAS_VALIDAS:
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Nenhuma empresa selecionada', 'Escolha a empresa no topo da tela e recarregue a página.',
        ))
    arquivo, _ = _arquivo_visivel(arquivo_id, empresa)
    if arquivo is None:
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Arquivo desconhecido', 'Este arquivo não existe para a empresa selecionada. Recarregue a página.',
        ))
    if not _tela_na_empresa_certa(request.GET.get('empresa', empresa), empresa):
        return _janela_do_visualizador(request, erro=_erro_da_janela('Empresa trocada', TEXTO_EMPRESA_MUDOU))

    try:
        lido = ler_do_drive(arquivo)
    except ArquivoAusenteNoDrive as problema:
        return _janela_do_visualizador(request, erro=_erro_da_janela('O Drive ainda não tem este arquivo', problema.mensagem))
    except ErroDoEnvio as problema:
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Não consegui ler o arquivo no Drive', problema.mensagem,
            link=_link_da_gestao_de_apis() if problema.renovar_autorizacao else None,
        ))
    except Exception:
        traceback.print_exc()
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Erro do sistema', 'Erro do próprio sistema ao ler o arquivo do Drive (não é problema do arquivo). Veja o terminal do servidor.',
        ))

    try:
        visualizacao = montar_visualizacao(lido['conteudo'], lido['nome'], ORIGEM_DRIVE, lido['modificado_em'])
    except ErroDeLeitura as problema:
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Não consegui abrir o arquivo que está no Drive', problema.o_que, problema.como_corrigir,
        ))
    except Exception:
        traceback.print_exc()
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Erro do sistema', 'Erro do próprio sistema ao desenhar o arquivo (não é problema do arquivo). Veja o terminal do servidor.',
        ))
    return _janela_do_visualizador(request, visualizacao)


@require_POST
def view_ver_arquivo_escolhido(request, arquivo_id):
    # * [EXPLICAÇÃO] → O arquivo que a pessoa escolheu no computador (o navegador manda de novo). Só abre na memória e desenha; nada é
    #   gravado, nem no Drive. O id do cartão só serve para conferir que a empresa selecionada pode usar aquele cartão.
    empresa = obter_empresa_ativa()
    if empresa not in EMPRESAS_VALIDAS:
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Nenhuma empresa selecionada', 'Escolha a empresa no topo da tela e recarregue a página.',
        ))
    arquivo, _ = _arquivo_visivel(arquivo_id, empresa)
    if arquivo is None:
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Arquivo desconhecido', 'Este arquivo não existe para a empresa selecionada. Recarregue a página.',
        ))
    enviado = request.FILES.get('arquivo')
    if enviado is None:
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Nenhum arquivo chegou ao servidor', 'Escolha o arquivo de novo e tente abrir outra vez.',
        ))
    try:
        # Lê 1 byte a mais que o limite: se vier, o arquivo é grande demais e a conferência explica.
        conteudo = enviado.read(TAMANHO_MAXIMO_DO_ARQUIVO + 1)
        visualizacao = montar_visualizacao(conteudo, (enviado.name or 'arquivo')[:TAMANHO_MAXIMO_DO_NOME_EXIBIDO], ORIGEM_ESCOLHIDO)
    except ErroDeLeitura as problema:
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Não consegui abrir este arquivo', problema.o_que, problema.como_corrigir,
        ))
    except Exception:
        traceback.print_exc()
        return _janela_do_visualizador(request, erro=_erro_da_janela(
            'Erro do sistema', 'Erro do próprio sistema ao desenhar o arquivo (não é problema do arquivo). Veja o terminal do servidor.',
        ))
    return _janela_do_visualizador(request, visualizacao)
