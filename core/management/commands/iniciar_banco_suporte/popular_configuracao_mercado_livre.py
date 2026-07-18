# * [RESUMO] → Seed inicial da configuração de precificação do Mercado
#              Livre — só o que é regra de negócio EXCLUSIVA do ML: 2
#              tipos de anúncio (Clássico/Premium), comissão e margens.
#              fator_coleta/faixas de armazenagem migraram pra
#              popular_configuracao_operacional.py (17/07) — são custo
#              físico compartilhado, não config do ML. Usa get_or_create
#              — seguro rodar mais de uma vez, nunca duplica.

from decimal import Decimal
from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio


def popular_configuracao_mercado_livre(stdout, style):
    stdout.write('  [CONFIG ML] Tipos de anúncio...')
    tipos = [
        ('Clássico', TipoAnuncio.CLASSICO, 12),
        ('Premium',  TipoAnuncio.PREMIUM,  17),
    ]

    for nome, tipo_anuncio, comissao in tipos:
        _, criado = ConfiguracaoTipoAnuncioMercadoLivre.objects.get_or_create(
            tipo_anuncio=tipo_anuncio,
            defaults={
                'comissao': Decimal(str(comissao)),
                'margem_padrao': Decimal('15'),
                'margem_minima': Decimal('10'),
                'margem_maxima': Decimal('20'),
                'margem_competicao': Decimal('5'),
            }
        )
        stdout.write(f'       {nome}: {"criado" if criado else "já existe"}')