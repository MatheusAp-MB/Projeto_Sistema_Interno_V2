# gestao_apis/funcoes_auxiliares/catalogo_conexoes.py

# Função Objetivo: Lista FIXA das conexões que a tela mostra (na ordem em que
# aparecem, em 2 colunas) e a lista FECHADA de links externos que a tela pode oferecer.
#
# * [IMPORTANTE] → Os links são montados AQUI, no servidor, a partir desta lista
#   fechada — nunca a partir de dado digitado, vindo do banco ou da API. A tela
#   só recebe o endereço final (e abre com rel="noopener noreferrer").
# * [DECISÃO, 14/10/2026] → Layout fixo: a ordem e a quantidade de cartões não
#   mudam conforme o estado. Conexão nova = linha nova neste catálogo.
# * [DECISÃO, 14/10/2026] → A tela mostra só a empresa ativa: com Magazine selecionada aparecem as
#   conexões da Magazine + as COMPARTILHADAS; com Samvale, as da Samvale + as compartilhadas.
#   Quem decide é o campo `empresa` de cada conexão (None = compartilhada, aparece nas duas).
# * [DECISÃO, 14/10/2026] → O usuário enxerga UMA conexão por API ("Google Drive"), não um cartão por
#   caminho interno dela. Quando a API é verificada por mais de um caminho (o Drive é lido pela conta
#   de serviço E enviado pelo login OAuth da conta dona), a conexão tem `partes`: um único botão Testar
#   roda todas, o estado do cartão é o das partes juntas, e o detalhe de cada parte aparece em
#   "Ver detalhes" e no histórico.

from dataclasses import dataclass
from urllib.parse import quote

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_PADRAO, EMPRESA_SAMVALE, obter_empresa_ativa

# * [EXPLICAÇÃO] → ID do projeto do Google Cloud onde mora o app OAuth do Drive
#                  (informado pelo Matheus em 14/10/2026). Não é segredo.
GOOGLE_PROJETO_ID = 'agenda-videos-mb-sv'


@dataclass(frozen=True)
class LinkExterno:
    rotulo: str   # texto curto do botão
    dica: str     # texto completo (aparece ao passar o mouse)
    url: str


LINKS_EXTERNOS = {
    'google_publicar_app': LinkExterno(
        'Público',
        'Google Cloud → Público: onde o app OAuth passa de "Testando" para "Em produção" '
        '(em "Testando" a autorização do Drive vence a cada 7 dias).',
        f'https://console.cloud.google.com/auth/audience?project={quote(GOOGLE_PROJETO_ID)}',
    ),
    'google_identidade_visual': LinkExterno(
        'Branding',
        'Google Cloud → Branding: nome do app e dados de contato (exigidos antes de publicar).',
        f'https://console.cloud.google.com/auth/branding?project={quote(GOOGLE_PROJETO_ID)}',
    ),
    'google_permissoes_conta': LinkExterno(
        'Permissões',
        'Conta Google → acessos liberados a apps de terceiros (revogar ou conferir a autorização do Drive).',
        'https://myaccount.google.com/permissions',
    ),
    'claude_console': LinkExterno(
        'Console',
        'Claude Console: chaves de API, workspaces e uso da conta da Anthropic.',
        'https://platform.claude.com/',
    ),
    'claude_cobranca': LinkExterno(
        'Cobrança',
        'Claude Console → Cobrança: créditos, pagamento e teto de gasto mensal.',
        'https://platform.claude.com/settings/billing',
    ),
    'claude_uso_limites': LinkExterno(
        'Uso e limites',
        'Claude Console → Uso e limites: nível da conta e limites de requisições.',
        'https://platform.claude.com/usage/limits',
    ),
    'ml_devcenter': LinkExterno(
        'DevCenter',
        'Mercado Livre → DevCenter: suas aplicações, Client ID e Client Secret.',
        'https://developers.mercadolivre.com.br/devcenter/',
    ),
    'ml_doc_autenticacao': LinkExterno(
        'Documentação',
        'Mercado Livre → documentação oficial de autenticação e autorização.',
        'https://developers.mercadolivre.com.br/pt_br/autenticacao-e-autorizacao',
    ),
}


@dataclass(frozen=True)
class ParteDaConexao:
    """
    Uma verificação independente dentro de uma conexão que o usuário vê como UMA coisa só.
    O `id` é o que vai para o histórico (EventoIntegracao.conexao) e para os verificadores.
    """
    id: str
    nome: str                  # nome curto (aparece nos detalhes e no histórico)
    descricao: str             # o que esta parte prova
    impacto_padrao: str        # o que para de funcionar se só esta parte cair


@dataclass(frozen=True)
class Conexao:
    id: str
    nome: str
    subtitulo: str
    icone: str                 # classes do Font Awesome 6
    impacto_padrao: str        # o que para de funcionar se esta conexão cair
    links: tuple = ()          # ids de LINKS_EXTERNOS
    testavel: bool = True
    motivo_sem_teste: str = ''
    empresa: str = None        # EMPRESA_MAGAZINE / EMPRESA_SAMVALE; None = compartilhada (aparece nas duas)
    partes: tuple = ()         # ParteDaConexao; vazio = a conexão é verificada por um caminho só


IMPACTO_ML = (
    'Sem isso, as telas que consultam o Mercado Livre desta conta (pedidos, devoluções, '
    'anúncios, estoque do Full, vendas) deixam de carregar dados novos.'
)
IMPACTO_SYSEMP = (
    'Sem isso, o sistema não carrega os dados do Sysemp desta empresa '
    '(impostos de entrada e análise de estoque do Full).'
)

