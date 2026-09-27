# core/management/commands/migrate.py

# Função Objetivo: Sobrescreve o comando `migrate` nativo do Django — só adiciona a
# exigência de --database explícito (ver _exigir_database_explicito.py), sem mudar
# mais nada do comando original. Funciona porque 'core' é o 1º app da lista em
# INSTALLED_APPS — o Django resolve comando com mesmo nome dando prioridade ao app
# listado primeiro.

from django.core.management.commands.migrate import Command as ComandoMigrateOriginal
from core.management.commands._exigir_database_explicito import ExigirDatabaseExplicito


class Command(ExigirDatabaseExplicito, ComandoMigrateOriginal):
    pass