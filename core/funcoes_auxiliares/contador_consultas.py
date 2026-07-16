# * [RESUMO] → Contador de consultas SQL SEM TETO — substitui
#              len(connection.queries_log), que trava em 9.000 por
#              padrão do Django (achado real: Recomendação de
#              Precificação bateu EXATAMENTE 9.000 em 2 rodadas
#              diferentes, escondendo o número real). Não guarda o
#              texto de nenhuma consulta (sem custo de memória) — só
#              incrementa um número a cada consulta real disparada.

from contextlib import contextmanager
from django.db import connection


@contextmanager
def contar_consultas():
    """Uso:
        with contar_consultas() as contador:
            ... código que consulta o banco ...
        stdout.write(f'Consultas: {contador["total"]}')
    """
    contador = {'total': 0}

    def wrapper(execute, sql, params, many, context):
        contador['total'] += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        yield contador