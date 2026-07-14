# * [RESUMO] → Comando de importação de dados reais e variáveis do sistema.
#              Diferente de iniciar_banco (seed fixo), este importa dado
#              que muda com o tempo — vem de arquivos gerados pela API.
#              Cresce incrementalmente, mesma filosofia do iniciar_banco:
#              cada import vive em popular_banco_suporte/, agrupado por
#              ser exclusivo deste comando.

import time
from pathlib import Path
from django.core.management.base import BaseCommand
from core.management.commands.popular_banco_suporte.importar_produtos_ml import importar_produtos_ml
from core.management.commands.popular_banco_suporte.importar_produtos_erp_completo import importar_produtos_erp_completo
from core.management.commands.popular_banco_suporte.importar_anuncios_ml import importar_anuncios_ml
from core.management.commands.popular_banco_suporte.importar_qualidade_anuncio import importar_qualidade_anuncio
from core.management.commands.popular_banco_suporte.importar_competicao_catalogo import importar_competicao_catalogo
from core.management.commands.popular_banco_suporte.importar_tabela_frete_ml import importar_tabela_frete_ml
from core.management.commands.popular_banco_suporte.importar_planilha_precificacao import importar_planilha_precificacao
from core.management.commands.popular_banco_suporte.importar_promocoes_ml import importar_promocoes_ml
from core.management.commands.popular_banco_suporte.calcular_recomendacoes_precificacao import calcular_recomendacoes_precificacao
from precificacao.funcoes_auxiliares.mercado_livre.calcular_grade_precificacao_ml import calcular_grade_precificacao_ml
CAMINHO_DETALHES_MLBS = Path('Arquivos_API/detalhes_mlbs.json')
CAMINHO_QUALIDADE = Path('Arquivos_API/dados_completos_por_sku.json')



class Command(BaseCommand):
    help = 'Popula o banco com dados reais vindos da API (via arquivos)'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando importação de dados reais...\n')

        etapas = [
            ('PRODUTOS ML', importar_produtos_ml, (CAMINHO_DETALHES_MLBS,)),
            ('PRODUTOS ERP COMPLETO', importar_produtos_erp_completo, ()),
            ('ANUNCIOS ML', importar_anuncios_ml, (CAMINHO_DETALHES_MLBS,)),
            ('QUALIDADE', importar_qualidade_anuncio, (CAMINHO_QUALIDADE,)),
            ('COMPETICAO', importar_competicao_catalogo, (CAMINHO_QUALIDADE,)),
            ('FRETE ML', importar_tabela_frete_ml, ()),
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
            ('PROMOÇÕES ML', importar_promocoes_ml, ()),
            ('RECOMENDAÇÃO PRECIFICAÇÃO', calcular_recomendacoes_precificacao, ()),
        ]

        for nome, funcao, argumentos in etapas:
            inicio = time.time()
            funcao(self.stdout, self.style, *argumentos)
            duracao = time.time() - inicio
            self.stdout.write(self.style.WARNING(f'  ⏱ {nome}: {duracao:.1f}s\n'))

        self.stdout.write(self.style.SUCCESS('Importação concluída!'))

