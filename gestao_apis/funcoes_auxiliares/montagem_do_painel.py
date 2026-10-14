# gestao_apis/funcoes_auxiliares/montagem_do_painel.py

# Função Objetivo: Monta tudo que a tela "Gestão de APIs" mostra — os cartões da empresa ativa (+ os
# compartilhados), a faixa de urgência, a lista de problemas e a tabela de eventos — e executa os
# testes por conexão.
#
# * [EXPLICAÇÃO] → O estado de cada cartão sai de 2 fontes, sem chamar a internet ao abrir a página:
#     1) a leitura LOCAL (configuração/relógio — ler_local_*), que nunca diz "Funcionando";
#     2) o ÚLTIMO EVENTO gravado dessa conexão (o resultado do último teste), que é o que pode
#        confirmar "Funcionando" (se for recente) ou apontar o problema.
#   Só o botão Testar vai à internet.
#
# * [DECISÃO, 14/10/2026] → Falha de leitura de UM cartão (bug nosso) nunca derruba a página:
#   o cartão mostra "erro interno" e o traceback vai pro terminal.
#
# * [DECISÃO, 14/10/2026] → Conexão com `partes` (Google Drive): cada parte tem a sua leitura local e o seu
#   histórico; o cartão junta as partes assim — Com problema se alguma tem problema; senão Atenção se
#   alguma está em atenção (ou configurada só pela metade); "Funcionando" SÓ se todas funcionam; senão
#   Não configurada (todas) ou Não verificada. O detalhe de cada parte vai em "Ver detalhes".

import traceback
from collections import Counter
from datetime import timedelta

from django.db import DatabaseError
from django.utils import timezone

from .catalogo_conexoes import (
    CONEXOES, conexoes_da_empresa, ids_de_historico, links_da_conexao, unidades_de_teste,
)
from .estados import (
    ATENCAO, COM_PROBLEMA, ESTADOS_VISUAIS, FUNCIONANDO, JANELA_DE_VALIDADE_DO_TESTE_HORAS,
    NAO_CONFIGURADA, NAO_VERIFICADA, ORDEM_DE_URGENCIA, Resultado,
)
from .eventos import listar_eventos, ultimo_evento_da_conexao
from .tempo_legivel import descrever_duracao

ROTULO_DA_ACAO = {'teste': 'Teste', 'erro_interno': 'Teste (erro interno)'}


# ================================================
# DESPACHO: o que chamar em cada conexão
# ================================================
# * [EXPLICAÇÃO] → Imports dentro das funções de propósito: se uma biblioteca de uma integração
#                  falhar ao carregar, só os cartões dela mostram o erro — a tela abre igual.

def _local_drive_leitura():
    from .verificador_google_drive import ler_local_drive_leitura
    return ler_local_drive_leitura()


def _local_drive_envio():
    from .verificador_google_drive import ler_local_drive_envio
    return ler_local_drive_envio()


def _local_ml(conta):
    from .verificador_mercado_livre import ler_local_mercado_livre
    return ler_local_mercado_livre(conta)


def _local_sysemp(conexao_id):
    from .verificador_demais_conexoes import ler_local_sysemp
    return ler_local_sysemp(conexao_id)


def _local_agente():
    from .verificador_demais_conexoes import ler_local_agente
    return ler_local_agente()


def _local_claude():
    from .verificador_claude import ler_local_claude
    return ler_local_claude()


def _teste_drive_leitura():
    from .verificador_google_drive import testar_drive_leitura
    return testar_drive_leitura()


def _teste_drive_envio():
    from .verificador_google_drive import testar_drive_envio
    return testar_drive_envio()


def _teste_ml(conta):
    from .verificador_mercado_livre import testar_mercado_livre
    return testar_mercado_livre(conta)


def _teste_claude():
    from .verificador_claude import testar_claude
    return testar_claude()


LEITURAS_LOCAIS = {
    'google_drive_leitura': _local_drive_leitura,
    'google_drive_envio': _local_drive_envio,
    'ml_mb': lambda: _local_ml('MB'),
    'ml_sv': lambda: _local_ml('SV'),
    'sysemp_mb': lambda: _local_sysemp('sysemp_mb'),
    'sysemp_sv': lambda: _local_sysemp('sysemp_sv'),
    'agente': _local_agente,
    'claude': _local_claude,
}

TESTES = {
    'google_drive_leitura': _teste_drive_leitura,
    'google_drive_envio': _teste_drive_envio,
    'ml_mb': lambda: _teste_ml('MB'),
    'ml_sv': lambda: _teste_ml('SV'),
    'claude': _teste_claude,
}


