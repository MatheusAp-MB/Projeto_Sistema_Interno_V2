# * [RESUMO] → Comando de importação de dados reais e variáveis do sistema.
#              Diferente de iniciar_banco (seed fixo), este importa dado
#              que muda com o tempo — vem de arquivos gerados pela API.
#              Cresce incrementalmente, mesma filosofia do iniciar_banco:
#              cada import vive em popular_banco_suporte/, agrupado por
#              ser exclusivo deste comando.
#
#              Log em arquivo (17/07): tudo que vai pro console também é
#              espelhado em logs/popular_banco_<timestamp>.log, via
#              SaidaDupla — o log ficou grande demais só no terminal.
#
#              Etapas do Mercado Livre desativadas (15/08): os 3 arquivos
#              JSON de que elas dependiam deixaram de ser lidos por este
#              comando — a origem desse dado (API do ML) ainda está sendo
#              integrada de forma organizada, com comando próprio, em vez
#              de arquivo solto. Etapas mantidas comentadas (não apagadas),
#              voltam quando esse comando novo existir.

import time
from pathlib import Path
from datetime import datetime
from django.core.management.base import BaseCommand, OutputWrapper

from rich import print
from core.funcoes_auxiliares.saida_dupla import SaidaDupla
from core.management.commands.popular_banco_suporte.importar_produtos_erp import importar_produtos_erp
from core.management.commands.popular_banco_suporte.sincronizar_indicadores_agenda_em_lote import sincronizar_indicadores_agenda_em_lote
# * [EXPLICAÇÃO] → Desativadas (15/08) — dependiam de detalhes_mlbs.json,
#                  que deixou de ser lido por este comando. Ver explicação
#                  no topo do arquivo.
# from core.management.commands.popular_banco_suporte.importar_anuncios_ml import importar_anuncios_ml
# from core.management.commands.popular_banco_suporte.importar_dimensoes_declaradas_ml import importar_dimensoes_declaradas_ml
# * [EXPLICAÇÃO] → Desativadas (15/08) — dependiam de dados_completos_por_sku.json,
#                  mesmo motivo acima.
# from core.management.commands.popular_banco_suporte.importar_qualidade_anuncio import importar_qualidade_anuncio
# from core.management.commands.popular_banco_suporte.importar_competicao_catalogo import importar_competicao_catalogo
from core.management.commands.popular_banco_suporte.importar_tabela_frete_ml import importar_tabela_frete_ml
from core.management.commands.popular_banco_suporte.importar_tabela_frete_magalu import importar_tabela_frete_magalu
from core.management.commands.popular_banco_suporte.importar_tabela_frete_tiktok import importar_tabela_frete_tiktok
from core.management.commands.popular_banco_suporte.importar_tabela_frete_amazon import importar_tabela_frete_amazon
from core.management.commands.popular_banco_suporte.organizar_e_verificar_divergencias_dimensoes_envio import organizar_e_verificar_divergencias_dimensoes_envio
# * [EXPLICAÇÃO] → Desativada (15/08) — dependia de promocoes_completo.json,
#                  mesmo motivo das outras etapas do ML acima.
# from core.management.commands.popular_banco_suporte.importar_promocoes_ml import importar_promocoes_ml
from core.management.commands.popular_banco_suporte.calcular_recomendacoes_precificacao import calcular_recomendacoes_precificacao
from precificacao.funcoes_auxiliares.mercado_livre.calcular_grade_precificacao_ml import calcular_grade_precificacao_ml
from precificacao.funcoes_auxiliares.magalu.calcular_grade_precificacao_magalu import calcular_grade_precificacao_magalu
from precificacao.funcoes_auxiliares.raia.calcular_grade_precificacao_raia import calcular_grade_precificacao_raia
from precificacao.funcoes_auxiliares.shopee.calcular_grade_precificacao_shopee import calcular_grade_precificacao_shopee
from precificacao.funcoes_auxiliares.tiktok.calcular_grade_precificacao_tiktok import calcular_grade_precificacao_tiktok
from precificacao.funcoes_auxiliares.amazon.calcular_grade_precificacao_amazon import calcular_grade_precificacao_amazon


