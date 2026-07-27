import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

# * [RESUMO] → Popula o banco com produtos de teste, 1 por cenário real que um
# produto pode assumir na Agenda de Vídeos — pensado pra testar os filtros
# novos (Atrasado/Risco/Sem Vídeo/Vencimento/Pendente Agora) e o resto do
# fluxo, sem mexer em produto real nenhum. Todo produto de teste tem EAN
# começando com PREFIXO_TESTE — rode limpar_produtos_teste() quantas vezes
# quiser antes de recriar, nunca acumula duplicata.
#
# IMPORTANTE: ConfiguracaoFase (Diária/Semanal/Mensal) precisa já existir
# no banco antes de rodar isso — o script LÊ o periodo atual de cada fase,
# nunca cria/edita a Configuração.

from datetime import timedelta, date
from django.utils import timezone
from produtos.models import Produto
from agenda_videos.models import (
    ProgressoProducaoVideo, StatusVideo, PreparacaoVideoFase, Fase,
    AndamentoAgenda, StatusManualAgenda, ConfiguracaoFase, Postagem, StatusPostagem,
    RoadmapAgenda,
)
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import (
    calcular_janela_fase, calcular_janela_ocorrencia, adicionar_dias_uteis,
)
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto

PREFIXO_TESTE = 'TESTE-AGENDA-'


def limpar_produtos_teste():
    # * [EXPLICAÇÃO] → Corrigido — VariacaoAnuncioMercadoLivre.produto é
    #                  on_delete=SET_NULL, não CASCADE. Apagar só o Produto
    #                  deixava o AnuncioMercadoLivre/Variação/Qualidade do
    #                  cenário 19 órfãos no banco, sobrevivendo à limpeza —
    #                  na 2ª rodada, criar de novo com o mesmo "mlb" colidia
    #                  com o que já existia (unique constraint). Apagando o
    #                  AnuncioMercadoLivre primeiro, em cascata de verdade
    #                  (Variação → Qualidade → Critério de Avaliação são
    #                  CASCADE de propósito), resolve. CriterioQualidade
    #                  (o "UP_HAS_SHORTS" em si) NUNCA é apagado — não é dado
    #                  de teste, é referência compartilhada com o resto do
    #                  sistema.
    from mercado_livre.models import AnuncioMercadoLivre
    qtd_anuncios, _ = AnuncioMercadoLivre.objects.filter(mlb__startswith=PREFIXO_TESTE).delete()
    qtd_produtos, _ = Produto.objects.filter(ean__startswith=PREFIXO_TESTE).delete()
    print(
        f'Limpeza: {qtd_produtos} registro(s) de produtos de teste anteriores removido(s) '
        f'({qtd_anuncios} registro(s) ligado(s), incluindo Anúncio/Variação/Qualidade em cascata).'
    )


def obter_periodo_atual(fase):
    config = ConfiguracaoFase.objects.filter(fase=fase).first()
    if config is None:
        raise RuntimeError(
            f'ConfiguracaoFase da fase "{fase}" não existe — configure ela pela tela '
            f'"Agenda de Vídeos → Configurações" antes de rodar este script.'
        )
    return config.periodo


# Função Objetivo: Cria 1 Produto de teste básico — EAN/SKU previsíveis
# (numerados), sem nenhum estado de Agenda ainda (isso é papel de cada
# função de cenário, chamada depois).
def criar_produto_base(numero, titulo, marca='TESTE'):
    sufixo = f'{numero:03d}'
    return Produto.objects.create(
        ean=f'{PREFIXO_TESTE}{sufixo}',
        sku=f'{PREFIXO_TESTE}{sufixo}',
        titulo=f'[{sufixo}] {titulo}',
        marca=marca,
        estoque=10,
    )