def executar_teste(unidade_id):
    """
    Roda o teste real de UMA unidade (uma conexão simples ou uma parte de conexão) — vai à internet.
    Quem chama trata exceção inesperada como erro interno.
    """
    return TESTES[unidade_id]()


def _ler_local_com_seguranca(conexao_id):
    try:
        return LEITURAS_LOCAIS[conexao_id]()
    except Exception:
        traceback.print_exc()
        return Resultado(
            NAO_VERIFICADA,
            'Erro interno ao ler a configuração desta conexão (não é problema da conexão). Veja o terminal do servidor.',
        )


# ================================================
# CARTÃO
# ================================================

def _juntar_textos(*partes):
    vistos = []
    for parte in partes:
        if parte and parte not in vistos:
            vistos.append(parte)
    return ' · '.join(vistos)


def _combinar_leitura_local_com_ultimo_evento(local, evento, agora):
    idade = agora - evento.criado_em

    if evento.acao == 'erro_interno':
        return Resultado(NAO_VERIFICADA, evento.motivo, evento.impacto, evento.como_resolver, local.evidencia)

    if evento.estado == FUNCIONANDO:
        if idade <= timedelta(hours=JANELA_DE_VALIDADE_DO_TESTE_HORAS):
            return Resultado(
                FUNCIONANDO, evento.motivo, evento.impacto, '',
                _juntar_textos(evento.evidencia, local.evidencia),
            )
        return Resultado(
            NAO_VERIFICADA,
            f'O último teste deu certo há {descrever_duracao(idade.total_seconds())}, '
            f'mas já passou de {JANELA_DE_VALIDADE_DO_TESTE_HORAS} h. Teste de novo para confirmar.',
            evidencia=local.evidencia,
        )

    # * [EXPLICAÇÃO] → Último teste foi Atenção/Com problema: continua assim até um teste dar certo.
    #                  A tela mostra o que o teste encontrou; clicar em Testar confirma se já foi resolvido.
    return Resultado(
        evento.estado, evento.motivo, evento.impacto, evento.como_resolver,
        _juntar_textos(evento.evidencia, local.evidencia),
    )


def _formatar_data_hora(momento):
    return timezone.localtime(momento).strftime('%d/%m/%Y %H:%M:%S')


def _resolver_unidade(unidade_id, evento, agora):
    """
    Situação de UMA unidade testável (conexão simples ou parte de conexão):
    (Resultado, momento do último teste ou None).
    """
    local = _ler_local_com_seguranca(unidade_id)
    if local.estado == NAO_CONFIGURADA or evento is None:
        return local, None
    return _combinar_leitura_local_com_ultimo_evento(local, evento, agora), evento.criado_em


# ------------------------------------------------
# Conexão com partes (Google Drive): junta as partes em UM resultado
# ------------------------------------------------

def _estado_das_partes_juntas(estados):
    if COM_PROBLEMA in estados:
        return COM_PROBLEMA
    if ATENCAO in estados:
        return ATENCAO
    if all(estado == FUNCIONANDO for estado in estados):
        return FUNCIONANDO
    if all(estado == NAO_CONFIGURADA for estado in estados):
        return NAO_CONFIGURADA
    if NAO_CONFIGURADA in estados:
        # Uma parte sem configuração e outra que funciona (ou ainda não testada): a conexão está
        # pela metade — merece atenção, não "Não configurada" nem "Funcionando".
        return ATENCAO
    return NAO_VERIFICADA


def _juntar_textos_das_partes(itens, total_de_partes, rotular):
    """
    itens = [(nome da parte, texto)]. Partes com texto IGUAL viram uma frase só. rotular:
      'sempre'    → cada frase leva o nome da(s) parte(s), a menos que a frase valha para a conexão inteira;
      'se_varias' → só rotula quando as partes dizem coisas diferentes;
      'nunca'     → sem nome de parte.
    """
    grupos = []
    for nome, texto in itens:
        if not texto:
            continue
        for grupo in grupos:
            if grupo[1] == texto:
                grupo[0].append(nome)
                break
        else:
            grupos.append([[nome], texto])
    if not grupos:
        return ''

    vale_para_todas = len(grupos) == 1 and len(grupos[0][0]) == total_de_partes
    if rotular == 'nunca' or vale_para_todas or (rotular == 'se_varias' and len(grupos) == 1):
        return ' '.join(texto for _, texto in grupos)
    return ' · '.join(f'{" e ".join(nomes)}: {texto}' for nomes, texto in grupos)


_SEVERIDADE_DAS_PARTES = {COM_PROBLEMA: 0, ATENCAO: 1, NAO_CONFIGURADA: 2}


