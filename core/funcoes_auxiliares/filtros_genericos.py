# core/funcoes_auxiliares/filtros_genericos.py

# Função Objetivo: Aplica filtro de faixa (mín/máx) a qualquer campo numérico ou de data.
# Explicação em detalhe: promovida de produtos/funcoes_auxiliares/filtros_produtos.py (24/07)
# — nasceu específica de Produto, mas é genuinamente neutra (funciona com qualquer caminho
# de campo, inclusive relações tipo "andamento_agenda__ocorrencia_atual"). Promovida pra core
# só agora, no 2º uso real (agenda_videos), seguindo a regra do projeto de nunca generalizar
# de 1 caso só.

def aplicar_filtro_faixa(qs, filtros_faixa, campo):
    """Filtro genérico de mín/máx — funciona igual pra número e data,
    porque __gte/__lte do Django não diferenciam tipo."""
    minimo = filtros_faixa.get(f'{campo}_min')
    maximo = filtros_faixa.get(f'{campo}_max')

    if minimo:
        qs = qs.filter(**{f'{campo}__gte': minimo})
    if maximo:
        qs = qs.filter(**{f'{campo}__lte': maximo})

    return qs