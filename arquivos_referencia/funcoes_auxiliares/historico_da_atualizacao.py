# arquivos_referencia/funcoes_auxiliares/historico_da_atualizacao.py

# Função Objetivo: Gravar e ler o histórico "quando o sistema foi atualizado com este arquivo" (model AtualizacaoDoSistema), no banco de
# CADA empresa. Quem grava é a atualização do sistema (atualizacao_do_sistema.py); quem lê é a linha "No sistema" de cada cartão.
#
# * [DECISÃO, 16/10/2026] → INDEPENDÊNCIA entre as empresas: a leitura é SEMPRE de uma empresa só (a selecionada na tela). A tela da
#   Magazine nunca mostra a data/selo da Samvale, e vice-versa (igual à Gestão de APIs).
# * [EXPLICAÇÃO] → Estado da empresa para um arquivo (sempre ícone + texto na tela, nunca só cor):
#   - "em dia": o sistema foi atualizado com EXATAMENTE o arquivo que está no Drive agora (mesma impressão digital, MD5);
#   - "desatualizado": o sistema foi atualizado alguma vez, mas o Drive tem uma versão diferente (alguém enviou um arquivo novo);
#   - "nunca": o sistema nunca foi atualizado com este arquivo por este botão;
#   - "indisponivel": não deu para ler o histórico (a tabela ainda não existe no banco: falta rodar o migrate — ou o banco falhou).
# * [EXPLICAÇÃO] → Quando o Drive não pôde ser consultado (md5 desconhecido) não se afirma "em dia" nem "desatualizado": mostra-se só a data
#   ("sem comparação com o Drive").
# * [IMPORTANTE] → Ler o histórico NUNCA derruba a tela: qualquer falha vira "indisponivel" e o resto do cartão continua funcionando.

import logging

from django.db import connections
from django.utils import timezone

from core.empresa import ALIAS_BANCO_POR_EMPRESA, EMPRESA_MAGAZINE, EMPRESA_SAMVALE

from ..models import AtualizacaoDoSistema
from .catalogo_arquivos import GRUPO_IMPOSTOS_SAIDA, buscar_arquivo

logger = logging.getLogger(__name__)

ESTADO_EM_DIA = 'em_dia'
ESTADO_DESATUALIZADO = 'desatualizado'
ESTADO_NUNCA = 'nunca'
ESTADO_INDISPONIVEL = 'indisponivel'
ESTADO_SEM_COMPARACAO = 'sem_comparacao'   # tem a data, mas o Drive não disse a impressão digital: não dá para afirmar "em dia"

NOMES_CURTOS_DAS_EMPRESAS = {EMPRESA_MAGAZINE: 'Magazine', EMPRESA_SAMVALE: 'Samvale'}

# estado -> (rótulo curto, ícone COMPLETO do Font Awesome 6)
ESTADOS_DO_HISTORICO = {
    ESTADO_EM_DIA: ('Em dia', 'fas fa-circle-check'),
    ESTADO_DESATUALIZADO: ('Drive tem arquivo mais novo', 'fas fa-triangle-exclamation'),
    ESTADO_NUNCA: ('Ainda não atualizado', 'fas fa-circle-minus'),
    ESTADO_INDISPONIVEL: ('Histórico indisponível', 'fas fa-triangle-exclamation'),
    ESTADO_SEM_COMPARACAO: ('Sem comparação com o Drive', 'fas fa-circle-question'),
}


# Função Objetivo: A tabela do histórico já existe no banco desta empresa? (Falta rodar o migrate = não existe.)
def tabela_existe(alias):
    return AtualizacaoDoSistema._meta.db_table in connections[alias].introspection.table_names()


# Função Objetivo: Grava (ou troca) a linha do histórico de 1 arquivo, no banco da empresa. Chamada DENTRO da transação da importação.
def registrar(alias, arquivo_id, md5, enviado_em, novas, mudaram, iguais, removidas):
    AtualizacaoDoSistema.objects.using(alias).update_or_create(
        arquivo_id=arquivo_id,
        defaults={
            'atualizado_em': timezone.now(), 'arquivo_md5': md5, 'arquivo_enviado_em': enviado_em,
            'linhas_novas': novas, 'linhas_mudaram': mudaram, 'linhas_iguais': iguais, 'linhas_removidas': removidas,
        },
    )


