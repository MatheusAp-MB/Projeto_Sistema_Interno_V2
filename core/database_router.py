# core/database_router.py

# * [RESUMO] → Decide, pra cada consulta ao banco, se ela vai pra
#              'magazine' ou 'samvale' — lendo a empresa que o
#              EmpresaMiddleware já descobriu pra esta requisição.
#              allow_migrate sempre True: as 2 empresas têm o MESMO
#              schema completo, nunca dividimos apps entre bancos.

from core.empresa import obter_alias_banco_ativo


class EmpresaRouter:
    def db_for_read(self, model, **hints):
        return obter_alias_banco_ativo()

    def db_for_write(self, model, **hints):
        return obter_alias_banco_ativo()

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True