class Command(BaseCommand):
    help = 'Popula o banco com dados reais vindos da API (via arquivos)'

    def handle(self, *args, **options):
        inicio_geral = time.time()

        pasta_logs = Path('logs')
        pasta_logs.mkdir(exist_ok=True)
        caminho_log = pasta_logs / f'popular_banco_{datetime.now():%Y%m%d_%H%M%S}.log'

        with open(caminho_log, 'w', encoding='utf-8') as arquivo_log:
            self.stdout = OutputWrapper(SaidaDupla(arquivo_log))
            self._executar(inicio_geral)

        print(f'\n[dim]Log completo salvo em: {caminho_log}[/dim]')

    def _executar(self, inicio_geral):
        self.stdout.write('Iniciando importação de dados reais...\n')

        etapas = [
            ('PRODUTOS ERP', importar_produtos_erp, ()),
            # * [EXPLICAÇÃO] → Desativadas (15/08) — ver explicação no topo do arquivo.
            # ('ANUNCIOS ML', importar_anuncios_ml, (CAMINHO_DETALHES_MLBS,)),
            ('INDICADORES AGENDA', sincronizar_indicadores_agenda_em_lote, ()),
            # ('DIMENSÕES DECLARADAS ML', importar_dimensoes_declaradas_ml, (CAMINHO_DETALHES_MLBS,)),
            # ('QUALIDADE', importar_qualidade_anuncio, (CAMINHO_QUALIDADE,)),
            # ('COMPETICAO', importar_competicao_catalogo, (CAMINHO_QUALIDADE,)),
            ('FRETE ML', importar_tabela_frete_ml, ()),
            ('FRETE MAGALU', importar_tabela_frete_magalu, ()),
            ('FRETE TIKTOK', importar_tabela_frete_tiktok, ()),
            ('FRETE AMAZON', importar_tabela_frete_amazon, ()),
            # * [EXPLICAÇÃO] → Roda logo depois de DIMENSÕES DECLARADAS ML —
            #                  precisa dos 2 lados (Produto + Variação) já
            #                  importados pra organizar/comparar. Roda ANTES de
            #                  qualquer GRADE, porque as 5 fórmulas de marketplace
            #                  (via resolver_dimensao_produto) e a Grade ML (via
            #                  resolver_dimensoes_efetivas) agora dependem dos
            #                  campos "_ordenada_cm" calculados aqui.
            #                  Atenção (15/08): com DIMENSÕES DECLARADAS ML
            #                  desativada, esta etapa roda só com o lado Produto
            #                  — comportamento a confirmar quando a etapa do ML
            #                  voltar.
            ('DIMENSÃO DE ENVIO — ORGANIZAR E COMPARAR', organizar_e_verificar_divergencias_dimensoes_envio, ()),
            ('GRADE DE PRECIFICAÇÃO ML', calcular_grade_precificacao_ml, ()),
            ('GRADE MAGALU', calcular_grade_precificacao_magalu, ()),
            ('GRADE RAIA', calcular_grade_precificacao_raia, ()),
            ('GRADE SHOPEE', calcular_grade_precificacao_shopee, ()),
            ('GRADE TIKTOK', calcular_grade_precificacao_tiktok, ()),
            ('GRADE AMAZON', calcular_grade_precificacao_amazon, ()),
            # ('PROMOÇÕES ML', importar_promocoes_ml, ()),
            ('RECOMENDAÇÃO PRECIFICAÇÃO', calcular_recomendacoes_precificacao, ()),
        ]

        for nome, funcao, argumentos in etapas:
            inicio = time.time()
            funcao(self.stdout, self.style, *argumentos)
            duracao = time.time() - inicio
            self.stdout.write(self.style.WARNING(f'  ⏱ {nome}: {duracao:.1f}s\n'))

        self.stdout.write(self.style.SUCCESS('Importação concluída!'))

        final_geral = time.time()
        duracao_geral = final_geral - inicio_geral

        # * [EXPLICAÇÃO] → self.stdout.write, não print() direto — precisa
        #                  passar pela SaidaDupla pra essa linha (a mais
        #                  importante do resumo) também cair no arquivo
        #                  de log, não só aparecer no console.
        self.stdout.write(self.style.ERROR(f'  ⏱ Duração TOTAL GERAL: {duracao_geral:.1f}s\n'))