# integracao_mercado_livre/servicos/sincronizar_caracteristicas_ml.py
#
# Lê do Mercado Livre as CARACTERÍSTICAS dos anúncios e grava no banco da
# empresa, para a tela "Características dos anúncios" só precisar LER do
# banco. Duas entradas públicas — e SÓ ELAS chamam a API:
#
#   varredura_completa(empresa)       -> botão "Fazer varredura completa"
#   atualizar_produto(empresa, sku)   -> botão "Atualizar" de 1 produto
#
# REGRA DO MATHEUS: NUNCA requisição automática à API. Nada aqui é chamado
# por tela aberta, rotina agendada, importação ou comando de rotina — só por
# clique de botão.
#
# O que cada leitura faz, nesta ordem:
#   1) Escolhe do BANCO os anúncios elegíveis (sem chamar API):
#        - ligados a um Produto do ERP (alguma variação com produto);
#        - fora os "fósseis" de migração e fora os anúncios de catálogo
#          (mesmos filtros já usados na exploração das características);
#        - status active/paused no banco (anúncio sem tipo também entra).
#   2) Lê os valores de cada anúncio: GET /items/{mlb} (1 chamada por MLB,
#      em paralelo) e grava o array "attributes" CRU em
#      AnuncioMercadoLivre.atributos_ml, mais data, categoria e status que
#      o ML informou naquela leitura.
#   3) Lê o que cada CATEGORIA pede (technical_specs/input + attributes =
#      2 chamadas por categoria, em paralelo) e grava em
#      AtributoCategoriaMercadoLivre:
#        - varredura completa: relê TODAS as categorias dos anúncios lidos;
#        - atualizar produto: só as categorias que ainda não estão no banco
#          (a definição de uma categoria é a mesma para qualquer produto).
#
# Estimativa da varredura completa: ~2 chamadas por categoria + 1 por MLB
# elegível. O limite do ML é 18.000 chamadas/hora por app.
#
# Threads: as chamadas à API rodam em threads de trabalho; TODA gravação no
# banco acontece na thread que chamou o serviço (as threads de trabalho
# nunca tocam no banco). Como a empresa ativa é thread-local
# (core/empresa.py), cada thread chama definir_empresa_ativa(empresa) antes
# de qualquer coisa. Quem chama o serviço a partir de uma view precisa
# capturar a empresa na thread da requisição e passá-la para a nova thread
# (mesmo padrão do Portal do Drive).

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from django.db import DatabaseError
from django.utils import timezone

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from mercado_livre.funcoes_auxiliares.caracteristicas_ml import consultar_anuncios_elegiveis
from mercado_livre.models import (
    AnuncioMercadoLivre,
    AtributoCategoriaMercadoLivre,
    CategoriaMercadoLivre,
    VarreduraCaracteristicasMercadoLivre,
)

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/

NOME_PASTA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Magazine',
    EMPRESA_SAMVALE: 'Samvale',
}

# * [EXPLICAÇÃO] → Chamadas simultâneas à API. 20 é o teto já validado em
#                  outros domínios do ML (o pool de conexões aguenta 50, mas
#                  este endpoint não foi medido isoladamente — se aparecer
#                  429 de verdade, medir antes de mexer).
MAX_WORKERS_LEITURA = 20

# * [EXPLICAÇÃO] → Quantos anúncios acumulam antes de gravar no banco. Cada
#                  anúncio leva ~10 KB de JSON; 50 por vez mantém cada
#                  comando de gravação pequeno.
TAMANHO_LOTE_GRAVACAO = 50

# * [EXPLICAÇÃO] → Quantas falhas ficam guardadas no histórico (o objetivo é
#                  diagnosticar, não arquivar tudo).
LIMITE_FALHAS_GUARDADAS = 200

CAMPOS_ANUNCIO = [
    'atributos_ml', 'atributos_ml_lido_em',
    'atributos_ml_categoria_id', 'atributos_ml_status',
]

CAMPOS_ATRIBUTO_CATEGORIA = [
    'nome', 'tipo_valor', 'tags', 'tamanho_maximo', 'unidades_permitidas',
    'opcoes', 'permite_valor_proprio', 'componente', 'ordem', 'lido_em',
]

FASE_ANUNCIOS = 'lendo_anuncios'
FASE_CATEGORIAS = 'lendo_categorias'


