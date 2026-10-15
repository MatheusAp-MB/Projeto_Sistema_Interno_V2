# mercado_livre/funcoes_auxiliares/sugestoes_ia_salvas.py
#
# Função Objetivo: Guarda no banco a ÚLTIMA sugestão da IA de cada campo de cada produto (tela
# "Características dos anúncios"), para ela sobreviver ao F5, a fechar a aba e a trocar de máquina.
# Quem pede à IA é sugestao_ia_caracteristicas.py (que não grava nada); a view chama as funções daqui.
#
# * [EXPLICAÇÃO] → Duas tabelas (models/sugestao_ia_caracteristica.py):
#   - ConsultaIACaracteristicaMercadoLivre: 1 linha por produto = a última consulta (custo, tokens,
#     texto enviado/devolvido, descartadas). Pedir de novo SUBSTITUI a linha.
#   - SugestaoIACaracteristicaMercadoLivre: 1 linha por produto + campo = a última sugestão daquele
#     campo. Pedir de novo SUBSTITUI o conjunto inteiro do produto; produtos e campos diferentes
#     nunca se misturam (a chave é produto + atributo_id).
#
# * [DECISÃO, 15/10/2026] → Quando um campo é ENVIADO ao Mercado Livre, a sugestão dele sai do banco
#   (já foi usada). As outras continuam até alguém pedir de novo à IA.
#
# * [IMPORTANTE] → Nada aqui chama a API do Mercado Livre nem a do Claude. Se as tabelas ainda não
#   existem num dos bancos (migração 0040 não rodada na empresa), as funções não derrubam a tela:
#   carregar devolve None; salvar devolve (False, motivo) para a tela avisar que a sugestão não ficou
#   guardada.

from decimal import Decimal

from django.db import DatabaseError, transaction
from django.utils import timezone

from core.empresa import obter_alias_banco_ativo

LIMITE_TEXTO = 300
LIMITE_EVIDENCIA = 255


def _modelos():
    from mercado_livre.models import ConsultaIACaracteristicaMercadoLivre, SugestaoIACaracteristicaMercadoLivre

    return ConsultaIACaracteristicaMercadoLivre, SugestaoIACaracteristicaMercadoLivre


def _custo_decimal(bruto):
    # O serviço devolve o custo como texto pt-BR ("0,001690").
    try:
        return Decimal(str(bruto).replace(',', '.'))
    except Exception:
        return Decimal('0')


def _custo_texto(custo):
    return format(Decimal(custo).quantize(Decimal('0.000001')), 'f').replace('.', ',')


# Função Objetivo: Grava o resultado de uma consulta bem-sucedida, SUBSTITUINDO o que havia do produto.
# `resultado` é o dict de sugerir_para_ficha. Devolve (True, '') ou (False, motivo) — nunca levanta:
# a sugestão já foi paga, então um problema ao gravar não pode escondê-la da tela.
def salvar_consulta(produto_id, resultado, usuario=''):
    try:
        Consulta, Sugestao = _modelos()
        agora = timezone.now()
        linhas = []
        for atributo_id, sugestao in (resultado.get('sugestoes') or {}).items():
            linhas.append(Sugestao(
                produto_id=produto_id,
                atributo_id=atributo_id,
                valor=sugestao['valor'],
                texto=str(sugestao.get('texto') or '')[:LIMITE_TEXTO],
                evidencia=str(sugestao.get('evidencia') or '')[:LIMITE_EVIDENCIA],
                atualizada_em=agora,
            ))
        with transaction.atomic(using=obter_alias_banco_ativo()):
            Consulta.objects.update_or_create(produto_id=produto_id, defaults={
                'consultada_em': agora,
                'usuario': (usuario or '')[:150],
                'modelo': resultado.get('modelo') or '',
                'modelo_rotulo': resultado.get('modelo_rotulo') or '',
                'esforco': resultado.get('esforco') or '',
                'modo': resultado.get('modo') or '',
                'tokens_entrada': int(resultado.get('tokens_entrada') or 0),
                'tokens_saida': int(resultado.get('tokens_saida') or 0),
                'custo_usd': _custo_decimal(resultado.get('custo_usd')),
                'duracao_segundos': Decimal(str(resultado.get('duracao_segundos') or 0)),
                'n_sugestoes': int(resultado.get('n_sugestoes') or 0),
                'n_campos_enviados': int(resultado.get('n_campos_enviados') or 0),
                'campos_enviados': list(resultado.get('campos_enviados') or []),
                'ignoradas': list(resultado.get('ignoradas') or []),
                'entrada': resultado.get('entrada') or '',
                'saida': resultado.get('saida') or '',
            })
            Sugestao.objects.filter(produto_id=produto_id).delete()
            Sugestao.objects.bulk_create(linhas)
        return True, ''
    except Exception as erro:       # a sugestão já foi paga: qualquer falha ao gravar vira aviso, nunca perda
        return False, f'{type(erro).__name__}: {str(erro)[:300]}'


