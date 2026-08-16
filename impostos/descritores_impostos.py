# impostos/descritores_impostos.py

# Função Objetivo: Descreve o que cada 1 dos 6 impostos de entrada TEM —
# única fonte dessa informação, usada tanto pra gravar (sincronizacao_
# impostos_entrada.py) quanto pra exibir (exibicao_impostos_entrada.py).
#
# Os 6 impostos são parecidos (todos têm base_calculo e valor) mas não
# idênticos — cada um pode ou não ter alíquota, CST, redução ou FCP. Em
# vez de repetir "se for ICMS faça X, se for IPI faça Y" nos 2 lugares
# (gravar e exibir), esta tabela guarda a diferença como booleano simples,
# e quem usa faz 1 loop só.

from __future__ import annotations

from dataclasses import dataclass

from django.db import models

from impostos.models import (
    CofinsEntradaProduto,
    IcmsEntradaProduto,
    IcmsRetEntradaProduto,
    IcmsStEntradaProduto,
    IpiEntradaProduto,
    PisEntradaProduto,
)


@dataclass(frozen=True)
class DescritorImposto:
    # Função Objetivo: O "molde" de 1 imposto — imutável, é uma descrição
    # fixa da regra fiscal, não um dado que muda.

    nome_para_exibicao: str

    # Nome do atributo dentro de DadosXmlNF onde este imposto mora (ex:
    # 'icms') — usado como getattr(dados, este_nome) ao gravar.
    nome_do_atributo_em_dados_xml: str

    # Nome do related_name no guarda-chuva (ex: self.icms, self.icms_st) —
    # usado como getattr(guarda_chuva, este_nome) ao exibir.
    nome_do_related_name_no_banco: str

    classe_do_model_no_banco: type[models.Model]

    possui_aliquota: bool
    possui_cst: bool
    possui_reducao: bool
    possui_fcp: bool

    # PIS e COFINS são os únicos 2 cuja redução não vem pronta no XML — é
    # calculada aqui no sistema (Base de Cálculo ÷ Custo Total). Esta flag
    # só controla o popover de explicação no modal, nunca a gravação.
    a_reducao_e_calculada_no_sistema: bool = False


DESCRITORES_IMPOSTOS: tuple[DescritorImposto, ...] = (
    DescritorImposto(
        nome_para_exibicao='ICMS',
        nome_do_atributo_em_dados_xml='icms',
        nome_do_related_name_no_banco='icms',
        classe_do_model_no_banco=IcmsEntradaProduto,
        possui_aliquota=True,
        possui_cst=True,
        possui_reducao=True,
        possui_fcp=False,
    ),

    DescritorImposto(
        nome_para_exibicao='ICMS ST',
        nome_do_atributo_em_dados_xml='icms_st',
        nome_do_related_name_no_banco='icms_st',
        classe_do_model_no_banco=IcmsStEntradaProduto,
        possui_aliquota=True,
        possui_cst=False,
        possui_reducao=True,
        possui_fcp=True,
    ),

    DescritorImposto(
        nome_para_exibicao='ICMS Retido',
        nome_do_atributo_em_dados_xml='icms_ret',
        nome_do_related_name_no_banco='icms_ret',
        classe_do_model_no_banco=IcmsRetEntradaProduto,
        possui_aliquota=False,
        possui_cst=False,
        possui_reducao=False,
        possui_fcp=False,
    ),

    DescritorImposto(
        nome_para_exibicao='IPI',
        nome_do_atributo_em_dados_xml='ipi',
        nome_do_related_name_no_banco='ipi',
        classe_do_model_no_banco=IpiEntradaProduto,
        possui_aliquota=True,
        possui_cst=True,
        possui_reducao=False,
        possui_fcp=False,
    ),

    DescritorImposto(
        nome_para_exibicao='PIS',
        nome_do_atributo_em_dados_xml='pis',
        nome_do_related_name_no_banco='pis',
        classe_do_model_no_banco=PisEntradaProduto,
        possui_aliquota=True,
        possui_cst=True,
        possui_reducao=True,
        possui_fcp=False,
        a_reducao_e_calculada_no_sistema=True,
    ),

    DescritorImposto(
        nome_para_exibicao='COFINS',
        nome_do_atributo_em_dados_xml='cofins',
        nome_do_related_name_no_banco='cofins',
        classe_do_model_no_banco=CofinsEntradaProduto,
        possui_aliquota=True,
        possui_cst=True,
        possui_reducao=True,
        possui_fcp=False,
        a_reducao_e_calculada_no_sistema=True,
    ),
)