def _juntar_partes(itens):
    """itens = [(parte, Resultado, momento do último teste)] → um Resultado para o cartão inteiro."""
    total = len(itens)
    estado = _estado_das_partes_juntas([resultado.estado for _, resultado, _ in itens])

    evidencia = ' · '.join(
        f'{parte.nome}: {ESTADOS_VISUAIS[resultado.estado]["rotulo"]}' for parte, resultado, _ in itens
    )

    if estado == FUNCIONANDO:
        nomes = ' · '.join(parte.nome for parte, _, _ in itens)
        return Resultado(
            FUNCIONANDO, f'As {total} verificações da API deram certo ({nomes}).', evidencia=evidencia,
        )

    ruins = sorted(
        (item for item in itens if item[1].estado in _SEVERIDADE_DAS_PARTES),
        key=lambda item: _SEVERIDADE_DAS_PARTES[item[1].estado],
    )
    relevantes = ruins or [item for item in itens if item[1].estado == NAO_VERIFICADA]

    motivo = _juntar_textos_das_partes(
        [(parte.nome, resultado.motivo) for parte, resultado, _ in relevantes], total, 'sempre',
    )
    como_resolver = _juntar_textos_das_partes(
        [(parte.nome, resultado.como_resolver) for parte, resultado, _ in relevantes], total, 'se_varias',
    )
    # Quando nada está errado ainda (só falta testar), o impacto é o da conexão inteira (vem do catálogo).
    impacto = ''
    if ruins:
        impacto = _juntar_textos_das_partes(
            [(parte.nome, resultado.impacto or parte.impacto_padrao) for parte, resultado, _ in ruins],
            total, 'nunca',
        )
    return Resultado(estado, motivo, impacto, como_resolver, evidencia)


def _montar_partes_para_tela(itens):
    partes = []
    for parte, resultado, verificado_em in itens:
        visual = ESTADOS_VISUAIS[resultado.estado]
        partes.append({
            'nome': parte.nome,
            'descricao': parte.descricao,
            'estado': resultado.estado,
            'estado_rotulo': visual['rotulo'],
            'estado_icone': visual['icone'],
            'motivo': resultado.motivo,
            'como_resolver': resultado.como_resolver or ('Nada a fazer agora.' if resultado.estado == FUNCIONANDO else ''),
            'evidencia': resultado.evidencia,
            'quando_completo': (
                'Nunca testada por esta tela.' if verificado_em is None
                else f'Último teste em {_formatar_data_hora(verificado_em)}.'
            ),
        })
    return partes


def montar_cartao(conexao, eventos, agora, aviso=''):
    """
    eventos = {id da unidade testável: último evento ou None}. A unidade é a própria conexão ou, se
    ela tem partes, cada uma das partes.
    """
    partes_para_tela = []
    if conexao.partes:
        itens = []
        for parte in conexao.partes:
            resultado_da_parte, verificado_da_parte = _resolver_unidade(parte.id, eventos.get(parte.id), agora)
            itens.append((parte, resultado_da_parte, verificado_da_parte))
        resultado = _juntar_partes(itens)
        # Conservador: vale o teste MAIS ANTIGO entre as partes (cada parte mostra o seu em "Ver detalhes").
        momentos = [momento for _, _, momento in itens if momento is not None]
        verificado_em = min(momentos) if momentos else None
        partes_para_tela = _montar_partes_para_tela(itens)
    else:
        resultado, verificado_em = _resolver_unidade(conexao.id, eventos.get(conexao.id), agora)

    visual = ESTADOS_VISUAIS[resultado.estado]
    if verificado_em is None:
        quando = 'Nunca testada por esta tela.'
        quando_completo = 'Nunca testada por esta tela.'
    else:
        quando = f'Testada há {descrever_duracao((agora - verificado_em).total_seconds())}.'
        quando_completo = f'Último teste em {_formatar_data_hora(verificado_em)}.'

    return {
        'id': conexao.id,
        'nome': conexao.nome,
        'subtitulo': conexao.subtitulo,
        'icone': conexao.icone,
        'testavel': conexao.testavel,
        'motivo_sem_teste': conexao.motivo_sem_teste,
        'estado': resultado.estado,
        'estado_rotulo': visual['rotulo'],
        'estado_icone': visual['icone'],
        'motivo': resultado.motivo,
        'impacto': resultado.impacto or conexao.impacto_padrao,
        'como_resolver': resultado.como_resolver or ('Nada a fazer agora.' if resultado.estado == FUNCIONANDO else ''),
        'evidencia': resultado.evidencia,
        'quando': quando,
        'quando_completo': quando_completo,
        'links': links_da_conexao(conexao),
        'aviso': aviso,
        'partes': partes_para_tela,
    }


# ================================================
# FAIXA DE URGÊNCIA + LISTA DE PROBLEMAS
# ================================================

