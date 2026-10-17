# arquivos_referencia/views_arquivos_referencia.py

# Função Objetivo: Views da tela "Arquivos de referência" — onde se confere e se ENVIA ao Drive os arquivos que o
# "popular banco" lê: 4 tabelas de frete e 2 planilhas do Busca Legal.
#
# * [DECISÃO, 14/10/2026] → O fluxo final tem 2 passos SEPARADOS: (1) conferir e enviar ao Drive; (2) atualizar o sistema com o
#   que está no Drive (outro clique). Só a view de atualizar (view_atualizar_arquivo) toca no banco do sistema; conferir e enviar
#   nunca tocam.
# * [DECISÃO, 16/10/2026] → Passo 2, ciclo dos impostos: a planilha Busca Legal da empresa selecionada entra no mesmo botão (modo Expandir: nada é
#   apagado), logo depois das 4 tabelas de frete, no mesmo esquema de 1 pedido por arquivo e com a mesma recusa de tela velha.
# * [DECISÃO, 16/10/2026] → Passo 3 (Ciclo 3): depois dos arquivos, a MESMA janela recalcula as grades de preço LOCAIS que usam o que mudou (Magalu, TikTok Shop, Amazon,
#   Raia, Shopee), 1 pedido por grade (view_recalcular_grade), uma depois da outra, com a mesma recusa de tela velha (409 se a empresa selecionada mudou). Só a view de
#   atualizar e a de recalcular tocam no banco do sistema. A grade do Mercado Livre (usa a API do ML) fica para o ciclo 4.
# * [DECISÃO, 16/10/2026] → O MODO da Busca Legal (Expandir/Substituir) é UMA configuração da empresa, num card no topo da tela (view_modo_da_importacao grava no banco
#   da empresa), e vale para os dois passos: no ENVIO, Expandir junta a planilha ao arquivo que está no Drive (view_enviar_arquivo → uniao_da_busca_legal) e Substituir
#   troca o arquivo por inteiro; no ATUALIZAR, Expandir atualiza o que existe e cria o que falta, e Substituir deixa o sistema igual à planilha. Nenhuma das duas janelas
#   escolhe o modo: só mostram o da empresa. O navegador não manda o modo em pedido nenhum: o servidor lê da configuração. Quem apaga continua com as 2 travas (prévia + md5).
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
# * [DECISÃO, 16/10/2026] → "Baixar": cópia do arquivo que está no Drive agora, para a pessoa guardar no computador (backup antes de trocar o
#   arquivo ou de atualizar o sistema). O servidor lê do Drive só na memória (a mesma leitura com conferência de integridade do botão de
#   atualizar) e repassa ao navegador; nada é gravado no servidor. Só leitura: não muda o Drive nem o sistema. Erros voltam como erro + JSON
#   {"mensagem", "link"} (o JS mostra no aviso da tela), porque a resposta certa é um arquivo, não uma página.
# * [DECISÃO, 16/10/2026] → Busca Legal em modo SUBSTITUIR (o sistema da empresa fica LITERALMENTE igual à planilha: o que ela não tem é apagado dos produtos
#   — CST e impostos de saída — e das tabelas de ICMS e PIS/COFINS; os produtos em si nunca são apagados). Como apaga, tem DUAS travas no servidor:
#   (1) a PRÉVIA (view_previa_do_substituir): roda a mesma atualização dentro de uma transação que é DESFEITA no fim e devolve a lista exata do que seria
#   apagado, cada item com o motivo; (2) a gravação (view_atualizar_arquivo com modo=substituir) só roda se trouxer o MD5 do arquivo que a prévia mostrou
#   (`previa_md5`) e o Drive ainda tiver esse mesmo arquivo — senão não grava nada. Quem lê a prévia ainda marca que leu antes de o botão liberar (a tela).
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
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.empresa import EMPRESAS_VALIDAS, obter_empresa_ativa
from impostos.funcoes_auxiliares.saida.preenchimento_impostos_saida import COLUNA_EAN