# Função Objetivo: Reposiciona um AndamentoAgenda no tempo (inicio_fase +
# ocorrencia_atual) SEMPRE recalculando fim_ocorrencia_atual junto — nunca
# deixa os 2 dessincronizados. Existe porque 2 cenários (Risco e Recusado
# com cota cumprida) precisavam simular uma data específica manualmente, e
# corrigir só 1 dos 2 campos gerou exatamente o tipo de bug "campo-cópia
# desatualizado" que o resto desta sessão passou o dia caçando no sistema
# real — só que dessa vez no próprio script de teste.
def _reposicionar_andamento(andamento, inicio_fase, ocorrencia_atual):
    andamento.inicio_fase = inicio_fase
    andamento.ocorrencia_atual = ocorrencia_atual
    janela_ocorrencia = calcular_janela_ocorrencia(andamento.fase_atual.fase, inicio_fase, ocorrencia_atual)
    andamento.fim_ocorrencia_atual = janela_ocorrencia.fim
    andamento.save()
    return janela_ocorrencia


def _agendar(produto, fase_inicial, data_referencia=None):
    config = ConfiguracaoFase.objects.filter(fase=fase_inicial).first()
    if config is None:
        raise RuntimeError(f'ConfiguracaoFase da fase "{fase_inicial}" não existe.')

    referencia = data_referencia or timezone.now().date()
    janela = calcular_janela_fase(fase_inicial, referencia, config.periodo)
    janela_ocorrencia_1 = calcular_janela_ocorrencia(fase_inicial, janela.inicio, 1)

    return AndamentoAgenda.objects.create(
        produto=produto, fase_atual=config, ocorrencia_atual=1,
        inicio_fase=janela.inicio, fim_fase=janela.fim,
        fim_ocorrencia_atual=janela_ocorrencia_1.fim,
        status_manual=StatusManualAgenda.ATIVO,
        agendado_em=timezone.now(),
    )


def _marcar_video_pronto(produto):
    ProgressoProducaoVideo.objects.create(
        produto=produto,
        video_simples_status=StatusVideo.GERADO, video_simples_marcado_em=timezone.now(),
        video_base_status=StatusVideo.GERADO, video_base_marcado_em=timezone.now(),
    )


def _marcar_pool_pronto(produto, fase, quantidade_no_clique=None):
    periodo_atual = obter_periodo_atual(fase)
    quantidade = quantidade_no_clique if quantidade_no_clique is not None else periodo_atual
    PreparacaoVideoFase.objects.create(
        produto=produto, fase=fase,
        roteiros_gerados=True, roteiros_quantidade_no_clique=quantidade, roteiros_marcado_em=timezone.now(),
        completos_produzidos=True, completos_quantidade_no_clique=quantidade, completos_marcado_em=timezone.now(),
    )


# ===================================================================
# Cenários — cada função monta 1 produto de teste completo, do jeito
# que ele estaria de verdade se alguém tivesse clicado tudo na tela.
# ===================================================================

def cenario_nao_agendado_do_zero(numero):
    produto = criar_produto_base(numero, 'Não agendado — do zero (Simples/Base pendentes)')
    ProgressoProducaoVideo.objects.create(produto=produto)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_nao_agendado_simples_feito(numero):
    produto = criar_produto_base(numero, 'Não agendado — Simples feito, Base pendente')
    ProgressoProducaoVideo.objects.create(
        produto=produto, video_simples_status=StatusVideo.GERADO, video_simples_marcado_em=timezone.now(),
    )
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_pronto_para_agendar(numero):
    produto = criar_produto_base(numero, 'Pronto para Agendar')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_diaria_aguardando_postar(numero):
    produto = criar_produto_base(numero, 'Diária — Aguardando Postar (pool pronto, nada postado)')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _agendar(produto, Fase.DIARIA)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def _cenario_diaria_com_postagem(numero, titulo, status, com_urgente=False, com_pausado=False):
    produto = criar_produto_base(numero, titulo)
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    andamento = _agendar(produto, Fase.DIARIA)

    if com_pausado:
        andamento.status_manual = StatusManualAgenda.PAUSADO
        andamento.save(update_fields=['status_manual'])

    agora = timezone.now()
    janela_ocorrencia = calcular_janela_ocorrencia(Fase.DIARIA, andamento.inicio_fase, 1)
    postagem = Postagem.objects.create(
        produto=produto, fase=Fase.DIARIA, numero_ocorrencia=1,
        inicio_ocorrencia=janela_ocorrencia.inicio, fim_ocorrencia=janela_ocorrencia.fim,
        status=StatusPostagem.AGUARDANDO_APROVACAO, aguardando_aprovacao_em=agora,
    )
    if status in (StatusPostagem.APROVADO, StatusPostagem.RECUSADO):
        postagem.status = status
        postagem.aprovado_ou_recusado_em = agora
        postagem.save()

    if com_urgente:
        roadmap_agenda, _ = RoadmapAgenda.objects.get_or_create(produto=produto)
        roadmap_agenda.urgente = True
        roadmap_agenda.save()

    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_diaria_aguardando_aprovacao(numero):
    return _cenario_diaria_com_postagem(numero, 'Diária — Aguardando aprovação do ML', StatusPostagem.AGUARDANDO_APROVACAO)


