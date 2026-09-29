"""
scripts_exploracao_ML/ativar_pool_conexao.py

Patch de runtime, isolado, que troca a função de transporte HTTP usada por
chamar_api() (requests.request() solto, sem reuso de conexão) por uma
requests.Session() persistente com pool de conexões (HTTPAdapter).

NÃO altera nenhum arquivo do projeto real -- o patch existe só dentro do
processo Python deste script de teste, e é revertido automaticamente
(restaurar_original()) se chamado.

Muda 1 variável só: se a chamada HTTP abre conexão TCP+TLS nova a cada vez
(comportamento atual) ou reaproveita uma conexão já aberta do pool.
Retry/backoff/exceções/log dentro de chamar_api() continuam 100% originais,
porque o patch age só na função requests.request() que chamar_api() já
usa por baixo -- chamar_api() não sabe que foi trocado.

Uso: importar este módulo ANTES de rodar o teste de paralelismo.
    import ativar_pool_conexao
    ativar_pool_conexao.instalar(pool_size=50)
    # ... roda o teste normalmente (chamar_api segue sendo chamado igual) ...
    ativar_pool_conexao.restaurar_original()
"""

import requests

_original_request = None


def instalar(pool_size: int = 50):
    """Instala o patch: toda chamada requests.request(...) (inclusive as
    feitas por dentro de chamar_api()) passa a usar uma Session persistente
    com pool, em vez de criar uma conexão nova por chamada."""
    global _original_request

    if _original_request is not None:
        raise RuntimeError("Patch já instalado -- chame restaurar_original() antes de instalar de novo.")

    _original_request = requests.request

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=10,   # nº de hosts distintos cacheados (só 1 host aqui, sobra margem)
        pool_maxsize=pool_size,  # conexões simultâneas mantidas no pool -- cobre o maior nível de thread testado
        max_retries=0,          # retry já é feito dentro de chamar_api() -- não duplicar aqui
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    def request_com_pool(metodo, url, **kwargs):
        return session.request(metodo, url, **kwargs)

    requests.request = request_com_pool
    print(f">>> Patch instalado: Session com pool (pool_maxsize={pool_size})")


def restaurar_original():
    """Desfaz o patch -- volta requests.request() ao original."""
    global _original_request
    if _original_request is None:
        return
    requests.request = _original_request
    _original_request = None
    print(">>> Patch removido: requests.request() voltou ao original")