from .funcoes_auxiliares.atualizacao_do_sistema import (
    STATUS_PREVIA, arquivos_que_o_botao_atualiza, atualizar_arquivo, o_botao_atualiza, resultado_de_falha_do_sistema,
)
from .funcoes_auxiliares.auditor_de_arquivos import auditar_arquivo
from .funcoes_auxiliares.modelo_do_arquivo import ModeloDesatualizado, gerar_modelo
from .funcoes_auxiliares.catalogo_arquivos import GRUPO_FRETE, GRUPO_IMPOSTOS_SAIDA, arquivo_e_da_empresa, buscar_arquivo
from .funcoes_auxiliares.configuracao_da_importacao import (
    MODOS_DA_IMPORTACAO, ConfiguracaoIndisponivel, gravar_modo_da_busca_legal, modo_da_busca_legal, situacao_do_modo,
)
from .funcoes_auxiliares.envio_ao_drive import (
    MIME_XLSX, ArquivoAusenteNoDrive, ErroDoEnvio, consultar_no_drive, enviar_para_o_drive, ler_do_drive,
)
from .funcoes_auxiliares.importacao_busca_legal import MODO_EXPANDIR, MODO_SUBSTITUIR
from .funcoes_auxiliares.leitura_planilha import TAMANHO_MAXIMO_DO_ARQUIVO, ErroDeLeitura
from .funcoes_auxiliares.nome_do_download import nome_do_download
from .funcoes_auxiliares.recalculo_das_grades import GRADES_LOCAIS, buscar_grade, recalcular_grade, resultado_de_falha_da_grade
from .funcoes_auxiliares.uniao_da_busca_legal import ErroDaUniao, juntar_planilhas
from .funcoes_auxiliares.visualizacao_do_arquivo import ORIGEM_DRIVE, ORIGEM_ESCOLHIDO, montar_visualizacao
from .funcoes_auxiliares.montagem_da_tela import (
    montar_cartao, montar_grupos, montar_item_da_atualizacao, montar_item_da_grade, montar_linha_do_drive, nome_curto_da_empresa,
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
    para_atualizar = arquivos_que_o_botao_atualiza(empresa)
    return render(request, 'arquivos_referencia/estrutura_arquivos_referencia.html', {
        'empresa_da_tela': empresa,
        'empresa_da_tela_nome': nome_curto_da_empresa(empresa),
        'configuracao': situacao_do_modo(empresa),   # o card de modo no topo da tela
        'grupos': montar_grupos(empresa),
        'arquivos_para_atualizar': para_atualizar,
        'grades_para_recalcular': GRADES_LOCAIS,   # o JS copia para a janela só as que o que foi gravado afeta
        # A janela de confirmação descreve cada tipo de arquivo à parte: frete (espelha o arquivo) e Busca Legal (modo Expandir, 1 só por empresa).
        'arquivos_de_frete_para_atualizar': [a for a in para_atualizar if a.grupo == GRUPO_FRETE],
        'arquivo_de_impostos_para_atualizar': next((a for a in para_atualizar if a.grupo == GRUPO_IMPOSTOS_SAIDA), None),
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


# Função Objetivo: A função que o envio usa no modo EXPANDIR: recebe os bytes do arquivo que está no Drive AGORA, junta a planilha nova a ele (pelo EAN) e confere o
# arquivo que ficaria lá com a MESMA auditoria do envio. Qualquer problema vira ErroDoEnvio (nada é enviado e a pessoa lê o motivo no aviso).
def _funcao_de_juntar(arquivo, conteudo_novo):
    def juntar(conteudo_do_drive):
        try:
            uniao = juntar_planilhas(conteudo_do_drive, conteudo_novo, COLUNA_EAN)
        except ErroDaUniao as problema:
            raise ErroDoEnvio(f'{problema} Nada foi enviado.', 409) from problema
        resultante = uniao.pop('conteudo')
        relatorio = auditar_arquivo(arquivo, resultante, 'arquivo do Drive depois de juntar', tamanho_em_bytes=len(resultante))
        if not relatorio.pode_enviar:
            raise ErroDoEnvio(
                'O arquivo que ficaria no Drive depois de juntar a planilha não passou na conferência (ele ficaria com erro). Nada foi enviado. '
                'Corrija o arquivo, ou use o modo Substituir para trocar o arquivo do Drive por inteiro.',
                409,
            )
        return resultante, uniao
    return juntar


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

    # O modo (Expandir/Substituir) só existe para a planilha Busca Legal e vem da configuração da empresa (lida AGORA do banco; o navegador não manda modo nenhum).
    # Expandir junta a planilha ao arquivo do Drive; Substituir (e as tabelas de frete) trocam o arquivo por inteiro.
    modo = modo_da_busca_legal(empresa) if arquivo.grupo == GRUPO_IMPOSTOS_SAIDA else None
    juntar = _funcao_de_juntar(arquivo, conteudo) if modo == MODO_EXPANDIR else None
    try:
        envio = enviar_para_o_drive(arquivo, conteudo, juntar=juntar)
    except ErroDoEnvio as problema:
        return _erro_do_drive(problema)
    except Exception:
        traceback.print_exc()
        return _erro_do_sistema(
            'O envio quebrou por um erro do próprio sistema (não é problema do arquivo). O Drive pode não ter sido alterado — '
            'veja o terminal do servidor.',
            500,
        )

    juncao = envio['juncao']
    if juncao:
        mensagem = (
            f'Enviado ao Drive: {envio["nome"]}. Modo Expandir: as linhas da planilha foram juntadas ao arquivo que já estava lá — '
            f'{juncao["atualizadas"]} atualizada{"" if juncao["atualizadas"] == 1 else "s"}, {juncao["novas"]} nova{"" if juncao["novas"] == 1 else "s"} no final, '
            f'{juncao["iguais"]} já {"estava" if juncao["iguais"] == 1 else "estavam"} igual{"" if juncao["iguais"] == 1 else "is"}.'
        )
        if juncao['formulas_viraram_valor']:
            mensagem += f' {juncao["formulas_viraram_valor"]} fórmula(s) do arquivo do Drive passaram a guardar só o valor.'
        if juncao['sem_chave']:
            mensagem += f' {juncao["sem_chave"]} linha(s) da planilha sem EAN foram ignoradas.'
    else:
        mensagem = f'Enviado ao Drive: {envio["nome"]}. ' + (
            'O arquivo que estava lá foi trocado.' if envio['substituiu'] else 'Era um arquivo novo na pasta.'
        )
        if modo == MODO_SUBSTITUIR:
            mensagem += ' Modo Substituir: o arquivo do Drive foi trocado por inteiro.'
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


@require_GET
def view_baixar_arquivo_do_drive(request, arquivo_id):
    # * [EXPLICAÇÃO] → Cada empresa só baixa os arquivos que são dela (o Busca Legal da outra empresa responde 404, como se não existisse). A tela manda
    #   `?empresa=`: se a empresa selecionada mudou em outra aba, o servidor recusa (409) e pede para recarregar — a mesma regra do resto da tela.
    # * [EXPLICAÇÃO] → O corpo é o arquivo do Drive, byte a byte (já conferido por MD5 e tamanho dentro de ler_do_drive). O nome sugerido ao navegador
    #   leva a data do envio (ver nome_do_download.py) e vai também em X-Arquivo-Nome (texto codificado), porque quem baixa é o JS da tela (fetch),
    #   que assim consegue mostrar o motivo quando algo dá errado em vez de o navegador salvar uma página de erro como se fosse o arquivo.
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    arquivo, erro = _arquivo_visivel(arquivo_id, empresa)
    if erro:
        return erro
    if not _tela_na_empresa_certa(request.GET.get('empresa', empresa), empresa):
        return _erro_do_sistema(TEXTO_EMPRESA_MUDOU, 409)

    try:
        lido = ler_do_drive(arquivo)
    except ArquivoAusenteNoDrive as problema:
        return _erro_do_sistema(
            f'Não há o que baixar: o Drive ainda não tem “{arquivo.nome_no_drive}”. Envie o arquivo pelo cartão dele primeiro.', problema.status,
        )
    except ErroDoEnvio as problema:
        return _erro_do_drive(problema)
    except Exception:
        traceback.print_exc()
        return _erro_do_sistema(
            'O download quebrou por um erro do próprio sistema (não é problema do arquivo). Veja o terminal do servidor.', 500,
        )

    nome = nome_do_download(lido['nome'], lido['modificado_em'])
    resposta = HttpResponse(lido['conteudo'], content_type=MIME_XLSX)
    resposta['Content-Disposition'] = content_disposition_header(True, nome)
    resposta['X-Arquivo-Nome'] = quote(nome)
    resposta['X-Content-Type-Options'] = 'nosniff'
    resposta['Cache-Control'] = 'no-store'
    return resposta


@require_GET
def view_baixar_modelo(request, arquivo_id):
    # * [EXPLICAÇÃO] → "Modelo" (GET, só leitura): entrega uma planilha IGUAL ao arquivo real (visual e estrutura), só com o cabeçalho, 1 linha de exemplo
    #   (2 no Mercado Livre) e uma linha cinza escura marcando o fim, para a pessoa usar de guia
    #   (ver modelo_do_arquivo.py). Não consulta o Drive nem o banco: é um arquivo guardado em modelos_base, conferido na hora contra o que o
    #   importador lê, então funciona até com o Drive fora do ar.
    #   A Busca Legal da outra empresa responde 404, como nos outros botões do cartão.
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    arquivo, erro = _arquivo_visivel(arquivo_id, empresa)
    if erro:
        return erro

    try:
        modelo = gerar_modelo(arquivo)
    except ModeloDesatualizado as exc:
        # * [EXPLICAÇÃO] → O modelo guardado não bate mais com o importador: melhor avisar do que entregar um arquivo que o sistema leria errado.
        return _erro_do_sistema(
            f'O modelo deste arquivo ficou desatualizado: {exc}. Rode scripts_dev/gerar_modelos_base_dos_arquivos_de_referencia.py '
            'e, se o erro continuar, o importador mudou e o script precisa acompanhar.', 500)
    except Exception:
        traceback.print_exc()
        return _erro_do_sistema('Não consegui montar o modelo por um erro do próprio sistema. Veja o terminal do servidor.', 500)

    resposta = HttpResponse(modelo['conteudo'], content_type=MIME_XLSX)
    resposta['Content-Disposition'] = content_disposition_header(True, modelo['nome'])
    resposta['X-Content-Type-Options'] = 'nosniff'
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
        # O modo NÃO vem do navegador: o servidor lê a configuração da empresa (card no topo da tela). Se for Substituir, `previa_md5` é o MD5 do arquivo que a
        # prévia mostrou: sem ele (ou com o Drive já trocado) nada é apagado.
        resultado = atualizar_arquivo(arquivo, empresa, md5_da_previa=request.POST.get('previa_md5') or None)
    except Exception:
        traceback.print_exc()
        resultado = resultado_de_falha_do_sistema(arquivo, empresa)

    link = _link_da_gestao_de_apis() if resultado['renovar_autorizacao'] else None
    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_resultado_atualizacao.html', {
        'resultado': montar_item_da_atualizacao(resultado, link),
    })
    resposta['Cache-Control'] = 'no-store'
    return resposta


@require_POST
def view_recalcular_grade(request, grade_id):
    # * [EXPLICAÇÃO] → Passo 3: recalcula UMA grade de preço local da empresa SELECIONADA (a mesma calculadora do terminal, tudo ou nada). A grade é escolhida pelo ID
    #   da lista fechada (GRADES_LOCAIS): nada vindo do navegador entra em nome de módulo ou de função. A grade do Mercado Livre não está na lista (ciclo 4).
    # * [IMPORTANTE] → Como na atualização, o pedido OBRIGATORIAMENTE diz em qual empresa a tela estava (`empresa`): faltou, ou a empresa selecionada agora é outra
    #   (trocada em outra aba) → 409 e NADA é recalculado.
    # * [EXPLICAÇÃO] → Falha prevista (outro recálculo igual em andamento) e erro do sistema voltam como linha de resultado (200), com o botão "Tentar de novo".
    #   O cabeçalho HX-Trigger avisa a janela (evento "arqGradeTerminou") para ela atualizar o resumo, inclusive quando a pessoa tenta de novo depois.
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    if not _tela_na_empresa_certa(request.POST.get('empresa'), empresa):
        return _erro_do_sistema(f'{TEXTO_EMPRESA_MUDOU} Nada foi recalculado.', 409)
    grade = buscar_grade(grade_id)
    if grade is None:
        return _erro_do_sistema('Grade de preço desconhecida. Recarregue a página. Nada foi recalculado.', 404)

    try:
        resultado = recalcular_grade(grade, empresa)
    except Exception:
        traceback.print_exc()
        resultado = resultado_de_falha_da_grade(grade, empresa)

    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_resultado_grade.html', {
        'resultado': montar_item_da_grade(resultado),
    })
    resposta['Cache-Control'] = 'no-store'
    resposta['HX-Trigger'] = json.dumps({'arqGradeTerminou': {'grade': grade.id}})
    return resposta


