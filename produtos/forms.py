# produtos/forms.py

# Função Objetivo: Formulários do app Produtos. Hoje só existe 1: o do cartão "Financeiro" do
# painel do produto, que edita o Frete Fornecedor. É o ÚNICO campo do cadastro editável pela
# tela — o resto vem do ERP/importações (ver CAMPOS_PRODUTO em importar_produtos_erp.py).

from decimal import Decimal

from django import forms

from .models import Produto

# * [EXPLICAÇÃO] → Faixa válida do Frete Fornecedor: é um PERCENTUAL do custo do produto, então vai
#                  de 0 (sem frete) a 100. A regra mora AQUI (dono único); a definição do campo no
#                  banco continua a mesma de antes do rename (ver comentário no model).
FRETE_FORNECEDOR_MINIMO = Decimal('0')
FRETE_FORNECEDOR_MAXIMO = Decimal('100')


# Função Objetivo: Valida e prepara o Frete Fornecedor digitado no cartão Financeiro.
class FormularioFreteFornecedor(forms.ModelForm):
    # * [EXPLICAÇÃO] → localize=True: aceita e mostra a vírgula decimal ("3,50"), igual ao resto das
    #                  telas. Também aceita ponto ("3.50"). max_digits=5 / decimal_places=2 cobrem 0 a
    #                  100,00 com 2 casas — o mesmo limite de casas do campo no banco.
    frete_fornecedor = forms.DecimalField(
        label='Frete Fornecedor (%)',
        min_value=FRETE_FORNECEDOR_MINIMO, max_value=FRETE_FORNECEDOR_MAXIMO,
        max_digits=5, decimal_places=2, localize=True,
        widget=forms.TextInput(attrs={
            'id': 'campo-frete-fornecedor',
            'class': 'modal-form-frete-input',
            'inputmode': 'decimal',
            'autocomplete': 'off',
        }),
        error_messages={
            'required': 'Informe o percentual (use 0 quando não houver frete).',
            'invalid': 'Informe um número, por exemplo 3,50.',
            'min_value': 'O percentual não pode ser negativo.',
            # * [EXPLICAÇÃO] → O Django aplica "mensagem % params" nestas mensagens: um "%" solto quebra
            #                  (ValueError). Por isso "%%" literal e o limite vem do próprio validador.
            'max_value': 'O percentual não pode passar de %(limit_value)s%%.',
            'max_decimal_places': 'Use no máximo 2 casas decimais.',
            'max_digits': 'Percentual fora da faixa de 0 a 100.',
            'max_whole_digits': 'Percentual fora da faixa de 0 a 100.',
        },
    )

    class Meta:
        model = Produto
        fields = ['frete_fornecedor']