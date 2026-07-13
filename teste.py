"""
gerar_dados_apresentacao.py — Script de extração (SÓ LEITURA, não
altera nada no banco).

Roda de dentro da pasta raiz do projeto (onde fica o manage.py):
    python gerar_dados_apresentacao.py > dados_apresentacao.json

Objetivo: extrair (1) os totais reais por estado (os 7 estados) e
(2) 1 exemplo real de cada estado, com todos os campos que os cards
mostram — pra montar a apresentação em HTML com dados reais do seu
negócio, sem inventar números.

Copie a saída (o JSON impresso) e cole de volta na conversa.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

import json
from collections import Counter
from decimal import Decimal

from mercado_livre.models import VariacaoAnuncioMercadoLivre, RecomendacaoPrecificacao
from mercado_livre.funcoes_auxiliares.calculo_margem import buscar_configuracao_tipo_anuncio
from mercado_livre.funcoes_auxiliares.recomendacao_precificacao import montar_motivo


def num(valor):
    """Converte Decimal pra float (JSON não serializa Decimal direto)."""
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


Categoria = RecomendacaoPrecificacao.CategoriaEstado

variacoes = (
    VariacaoAnuncioMercadoLivre.objects
    .exclude(anuncio__eh_fossil_migracao=True)
    .select_related('anuncio', 'anuncio__tipo_de_anuncio', 'anuncio__competicao', 'produto')
    .prefetch_related('promocoes', 'recomendacoes')
)

contagem = Counter()
exemplos = {}
config_cache = {}

for v in variacoes:
    rec = next((r for r in v.recomendacoes.all() if r.comportamento == v.comportamento_ativo), None)
    if not rec or not rec.categoria_estado:
        continue

    contagem[rec.categoria_estado] += 1

    # * [EXPLICAÇÃO] → Guarda só o PRIMEIRO exemplo real encontrado de
    #                  cada estado — suficiente pra ilustrar, não
    #                  precisa de mais de 1 por categoria.
    if rec.categoria_estado in exemplos:
        continue

    anuncio = v.anuncio
    tipo_obj = anuncio.tipo_de_anuncio if anuncio else None

    if tipo_obj and tipo_obj.pk not in config_cache:
        config_cache[tipo_obj.pk] = buscar_configuracao_tipo_anuncio(tipo_obj)
    config = config_cache.get(tipo_obj.pk) if tipo_obj else None
    margem_minima = config.margem_padrao if config else None

    ativas = [p for p in v.promocoes.all() if p.status == 'started']
    promocao_ativa_nome = ativas[0].nome or ativas[0].tipo if len(ativas) == 1 else None

    margem_atual_exibicao = None
    if rec.margem_recomendada is not None and rec.variacao_margem_pp is not None:
        margem_atual_exibicao = rec.margem_recomendada - rec.variacao_margem_pp

    sugestao_vs_original_pp = None
    if rec.variacao_margem_pp is not None and v.margem_atual_vs_original_pp is not None:
        sugestao_vs_original_pp = rec.variacao_margem_pp + v.margem_atual_vs_original_pp

    motivo = montar_motivo(rec.bucket_nome, rec.preco_recomendado, rec.margem_recomendada, margem_minima)

    exemplos[rec.categoria_estado] = {
        'mlb': anuncio.mlb if anuncio else None,
        'titulo': anuncio.titulo_anuncio if anuncio else None,
        'eh_catalogo': hasattr(anuncio, 'competicao') if anuncio else False,
        'preco_atual': num(v.preco_atual),
        'preco_original': num(v.preco_original),
        'promocao_ativa_nome': promocao_ativa_nome,
        'margem_atual_exibicao': num(margem_atual_exibicao),
        'margem_atual_vs_original_pp': num(v.margem_atual_vs_original_pp),
        'cenario_nome': rec.cenario_nome,
        'preco_recomendado': num(rec.preco_recomendado),
        'margem_recomendada': num(rec.margem_recomendada),
        'variacao_margem_pp': num(rec.variacao_margem_pp),
        'sugestao_vs_original_pp': num(sugestao_vs_original_pp),
        'exige_aprovacao': rec.exige_aprovacao,
        'motivo': motivo,
        'margem_minima': num(margem_minima),
    }

resultado = {
    'contadores': {
        chave: {'label': label, 'quantidade': contagem.get(chave, 0)}
        for chave, label in Categoria.choices
    },
    'exemplos': exemplos,
}

print(json.dumps(resultado, ensure_ascii=False, indent=2))