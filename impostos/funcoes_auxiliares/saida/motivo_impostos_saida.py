# impostos/funcoes_auxiliares/motivo_impostos_saida.py

# Função Objetivo: Classifica, pra 1 produto, o motivo exato de cada campo
# fiscal de saída vindo de tabela normalizada (icms_saida_sp,
# icms_saida_media, pis_percentual, cofins_percentual) estar em branco —
# Camada B da auditoria fiscal (ver Descoberta "Auditoria Fiscal de
# Impostos de Saida" no vault, 13/09/2026). ÚNICA função de motivo do
# sistema: reaproveitada por validar_impostos_saida.py (raiz do repo), pela
# tela de produto (Camada C) e pela tela de Auditoria Fiscal (Camada D) —
# nunca duplicada em 2 lugares (garantia do vault).
#
# Nunca lê a planilha Excel: só consulta IcmsNcmUf/PisCofinsNcmCst (o que
# já está validado agora) e IcmsNcmRejeitado/PisCofinsNcmCstRejeitado (o
# motivo já persistido da última rejeição, gravado por
# importacao_icms_ncm.py/importacao_pis_cofins_ncm_cst.py) — garante que
# qualquer tela que use isso nunca desalinha do banco (guarantee de
# eficiência/segurança do vault: a tela nunca lê a planilha ao vivo).

from dataclasses import dataclass, field
from typing import Optional

from impostos.funcoes_auxiliares.saida.exibicao_icms_por_ncm import calcular_media_ponderada
from impostos.funcoes_auxiliares.saida.preenchimento_impostos_saida import _normalizar_chave_para_busca
from impostos.models import IcmsNcmRejeitado, IcmsNcmUf, PisCofinsNcmCst, PisCofinsNcmCstRejeitado

MOTIVO_SEM_NCM = 'sem_ncm'
MOTIVO_NCM_REJEITADO_ICMS = 'ncm_rejeitado_icms'
MOTIVO_NCM_NUNCA_IMPORTADO_ICMS = 'ncm_nunca_importado_icms'
MOTIVO_ICMS_MEDIA_SEM_COBERTURA_UFS = 'icms_media_sem_cobertura_ufs'
MOTIVO_SEM_CST = 'sem_cst'
MOTIVO_NCM_CST_REJEITADO_PIS_COFINS = 'ncm_cst_rejeitado_pis_cofins'
MOTIVO_NCM_CST_NUNCA_IMPORTADO_PIS_COFINS = 'ncm_cst_nunca_importado_pis_cofins'

# * [EXPLICAÇÃO] → Texto pronto pra exibir em qualquer tela (Camada C e D)
#                  — 1 fonte só, nunca reescrito diferente em cada tela.
DESCRICAO_POR_MOTIVO = {
    MOTIVO_SEM_NCM: 'Produto sem NCM cadastrado — não há como buscar ICMS por NCM sem ele.',
    MOTIVO_NCM_REJEITADO_ICMS: (
        'NCM rejeitado na última importação — os EANs deste NCM divergem em pelo menos 1 UF.'
    ),
    MOTIVO_NCM_NUNCA_IMPORTADO_ICMS: 'Este NCM nunca apareceu na planilha Busca Legal de ICMS.',
    MOTIVO_ICMS_MEDIA_SEM_COBERTURA_UFS: (
        'NCM aceito e com ICMS SP cadastrado, mas nenhuma das outras 26 UFs tem alíquota '
        'suficiente pra calcular a Média Ponderada (SP × 50% + média das outras 26 × 50%).'
    ),
    MOTIVO_SEM_CST: (
        'Produto sem CST de saída cadastrado — não há como buscar ICMS ou PIS/COFINS por '
        'NCM+CST sem ele.'
    ),
    MOTIVO_NCM_CST_REJEITADO_PIS_COFINS: (
        'NCM+CST rejeitado na última importação — os EANs deste grupo divergem em PIS e/ou COFINS.'
    ),
    MOTIVO_NCM_CST_NUNCA_IMPORTADO_PIS_COFINS: (
        'Este NCM+CST nunca apareceu na planilha Busca Legal de PIS/COFINS.'
    ),
}