# Função Objetivo: A última consulta + sugestões de 1 produto, no mesmo formato que a tela já usa
# (o mesmo dict que o botão "Sugerir com IA" devolve), mais "consultada_em_txt". None se o produto
# nunca consultou a IA (ou se as tabelas ainda não existem neste banco).
def carregar_registro(produto_id):
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import formatar_data_hora

    try:
        Consulta, Sugestao = _modelos()
        consulta = Consulta.objects.filter(produto_id=produto_id).first()
        if consulta is None:
            return None
        sugestoes = {
            linha.atributo_id: {'valor': linha.valor, 'texto': linha.texto, 'evidencia': linha.evidencia}
            for linha in Sugestao.objects.filter(produto_id=produto_id)
        }
    except DatabaseError:
        return None

    return {
        'sugestoes': sugestoes,
        'ignoradas': consulta.ignoradas or [],
        'n_sugestoes': consulta.n_sugestoes,
        'n_campos_enviados': consulta.n_campos_enviados,
        'campos_enviados': consulta.campos_enviados or [],
        'modo': consulta.modo,
        'modelo': consulta.modelo,
        'modelo_rotulo': consulta.modelo_rotulo,
        'esforco': consulta.esforco,
        'tokens_entrada': consulta.tokens_entrada,
        'tokens_saida': consulta.tokens_saida,
        'custo_usd': _custo_texto(consulta.custo_usd),
        'duracao_segundos': float(consulta.duracao_segundos),
        'entrada': consulta.entrada,
        'saida': consulta.saida,
        'consultada_em_txt': formatar_data_hora(consulta.consultada_em),
        'usuario': consulta.usuario,
    }


# Função Objetivo: Tira do banco as sugestões dos campos que acabaram de ser ENVIADOS ao Mercado
# Livre (já foram usadas) e esses campos saem de "campos_enviados" (a tela não escreve "Sem sugestão"
# num campo que a IA nem deixou de sugerir). Nunca levanta: é só limpeza, não pode atrapalhar o envio.
def apagar_sugestoes_enviadas(produto_id, atributo_ids):
    atributo_ids = [a for a in (atributo_ids or []) if a]
    if not atributo_ids:
        return 0
    try:
        Consulta, Sugestao = _modelos()
        with transaction.atomic(using=obter_alias_banco_ativo()):
            apagadas = Sugestao.objects.filter(produto_id=produto_id, atributo_id__in=atributo_ids).delete()[0]
            consulta = Consulta.objects.filter(produto_id=produto_id).first()
            if consulta is not None:
                restantes = [campo for campo in (consulta.campos_enviados or []) if campo not in atributo_ids]
                if restantes != (consulta.campos_enviados or []):
                    consulta.campos_enviados = restantes
                    consulta.save(update_fields=['campos_enviados'])
        return apagadas
    except DatabaseError:
        return 0