def cenario_diaria_aprovado(numero):
    return _cenario_diaria_com_postagem(numero, 'Diária — Aprovado (esperando "já repliquei")', StatusPostagem.APROVADO)


def cenario_diaria_recusado(numero):
    return _cenario_diaria_com_postagem(numero, 'Diária — Recusado, aguardando decisão', StatusPostagem.RECUSADO)


def cenario_urgente(numero):
    return _cenario_diaria_com_postagem(
        numero, 'Urgente (Diária, Aguardando Postar)', None, com_urgente=True,
    )


def cenario_pausado(numero):
    return _cenario_diaria_com_postagem(
        numero, 'Pausado (Diária, Aguardando aprovação)', StatusPostagem.AGUARDANDO_APROVACAO, com_pausado=True,
    )


def cenario_diaria_atrasado(numero):
    produto = criar_produto_base(numero, 'Diária — Atrasado')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    # * [EXPLICAÇÃO] → 15 dias corridos atrás garante pelo menos 1 dia útil
    #                  vencido, mesmo passando por 1 fim de semana no meio.
    referencia = timezone.now().date() - timedelta(days=15)
    _agendar(produto, Fase.DIARIA, data_referencia=referencia)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_semanal_risco(numero):
    produto = criar_produto_base(numero, 'Semanal — Risco de Atraso')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _marcar_pool_pronto(produto, Fase.SEMANAL)
    andamento = _agendar(produto, Fase.SEMANAL)
    # * [EXPLICAÇÃO] → Corrigido de novo — a versão anterior só sobrescrevia
    #                  fim_ocorrencia_atual, mas calcular_indicadores_atraso
    #                  (A Fazer Hoje) recalcula a janela do ZERO a partir de
    #                  inicio_fase, ignorando esse campo — resultado: SQL via
    #                  "Risco" certo, A Fazer Hoje não. Agora os 2 concordam,
    #                  porque inicio_fase muda de verdade (via
    #                  _reposicionar_andamento), não só o campo-cópia.
    alvo_fim_ocorrencia_1 = adicionar_dias_uteis(timezone.now().date(), 1)
    inicio_fase_ajustado = alvo_fim_ocorrencia_1 - timedelta(days=4)
    _reposicionar_andamento(andamento, inicio_fase_ajustado, 1)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_diaria_roteiros_pendente(numero):
    produto = criar_produto_base(numero, 'Diária — Roteiros pendentes (Simples/Base prontos)')
    _marcar_video_pronto(produto)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_diaria_completos_pendente(numero):
    produto = criar_produto_base(numero, 'Diária — Completos pendentes (Roteiros já feito)')
    _marcar_video_pronto(produto)
    periodo_diaria = obter_periodo_atual(Fase.DIARIA)
    PreparacaoVideoFase.objects.create(
        produto=produto, fase=Fase.DIARIA,
        roteiros_gerados=True, roteiros_quantidade_no_clique=periodo_diaria, roteiros_marcado_em=timezone.now(),
        completos_produzidos=False,
    )
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_mensal_roteiros_pendente(numero):
    produto = criar_produto_base(numero, 'Mensal — Roteiros pendentes')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _marcar_pool_pronto(produto, Fase.SEMANAL)
    # * [EXPLICAÇÃO] → Mesma correção do cenario_mensal_normal — Mensal só
    #                  começa no dia 1; agendar com "hoje" jogava a ocorrência
    #                  pro mês que vem, invisível em "A Fazer Hoje". Faltou
    #                  aplicar aqui quando criei este cenário depois.
    referencia = timezone.now().date() - timedelta(days=45)
    _agendar(produto, Fase.MENSAL, data_referencia=referencia)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_mensal_completos_pendente(numero):
    produto = criar_produto_base(numero, 'Mensal — Completos pendentes (Roteiros já feito)')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _marcar_pool_pronto(produto, Fase.SEMANAL)
    referencia = timezone.now().date() - timedelta(days=45)
    _agendar(produto, Fase.MENSAL, data_referencia=referencia)
    periodo_mensal = obter_periodo_atual(Fase.MENSAL)
    PreparacaoVideoFase.objects.create(
        produto=produto, fase=Fase.MENSAL,
        roteiros_gerados=True, roteiros_quantidade_no_clique=periodo_mensal, roteiros_marcado_em=timezone.now(),
        completos_produzidos=False,
    )
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_semanal_roteiros_pendente(numero):
    produto = criar_produto_base(numero, 'Semanal — Roteiros pendentes')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _agendar(produto, Fase.SEMANAL)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_semanal_completos_pendente(numero):
    produto = criar_produto_base(numero, 'Semanal — Completos pendentes (Roteiros já feito)')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _agendar(produto, Fase.SEMANAL)
    periodo_semanal = obter_periodo_atual(Fase.SEMANAL)
    PreparacaoVideoFase.objects.create(
        produto=produto, fase=Fase.SEMANAL,
        roteiros_gerados=True, roteiros_quantidade_no_clique=periodo_semanal, roteiros_marcado_em=timezone.now(),
        completos_produzidos=False,
    )
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_mensal_normal(numero):
    produto = criar_produto_base(numero, 'Mensal — em andamento normal')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _marcar_pool_pronto(produto, Fase.SEMANAL)
    _marcar_pool_pronto(produto, Fase.MENSAL)
    # * [EXPLICAÇÃO] → Corrigido — Mensal só começa no dia 1 do mês; agendar
    #                  com a data de hoje faz a ocorrência "oficial" cair no
    #                  mês QUE VEM (ainda não chegou), e por isso não aparecia
    #                  em "A Fazer Hoje". 45 dias atrás garante estar pelo
    #                  menos 1 mês fechado no passado, então a ocorrência
    #                  atual já está genuinamente em andamento hoje.
    referencia = timezone.now().date() - timedelta(days=45)
    _agendar(produto, Fase.MENSAL, data_referencia=referencia)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_otimizado(numero):
    produto = criar_produto_base(numero, 'Otimizado — ciclo completo')
    _marcar_video_pronto(produto)
    for fase in (Fase.DIARIA, Fase.SEMANAL, Fase.MENSAL):
        _marcar_pool_pronto(produto, fase)
    andamento = _agendar(produto, Fase.MENSAL)
    andamento.concluido = True
    andamento.concluido_em = timezone.now().date()
    andamento.concluido_marcado_em = timezone.now()
    andamento.save()
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_pool_insuficiente(numero):
    produto = criar_produto_base(numero, 'Diária — Pool insuficiente (período subiu depois do clique)')
    _marcar_video_pronto(produto)
    periodo_atual = obter_periodo_atual(Fase.DIARIA)
    # * [EXPLICAÇÃO] → Simula "marcado pronto quando o período era menor" —
    #                  quantidade capturada fica 1 a menos que o período de
    #                  agora, forçando o badge de insuficiente aparecer.
    quantidade_simulada = max(periodo_atual - 1, 1)
    _marcar_pool_pronto(produto, Fase.DIARIA, quantidade_no_clique=quantidade_simulada)
    _agendar(produto, Fase.DIARIA)
    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_divergencia_fase_concluida(numero):
    produto = criar_produto_base(numero, 'Semanal — Diária concluída com período diferente')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _marcar_pool_pronto(produto, Fase.SEMANAL)
    andamento = _agendar(produto, Fase.DIARIA)

    # * [EXPLICAÇÃO] → Cria só 1 Postagem Replicada pra Diária (real=1) e
    #                  avança direto pra Semanal, simulando um período menor
    #                  no passado — a divergência só aparece de verdade se o
    #                  período ATUAL de Diária, configurado agora, for > 1.
    agora = timezone.now()
    janela_ocorrencia = calcular_janela_ocorrencia(Fase.DIARIA, andamento.inicio_fase, 1)
    Postagem.objects.create(
        produto=produto, fase=Fase.DIARIA, numero_ocorrencia=1,
        inicio_ocorrencia=janela_ocorrencia.inicio, fim_ocorrencia=janela_ocorrencia.fim,
        status=StatusPostagem.REPLICADO,
        aguardando_aprovacao_em=agora, aprovado_ou_recusado_em=agora, replicado_em=agora,
    )

    config_semanal = ConfiguracaoFase.objects.get(fase=Fase.SEMANAL)
    referencia = janela_ocorrencia.fim + timedelta(days=1)
    janela_semanal = calcular_janela_fase(Fase.SEMANAL, referencia, config_semanal.periodo)
    janela_ocorrencia_semanal_1 = calcular_janela_ocorrencia(Fase.SEMANAL, janela_semanal.inicio, 1)
    andamento.fase_atual = config_semanal
    andamento.ocorrencia_atual = 1
    andamento.inicio_fase = janela_semanal.inicio
    andamento.fim_fase = janela_semanal.fim
    # * [EXPLICAÇÃO] → Corrigido — esqueci de recalcular fim_ocorrencia_atual
    #                  pra nova fase/ocorrência; ficou com a data antiga (de
    #                  quando ainda era Diária), que por acaso caía dentro da
    #                  janela de risco, fazendo esse produto aparecer como
    #                  "Risco de Atraso" por engano.
    andamento.fim_ocorrencia_atual = janela_ocorrencia_semanal_1.fim
    andamento.save()

    periodo_diaria_agora = obter_periodo_atual(Fase.DIARIA)
    if periodo_diaria_agora <= 1:
        print(
            f'  [AVISO] Diária está configurada com período {periodo_diaria_agora} — '
            f'esse cenário só mostra divergência se o período for MAIOR que 1.'
        )

    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_recusado_cota_cumprida(numero):
    produto = criar_produto_base(numero, 'Diária — Recusado com cota já cumprida ("Seguir sem repor")')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    andamento = _agendar(produto, Fase.DIARIA)

    periodo_diaria = obter_periodo_atual(Fase.DIARIA)
    # * [EXPLICAÇÃO] → ocorrencia_atual = periodo garante completadas
    #                  (periodo - 1) < periodo — ainda não é "cota cumprida"
    #                  sozinho; o pulo real acontece quando ESSA ocorrência
    #                  também for tratada como concluída (completadas =
    #                  ocorrencia_atual, não ocorrencia_atual - 1). Pra
    #                  simular "cota cumprida" de forma simples e direta,
    #                  usamos ocorrencia_atual = periodo (a ÚLTIMA válida).
    # * [EXPLICAÇÃO] → Corrigido de novo — a versão anterior mudava
    #                  inicio_fase/ocorrencia_atual na mão mas esquecia de
    #                  recalcular fim_ocorrencia_atual junto (o campo-cópia
    #                  ficava com o valor de ANTES da mudança) — SQL e A
    #                  Fazer Hoje passavam a discordar sobre a mesma posição
    #                  no tempo desse produto. _reposicionar_andamento
    #                  garante os 2 sempre juntos.
    #
    #                  A escolha de "quantos dias atrás" também é só uma
    #                  aproximação (nem sempre cai exatamente hoje, pode
    #                  cair um pouco atrasado dependendo do período
    #                  configurado) — não é problema pra ESTE cenário
    #                  específico (o foco é testar "cota cumprida", não a
    #                  precisão de atraso), mas está registrado aqui caso
    #                  vire relevante um dia.
    referencia = timezone.now().date() - timedelta(days=periodo_diaria + 5)
    janela_ocorrencia = _reposicionar_andamento(andamento, referencia, periodo_diaria)
    agora = timezone.now()
    Postagem.objects.create(
        produto=produto, fase=Fase.DIARIA, numero_ocorrencia=periodo_diaria,
        inicio_ocorrencia=janela_ocorrencia.inicio, fim_ocorrencia=janela_ocorrencia.fim,
        status=StatusPostagem.RECUSADO, aguardando_aprovacao_em=agora, aprovado_ou_recusado_em=agora,
    )

    if periodo_diaria <= 1:
        print(
            f'  [AVISO] Diária está com período {periodo_diaria} — pra "cota cumprida" '
            f'funcionar bem no teste, prefira período >= 2 antes de testar este cenário.'
        )

    sincronizar_roadmap_agenda_produto(produto)
    return produto