# Função Objetivo: Os números da última atualização em palavras. Frete conta LINHAS; o Busca Legal conta GRUPOS fiscais (ICMS por NCM+CST+origem
# e PIS/COFINS por NCM+CST, somados) e, no modo Expandir, nunca remove nada.
def _numeros_do_registro(registro):
    arquivo = buscar_arquivo(registro.arquivo_id)
    if arquivo is not None and arquivo.grupo == GRUPO_IMPOSTOS_SAIDA:
        return f'{registro.linhas_novas} grupos novos, {registro.linhas_mudaram} mudaram, {registro.linhas_iguais} iguais'
    return (
        f'{registro.linhas_novas} novas, {registro.linhas_mudaram} mudaram, {registro.linhas_iguais} iguais, '
        f'{registro.linhas_removidas} removidas'
    )


# Função Objetivo: Texto que aparece ao passar o mouse na linha da empresa (explica o selo e traz os números da última atualização).
def _dica_da_empresa(estado, registro):
    if estado == ESTADO_INDISPONIVEL:
        return 'Não consegui ler o histórico desta empresa. Se a tabela ainda não existe, falta rodar o migrate deste banco.'
    if registro is None:
        return 'O sistema ainda não foi atualizado com este arquivo por este botão.'
    quando = timezone.localtime(registro.atualizado_em).strftime('%d/%m/%Y %H:%M')
    numeros = _numeros_do_registro(registro)
    if estado == ESTADO_EM_DIA:
        return f'O sistema foi atualizado com o arquivo que está no Drive agora (em {quando}: {numeros}).'
    if estado == ESTADO_DESATUALIZADO:
        return (
            f'O Drive tem um arquivo diferente do que o sistema leu na última atualização (em {quando}: {numeros}). '
            'Use “Atualizar o sistema com o Drive” para trazer o arquivo novo.'
        )
    return f'O Drive não respondeu agora, então não dá para dizer se está em dia. Última atualização: {quando} ({numeros}).'


def _estado_da_empresa(registro, md5_do_drive):
    if registro is None:
        return ESTADO_NUNCA
    if not md5_do_drive:
        return ESTADO_SEM_COMPARACAO
    return ESTADO_EM_DIA if registro.arquivo_md5.lower() == md5_do_drive.lower() else ESTADO_DESATUALIZADO


# Função Objetivo: O histórico de 1 arquivo em UMA empresa (a da tela), pronto para a tela:
#   {'empresa', 'nome', 'estado', 'rotulo', 'icone', 'dica', 'atualizado_em', 'novas', 'mudaram', 'iguais', 'removidas'}
# `md5_do_drive` = impressão digital do arquivo que está no Drive AGORA (None se o Drive não respondeu).
# Só lê o banco desta empresa (explicitamente, por alias): nunca o da outra.
def situacao_do_sistema(arquivo_id, md5_do_drive, empresa):
    alias = ALIAS_BANCO_POR_EMPRESA[empresa]
    registro = None
    estado = None
    try:
        if tabela_existe(alias):
            registro = AtualizacaoDoSistema.objects.using(alias).filter(arquivo_id=arquivo_id).first()
        else:
            estado = ESTADO_INDISPONIVEL
    except Exception:
        logger.exception('Histórico da atualização: não consegui ler o banco %s', alias)
        estado = ESTADO_INDISPONIVEL
    if estado is None:
        estado = _estado_da_empresa(registro, md5_do_drive)
    rotulo, icone = ESTADOS_DO_HISTORICO[estado]
    return {
        'empresa': empresa, 'nome': NOMES_CURTOS_DAS_EMPRESAS.get(empresa, empresa.title()), 'estado': estado,
        'rotulo': rotulo, 'icone': icone, 'dica': _dica_da_empresa(estado, registro),
        'atualizado_em': registro.atualizado_em if registro else None,
        'novas': registro.linhas_novas if registro else 0, 'mudaram': registro.linhas_mudaram if registro else 0,
        'iguais': registro.linhas_iguais if registro else 0, 'removidas': registro.linhas_removidas if registro else 0,
    }
