# arquivos_referencia/funcoes_auxiliares/configuracao_da_importacao.py

# Função Objetivo: Ler e gravar, no banco de CADA empresa, o MODO da planilha Busca Legal (Expandir ou Substituir) — a configuração do card no topo da tela
# "Arquivos de referência". Quem lê: o envio ao Drive (juntar ou trocar o arquivo), o "Atualizar o sistema" e o próprio card. Quem grava: só o card.
#
# * [DECISÃO, 16/10/2026] → O modo é UMA configuração por empresa e vale para os dois passos (ver models.ConfiguracaoDaImportacao). As tabelas de frete não
#   têm modo: sempre espelham o arquivo.
# * [EXPLICAÇÃO] → Expandir (o padrão): ao enviar, junta a planilha ao arquivo do Drive (existentes atualizadas, novas no final); ao atualizar o sistema,
#   atualiza o que existe e cria o que falta, sem apagar nada. Substituir: ao enviar, troca o arquivo do Drive por inteiro; ao atualizar o sistema, o sistema
#   fica igual à planilha (apaga o que ela não tem, depois de a pessoa ler a prévia).
# * [IMPORTANTE] → Ler o modo NUNCA derruba a tela nem a atualização: sem linha gravada, sem a tabela (falta rodar o migrate) ou com banco com problema, o modo
#   é Expandir — o lado seguro, que não apaga nada. O card avisa quando a tabela não existe (`disponivel` = False) e não deixa mudar o modo.
# * [IMPORTANTE] → Só lê e grava o banco da empresa pedida (explicitamente, por alias): nunca o da outra.

import logging

from django.db import connections

from core.empresa import ALIAS_BANCO_POR_EMPRESA

from ..models import ConfiguracaoDaImportacao

logger = logging.getLogger(__name__)

MODO_EXPANDIR = 'expandir'
MODO_SUBSTITUIR = 'substituir'
MODOS_DA_IMPORTACAO = (MODO_EXPANDIR, MODO_SUBSTITUIR)
MODO_PADRAO = MODO_EXPANDIR
CHAVE_DO_MODO_DA_BUSCA_LEGAL = 'modo-da-busca-legal'


class ConfiguracaoIndisponivel(Exception):
    """Não deu para gravar a configuração (a tabela ainda não existe no banco da empresa, ou o banco falhou). `args[0]` é o texto para a tela."""


def _tabela_existe(alias):
    return ConfiguracaoDaImportacao._meta.db_table in connections[alias].introspection.table_names()


# Função Objetivo: O modo da Busca Legal de UMA empresa, pronto para a tela: {'modo', 'disponivel', 'alterado_em'}. Nunca levanta erro (ver cabeçalho).
def situacao_do_modo(empresa):
    alias = ALIAS_BANCO_POR_EMPRESA[empresa]
    try:
        if not _tabela_existe(alias):
            return {'modo': MODO_PADRAO, 'disponivel': False, 'alterado_em': None}
        linha = ConfiguracaoDaImportacao.objects.using(alias).filter(chave=CHAVE_DO_MODO_DA_BUSCA_LEGAL).first()
    except Exception:
        logger.exception('Configuração da importação: não consegui ler o banco %s', alias)
        return {'modo': MODO_PADRAO, 'disponivel': False, 'alterado_em': None}
    if linha is None or linha.valor not in MODOS_DA_IMPORTACAO:
        return {'modo': MODO_PADRAO, 'disponivel': True, 'alterado_em': None}
    return {'modo': linha.valor, 'disponivel': True, 'alterado_em': linha.alterado_em}


def modo_da_busca_legal(empresa):
    return situacao_do_modo(empresa)['modo']


# Função Objetivo: Grava o modo da Busca Legal da empresa. `modo` fora da lista é erro de quem chamou (ValueError); banco sem a tabela é ConfiguracaoIndisponivel.
def gravar_modo_da_busca_legal(empresa, modo):
    if modo not in MODOS_DA_IMPORTACAO:
        raise ValueError(f'Modo desconhecido: {modo!r}')
    alias = ALIAS_BANCO_POR_EMPRESA[empresa]
    try:
        if not _tabela_existe(alias):
            raise ConfiguracaoIndisponivel(
                'A tabela de configurações ainda não existe no banco desta empresa: falta rodar o migrate (python manage.py migrate --database=...). O modo não foi alterado.',
            )
        ConfiguracaoDaImportacao.objects.using(alias).update_or_create(
            chave=CHAVE_DO_MODO_DA_BUSCA_LEGAL, defaults={'valor': modo},
        )
    except ConfiguracaoIndisponivel:
        raise
    except Exception as erro:
        logger.exception('Configuração da importação: não consegui gravar no banco %s', alias)
        raise ConfiguracaoIndisponivel('Não consegui gravar o modo no banco desta empresa. O modo não foi alterado. Veja o terminal do servidor.') from erro
