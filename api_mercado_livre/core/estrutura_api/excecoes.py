# api_mercado_livre/core/estrutura_api/excecoes.py

# Função Objetivo: Hierarquia de exceção da API do Mercado Livre — movida
# pra cá de dentro de cliente_api.py (Peça 1 da reforma estrutural do app
# integracao_mercado_livre, ver vault "Modelagem de Objeto e Encapsulamento"
# / "Padrão de Robustez para Clientes de API Externa"). Puramente
# estrutural: as 2 classes abaixo são idênticas às que existiam antes
# (mesmo nome, mesma herança direta de Exception, mesmo texto, mesma
# condição de disparo) — só mudaram de arquivo. Nenhuma subclasse nova
# nesta peça; categorização mais fina de erro (rede/servidor/negócio, no
# padrão que já existe em api_sysemp/core/excecoes.py) fica pra uma peça
# futura, decidida à parte.


class ErroAPI(Exception):
    """Erro genérico após esgotar tentativas ou erro não recuperável."""
    pass


class ErroAutenticacaoAPI(Exception):
    """401 mesmo com token considerado válido. Caso grave e distinto — não tenta de novo sozinho."""
    pass