@dataclass
class RelatorioLeituraCaracteristicas:
    """Contagens e tempo de 1 leitura — objeto de processo (nunca salvo
    direto no banco), mesmo padrão de RelatorioBuscaDetalhes."""
    empresa: str
    total_anuncios: int = 0
    anuncios_lidos: int = 0
    total_categorias: int = 0
    categorias_lidas: int = 0
    falhas: list[dict] = field(default_factory=list)  # [{"tipo": "anuncio"|"categoria", "id", "erro"}]
    duracao_segundos: float = 0.0


def _sem_progresso(fase, atual, total):
    return None


def _pasta_logs(empresa: str) -> Path:
    if empresa not in NOME_PASTA_POR_EMPRESA:
        raise ValueError(f'Empresa inválida: "{empresa}". Use {list(NOME_PASTA_POR_EMPRESA)}.')
    return RAIZ_APP / 'logs' / NOME_PASTA_POR_EMPRESA[empresa]


# ─── SELEÇÃO NO BANCO (nenhuma chamada à API) ───────────────────────────

# Função Objetivo: Devolve os anúncios que entram na leitura (só id e mlb
# carregados — o resto é preenchido pela gravação). skus=None = todos os
# anúncios elegíveis; lista de SKUs = só os anúncios desses produtos. A regra
# de quem é elegível mora em consultar_anuncios_elegiveis (a mesma que a tela
# usa para listar), para a leitura e a tela nunca discordarem.
def _carregar_anuncios(skus=None) -> list[AnuncioMercadoLivre]:
    return list(consultar_anuncios_elegiveis(skus).only('id', 'mlb'))


# ─── LEITURA EM PARALELO ────────────────────────────────────────────────

# Função Objetivo: Workers das threads — SÓ chamam a API (nunca o banco).
def _ler_anuncio(empresa: str, api_ml: ApiMercadoLivre, mlb: str) -> dict:
    definir_empresa_ativa(empresa)
    return api_ml.buscar_atributos_item(mlb)


def _ler_categoria(empresa: str, api_ml: ApiMercadoLivre, category_id: str) -> dict:
    definir_empresa_ativa(empresa)
    return api_ml.buscar_card_categoria(category_id)


# Função Objetivo: Roda funcao(chave) para cada chave em threads e chama
# ao_terminar(chave, resultado, erro) NA THREAD QUE CHAMOU, conforme cada
# leitura termina (erro vem preenchido quando a leitura daquela chave
# falhou). Falha de autenticação (401) é a única que derruba tudo: com o
# token rejeitado, todas as próximas chamadas falhariam do mesmo jeito.
def _ler_em_paralelo(chaves, funcao, ao_terminar) -> None:
    if not chaves:
        return
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS_LEITURA)
    try:
        futuros = {pool.submit(funcao, chave): chave for chave in chaves}
        for futuro in as_completed(futuros):
            chave = futuros[futuro]
            try:
                resultado = futuro.result()
            except ErroAutenticacaoAPI:
                raise
            except Exception as erro:  # uma falha não derruba o lote inteiro
                ao_terminar(chave, None, f'{type(erro).__name__}: {erro}'[:300])
            else:
                ao_terminar(chave, resultado, None)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


# ─── ANÚNCIOS: valores de hoje ──────────────────────────────────────────

# Função Objetivo: Lê os valores atuais de cada anúncio e grava em
# AnuncioMercadoLivre (em lotes, conforme vão chegando — o que já foi lido
# não se perde se a leitura for interrompida). Devolve o conjunto de
# category_id que o ML informou para os anúncios lidos.
def _ler_e_gravar_anuncios(empresa, api_ml, anuncios, relatorio, ao_progredir) -> set[str]:
    por_mlb = {anuncio.mlb: anuncio for anuncio in anuncios}
    total = len(por_mlb)
    pendentes = []
    categorias = set()
    contador = {'feitos': 0}

    def gravar_pendentes():
        if pendentes:
            AnuncioMercadoLivre.objects.bulk_update(
                pendentes, CAMPOS_ANUNCIO, batch_size=TAMANHO_LOTE_GRAVACAO,
            )
            pendentes.clear()

    def ao_terminar(mlb, leitura, erro):
        contador['feitos'] += 1
        if erro is not None:
            relatorio.falhas.append({'tipo': 'anuncio', 'id': mlb, 'erro': erro})
        else:
            anuncio = por_mlb[mlb]
            anuncio.atributos_ml = leitura['attributes']
            anuncio.atributos_ml_lido_em = timezone.now()
            anuncio.atributos_ml_categoria_id = leitura['category_id']
            anuncio.atributos_ml_status = leitura['status']
            pendentes.append(anuncio)
            relatorio.anuncios_lidos += 1
            if leitura['category_id']:
                categorias.add(leitura['category_id'])
        if len(pendentes) >= TAMANHO_LOTE_GRAVACAO:
            gravar_pendentes()
        ao_progredir(FASE_ANUNCIOS, contador['feitos'], total)

    try:
        _ler_em_paralelo(
            list(por_mlb),
            lambda mlb: _ler_anuncio(empresa, api_ml, mlb),
            ao_terminar,
        )
    finally:
        gravar_pendentes()

    return categorias


