# gestao_apis/funcoes_auxiliares/verificador_claude.py

# Função Objetivo: Lê e testa a conexão com a API do Claude (Anthropic) — uma só, compartilhada
# pelas duas empresas (a chave e o workspace são do sistema, não de uma empresa).
#
# * [EXPLICAÇÃO] → ler_local_claude() NÃO chama a internet: só confere se a chave (ANTHROPIC_API_KEY) está no
#   .env. Nunca devolve "Funcionando" — ter a chave no .env não prova que a Anthropic a aceita.
#
# * [DECISÃO, 14/10/2026] → ANTHROPIC_WORKSPACE_ID é OPCIONAL. Segundo a documentação oficial, uma chave presa a
#   UM workspace (o caso da chave criada no workspace Default) não precisa do cabeçalho anthropic-workspace-id;
#   só a chave que vale para VÁRIOS workspaces exige o cabeçalho (sem ele a API responde 400). Por isso o
#   cabeçalho só é enviado quando a variável existe no .env.
#
# * [EXPLICAÇÃO] → testar_claude() faz 1 chamada por clique: messages.count_tokens (contagem de tokens).
#   Essa chamada é GRATUITA na documentação oficial (limite de requisições próprio, independente do
#   da geração) e só aceita a chave se ela for válida. Usa o MESMO jeito de montar o cliente do
#   integracao_claude/config_claude.py (chave + cabeçalho anthropic-workspace-id, sem tentativas
#   automáticas), para o teste provar o que o sistema vai de fato usar.
#
# * [LIMITE CONHECIDO] → Como a contagem é gratuita, ela NÃO prova que ainda existe crédito/saldo para
#   GERAR texto (isso é uma chamada paga). O texto de "Funcionando" avisa isso de propósito.
#
# * [FATOS CONFERIDOS NA DOCUMENTAÇÃO OFICIAL — platform.claude.com/docs/en/api/errors, 14/10/2026]
#   401 chave inválida/revogada · 402 problema de cobrança · 403 chave sem permissão · 404 recurso não
#   encontrado · 429 limite de uso ou teto de gasto · 5xx/529 instabilidade da Anthropic.
#
# * [IMPORTANTE] → Os textos de "O que aconteceu / Próximo passo" são sempre nossos (só o código de status
#   vem da API). A resposta REAL da API (a contagem de tokens, ou o erro que ela devolveu) aparece num bloco
#   à parte em "Ver detalhes", depois de passar por preparar_resposta_para_exibir() (decisão de 14/10/2026).
#   A chave nunca é escrita em lugar nenhum.
# * [IMPORTANTE] → `import anthropic` é feito dentro da função: se a biblioteca faltar no ambiente, só o
#   cartão do Claude avisa — a tela abre igual.

import os

from .estados import (
    ATENCAO, COM_PROBLEMA, FUNCIONANDO, NAO_CONFIGURADA, NAO_VERIFICADA, Resultado,
)
from .protecao_de_segredos import preparar_resposta_para_exibir

VARIAVEL_CHAVE = 'ANTHROPIC_API_KEY'
VARIAVEL_WORKSPACE = 'ANTHROPIC_WORKSPACE_ID'

# * [EXPLICAÇÃO] → Mesmo modelo do integracao_claude/config_claude.py. Se um dia a Anthropic aposentar
#                  esse nome, o teste responde 404 e o cartão avisa para atualizar esta linha.
MODELO_DO_TESTE = 'claude-haiku-5-5'
TIMEOUT_DO_TESTE_SEGUNDOS = 15.0

TEXTO_COMO_TROCAR_A_CHAVE = (
    f'Gerar uma chave nova no Claude Console (atalho neste cartão), trocar {VARIAVEL_CHAVE} no .env '
    'e reiniciar o servidor.'
)
TEXTO_COMO_CONFERIR_O_WORKSPACE = (
    f'Conferir se a chave pertence ao workspace de {VARIAVEL_WORKSPACE} (Claude Console, atalho neste cartão) '
    'e reiniciar o servidor.'
)


def _valor_do_env(nome):
    return (os.environ.get(nome) or '').strip()


def ler_local_claude():
    if not _valor_do_env(VARIAVEL_CHAVE):
        return Resultado(
            NAO_CONFIGURADA,
            f'Falta no .env: {VARIAVEL_CHAVE}.',
            como_resolver=(
                f'Adicionar a linha {VARIAVEL_CHAVE}=... no .env da raiz do projeto (o mesmo da AGENTE_TOKEN) e '
                'reiniciar o servidor. A chave sai do Claude Console (atalho neste cartão).'
            ),
        )
    if _valor_do_env(VARIAVEL_WORKSPACE):
        workspace = f'{VARIAVEL_WORKSPACE} configurado (enviado a cada chamada).'
    else:
        workspace = f'Sem {VARIAVEL_WORKSPACE} (certo para chave de um workspace só).'
    return Resultado(
        NAO_VERIFICADA,
        'Configuração completa. Falta testar a conexão com a API do Claude.',
        evidencia=f'Modelo do teste: {MODELO_DO_TESTE} (contagem de tokens, gratuita). {workspace}',
    )


def _criar_cliente(anthropic, chave, workspace):
    # * [EXPLICAÇÃO] → Função à parte só para os testes poderem trocar o cliente por um falso.
    return anthropic.Anthropic(
        api_key=chave,
        default_headers={'anthropic-workspace-id': workspace} if workspace else None,
        max_retries=0,
        timeout=TIMEOUT_DO_TESTE_SEGUNDOS,
    )