def cenario_sem_video(numero):
    from mercado_livre.models import (
        AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre, QualidadeAnuncio,
        QualidadeAnuncioCriterio, CriterioQualidade,
    )

    produto = criar_produto_base(numero, 'Sem Vídeo (reprovado em UP_HAS_SHORTS)')
    _marcar_video_pronto(produto)
    _marcar_pool_pronto(produto, Fase.DIARIA)
    _agendar(produto, Fase.DIARIA)

    anuncio = AnuncioMercadoLivre.objects.create(mlb=f'{PREFIXO_TESTE}MLB-{numero:03d}')
    variacao = VariacaoAnuncioMercadoLivre.objects.create(
        anuncio=anuncio, variacao_id='unica', produto=produto,
    )
    qualidade = QualidadeAnuncio.objects.create(variacao=variacao)
    criterio, _ = CriterioQualidade.objects.get_or_create(
        rule_key='UP_HAS_SHORTS',
        defaults={
            'grupo': CriterioQualidade.Grupo.SHORTS,
            'nome': 'Vídeo curto (Shorts)',
            'pergunta': 'O anúncio tem vídeo curto?',
        },
    )
    QualidadeAnuncioCriterio.objects.create(
        qualidade=qualidade, criterio=criterio, status='nao_aprovado',
    )

    sincronizar_roadmap_agenda_produto(produto)
    return produto