@require_POST
def view_previa_do_substituir(request, arquivo_id):
    # * [EXPLICAÇÃO] → A prévia do Substituir: mostra, ANTES de qualquer coisa ser apagada, o que o Substituir apagaria. Roda a mesma atualização da
    #   gravação real dentro de uma transação que é desfeita no fim (nada fica gravado, nem no histórico), então a lista é exatamente o que a
    #   gravação faria — com o arquivo que está no Drive neste instante. O MD5 desse arquivo volta na tela (data-arq-previa-md5) e é o que a
    #   gravação real exige de volta.
    # * [EXPLICAÇÃO] → Problema PREVISTO (Drive fora do ar, arquivo com erro, planilha da empresa errada, já tem atualização em andamento) volta como resposta
    #   200 com a explicação dentro da própria janela da prévia (como no "Ver arquivo"): ela nunca fica "carregando" para sempre e o botão de
    #   apagar não é liberado. Só pedido inválido (empresa trocada, arquivo desconhecido, arquivo que não é o Busca Legal) volta com erro + JSON.
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    if not _tela_na_empresa_certa(request.POST.get('empresa'), empresa):
        return _erro_do_sistema(f'{TEXTO_EMPRESA_MUDOU} Nada foi gravado.', 409)
    arquivo, erro = _arquivo_visivel(arquivo_id, empresa)
    if erro:
        return erro
    if not o_botao_atualiza(arquivo.id) or arquivo.grupo != GRUPO_IMPOSTOS_SAIDA:
        return _erro_do_sistema('A prévia do Substituir só existe para a planilha Busca Legal.', 409)

    try:
        resultado = atualizar_arquivo(arquivo, empresa, modo=MODO_SUBSTITUIR, simular=True)
    except Exception:
        traceback.print_exc()
        resultado = resultado_de_falha_do_sistema(arquivo, empresa)

    link = _link_da_gestao_de_apis() if resultado['renovar_autorizacao'] else None
    item = montar_item_da_atualizacao(resultado, link)
    previa_pronta = item['status'] == STATUS_PREVIA and bool(item.get('drive'))
    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_previa_substituir.html', {
        'resultado': item,
        'empresa': item['empresas'][0] if item['empresas'] else None,
        'previa_pronta': previa_pronta,
        'previa_md5': item['drive']['md5'] if previa_pronta else '',
        'empresa_da_tela': empresa,
        'empresa_da_tela_nome': nome_curto_da_empresa(empresa),
        'url_para_baixar': f"{reverse('arquivos_referencia_baixar', args=[arquivo.id])}?empresa={empresa}",
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


