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

import time
from pathlib import Path
from datetime import datetime
from django.core.management.base import BaseCommand, OutputWrapper

from rich import print
from core.funcoes_auxiliares.saida_dupla import SaidaDupla
from core.management.commands.popular_banco_suporte.importar_produtos_erp import importar_produtos_erp
from core.management.commands.popular_banco_suporte.importar_anuncios_ml import importar_anuncios_ml
from core.management.commands.popular_banco_suporte.importar_dimensoes_declaradas_ml import importar_dimensoes_declaradas_ml
from core.management.commands.popular_banco_suporte.importar_qualidade_anuncio import importar_qualidade_anuncio
from core.management.commands.popular_banco_suporte.importar_competicao_catalogo import importar_competicao_catalogo
from core.management.commands.popular_banco_suporte.importar_tabela_frete_ml import importar_tabela_frete_ml
from core.management.commands.popular_banco_suporte.importar_tabela_frete_magalu import importar_tabela_frete_magalu
from core.management.commands.popular_banco_suporte.importar_planilha_precificacao import importar_planilha_precificacao
from core.management.commands.popular_banco_suporte.importar_promocoes_ml import importar_promocoes_ml
from core.management.commands.popular_banco_suporte.calcular_recomendacoes_precificacao import calcular_recomendacoes_precificacao
from precificacao.funcoes_auxiliares.mercado_livre.calcular_grade_precificacao_ml import calcular_grade_precificacao_ml
from precificacao.funcoes_auxiliares.magalu.calcular_grade_precificacao_magalu import calcular_grade_precificacao_magalu

CAMINHO_DETALHES_MLBS = Path('Arquivos_API/detalhes_mlbs.json')
CAMINHO_QUALIDADE = Path('Arquivos_API/dados_completos_por_sku.json')


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
            ('PRODUTOS ERP', importar_produtos_erp, (CAMINHO_DETALHES_MLBS,)),
            ('ANUNCIOS ML', importar_anuncios_ml, (CAMINHO_DETALHES_MLBS,)),
            ('DIMENSÕES DECLARADAS ML', importar_dimensoes_declaradas_ml, (CAMINHO_DETALHES_MLBS,)),
            ('QUALIDADE', importar_qualidade_anuncio, (CAMINHO_QUALIDADE,)),
            ('COMPETICAO', importar_competicao_catalogo, (CAMINHO_QUALIDADE,)),
            ('FRETE ML', importar_tabela_frete_ml, ()),
            ('FRETE MAGALU', importar_tabela_frete_magalu, ()),
            # * [EXPLICAÇÃO] → Roda por ÚLTIMO de propósito — precisa
            #                  "vencer" a disputa de campos compartilhados
            #                  com PRODUTOS ERP COMPLETO (custo, fiscais,
            #                  dimensões). Essa é a fonte validada
            #                  especificamente para precificação.
            ('PRECIFICAÇÃO — PLANILHA VALIDADA', importar_planilha_precificacao, ()),
            # * [EXPLICAÇÃO] → Roda logo depois da Planilha Validada —
            #                  precisa de Produto com custo/dimensões/
            #                  peso_cubado já corretos (a fonte validada
            #                  acabou de rodar). Não depende de
            #                  Promoções nem de Qualidade/Competição —
            #                  poderia rodar em qualquer ponto depois
            #                  daqui, mas fica agrupada perto do resto
            #                  de precificação por clareza.
            ('GRADE DE PRECIFICAÇÃO ML', calcular_grade_precificacao_ml, ()),
            ('GRADE MAGALU', calcular_grade_precificacao_magalu, ()),
            ('PROMOÇÕES ML', importar_promocoes_ml, ()),
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