def _montar_faixa(cartoes):
    problemas = [c for c in cartoes if c['estado'] in ORDEM_DE_URGENCIA]
    ordem_original = {c['id']: posicao for posicao, c in enumerate(cartoes)}
    problemas.sort(key=lambda c: (ORDEM_DE_URGENCIA[c['estado']], ordem_original[c['id']]))
    contagem = Counter(c['estado'] for c in cartoes)

    # * [EXPLICAÇÃO] → Concorda no singular ("1 não verificada") e no plural ("3 não verificadas").
    def _s(quantidade):
        return '' if quantidade == 1 else 's'

    resumo = (
        f'{contagem[FUNCIONANDO]} funcionando · '
        f'{contagem[NAO_VERIFICADA]} não verificada{_s(contagem[NAO_VERIFICADA])} · '
        f'{contagem[NAO_CONFIGURADA]} não configurada{_s(contagem[NAO_CONFIGURADA])}'
    )

    if problemas:
        pior = problemas[0]
        return {
            'tem_problema': True,
            'estado': pior['estado'],
            'estado_icone': pior['estado_icone'],
            'titulo': f'{pior["nome"]}: {pior["estado_rotulo"]}',
            'texto': pior['motivo'],
            'total_problemas': len(problemas),
            'resumo': resumo,
            'problemas': problemas,
        }

    if contagem[FUNCIONANDO] == 0:
        titulo = 'Nenhuma conexão foi testada ainda'
        texto = 'Use "Testar todas" (ou o botão Testar de cada cartão) para confirmar quais estão funcionando.'
    else:
        titulo = 'Nenhum problema conhecido'
        texto = resumo
    return {
        'tem_problema': False,
        'estado': FUNCIONANDO if contagem[FUNCIONANDO] else NAO_VERIFICADA,
        'estado_icone': ESTADOS_VISUAIS[FUNCIONANDO if contagem[FUNCIONANDO] else NAO_VERIFICADA]['icone'],
        'titulo': titulo,
        'texto': texto,
        'total_problemas': 0,
        'resumo': resumo,
        'problemas': [],
    }


# ================================================
# EVENTOS
# ================================================

def _montar_eventos(eventos):
    nomes = {}
    for conexao in CONEXOES:
        if conexao.partes:
            for parte in conexao.partes:
                nomes[parte.id] = f'{conexao.nome} — {parte.nome}'
        else:
            nomes[conexao.id] = conexao.nome
    linhas = []
    for evento in eventos:
        visual = ESTADOS_VISUAIS.get(evento.estado, ESTADOS_VISUAIS[NAO_VERIFICADA])
        linhas.append({
            'quando': _formatar_data_hora(evento.criado_em),
            'conexao': nomes.get(evento.conexao, evento.conexao),
            'acao': ROTULO_DA_ACAO.get(evento.acao, evento.acao),
            'estado': evento.estado,
            'estado_rotulo': visual['rotulo'],
            'estado_icone': visual['icone'],
            'quem': evento.quem,
            'detalhe': evento.motivo,
        })
    return linhas


# ================================================
# PAINEL COMPLETO
# ================================================

def montar_painel(avisos_por_conexao=None, eventos_em_memoria=None, empresa=None):
    avisos_por_conexao = avisos_por_conexao or {}
    eventos_em_memoria = eventos_em_memoria or {}
    agora = timezone.now()
    eventos_disponiveis = True

    # * [DECISÃO, 14/10/2026] → Só a empresa ativa (+ as compartilhadas): cartões, faixa de urgência,
    #                           lista de problemas e tabela de eventos olham apenas para estas conexões.
    conexoes = conexoes_da_empresa(empresa)

    cartoes = []
    for conexao in conexoes:
        eventos_da_conexao = {}
        for unidade_id in unidades_de_teste(conexao):
            evento = eventos_em_memoria.get(unidade_id)
            if evento is None and eventos_disponiveis:
                try:
                    evento = ultimo_evento_da_conexao(unidade_id)
                except DatabaseError:
                    traceback.print_exc()
                    eventos_disponiveis = False
            eventos_da_conexao[unidade_id] = evento
        cartoes.append(montar_cartao(conexao, eventos_da_conexao, agora, avisos_por_conexao.get(conexao.id, '')))

    linhas_de_eventos = []
    if eventos_disponiveis:
        try:
            linhas_de_eventos = _montar_eventos(listar_eventos(conexoes=ids_de_historico(conexoes)))
        except DatabaseError:
            traceback.print_exc()
            eventos_disponiveis = False

    return {
        'cartoes': cartoes,
        'faixa': _montar_faixa(cartoes),
        'eventos': linhas_de_eventos,
        'eventos_disponiveis': eventos_disponiveis,
        'janela_horas': JANELA_DE_VALIDADE_DO_TESTE_HORAS,
    }
