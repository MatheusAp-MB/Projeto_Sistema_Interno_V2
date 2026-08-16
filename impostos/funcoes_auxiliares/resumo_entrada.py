# impostos/funcoes_auxiliares/resumo_entrada.py

# Função Objetivo: Busca e lista os produtos com impostos de entrada (XML/
# Sysemp) já sincronizados, prontos pra tela de Resumo de Impostos de
# Entrada — mesma query usada pela tela (paginada) e pela exportação (sem
# paginação), pra nunca divergir o que aparece na tela do que sai no Excel.

from django.db.models import Q

from produtos.models import Produto


def ler_busca_resumo_entrada(request) -> str:
    return request.GET.get('busca', '').strip()


# Função Objetivo: Devolve o queryset de produtos com impostos de entrada
# sincronizados, com os relacionamentos de imposto já carregados via
# select_related (evita 1 query por imposto por produto), opcionalmente
# filtrado por produto/EAN/fornecedor.
def listar_produtos_resumo_entrada_filtrados(busca: str = None):
    produtos = (
        Produto.objects
        .filter(impostos_entrada__isnull=False)
        .select_related(
            'impostos_entrada', 'impostos_entrada__icms', 'impostos_entrada__icms_st',
            'impostos_entrada__icms_ret', 'impostos_entrada__ipi', 'impostos_entrada__pis',
            'impostos_entrada__cofins',
        )
        .order_by('titulo')
    )
    if busca:
        produtos = produtos.filter(
            Q(titulo__icontains=busca)
            | Q(ean__icontains=busca)
            | Q(impostos_entrada__fornecedor__icontains=busca)
        )
    return produtos