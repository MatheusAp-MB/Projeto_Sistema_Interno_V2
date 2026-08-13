# agenda_videos/management/commands/resetar_agenda_videos.py

# Função Objetivo: Zera o progresso de TODOS os produtos na Agenda de Vídeos
# — nenhum CicloVideo, sem histórico de status manual, sem cache de Drive —
# devolvendo cada um pro estado "nao_agendado" de verdade (zero cliques).
# NUNCA confundir com a tela "Não Agendado" (que é o oposto: Simples já
# replicado, só falta o clique de Agendar). Feito pra montar terreno de
# teste manual limpo antes de validar o roadmap — nunca rodar com dado real.

from django.core.management.base import BaseCommand
from django.db import transaction

from agenda_videos.models import (
    CicloVideo,
    ExecucaoPostagemAutomatica,
    ExecucaoReplicacaoAutomatica,
    HistoricoStatusManualAgenda,
    ParticipacaoAgenda,
    SnapshotArquivosDrive,
)
from core.management.commands.popular_banco_suporte.sincronizar_indicadores_agenda_em_lote import (
    sincronizar_indicadores_agenda_em_lote,
)

# * [EXPLICAÇÃO] → ExecucaoPostagemAutomatica/ExecucaoReplicacaoAutomatica
#                  arrastam ItemExecucaoPostagem/ItemExecucaoReplicacao
#                  sozinhos (FK com on_delete=CASCADE) — apagar só o pai já
#                  basta. Produto e ConfiguracaoFase NUNCA entram nesta
#                  lista: o 1º é o catálogo real (vem do ERP), o 2º é a
#                  régua de fases que o roadmap precisa pra sequer existir.
MODELOS_PARA_ZERAR = [
    CicloVideo,
    ParticipacaoAgenda,
    HistoricoStatusManualAgenda,
    SnapshotArquivosDrive,
    ExecucaoPostagemAutomatica,
    ExecucaoReplicacaoAutomatica,
]


class Command(BaseCommand):
    help = (
        'Zera o progresso de TODOS os produtos na Agenda de Vídeos (nenhum '
        'CicloVideo, sem histórico de status manual, sem cache de Drive) — '
        'monta terreno de teste manual limpo. Nunca usar com dado real.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--sem-confirmar',
            action='store_true',
            help='Pula a confirmação escrita no terminal (uso em script; nunca em terminal interativo).',
        )

    def handle(self, *args, **options):
        if not options['sem_confirmar']:
            resposta = input(
                'Isso vai apagar o progresso de TODOS os produtos na Agenda de '
                'Vídeos (irreversível). Digite CONFIRMAR pra continuar: '
            )
            if resposta.strip() != 'CONFIRMAR':
                self.stdout.write(self.style.WARNING('Cancelado — nada foi apagado.'))
                return

        # * [EXPLICAÇÃO] → Tudo numa transação só: se alguma exclusão falhar
        #                  no meio, nenhuma acontece — nunca deixa a Agenda
        #                  pela metade zerada.
        with transaction.atomic():
            contagens = {}
            for modelo in MODELOS_PARA_ZERAR:
                quantidade, _ = modelo.objects.all().delete()
                contagens[modelo.__name__] = quantidade

        self.stdout.write(self.style.SUCCESS('Progresso zerado:'))
        for nome, quantidade in contagens.items():
            # * [EXPLICAÇÃO] → Pra Execucao*Automatica, essa contagem já
            #                  inclui os Item* arrastados pelo CASCADE.
            self.stdout.write(f'    {nome}: {quantidade} registro(s) apagado(s)')

        self.stdout.write('Ressincronizando indicadores (todo produto volta a "nao_agendado")...')
        sincronizar_indicadores_agenda_em_lote(self.stdout, self.style)

        self.stdout.write(self.style.SUCCESS('Agenda de Vídeos zerada — pronta pra testes.'))