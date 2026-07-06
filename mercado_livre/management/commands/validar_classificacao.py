#validar
from django.core.management.base import BaseCommand
from mercado_livre.funcoes_auxiliares.classificacao_catalogo import classificar_todos_os_skus


class Command(BaseCommand):
    help = 'Valida a classificação de catálogo (Simples/Base/Catálogo) para todos os SKUs'

    def handle(self, *args, **options):
        self.stdout.write('Classificando todos os SKUs...\n')

        resultado = classificar_todos_os_skus()

        total_skus       = len(resultado)
        total_paginas    = sum(len(r['paginas_catalogo']) for r in resultado.values())
        total_simples    = sum(len(r['anuncios_simples']) for r in resultado.values())
        total_orfaos     = sum(
            len(p['anuncios_catalogo_orfaos'])
            for r in resultado.values()
            for p in r['paginas_catalogo']
        )
        total_bases = sum(
            len(p['anuncios_base'])
            for r in resultado.values()
            for p in r['paginas_catalogo']
        )
        total_catalogo_ligados = sum(
            len(b['anuncios_catalogo'])
            for r in resultado.values()
            for p in r['paginas_catalogo']
            for b in p['anuncios_base']
        )
        total_catalogo = total_catalogo_ligados + total_orfaos
        skus_com_catalogo = sum(1 for r in resultado.values() if r['paginas_catalogo'])

        self.stdout.write(self.style.SUCCESS(
                    f'Concluído!\n'
                    f'    SKUs processados:          {total_skus}\n'
                    f'    SKUs com catálogo:          {skus_com_catalogo}\n'
                    f'    Páginas de catálogo:        {total_paginas}\n'
                    f'    Anúncios Base:              {total_bases}\n'
                    f'    Anúncios Catálogo (total):  {total_catalogo}\n'
                    f'      → ligados a uma Base:     {total_catalogo_ligados}\n'
                    f'      → órfãos (sem Base):      {total_orfaos}\n'
                    f'    Anúncios simples (total):   {total_simples}'
                ))