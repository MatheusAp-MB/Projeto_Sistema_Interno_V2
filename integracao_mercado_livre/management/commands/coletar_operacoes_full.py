# integracao_mercado_livre/management/commands/coletar_operacoes_full.py
# ============================================================================================================================
# AVISO — ENDPOINT DE OPERAÇÕES DO FULL ABANDONADO PARA O HISTÓRICO DE VENDAS (decisão do Matheus, 10/10/2026, 20:04)
# ============================================================================================================================
# Este código usa GET /stock/fulfillment/operations/search. Ele FUNCIONA (90 dias de 1 SKU = 3 Códigos ML foram coletados),
# mas foi ABANDONADO: o endpoint é instável e a necessidade é rodar para MAIS DE MIL SKUs. NÃO APAGUE — guarda o que foi
# aprendido. Notas completas no vault: 05_Integracao_Mercado_Livre/Historico_de_Vendas/ (descoberta, decisão, dúvida, checkpoint).
#
# PROBLEMAS OBSERVADOS (10/10/2026, dado real, conta Magazine, 1 SKU = 3 Códigos ML):
#  1) 429 FREQUENTE: 8 de 25 chamadas na sondagem (18:33-18:38) e 34 de 51 tentativas nas 3 rodadas reais do coletor (19:43-19:46).
#     Corpo: {"message": "Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota", "error": "over_quota"}
#     NÃO é o texto "requests por minuto" da doc: cita uma entidade interna; o ESCOPO da cota é DESCONHECIDO (app, vendedor, global?).
#  2) SEM PISTA DE QUANDO TENTAR DE NOVO: nenhuma resposta traz Retry-After nem cabeçalho de limite.
#  3) PESO E ESPAÇAMENTO NÃO MUDAM A TAXA: chamada leve (1 Código, limit=1) 3/8 x pesada (3 Códigos, limit=1000) 2/8 com 429;
#     esperar 15 s entre as chamadas ainda deu 5 de 16 primeiras páginas com 429. Os 429 vêm em rajadas e a taxa variou no tempo
#     (32% às 18:33 x 67% às 19:43) — a causa é desconhecida.
#  4) SCROLL FRÁGIL: repetir o MESMO scroll depois de um 429 costuma virar 404 {"message": "Operation not found"} (2 de 2 nas
#     rodadas reais; 1 de 3 passou na sondagem). O coletor recomeça a janela e descarta as linhas repetidas (2000 na rodada de 90 dias).
#  5) Chamadas SEM scroll: 13 de 15 terminaram em 200 nas rodadas reais; 1 esgotou as 5 tentativas com 429 e 1 foi interrompida.
#  6) 120 e 150 dias NÃO foram testados (Ctrl+C durante a espera de 60 s, antes da parte antiga): só 90 dias foram validados.
#  7) A profundidade do histórico NÃO é a causa: o 429 apareceu também na janela dos 7 dias mais recentes (11 de 14 tentativas).
#
# NUNCA TESTADO: máximo de Códigos ML por chamada; omitir "type" (1 chamada em vez de 4 por janela); dividir a janela por data até
# caber em 1000 operações (sem scroll); se o horário muda a taxa. Não há contato com o Mercado Livre por ora.
#
# CAMINHO NOVO: GET /orders/search (ver o checkpoint 'Checkpoint - Historico de Vendas e Calendario de Vendas' no vault).
# Textos mais abaixo que dizem que o limite é "por minuto" ou que o 429 "passa depois de esperar" foram escritos ANTES desses
# testes: valem os fatos deste aviso.
#
# ESCOPO: este comando continua funcionando (validado com --dias 90), mas NÃO deve ser a base para rodar mais de mil SKUs.
# ============================================================================================================================
#
# Função Objetivo: Gatilho MANUAL da coleta das operações do Full (vendas, cancelamentos, não entregues e devoluções) de 1 produto:
# pega os Códigos ML do SKU no banco, busca as operações no Mercado Livre e grava em OperacaoFullMercadoLivre. Quem decide rodar é
# sempre uma pessoa (este comando ou, depois, o botão da tela) — nunca uma tela aberta ou rotina agendada.
#
# Exemplo:  poetry run python manage.py coletar_operacoes_full --empresa magazine --produto F7908050719121.001
#           poetry run python manage.py coletar_operacoes_full --empresa magazine --produto F7908050719121.001 --dias 120
#
# * [EXPLICAÇÃO] → A 1ª vez de cada Código busca os últimos 90 dias (ou o que o --dias pedir, de 1 a 360); as seguintes buscam a parte
#                  nova, do ponto onde a cobertura parou (menos a margem de segurança). Com um --dias MAIOR que o histórico que o Código
#                  já tem, busca também só a parte mais antiga que falta (rodou com 90; rodar com 120 busca só os 30 dias a mais).
#                  A cobertura avança janela por janela: se der falha no meio, o que já terminou bem fica valendo e
#                  a próxima rodada continua dali. Rodar de novo é seguro: operação que já está no banco (mesmo id) é ignorada.
#                  Quando o Mercado Livre recusa por excesso de chamadas (429), o coletor espera e repete (ver o serviço); o resumo
#                  mostra quantas esperas foram.