def _resultado_de_erro_de_status(status, usa_workspace=False):
    evidencia = f'Teste: contagem de tokens respondeu {status}.'
    if status == 401:
        return Resultado(
            COM_PROBLEMA,
            'A API do Claude recusou a chave (status 401): ela está errada, foi revogada ou expirou.',
            como_resolver=TEXTO_COMO_TROCAR_A_CHAVE,
            evidencia=evidencia,
        )
    if status == 403:
        return Resultado(
            COM_PROBLEMA,
            'A API do Claude negou a permissão (status 403): a chave não pode usar este recurso'
            + (' ou este workspace.' if usa_workspace else '.'),
            como_resolver=(
                TEXTO_COMO_CONFERIR_O_WORKSPACE if usa_workspace else
                'Conferir no Claude Console (atalho neste cartão) se a chave está ativa e pode usar a API.'
            ),
            evidencia=evidencia,
        )
    if status == 402:
        return Resultado(
            COM_PROBLEMA,
            'A API do Claude acusou problema de cobrança (status 402).',
            como_resolver='Abrir "Cobrança" no Claude Console (atalho neste cartão) e regularizar o pagamento ou os créditos.',
            evidencia=evidencia,
        )
    if status == 404:
        return Resultado(
            ATENCAO,
            f'A API do Claude não encontrou o recurso do teste (status 404): o modelo "{MODELO_DO_TESTE}" '
            'pode ter sido renomeado'
            + (f' ou o {VARIAVEL_WORKSPACE} está errado.' if usa_workspace else '.'),
            como_resolver=(
                (f'Conferir o {VARIAVEL_WORKSPACE} no .env; se estiver certo, atualizar ' if usa_workspace else 'Atualizar ')
                + 'MODELO_DO_TESTE no verificador_claude.py.'
            ),
            evidencia=evidencia,
        )
    if status == 429:
        return Resultado(
            ATENCAO,
            'A API do Claude limitou o uso agora (status 429): excesso de chamadas ou teto de gasto atingido.',
            como_resolver='Testar de novo em alguns minutos. Se repetir, conferir "Cobrança" e "Uso e limites" no Claude Console (atalhos neste cartão).',
            evidencia=evidencia,
        )
    if status == 400:
        return Resultado(
            ATENCAO,
            'A API do Claude recusou o pedido de teste (status 400). Pode ser teto de gasto atingido'
            + (' ou workspace incorreto.' if usa_workspace else '.'),
            como_resolver=(
                (f'Conferir o {VARIAVEL_WORKSPACE} no .env e a ' if usa_workspace else 'Conferir a ')
                + '"Cobrança" no Claude Console (atalho neste cartão) e testar de novo.'
            ),
            evidencia=evidencia,
        )
    if status >= 500:
        return Resultado(
            ATENCAO,
            f'A API do Claude está instável ou sobrecarregada agora (status {status}).',
            como_resolver='Esperar alguns minutos e testar de novo. Não precisa mexer na chave por causa disso.',
            evidencia=evidencia,
        )
    return Resultado(
        ATENCAO,
        f'A API do Claude respondeu algo inesperado ao teste (status {status}).',
        como_resolver='Testar de novo; se repetir, ver o terminal do servidor.',
        evidencia=evidencia,
    )


def _corpo_da_resposta_de_erro(erro):
    resposta = getattr(erro, 'response', None)
    try:
        return resposta.text if resposta is not None else ''
    except Exception:
        return ''


def _corpo_da_resposta_de_sucesso(resposta, tokens):
    try:
        return resposta.model_dump()
    except Exception:
        return {'input_tokens': tokens}


def testar_claude():
    local = ler_local_claude()
    if local.estado == NAO_CONFIGURADA:
        return local

    try:
        import anthropic
    except ImportError:
        return Resultado(
            ATENCAO,
            'A biblioteca "anthropic" não está instalada neste ambiente do sistema.',
            como_resolver='Instalar as dependências do projeto (poetry install) e reiniciar o servidor.',
            evidencia=local.evidencia,
        )

    workspace = _valor_do_env(VARIAVEL_WORKSPACE)
    chave = _valor_do_env(VARIAVEL_CHAVE)
    segredos = (chave, workspace)
    cliente = _criar_cliente(anthropic, chave, workspace)
    try:
        resposta = cliente.messages.count_tokens(
            model=MODELO_DO_TESTE,
            messages=[{'role': 'user', 'content': 'ping'}],
        )
    except anthropic.APIStatusError as erro:
        resultado = _resultado_de_erro_de_status(getattr(erro, 'status_code', 0) or 0, bool(workspace))
        resultado.resposta = preparar_resposta_para_exibir(_corpo_da_resposta_de_erro(erro), segredos)
        return resultado
    except anthropic.APIConnectionError as erro:
        # * [EXPLICAÇÃO] → Inclui o tempo esgotado (APITimeoutError). Não diz nada sobre a chave.
        return Resultado(
            ATENCAO,
            f'A chamada de teste não chegou à API do Claude ({type(erro).__name__}).',
            como_resolver='Conferir a internet do servidor e testar de novo.',
            evidencia=local.evidencia,
        )

    tokens = getattr(resposta, 'input_tokens', None)
    corpo = preparar_resposta_para_exibir(_corpo_da_resposta_de_sucesso(resposta, tokens), segredos)
    if not isinstance(tokens, int):
        return Resultado(
            ATENCAO,
            'A API do Claude respondeu ao teste, mas sem a contagem de tokens esperada.',
            como_resolver='Testar de novo; se repetir, conferir a versão da biblioteca "anthropic".',
            resposta=corpo,
        )
    return Resultado(
        FUNCIONANDO,
        'A API do Claude aceitou a chave. O teste é gratuito, então não confirma que ainda há crédito para gerar textos.',
        evidencia=f'Teste: contagem de tokens no modelo {MODELO_DO_TESTE} respondeu com sucesso.',
        resposta=corpo,
    )
