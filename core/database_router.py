# core/database_router.py
from core.empresa import obter_alias_banco_ativo

# Apps de infraestrutura do próprio Django — NUNCA divididos por empresa.
# A sessão é o próprio mecanismo que decide qual empresa está ativa, então
# ela não pode estar sujeita a essa mesma decisão (era exatamente isso que
# causava o F5 voltar pra Magazine: sessão gravada num banco, lida de outro).
APPS_SEMPRE_COMPARTILHADOS = {'sessions', 'admin', 'contenttypes', 'auth'}


class EmpresaRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label in APPS_SEMPRE_COMPARTILHADOS:
            return None
        return obter_alias_banco_ativo()

    def db_for_write(self, model, **hints):
        if model._meta.app_label in APPS_SEMPRE_COMPARTILHADOS:
            return None
        return obter_alias_banco_ativo()

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True