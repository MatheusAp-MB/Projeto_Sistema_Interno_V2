# integracao_mercado_livre/servicos/sincronizar_caracteristicas_ml.py
#
# Lê do Mercado Livre as CARACTERÍSTICAS dos anúncios e grava no banco da
# empresa, para a tela "Características dos anúncios" só precisar LER do
# banco. Três entradas públicas — e SÓ ELAS chamam a API:
#
#   varredura_completa(empresa)       -> botão "Fazer varredura completa"
#   atualizar_produto(empresa, sku)   -> botão "Atualizar" de 1 produto
#   enviar_produto(empresa, plano)    -> botão "Confirmar envio" de 1 produto
#                                        (a ÚNICA que ESCREVE no ML)
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
# O que o envio faz (enviar_produto): o PLANO (quem recebe o quê) já vem
# pronto de mercado_livre.funcoes_auxiliares.envio_caracteristicas_ml. Para
# cada anúncio que precisa receber valores: 1 PUT /items/{mlb} só com os
# atributos que mudam — um anúncio de cada vez, SEM retentativa (escrita não
# se repete sozinha). Depois relê do ML, com a mesma leitura do "Atualizar",
# só os anúncios que receberam (ou cujo envio ficou incerto), grava no banco e
# confere campo a campo se o ML guardou o que foi enviado. Custo: 1 chamada de
# envio + 1 de leitura por anúncio que recebe. Nada de categoria é relido.
#
# Threads: as chamadas à API rodam em threads de trabalho; TODA gravação no
# banco acontece na thread que chamou o serviço (as threads de trabalho
# nunca tocam no banco). Como a empresa ativa é thread-local
# (core/empresa.py), cada thread chama definir_empresa_ativa(empresa) antes
# de qualquer coisa. Quem chama o serviço a partir de uma view precisa
# capturar a empresa na thread da requisição e passá-la para a nova thread
# (mesmo padrão do Portal do Drive).

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from django.db import DatabaseError
from django.utils import timezone

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from mercado_livre.funcoes_auxiliares.caracteristicas_ml import consultar_anuncios_elegiveis
from mercado_livre.funcoes_auxiliares.envio_caracteristicas_ml import conferir_depois_do_envio
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


@dataclass
class RelatorioEnvioCaracteristicas:
    """Resultado de 1 envio — objeto de processo (nunca salvo direto no
    banco). "mlbs" tem 1 dicionário por anúncio do plano, na ordem do plano:
    mlb, anuncio_id, titulo, permalink, situacao ("aceito" | "recusado" |
    "incerto" | "nao_enviado"), mensagem, avisos (os "warnings" do ML),
    status_http e campos (a conferência campo a campo, só dos anúncios que
    foram lidos de volta)."""
    empresa: str
    mlbs: list[dict] = field(default_factory=list)
    acesso_recusado: bool = False
    falhas_leitura: list[dict] = field(default_factory=list)
    duracao_segundos: float = 0.0

    # Função Objetivo: Quais campos NÃO ficaram aplicados em todos os anúncios
    # que deviam recebê-los (recusado, sem resposta e não confirmado, não
    # enviado por token recusado, aceito mas sem leitura de volta para
    # conferir, ou o ML guardou outro valor). A tela só mantém digitado o que
    # está pendente — o resto já está no banco, lido de volta do ML.
    def atributos_pendentes(self, plano: dict) -> list[str]:
        pendentes = []
        corpos = {alvo['mlb']: alvo['atributos_corpo'] for alvo in plano['mlbs'] if alvo['situacao'] == 'enviar'}
        for registro in self.mlbs:
            if registro['mlb'] not in corpos:
                continue
            ids = [corpo['id'] for corpo in corpos[registro['mlb']]]
            if registro['situacao'] != 'aceito' or not registro['campos']:
                candidatos = ids
            else:
                candidatos = [campo['atributo_id'] for campo in registro['campos'] if not campo['confirmado']]
            for atributo_id in candidatos:
                if atributo_id not in pendentes:
                    pendentes.append(atributo_id)
        return pendentes


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


