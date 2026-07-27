# agenda_videos/funcoes_auxiliares/estado_consumo_drive.py

# Função Objetivo: Guarda, localmente (JSON), quantos vídeos completos já
# foram CONSUMIDOS (baixados + movidos pra usados/) de cada fase de cada
# produto — evita reconsultar o Drive toda vez só pra saber "por onde
# paramos" (mesmo espírito já usado na API do ML: gasta 1 chamada, guarda o
# resultado, nunca re-deriva ao vivo).
#
# * [ATENÇÃO] → Mecanismo de TESTE ISOLADO (26/07) — quando esta integração
#               for ligada de verdade na Agenda, esse número já existe, com
#               outro nome: AndamentoAgenda.ocorrencia_atual. Não faz sentido
#               manter os 2 rastreando a mesma coisa depois de integrar —
#               este JSON é só o substituto provisório de agora.
#
# * [ATENÇÃO 2] → É um cache local, não a fonte de verdade real (a fonte real
#                 é o próprio Drive) — se alguém mexer na pasta manualmente,
#                 sem passar por este código, o JSON dessincroniza, sem
#                 aviso. Aceitável durante teste isolado.

import json
import os

CAMINHO_ARQUIVO_ESTADO = os.path.join(os.path.dirname(__file__), '..', '..', 'estado_consumo_drive.json')


def _carregar_estado():
    if not os.path.exists(CAMINHO_ARQUIVO_ESTADO):
        return {}
    with open(CAMINHO_ARQUIVO_ESTADO, 'r', encoding='utf-8') as arquivo:
        return json.load(arquivo)


def _salvar_estado(estado):
    with open(CAMINHO_ARQUIVO_ESTADO, 'w', encoding='utf-8') as arquivo:
        json.dump(estado, arquivo, indent=2, ensure_ascii=False)


def obter_ultimo_numero_consumido(ean, fase):
    estado = _carregar_estado()
    return estado.get(ean, {}).get(fase, 0)


def registrar_numero_consumido(ean, fase, numero):
    estado = _carregar_estado()
    estado.setdefault(ean, {})[fase] = numero
    _salvar_estado(estado)


# Função Objetivo: Reconstrói o estado a partir da fonte real (contagem de
# Videos/usados/ no Drive) — usado quando o JSON não tem registro ainda pra
# esse EAN/fase (1ª vez), ou quando se suspeita que ele dessincronizou (ex:
# alguém mexeu na pasta manualmente, sem passar por este código).
def reconstruir_a_partir_do_drive(ean, fase, quantidade_real_usada):
    registrar_numero_consumido(ean, fase, quantidade_real_usada)