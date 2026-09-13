# impostos/management/commands/preencher_CST_produtos.py

from core.management.commands._base_empresa import ComandoComEmpresa
from impostos.funcoes_auxiliares.saida.preenchimento_cst_produtos import preencher_cst_produtos


class Command(ComandoComEmpresa):
    help = (
        'Lê CST da planilha Busca Legal (por EAN) e grava só Produto.cst_saida — Passo 1 do fluxo '
        'de 4 comandos auto-suficientes. Único lugar do sistema que lê essa coluna; os demais '
        'comandos (importar_icms_por_ncm, importar_pis_cofins_por_ncm_cst) leem cst_saida daqui.'
    )

    def handle(self, *args, **options):
        preencher_cst_produtos(self.stdout, self.style)