# ─── CATEGORIAS: o que cada uma pede ────────────────────────────────────

# Função Objetivo: Junta o que a API devolveu (card + definições) nas linhas
# do nosso schema, na ordem do card do ML. As etiquetas das duas fontes
# viram uma lista só; listas vazias viram None.
def _montar_linhas_da_categoria(category_id: str, leitura: dict) -> list[AtributoCategoriaMercadoLivre]:
    defs = leitura['defs']
    linhas = []
    for ordem, (atributo_id, meta) in enumerate(leitura['card'].items()):
        definicao = defs.get(atributo_id, {})
        tags = sorted(set(meta.get('tags') or []) | set(definicao.get('tags') or []))
        linhas.append(AtributoCategoriaMercadoLivre(
            categoria_id=category_id,
            atributo_id=atributo_id,
            nome=meta.get('label') or atributo_id,
            tipo_valor=definicao.get('value_type') or '',
            tags=tags or None,
            tamanho_maximo=definicao.get('value_max_length'),
            unidades_permitidas=definicao.get('allowed_units') or None,
            opcoes=definicao.get('values') or None,
            permite_valor_proprio=meta.get('allow_custom_value'),
            componente=meta.get('componente') or '',
            ordem=ordem,
        ))
    return linhas


# Função Objetivo: Grava (upsert) os atributos de 1 categoria e apaga os que
# o ML não pede mais nela. Devolve quantos atributos a categoria tem agora.
def _gravar_categoria(category_id: str, leitura: dict) -> int:
    linhas = _montar_linhas_da_categoria(category_id, leitura)
    if linhas:
        AtributoCategoriaMercadoLivre.objects.bulk_create(
            linhas,
            update_conflicts=True,
            update_fields=CAMPOS_ATRIBUTO_CATEGORIA,
        )
    (
        AtributoCategoriaMercadoLivre.objects
        .filter(categoria_id=category_id)
        .exclude(atributo_id__in=[linha.atributo_id for linha in linhas])
        .delete()
    )
    return len(linhas)


# Função Objetivo: Lê e grava o que as categorias pedem. somente_ausentes=True
# pula as categorias que já têm atributos no banco (usado no "Atualizar" de
# 1 produto, para não repetir leitura que vale para todos os produtos).
def _ler_e_gravar_categorias(
    empresa, api_ml, category_ids, relatorio, ao_progredir, somente_ausentes=False,
) -> None:
    ids = sorted(c for c in category_ids if c)
    existentes = set(
        CategoriaMercadoLivre.objects
        .filter(category_id__in=ids)
        .values_list('category_id', flat=True)
    )
    for faltante in sorted(set(ids) - existentes):
        relatorio.falhas.append({
            'tipo': 'categoria', 'id': faltante,
            'erro': 'Categoria não existe na tabela local de categorias — '
                    'sincronize as categorias antes de ler as características.',
        })

    a_ler = [c for c in ids if c in existentes]
    if somente_ausentes and a_ler:
        ja_no_banco = set(
            AtributoCategoriaMercadoLivre.objects
            .filter(categoria_id__in=a_ler)
            .order_by()
            .values_list('categoria_id', flat=True)
            .distinct()
        )
        a_ler = [c for c in a_ler if c not in ja_no_banco]

    total = len(a_ler)
    relatorio.total_categorias = total
    contador = {'feitos': 0}

    def ao_terminar(category_id, leitura, erro):
        contador['feitos'] += 1
        if erro is not None:
            relatorio.falhas.append({'tipo': 'categoria', 'id': category_id, 'erro': erro})
        else:
            try:
                _gravar_categoria(category_id, leitura)
                relatorio.categorias_lidas += 1
            except DatabaseError as erro_banco:
                relatorio.falhas.append({
                    'tipo': 'categoria', 'id': category_id,
                    'erro': f'Falha ao gravar no banco: {erro_banco}'[:300],
                })
        ao_progredir(FASE_CATEGORIAS, contador['feitos'], total)

    _ler_em_paralelo(
        a_ler,
        lambda category_id: _ler_categoria(empresa, api_ml, category_id),
        ao_terminar,
    )