from datetime import timedelta

from django.core.management.base import CommandError

from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
from core.management.commands._base_empresa import ComandoComEmpresa
from gestao_full.funcoes_auxiliares.full_estoque_ml import codigos_ml_do_produto
from integracao_mercado_livre.servicos.coletar_operacoes_full_ml import (
    ESPERA_APOS_429_S, MAX_ESPERAS_429_POR_CHAMADA, ErroColetaOperacoes, coletar_operacoes,
)
from mercado_livre.models import CoberturaOperacaoFullMercadoLivre


def _data_br(valor):
    return valor.strftime('%d/%m/%Y') if valor else '-'


def _tempo(segundos):
    if segundos < 60:
        return f'{segundos:.1f}s'
    minutos, resto = divmod(int(round(segundos)), 60)
    return f'{minutos}min {resto:02d}s'


class Command(ComandoComEmpresa):
    help = (
        'Coleta no Mercado Livre as operações do Full (vendas, cancelamentos, não entregues e devoluções) de TODOS os Códigos ML '
        'de 1 produto (--produto <sku>) e grava em OperacaoFullMercadoLivre. Cada Código continua de onde a última coleta parou; '
        'a 1ª vez busca os últimos 90 dias (--dias muda; com um --dias maior, busca só a parte mais antiga que falta). '
        'Faz chamadas reais (GET) à API. '
        'Roda 1 empresa por vez (--empresa=magazine ou --empresa=samvale, obrigatório).'
    )

    def adicionar_argumentos(self, parser):
        parser.add_argument(
            '--produto',
            type=str,
            required=True,
            help='SKU do produto (ex.: F7908050719121.001) — coleta todos os Códigos ML dele que estão no banco.',
        )
        parser.add_argument(
            '--dias',
            type=int,
            default=None,
            help=(
                f'Quantos dias de histórico ter (de 1 a {CoberturaOperacaoFullMercadoLivre.RETENCAO_ML_DIAS}). Sem esta opção usa '
                f'{CoberturaOperacaoFullMercadoLivre.DIAS_PRIMEIRA_CARGA}. Se o Código já tem histórico, busca só a parte mais antiga que falta.'
            ),
        )

    def _avisar(self, texto):
        self.stdout.write(f'  > {texto}')
        self.stdout.flush()

    def handle(self, *args, **options):
        sku = (options['produto'] or '').strip()
        codigos = codigos_ml_do_produto(sku)
        if not codigos:
            raise CommandError(f'O produto {sku} não tem nenhum Código ML (inventory_id) no banco da empresa {options["empresa"]}.')

        self.stdout.write(f'\nColetando operações do Full — {self.empresa_ativa} — produto {sku}')
        self.stdout.write(f'Códigos ML ({len(codigos)}): {", ".join(codigos)}')
        dias_pedidos = options['dias']
        if dias_pedidos is None:
            self.stdout.write(f'Histórico: {CoberturaOperacaoFullMercadoLivre.DIAS_PRIMEIRA_CARGA} dias (padrão; use --dias para mudar)')
        else:
            self.stdout.write(f'Histórico: {dias_pedidos} dias (--dias)')
        self.stdout.write('Isto faz chamadas reais (GET) à API do Mercado Livre e pode levar vários minutos.')
        self.stdout.write(
            f'Se o ML recusar por excesso de chamadas (429), o coletor espera {ESPERA_APOS_429_S:.0f}s e repete a mesma chamada '
            f'(até {MAX_ESPERAS_429_POR_CHAMADA} vezes por chamada). Cada janela concluída já fica salva.\n'
        )

        try:
            relatorio = coletar_operacoes(self.empresa_ativa, codigos, avisar=self._avisar, dias_de_historico=dias_pedidos)
        except ErroAutenticacaoAPI as erro:
            raise CommandError(f'Acesso recusado pelo Mercado Livre: {erro}. O que já tinha sido concluído antes ficou gravado.')
        except ErroColetaOperacoes as erro:
            raise CommandError(str(erro))

        self.stdout.write('\n--- Resumo da coleta ---')
        self.stdout.write(f'Tempo total: {_tempo(relatorio.segundos_total)} | Janelas concluídas: {relatorio.janelas_concluidas}')
        pedido_desde = relatorio.hoje_utc - timedelta(days=relatorio.dias_de_historico)
        self.stdout.write(f'Histórico pedido: {relatorio.dias_de_historico} dias (de {_data_br(pedido_desde)} até hoje, datas UTC)')
        self.stdout.write(f'Chamadas à API: {relatorio.chamadas} ({_tempo(relatorio.segundos)} dentro das chamadas, contando as esperas internas do cliente por 429)')
        self.stdout.write(f'Esperas por 429 do coletor: {relatorio.esperas_por_429} ({_tempo(relatorio.segundos_de_espera_429)})')
        self.stdout.write(f'Linhas recebidas: {relatorio.linhas_recebidas}')
        self.stdout.write(f'Gravadas novas: {relatorio.gravadas_novas} | Já existiam: {relatorio.ja_existiam}')
        self.stdout.write(f'Repetidas descartadas (recomeço por scroll 404): {relatorio.repetidas_descartadas}')
        self.stdout.write(f'Recomeços por scroll 404: {relatorio.reinicios_por_scroll_404}')
        if relatorio.descartadas:
            motivos = ', '.join(f'{motivo}={quantas}' for motivo, quantas in sorted(relatorio.descartadas.items()))
            self.stdout.write(f'Descartadas na limpeza: {motivos}')
        else:
            self.stdout.write('Descartadas na limpeza: nenhuma')

        self.stdout.write('\nCobertura por Código ML (datas UTC, fim exclusivo):')
        for codigo in relatorio.codigos:
            if codigo in relatorio.coberturas:
                inicial, final = relatorio.coberturas[codigo]
                parou = ' — parou por falha' if codigo in relatorio.codigos_com_falha else ''
                profundidade = f', {(relatorio.hoje_utc - inicial).days} dias de histórico' if inicial else ''
                self.stdout.write(f'  {codigo}: {_data_br(inicial)} até {_data_br(final)} (exclusivo){profundidade}{parou}')
            else:
                self.stdout.write(f'  {codigo}: não avançou nesta coleta')

        if relatorio.puladas:
            self.stdout.write(self.style.WARNING(
                f'\nPulados (já estavam sendo coletados em outro lugar): {", ".join(relatorio.puladas)}'
            ))
        if relatorio.falhas:
            self.stdout.write(self.style.ERROR('\nFalhas (a cobertura não passou da última janela concluída):'))
            for falha in relatorio.falhas:
                self.stdout.write(self.style.ERROR(f'  {falha}'))
        elif not relatorio.puladas:
            self.stdout.write(self.style.SUCCESS('\nColeta concluída sem falhas.'))
