# precificacao/funcoes_auxiliares/exportacao/config_marketplaces_exportaveis.py

# Função Objetivo: Registro central — cada marketplace exportável, seu model de Grade,
# e os "tipos" internos (se tiver). Existe separado do MARKETPLACES_RESUMO (que serve o
# Resumo, com um propósito diferente: 1 linha por combinação marketplace+tipo) — aqui
# o usuário escolhe 1 marketplace E DEPOIS 1 tipo (se existir), não vê os 2 juntos.

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TipoExportavel:
    chave: str
    label: str


@dataclass(frozen=True)
class MarketplaceExportavel:
    chave: str
    label: str
    model: type
    campo_tipo: str | None = None  # nome do campo no model ('tipo_anuncio', 'tipo', ou None)
    tipos: list = field(default_factory=list)  # lista de TipoExportavel, vazia = sem tipo
    filtro_extra: dict = field(default_factory=dict)  # filtro fixo, além de margem/tipo


def montar_marketplaces_exportaveis():
    from precificacao.models import (
        GradePrecificacaoML, GradePrecificacaoMagalu, GradePrecificacaoRaia,
        GradePrecificacaoShopee, GradePrecificacaoTiktok, GradePrecificacaoAmazon,
    )
    return [
        MarketplaceExportavel(
            chave='mercado_livre', label='Mercado Livre', model=GradePrecificacaoML,
            campo_tipo='tipo_anuncio',
            tipos=[TipoExportavel('classico', 'Clássico'), TipoExportavel('premium', 'Premium')],
            filtro_extra={'variacao__isnull': True},
        ),
        MarketplaceExportavel(chave='magalu', label='Magalu', model=GradePrecificacaoMagalu),
        MarketplaceExportavel(chave='raia', label='Raia', model=GradePrecificacaoRaia),
        MarketplaceExportavel(chave='shopee', label='Shopee', model=GradePrecificacaoShopee),
        MarketplaceExportavel(
            chave='tiktok', label='TikTok Shop', model=GradePrecificacaoTiktok, campo_tipo='tipo',
            tipos=[TipoExportavel('sem_afiliado', 'Sem Afiliado'), TipoExportavel('com_afiliado', 'Com Afiliado')],
        ),
        MarketplaceExportavel(
            chave='amazon', label='Amazon', model=GradePrecificacaoAmazon, campo_tipo='tipo',
            tipos=[TipoExportavel('dba', 'DBA'), TipoExportavel('fba', 'FBA')],
        ),
    ]


MARKETPLACES_EXPORTAVEIS = montar_marketplaces_exportaveis()
MARKETPLACES_EXPORTAVEIS_POR_CHAVE = {m.chave: m for m in MARKETPLACES_EXPORTAVEIS}