# * [EXPLICAÇÃO] → Classe CSS (ver layout_badges.css) + rótulo curto pro
#                  badge de severidade — reaproveitado pela tela de produto
#                  (Camada C) e pela tela de Auditoria Fiscal (Camada D),
#                  nunca decidido diferente em cada tela. 3 severidades:
#                  cinza (cadastro incompleto no PRÓPRIO produto — sem NCM
#                  ou sem CST) / laranja (o NCM(+CST) ainda não tem
#                  cobertura, mas não foi rejeitado — só nunca apareceu, ou
#                  a Média não tem UF suficiente) / vermelho (rejeitado por
#                  divergência real entre EANs — o caso mais grave, exige
#                  corrigir a planilha).
_BADGE_POR_MOTIVO = {
    MOTIVO_SEM_NCM: ('badge-fiscal-cadastro-incompleto', 'Cadastro incompleto'),
    MOTIVO_SEM_CST: ('badge-fiscal-cadastro-incompleto', 'Cadastro incompleto'),
    MOTIVO_NCM_NUNCA_IMPORTADO_ICMS: ('badge-fiscal-cobertura-pendente', 'Cobertura pendente'),
    MOTIVO_NCM_CST_NUNCA_IMPORTADO_PIS_COFINS: ('badge-fiscal-cobertura-pendente', 'Cobertura pendente'),
    MOTIVO_ICMS_MEDIA_SEM_COBERTURA_UFS: ('badge-fiscal-cobertura-pendente', 'Cobertura pendente'),
    MOTIVO_NCM_REJEITADO_ICMS: ('badge-fiscal-rejeitado', 'Rejeitado — divergência'),
    MOTIVO_NCM_CST_REJEITADO_PIS_COFINS: ('badge-fiscal-rejeitado', 'Rejeitado — divergência'),
}


@dataclass
class MotivoFiscal:
    # Função Objetivo: 1 motivo classificado, pronto pra exibir — motivo
    # (chave estável, pra lógica/agrupamento) + descricao (texto pronto,
    # sempre a mesma fonte) + detalhe_rejeicao (o registro persistido de
    # IcmsNcmRejeitado/PisCofinsNcmCstRejeitado, só quando o motivo for
    # de rejeição — None nos outros casos, nunca inventa detalhe que não existe).
    motivo: str
    descricao: str
    detalhe_rejeicao: Optional[object] = field(default=None)

    @property
    def badge_classe(self):
        return _BADGE_POR_MOTIVO[self.motivo][0]

    @property
    def badge_rotulo(self):
        return _BADGE_POR_MOTIVO[self.motivo][1]