# Função Objetivo: O card de configuração do topo da tela (o MODO da Busca Legal da empresa selecionada). GET = devolve o card (a tela o usa para voltar ao valor
# gravado quando uma troca falha); POST = grava o modo escolhido no banco da empresa e devolve o card novo, com um aviso.
# * [IMPORTANTE] → Como o resto da tela, recusa (409, nada alterado) se a empresa selecionada agora não é a que a tela mostrava; modo fora da lista é recusado (400).
@require_http_methods(['GET', 'POST'])
def view_modo_da_importacao(request):
    empresa, erro = _empresa_da_requisicao()
    if erro:
        return erro
    aviso = None
    if request.method == 'POST':
        if not _tela_na_empresa_certa(request.POST.get('empresa'), empresa):
            return _erro_do_sistema(f'{TEXTO_EMPRESA_MUDOU} O modo não foi alterado.', 409)
        modo = request.POST.get('modo')
        if modo not in MODOS_DA_IMPORTACAO:
            return _erro_do_sistema('Modo desconhecido. Recarregue a página. O modo não foi alterado.', 400)
        try:
            gravar_modo_da_busca_legal(empresa, modo)
        except ConfiguracaoIndisponivel as problema:
            return _erro_do_sistema(str(problema), 409)
        aviso = (
            f'Modo da Busca Legal na {nome_curto_da_empresa(empresa)}: {"Substituir" if modo == MODO_SUBSTITUIR else "Expandir"}. '
            'Vale ao enviar ao Drive e ao atualizar o sistema.'
        )
    resposta = render(request, 'arquivos_referencia/parciais/estrutura_parcial_configuracao.html', {
        'configuracao': situacao_do_modo(empresa), 'empresa_da_tela': empresa, 'empresa_da_tela_nome': nome_curto_da_empresa(empresa),
    })
    resposta['Cache-Control'] = 'no-store'
    return _com_aviso(resposta, aviso, 'ok') if aviso else resposta