# Função Objetivo: "Confirmar envio" de 1 produto — manda os valores novos
# aos anúncios do plano que precisam deles e lê de volta o que o ML guardou.
# "plano" é o devolvido por preparar_envio (já validado, sem erros). Nunca
# levanta erro de 1 anúncio: o que aconteceu com cada um fica no relatório.
# Só o relatório diz se deu certo — a tela mostra anúncio por anúncio.
def enviar_produto(empresa: str, plano: dict) -> RelatorioEnvioCaracteristicas:
    definir_empresa_ativa(empresa)
    inicio = time.perf_counter()

    api_ml = ApiMercadoLivre(pasta_logs=_pasta_logs(empresa), empresa=empresa)
    relatorio = RelatorioEnvioCaracteristicas(empresa=empresa)

    for alvo in plano['mlbs']:
        registro = {
            'mlb': alvo['mlb'], 'anuncio_id': alvo['anuncio_id'], 'titulo': alvo['titulo'],
            'permalink': alvo['permalink'], 'situacao': 'nao_enviado', 'mensagem': '',
            'avisos': [], 'status_http': None, 'campos': [],
        }
        relatorio.mlbs.append(registro)

        if alvo['situacao'] != 'enviar':
            registro['mensagem'] = alvo['motivo'] or 'Não precisava receber envio.'
            continue
        if relatorio.acesso_recusado:
            registro['mensagem'] = 'Não enviado: o Mercado Livre recusou o acesso num envio anterior.'
            continue

        try:
            resultado = api_ml.enviar_atributos_item(alvo['mlb'], alvo['atributos_corpo'])
        except ErroAutenticacaoAPI:
            traceback.print_exc()
            relatorio.acesso_recusado = True
            registro['mensagem'] = 'O Mercado Livre recusou o acesso (token inválido ou vencido). Este anúncio não foi alterado.'
            continue
        except Exception as erro:
            # * [EXPLICAÇÃO] → Mantido de propósito: 1 anúncio com problema
            #                  inesperado não derruba o envio dos outros, mas
            #                  o detalhe precisa aparecer no terminal.
            traceback.print_exc()
            resultado = {
                'ok': False, 'incerto': True, 'status_http': None, 'avisos': [],
                'mensagem': f'Falha inesperada ao enviar ({type(erro).__name__}). Não sei se o Mercado Livre aplicou; a leitura de volta confere.',
            }

        registro['situacao'] = 'aceito' if resultado['ok'] else ('incerto' if resultado['incerto'] else 'recusado')
        registro['mensagem'] = resultado['mensagem']
        registro['avisos'] = resultado['avisos']
        registro['status_http'] = resultado['status_http']

    a_reler = [r for r in relatorio.mlbs if r['situacao'] in ('aceito', 'incerto')]
    if a_reler:
        _reler_e_conferir(empresa, api_ml, plano, a_reler, relatorio)

    relatorio.duracao_segundos = round(time.perf_counter() - inicio, 2)
    return relatorio


# Função Objetivo: Lê de volta, só dos anúncios que receberam (ou cujo envio
# ficou incerto), o que o ML guardou; grava no banco (mesma gravação do
# "Atualizar") e preenche, em cada registro, a conferência campo a campo.
# "Foi relido" = o anúncio ganhou uma data de leitura nova — assim vale
# também quando a leitura foi interrompida no meio (token recusado).
def _reler_e_conferir(empresa, api_ml, plano, registros, relatorio) -> None:
    ids = [registro['anuncio_id'] for registro in registros]
    anuncios = list(AnuncioMercadoLivre.objects.filter(id__in=ids).only('id', 'mlb'))
    leitura = RelatorioLeituraCaracteristicas(empresa=empresa, total_anuncios=len(anuncios))

    momento = timezone.now()
    try:
        _ler_e_gravar_anuncios(empresa, api_ml, anuncios, leitura, _sem_progresso)
    except ErroAutenticacaoAPI:
        traceback.print_exc()
        relatorio.acesso_recusado = True
    relatorio.falhas_leitura = leitura.falhas

    atualizados = {
        anuncio.id: anuncio
        for anuncio in AnuncioMercadoLivre.objects.filter(id__in=ids).only('id', 'atributos_ml', 'atributos_ml_lido_em')
    }
    corpos = {alvo['mlb']: alvo['atributos_corpo'] for alvo in plano['mlbs']}

    for registro in registros:
        anuncio = atualizados.get(registro['anuncio_id'])
        foi_relido = (
            anuncio is not None
            and anuncio.atributos_ml_lido_em is not None
            and anuncio.atributos_ml_lido_em >= momento
        )
        if not foi_relido:
            registro['mensagem'] += ' Não consegui ler de volta para confirmar; clique em "Atualizar" no produto.'
            continue

        registro['campos'] = conferir_depois_do_envio(plano['valores'], corpos[registro['mlb']], anuncio.atributos_ml)
        todos_confirmados = all(campo['confirmado'] for campo in registro['campos'])
        if registro['situacao'] == 'incerto' and todos_confirmados:
            registro['situacao'] = 'aceito'
            registro['mensagem'] = 'O Mercado Livre demorou a responder, mas a leitura de volta confirma que aplicou.'
        elif registro['situacao'] == 'incerto':
            registro['mensagem'] += ' A leitura de volta não confirmou todos os campos.'
        elif not todos_confirmados:
            registro['mensagem'] = 'Aceito pelo Mercado Livre, mas a leitura de volta mostra valor diferente em algum campo.'


def _fechar_registro(registro, relatorio, situacao) -> None:
    registro.situacao = situacao
    registro.concluida_em = timezone.now()
    registro.total_anuncios = relatorio.total_anuncios
    registro.anuncios_lidos = relatorio.anuncios_lidos
    registro.total_categorias = relatorio.total_categorias
    registro.categorias_lidas = relatorio.categorias_lidas
    registro.falhas = relatorio.falhas[:LIMITE_FALHAS_GUARDADAS] or None
    registro.save()
