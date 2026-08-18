# agenda_videos/funcoes_auxiliares/drive/localizador.py

# Função Objetivo: Navega a estrutura {marca}/{ean}/Videos/ no Google Drive e
# devolve os arquivos encontrados — só isso, nenhuma escrita no banco, nenhuma
# lógica de avançar roadmap.
#
# * [EXPLICAÇÃO] → contar_ja_usados() e o contador chamadas_realizadas() que
#                  existiam aqui foram removidos (28/07, pente fino) — nenhum
#                  código os chamava mais (só serviam a scripts de teste já
#                  apagados), e contar_ja_usados duplicava, com sua própria
#                  regex, o mesmo algoritmo de sequência que parser.py já
#                  faz corretamente.

from .cliente import obter_servico_drive, obter_pasta_raiz_id_ativa
from .constantes import NOME_PASTA_VIDEOS, NOME_PASTA_USADOS
from .utilitarios_pasta import buscar_subpasta


class LocalizadorArquivosProduto:

    def __init__(self):
        self.servico = obter_servico_drive()
        # * [EXPLICAÇÃO] → Resolvida 1x aqui, junto do serviço — mesma
        #                  empresa ativa vale pra toda a vida desta
        #                  instância (18/08/2026).
        self._pasta_raiz_id = obter_pasta_raiz_id_ativa()
        # * [EXPLICAÇÃO] → Cache só de pasta de MARCA, em memória, durante 1
        #                  execução — nunca persistido (não é fonte de
        #                  verdade, é só atalho pra não buscar a mesma marca
        #                  2x na mesma rodada).
        self._cache_pasta_marca = {}

    def _obter_pasta_marca(self, marca):
        if marca not in self._cache_pasta_marca:
            self._cache_pasta_marca[marca] = buscar_subpasta(
                self.servico, self._pasta_raiz_id, marca,
            )
        return self._cache_pasta_marca[marca]

    # Função Objetivo: Devolve (encontrado, arquivos, motivo, pasta_videos_id)
    # — "encontrado" distingue "pasta existe mas está vazia" de "pasta não
    # existe em algum nível" (marca/EAN/Videos). "pasta_videos_id" é
    # devolvido pra quem chama poder mover arquivo depois, ou listar usados/.
    def localizar_arquivos(self, marca, ean):
        pasta_marca_id = self._obter_pasta_marca(marca)
        if pasta_marca_id is None:
            return False, [], f'Pasta da marca "{marca}" não encontrada na raiz do Drive.', None

        pasta_ean_id = buscar_subpasta(self.servico, pasta_marca_id, ean)
        if pasta_ean_id is None:
            return False, [], f'Pasta do EAN "{ean}" não encontrada dentro de "{marca}".', None

        pasta_videos_id = buscar_subpasta(self.servico, pasta_ean_id, NOME_PASTA_VIDEOS)
        if pasta_videos_id is None:
            return False, [], f'Subpasta "{NOME_PASTA_VIDEOS}" não encontrada dentro de "{marca}/{ean}".', None

        # * [EXPLICAÇÃO] → Traz "id" junto com "name" — o parser precisa dos
        #                  2, não só do nome (ver parser.py, ArquivoDrive).
        resultado = self.servico.files().list(
            q=f"'{pasta_videos_id}' in parents and trashed = false",
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        return True, resultado.get('files', []), None, pasta_videos_id

    # Função Objetivo: Lista o conteúdo bruto de Videos/usados/ ([] se a
    # subpasta ainda não existir) — usado por quem precisa considerar "o que
    # já existiu" (completude do pool), não só "o que sobrou na pasta agora".
    def listar_arquivos_usados(self, pasta_videos_id):
        pasta_usados_id = buscar_subpasta(self.servico, pasta_videos_id, NOME_PASTA_USADOS)
        if pasta_usados_id is None:
            return []
        resultado = self.servico.files().list(
            q=f"'{pasta_usados_id}' in parents and trashed = false",
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        return resultado.get('files', [])