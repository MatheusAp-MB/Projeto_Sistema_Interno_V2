# gestao_full/funcoes_auxiliares/comparativo_estoque_locais.py

# Função Objetivo: O MAPA do Comparativo de estoque — o que cada local de estoque do ERP (id_empresa da API Sysemp) e cada coluna do arquivo do
# ERP significam, por empresa. É o ÚNICO lugar onde esse significado mora: o resto da tela só pergunta aqui ("quais locais são o Full?").
# Quando a Magazine tiver API ou o Matheus confirmar o mapa dela, só este arquivo muda.
#
# * [EXPLICAÇÃO] → SAMVALE (confirmado pelo Matheus em 08/10/2026; "apenas esses são relevantes"):
#                    id 4  = controle do ERP do que está no Full (em teoria sempre igual ao Full do Mercado Livre);
#                    id 2  = Samvale, o "Flex": tudo que não é Full, onde os produtos ficam fisicamente quando não são Full;
#                    id 10 = igual ao id 2, em outro barracão físico (só uma divisão por falta de espaço; independente do id 2);
#                    id 1  = VSComercio: empresa sem movimentação, NÃO deveria ter estoque nenhum.
#                  No arquivo do ERP da Samvale a coluna "Estoque" (a que alimenta o banco) bate com Emp 2 + Emp 10 em 98% das linhas e NÃO
#                  existe coluna do Full (id 4): por isso o Full só se compara entre API Sysemp e Mercado Livre.
# * [EXPLICAÇÃO] → MAGAZINE: a Sysemp ainda não liberou o método para a Magazine (a instância /61 responde "Metodo não Localizado"), então não
#                  há mapa da API. O arquivo da Magazine tem as colunas Estoque, Emp 1, Emp 4, Emp 5 e Fornecedor, mas qual delas é Full ou Flex
#                  ainda NÃO foi confirmado: a tela mostra todas cruas, sem rótulo. A tela já fica pronta: com a API liberada, é só trocar
#                  API_SYSEMP_DISPONIVEL_POR_EMPRESA e preencher os locais.

from dataclasses import dataclass

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE

PAPEL_FULL = 'full'
PAPEL_FLEX = 'flex'
PAPEL_SEM_MOVIMENTO = 'sem_movimento'


# Texto curto do papel de um local, para os títulos de coluna da tela.
ROTULO_DO_PAPEL = {
    PAPEL_FULL: 'Full',
    PAPEL_FLEX: 'Flex',
    PAPEL_SEM_MOVIMENTO: 'Sem movimento',
}


# Função Objetivo: 1 local de estoque do ERP. "id" é texto porque a API manda o id_empresa como texto ("4").
# "nome" é como o estoque se chama na tela ("Estoque Samvale"); o "rotulo" junta nome e id ("Estoque Samvale (id 2)") para nunca ficar ambíguo.
@dataclass(frozen=True)
class LocalSysemp:
    id: str
    nome: str
    papel: str
    explicacao: str

    @property
    def rotulo(self):
        return f'{self.nome} (id {self.id})'


LOCAIS_SYSEMP_POR_EMPRESA = {
    EMPRESA_SAMVALE: (
        LocalSysemp('4', 'Estoque Full no ERP', PAPEL_FULL,
                    'Controle do ERP do estoque que está no Full. Em teoria é sempre igual ao Full do Mercado Livre.'),
        LocalSysemp('2', 'Estoque Samvale', PAPEL_FLEX,
                    'Samvale: onde os produtos ficam fisicamente quando não são Full.'),
        LocalSysemp('10', 'Estoque Samvale 2º barracão', PAPEL_FLEX,
                    'Igual ao id 2, mas em outro barracão físico (divisão por falta de espaço). Independente do id 2.'),
        LocalSysemp('1', 'Estoque VSComercio', PAPEL_SEM_MOVIMENTO,
                    'Empresa sem movimentação. NÃO deveria ter estoque.'),
    ),
    EMPRESA_MAGAZINE: (),
}

# * [EXPLICAÇÃO] → A Sysemp só liberou o método listarAnaliseEstoqueFull para a Samvale (instância /84). Mude para True quando liberarem
#                  para a Magazine (e preencha os locais dela acima).
API_SYSEMP_DISPONIVEL_POR_EMPRESA = {
    EMPRESA_SAMVALE: True,
    EMPRESA_MAGAZINE: False,
}

# Qual coluna do arquivo do ERP é comparável ao Flex (o que não é Full). Samvale: "Estoque" (a que alimenta o banco). Magazine: ainda não confirmado.
COLUNA_FLEX_DO_ARQUIVO_POR_EMPRESA = {
    EMPRESA_SAMVALE: 'Estoque',
    EMPRESA_MAGAZINE: None,
}


def locais_da_empresa(empresa):
    return LOCAIS_SYSEMP_POR_EMPRESA.get(empresa, ())


def api_sysemp_disponivel(empresa):
    return API_SYSEMP_DISPONIVEL_POR_EMPRESA.get(empresa, False)


def coluna_flex_do_arquivo(empresa):
    return COLUNA_FLEX_DO_ARQUIVO_POR_EMPRESA.get(empresa)


# Função Objetivo: Os locais de um papel (ex.: todos os que são Flex), na ordem do mapa.
def locais_do_papel(empresa, papel):
    return tuple(local for local in locais_da_empresa(empresa) if local.papel == papel)


# Função Objetivo: O local com este id (texto), ou None se o id não está no mapa da empresa.
def local_por_id(empresa, id_local):
    for local in locais_da_empresa(empresa):
        if local.id == id_local:
            return local
    return None