CONEXOES = (
    Conexao(
        id='google_drive',
        nome='Google Drive',
        subtitulo='Leitura das pastas, envio de arquivos e portal de vídeos',
        icone='fab fa-google-drive',
        impacto_padrao=(
            'Sem isso, a Agenda de Vídeos não lê as pastas do Drive e não dá para enviar arquivos '
            'nem tocar os vídeos pelo portal.'
        ),
        links=('google_publicar_app', 'google_identidade_visual', 'google_permissoes_conta'),
        partes=(
            ParteDaConexao(
                id='google_drive_leitura',
                nome='Leitura das pastas',
                descricao='Conta de serviço (somente leitura): a Agenda de Vídeos varrendo as pastas do Drive.',
                impacto_padrao='Sem isso, a Agenda de Vídeos não consegue ler as pastas e os arquivos do Drive.',
            ),
            ParteDaConexao(
                id='google_drive_envio',
                nome='Envio e vídeos',
                descricao='Login da conta dona do Drive: envio de arquivos e portal de vídeos.',
                impacto_padrao='Sem isso, não dá para enviar arquivos ao Drive nem tocar os vídeos pelo portal.',
            ),
        ),
    ),
    Conexao(
        id='claude',
        nome='API do Claude',
        subtitulo='IA do sistema (chaves ANTHROPIC_* do .env)',
        icone='fas fa-wand-magic-sparkles',
        impacto_padrao=(
            'Sem isso, os recursos de IA do sistema (como gerar títulos de anúncio) '
            'não conseguem falar com o Claude.'
        ),
        links=('claude_console', 'claude_cobranca', 'claude_uso_limites'),
    ),
    Conexao(
        id='ml_mb',
        nome='Mercado Livre — Magazine (MB)',
        subtitulo='Token da conta MB (renovado sozinho)',
        icone='fas fa-handshake',
        impacto_padrao=IMPACTO_ML,
        links=('ml_devcenter', 'ml_doc_autenticacao'),
        empresa=EMPRESA_MAGAZINE,
    ),
    Conexao(
        id='ml_sv',
        nome='Mercado Livre — Samvale (SV)',
        subtitulo='Token da conta SV (renovado sozinho)',
        icone='fas fa-handshake',
        impacto_padrao=IMPACTO_ML,
        links=('ml_devcenter', 'ml_doc_autenticacao'),
        empresa=EMPRESA_SAMVALE,
    ),
    Conexao(
        id='sysemp_mb',
        nome='Sysemp — Magazine (MB)',
        subtitulo='ERP da Magazine (token de API)',
        icone='fas fa-database',
        impacto_padrao=IMPACTO_SYSEMP,
        testavel=False,
        motivo_sem_teste='Ainda não identificamos uma chamada leve do Sysemp para testar sem carregar dados pesados.',
        empresa=EMPRESA_MAGAZINE,
    ),
    Conexao(
        id='sysemp_sv',
        nome='Sysemp — Samvale (SV)',
        subtitulo='ERP da Samvale (token de API)',
        icone='fas fa-database',
        impacto_padrao=IMPACTO_SYSEMP,
        testavel=False,
        motivo_sem_teste='Ainda não identificamos uma chamada leve do Sysemp para testar sem carregar dados pesados.',
        empresa=EMPRESA_SAMVALE,
    ),
    Conexao(
        id='agente',
        nome='Agente de automação',
        subtitulo='Programa do computador (chave AGENTE_TOKEN)',
        icone='fas fa-robot',
        impacto_padrao=(
            'Sem isso, o agente do computador não consegue enviar postagens, replicações '
            'e verificações de aprovação para o sistema.'
        ),
        testavel=False,
        motivo_sem_teste='O sistema ainda não registra o último contato do agente, então não há o que testar daqui.',
    ),
)

CONEXOES_POR_ID = {conexao.id: conexao for conexao in CONEXOES}


def unidades_de_teste(conexao):
    """Ids de tudo que roda e grava histórico ao testar a conexão: as partes (se houver) ou ela mesma."""
    return tuple(parte.id for parte in conexao.partes) if conexao.partes else (conexao.id,)


def ids_de_historico(conexoes):
    """Ids sob os quais o histórico (EventoIntegracao.conexao) guarda os testes destas conexões."""
    ids = []
    for conexao in conexoes:
        ids.extend(unidades_de_teste(conexao))
    return ids


def conexoes_da_empresa(empresa=None):
    """
    Conexões que a tela mostra para a empresa: as dela + as compartilhadas (empresa=None), na ordem
    do catálogo. Sem `empresa`, usa a empresa ativa da requisição (EmpresaMiddleware); fora de uma
    requisição web (terminal, testes) cai no padrão do sistema (Magazine).
    """
    empresa = empresa or obter_empresa_ativa() or EMPRESA_PADRAO
    return tuple(c for c in CONEXOES if c.empresa is None or c.empresa == empresa)


def buscar_conexao(conexao_id):
    return CONEXOES_POR_ID.get(conexao_id)


def links_da_conexao(conexao):
    # * [EXPLICAÇÃO] → Só chega à tela o que está na lista fechada acima.
    return [
        {'rotulo': LINKS_EXTERNOS[chave].rotulo, 'dica': LINKS_EXTERNOS[chave].dica, 'url': LINKS_EXTERNOS[chave].url}
        for chave in conexao.links
        if chave in LINKS_EXTERNOS
    ]
