# core/management/commands/_exigir_database_explicito.py

# Função Objetivo: Mixin que torna a flag --database OBRIGATÓRIA em qualquer comando
# nativo do Django que já a declara com um valor padrão (normalmente 'default').
# Explicação em detalhe: decisão de Matheus (27/09/2026) — nenhum comando deste sistema
# pode mexer/ler banco sem que a pessoa tenha dito EXPLICITAMENTE qual banco é. Isso já
# valia pros comandos próprios (ComandoComEmpresa, --empresa obrigatório); esse mixin
# estende a MESMA regra pros comandos NATIVOS do Django que ainda usam --database — que
# tem um valor padrão silencioso pro banco 'default' (hoje uma cópia idêntica do banco
# da Magazine, sem avisar nada disso — foi assim que um `migrate` sem argumento nenhum
# migrou a Magazine sem erro nenhum).
#
# Uso: sobrescreve o comando nativo (mesmo nome de arquivo, dentro de
# core/management/commands/) herdando da classe original do Django + deste mixin,
# NESSA ORDEM (mixin primeiro — senão o MRO chama o add_arguments errado):
#
#   from django.core.management.commands.migrate import Command as ComandoMigrateOriginal
#   from core.management.commands._exigir_database_explicito import ExigirDatabaseExplicito
#
#   class Command(ExigirDatabaseExplicito, ComandoMigrateOriginal):
#       pass


class ExigirDatabaseExplicito:

    def add_arguments(self, parser):
        super().add_arguments(parser)

        # * [EXPLICAÇÃO] → Acha a ação --database que o comando original acabou de
        #                  registrar (na chamada super() acima, com valor padrão
        #                  'default') e torna ela OBRIGATÓRIA — sem isso, o comando
        #                  aceitava rodar sem --database e caía em silêncio pro banco
        #                  'default'.
        for action in parser._actions:
            if action.dest == 'database':
                action.default = None
                action.required = True
                break