# core/context_processors.py

# * [RESUMO] → Deixa a empresa ativa disponível em QUALQUER template,
#              sem cada view precisar passar isso manualmente — mesmo
#              mecanismo que já expõe request.user/messages hoje.

from core.empresa import (
    obter_empresa_ativa, NOME_EXIBICAO_POR_EMPRESA,
    EMPRESA_MAGAZINE, EMPRESA_SAMVALE,
)

CLASSE_CSS_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'badge-empresa-magazine',
    EMPRESA_SAMVALE: 'badge-empresa-samvale',
}


def empresa_ativa(request):
    empresa = obter_empresa_ativa()
    return {
        'empresa_ativa': empresa,
        'empresa_nome_exibicao': NOME_EXIBICAO_POR_EMPRESA[empresa],
        'empresa_classe_css': CLASSE_CSS_POR_EMPRESA[empresa],
    }