# Função Objetivo: Carrega 1 vez (por instância) tudo que a classificação
# precisa — pensado pra 1 instância por rodada (validar_impostos_saida.py)
# ou por request (Camada C/D) — nunca 1 query nova por produto classificado.
class ClassificadorMotivoFiscal:

    def __init__(self):
        # (ncm, cst, origem) normalizados -> {uf: aliquota} — chave
        # expandida em 13/09/2026 (ver Decisão no vault sobre CST+Origem
        # no ICMS). Mesma fonte que
        # exibicao_icms_por_ncm.montar_matriz_icms_por_ncm usa pra tela de
        # ICMS por NCM, nunca uma 2ª leitura reimplementada diferente.
        self.icms_valores_por_grupo = {}
        for registro in IcmsNcmUf.objects.all():
            ncm = _normalizar_chave_para_busca(registro.ncm)
            cst = _normalizar_chave_para_busca(registro.cst)
            if ncm is None or cst is None:
                continue
            origem = _normalizar_chave_para_busca(registro.origem_mercadoria_cadastro)
            self.icms_valores_por_grupo.setdefault((ncm, cst, origem), {})[registro.uf] = registro.aliquota

        # (ncm normalizado, cst normalizado) -> True — só precisa saber SE
        # o grupo está aceito, não os valores (esses vêm de Produto direto).
        self.pis_cofins_grupos_aceitos = set()
        for ncm, cst in PisCofinsNcmCst.objects.values_list('ncm', 'cst'):
            ncm_norm = _normalizar_chave_para_busca(ncm)
            cst_norm = _normalizar_chave_para_busca(cst)
            if ncm_norm is not None and cst_norm is not None:
                self.pis_cofins_grupos_aceitos.add((ncm_norm, cst_norm))

        self.rejeitados_icms_por_grupo = {
            (
                _normalizar_chave_para_busca(r.ncm),
                _normalizar_chave_para_busca(r.cst),
                _normalizar_chave_para_busca(r.origem_mercadoria_cadastro),
            ): r
            for r in IcmsNcmRejeitado.objects.all()
        }
        self.rejeitados_pis_cofins_por_grupo = {
            (_normalizar_chave_para_busca(r.ncm), _normalizar_chave_para_busca(r.cst)): r
            for r in PisCofinsNcmCstRejeitado.objects.all()
        }

    # Função Objetivo: Motivo de icms_saida_sp estar em branco — None
    # quando não há motivo nenhum (não deveria estar em branco; quem
    # chamou já devia ter conferido que o campo é None antes de perguntar).
    # Explicação em detalhe (13/09/2026): passa a exigir CST e Origem
    # também — desde a mudança de chave do ICMS (ver Decisão no vault),
    # produto sem CST cadastrado não tem mais como ser buscado aqui, igual
    # já acontecia com PIS/COFINS (reaproveita o mesmo MOTIVO_SEM_CST).
    # Origem pode ser None (produto sem impostos_entrada sincronizado) —
    # é um valor de chave válido, nunca bloqueia sozinho.
    def classificar_icms_sp(self, ncm_produto, cst_produto, origem_produto):
        ncm_norm = _normalizar_chave_para_busca(ncm_produto)
        if ncm_norm is None:
            return MotivoFiscal(MOTIVO_SEM_NCM, DESCRICAO_POR_MOTIVO[MOTIVO_SEM_NCM])

        cst_norm = _normalizar_chave_para_busca(cst_produto)
        if cst_norm is None:
            return MotivoFiscal(MOTIVO_SEM_CST, DESCRICAO_POR_MOTIVO[MOTIVO_SEM_CST])

        origem_norm = _normalizar_chave_para_busca(origem_produto)
        chave = (ncm_norm, cst_norm, origem_norm)

        if chave in self.rejeitados_icms_por_grupo:
            return MotivoFiscal(
                MOTIVO_NCM_REJEITADO_ICMS,
                DESCRICAO_POR_MOTIVO[MOTIVO_NCM_REJEITADO_ICMS],
                self.rejeitados_icms_por_grupo[chave],
            )
        if chave not in self.icms_valores_por_grupo:
            return MotivoFiscal(MOTIVO_NCM_NUNCA_IMPORTADO_ICMS, DESCRICAO_POR_MOTIVO[MOTIVO_NCM_NUNCA_IMPORTADO_ICMS])
        return None

    # Função Objetivo: Motivo de icms_saida_media estar em branco.
    # Explicação em detalhe: qualquer motivo que já explica o SP em branco
    # (sem NCM / rejeitado / nunca importado) TAMBÉM explica a Média —
    # sem SP, não tem como calcular Média (calcular_media_ponderada exige
    # sp is not None). Mas o INVERSO não é verdade: um NCM pode estar
    # ACEITO e com SP preenchido, e ainda assim a Média ficar em branco —
    # quando nenhuma das outras 26 UFs tem alíquota suficiente pra
    # calcular (produto genuinamente isento nelas). Esse caso é uma 4ª
    # situação, distinta de rejeição/nunca-importado, adicionada nesta
    # camada (13/09/2026) porque validar_impostos_saida.py, antes desta
    # correção, só classificava o motivo olhando pra SP — Média em branco
    # por essa razão específica ficava sem motivo NENHUM registrado em
    # lugar algum, o mesmo tipo de lacuna que motivou toda essa auditoria.
    def classificar_icms_media(self, ncm_produto, cst_produto, origem_produto):
        motivo_base = self.classificar_icms_sp(ncm_produto, cst_produto, origem_produto)
        if motivo_base is not None:
            return motivo_base

        ncm_norm = _normalizar_chave_para_busca(ncm_produto)
        cst_norm = _normalizar_chave_para_busca(cst_produto)
        origem_norm = _normalizar_chave_para_busca(origem_produto)
        valores_por_uf = self.icms_valores_por_grupo.get((ncm_norm, cst_norm, origem_norm))
        if valores_por_uf and calcular_media_ponderada(valores_por_uf) is None:
            return MotivoFiscal(
                MOTIVO_ICMS_MEDIA_SEM_COBERTURA_UFS, DESCRICAO_POR_MOTIVO[MOTIVO_ICMS_MEDIA_SEM_COBERTURA_UFS],
            )
        return None

    # Função Objetivo: Motivo de pis_percentual/cofins_percentual estarem
    # em branco — os 2 campos sempre vêm juntos (ver
    # ImportadorImpostosSaida._calcular_campos_por_tabela, que só entra
    # com os 2 preenchidos ou nenhum), por isso 1 classificação só serve
    # pros 2, igual ao comportamento já existente em validar_impostos_saida.py.
    def classificar_pis_cofins(self, ncm_produto, cst_produto):
        cst_norm = _normalizar_chave_para_busca(cst_produto)
        if cst_norm is None:
            return MotivoFiscal(MOTIVO_SEM_CST, DESCRICAO_POR_MOTIVO[MOTIVO_SEM_CST])

        ncm_norm = _normalizar_chave_para_busca(ncm_produto)
        if ncm_norm is None:
            return None  # sem NCM também impede PIS/COFINS, mas quem chama já filtrou por icms_sp nesse caso

        if (ncm_norm, cst_norm) in self.rejeitados_pis_cofins_por_grupo:
            return MotivoFiscal(
                MOTIVO_NCM_CST_REJEITADO_PIS_COFINS,
                DESCRICAO_POR_MOTIVO[MOTIVO_NCM_CST_REJEITADO_PIS_COFINS],
                self.rejeitados_pis_cofins_por_grupo[(ncm_norm, cst_norm)],
            )
        if (ncm_norm, cst_norm) not in self.pis_cofins_grupos_aceitos:
            return MotivoFiscal(
                MOTIVO_NCM_CST_NUNCA_IMPORTADO_PIS_COFINS,
                DESCRICAO_POR_MOTIVO[MOTIVO_NCM_CST_NUNCA_IMPORTADO_PIS_COFINS],
            )
        return None