CENARIOS = [
    ('001', cenario_nao_agendado_do_zero),
    ('002', cenario_nao_agendado_simples_feito),
    ('003', cenario_pronto_para_agendar),
    ('004', cenario_diaria_aguardando_postar),
    ('005', cenario_diaria_aguardando_aprovacao),
    ('006', cenario_diaria_aprovado),
    ('007', cenario_diaria_recusado),
    ('008', cenario_diaria_atrasado),
    ('009', cenario_semanal_risco),
    ('010', cenario_semanal_roteiros_pendente),
    ('011', cenario_semanal_completos_pendente),
    ('012', cenario_mensal_normal),
    ('013', cenario_otimizado),
    ('014', cenario_urgente),
    ('015', cenario_pausado),
    ('016', cenario_pool_insuficiente),
    ('017', cenario_divergencia_fase_concluida),
    ('018', cenario_recusado_cota_cumprida),
    ('019', cenario_sem_video),
    ('020', cenario_diaria_roteiros_pendente),
    ('021', cenario_diaria_completos_pendente),
    ('022', cenario_mensal_roteiros_pendente),
    ('023', cenario_mensal_completos_pendente),
]


if __name__ == '__main__':
    limpar_produtos_teste()
    print(f'\nCriando {len(CENARIOS)} produtos de teste...\n')

    criados = []
    for numero_str, funcao_cenario in CENARIOS:
        produto = funcao_cenario(int(numero_str))
        criados.append(produto)
        print(f'  [{numero_str}] {produto.titulo}  (EAN {produto.ean})')

    print(f'\n{len(criados)} produto(s) de teste criado(s) com sucesso.')
    print('Busque por "TESTE-AGENDA-" na Agenda de Vídeos pra ver todos juntos.')