# ─── ENTRADAS PÚBLICAS (só botão chama) ─────────────────────────────────

# Função Objetivo: "Fazer varredura completa" — lê TODOS os anúncios
# elegíveis e TODAS as categorias deles, e deixa um registro no histórico
# (VarreduraCaracteristicasMercadoLivre). ao_progredir(fase, atual, total) é
# opcional: a view usa para atualizar a barra de progresso.
def varredura_completa(empresa: str, usuario: str = '', ao_progredir=None) -> RelatorioLeituraCaracteristicas:
    definir_empresa_ativa(empresa)
    ao_progredir = ao_progredir or _sem_progresso
    inicio = time.perf_counter()

    api_ml = ApiMercadoLivre(pasta_logs=_pasta_logs(empresa), empresa=empresa)
    relatorio = RelatorioLeituraCaracteristicas(empresa=empresa)
    registro = VarreduraCaracteristicasMercadoLivre.objects.create(usuario=usuario or '')

    try:
        anuncios = _carregar_anuncios()
        relatorio.total_anuncios = len(anuncios)
        categorias = _ler_e_gravar_anuncios(empresa, api_ml, anuncios, relatorio, ao_progredir)
        _ler_e_gravar_categorias(empresa, api_ml, categorias, relatorio, ao_progredir)
    except Exception as erro:
        relatorio.falhas.append({'tipo': 'varredura', 'id': '', 'erro': f'{type(erro).__name__}: {erro}'[:300]})
        relatorio.duracao_segundos = round(time.perf_counter() - inicio, 2)
        _fechar_registro(registro, relatorio, VarreduraCaracteristicasMercadoLivre.Situacao.ERRO)
        raise

    relatorio.duracao_segundos = round(time.perf_counter() - inicio, 2)
    situacao = (
        VarreduraCaracteristicasMercadoLivre.Situacao.COM_FALHAS if relatorio.falhas
        else VarreduraCaracteristicasMercadoLivre.Situacao.CONCLUIDA
    )
    _fechar_registro(registro, relatorio, situacao)
    return relatorio


# Função Objetivo: "Atualizar" de 1 produto — relê os anúncios elegíveis
# daquele SKU (e só as categorias que ainda não estão no banco). Não gera
# linha no histórico de varreduras: a data de cada anúncio já fica em
# AnuncioMercadoLivre.atributos_ml_lido_em.
def atualizar_produto(empresa: str, sku: str, ao_progredir=None) -> RelatorioLeituraCaracteristicas:
    definir_empresa_ativa(empresa)
    ao_progredir = ao_progredir or _sem_progresso
    inicio = time.perf_counter()

    api_ml = ApiMercadoLivre(pasta_logs=_pasta_logs(empresa), empresa=empresa)
    relatorio = RelatorioLeituraCaracteristicas(empresa=empresa)

    anuncios = _carregar_anuncios([sku])
    relatorio.total_anuncios = len(anuncios)
    categorias = _ler_e_gravar_anuncios(empresa, api_ml, anuncios, relatorio, ao_progredir)
    _ler_e_gravar_categorias(empresa, api_ml, categorias, relatorio, ao_progredir, somente_ausentes=True)

    relatorio.duracao_segundos = round(time.perf_counter() - inicio, 2)
    return relatorio


def _fechar_registro(registro, relatorio, situacao) -> None:
    registro.situacao = situacao
    registro.concluida_em = timezone.now()
    registro.total_anuncios = relatorio.total_anuncios
    registro.anuncios_lidos = relatorio.anuncios_lidos
    registro.total_categorias = relatorio.total_categorias
    registro.categorias_lidas = relatorio.categorias_lidas
    registro.falhas = relatorio.falhas[:LIMITE_FALHAS_GUARDADAS] or None
    registro.save()
