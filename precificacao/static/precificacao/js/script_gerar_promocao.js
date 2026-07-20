// * [RESUMO] → Utilitário compartilhado: botão "Selecionar/Desmarcar tudo" e
// lista de chips de marcas selecionadas — usado em qualquer tela com o painel
// de marcas (Promoção Shopee/TikTok, Exportar Precificação).

function marcarTodasMarcas(botao) {
    var caixas = botao.closest('form').querySelectorAll('input[name="marca"]');
    var todasMarcadas = Array.from(caixas).every(function (c) { return c.checked; });
    caixas.forEach(function (c) { c.checked = !todasMarcadas; });
    botao.textContent = todasMarcadas ? 'Selecionar tudo' : 'Desmarcar tudo';
    atualizarChipsMarca();
}

function atualizarChipsMarca() {
    var caixas = document.querySelectorAll('input[name="marca"]:checked');
    var lista = document.getElementById('lista-chips-marcas');
    var contador = document.getElementById('contador-marcas');

    contador.textContent = caixas.length;

    if (caixas.length === 0) {
        lista.innerHTML = '<span class="promocao-chips-vazio">Nenhuma marca selecionada ainda.</span>';
        return;
    }

    lista.innerHTML = '';
    caixas.forEach(function (caixa) {
        var chip = document.createElement('span');
        chip.className = 'promocao-chip';
        chip.textContent = caixa.value;

        var remover = document.createElement('button');
        remover.type = 'button';
        remover.className = 'promocao-chip-remover';
        remover.innerHTML = '&times;';
        remover.onclick = function () {
            caixa.checked = false;
            atualizarChipsMarca();
        };

        chip.appendChild(remover);
        lista.appendChild(chip);
    });

    // * [EXPLICAÇÃO] → Se a página já carregou com marcas pré-marcadas
    //                  (ex: reabriu depois de um erro), sincroniza os
    //                  chips assim que o script carrega.
}

document.addEventListener('DOMContentLoaded', atualizarChipsMarca);