// * [RESUMO] → Script da tela de Recomendação de Precificação.
//              2 responsabilidades: (1) seletor de comportamento
//              reenvia o formulário ao trocar; (2) cabeçalhos de
//              tabela ordenam as linhas por coluna (A-Z/Z-A), usando
//              o atributo data-valor de cada célula (não o texto
//              exibido, pra números/datas ordenarem certo).

document.addEventListener('DOMContentLoaded', function () {

    // ================================================
    // SELETOR DE COMPORTAMENTO
    // ================================================
    var seletor = document.getElementById('select-comportamento');
    if (seletor) {
        seletor.addEventListener('change', function () {
            document.getElementById('form-comportamento').submit();
        });
    }

    // ================================================
    // ORDENAÇÃO DE TABELA POR COLUNA
    // ================================================
    document.querySelectorAll('.recpreco-th-ordenavel').forEach(function (th) {
        th.addEventListener('click', function () {
            ordenar_tabela_por_coluna(th);
        });
    });
});

function ordenar_tabela_por_coluna(th) {
    var tabela = th.closest('table');
    var tbody = tabela.querySelector('tbody');
    var indiceColuna = Array.from(th.parentElement.children).indexOf(th);

    // * [EXPLICAÇÃO] → Alterna asc/desc ao clicar de novo na mesma
    //                  coluna; clicar numa coluna diferente sempre
    //                  começa ascendente.
    var estaAscendente = th.classList.contains('recpreco-ordenado-asc');
    var novaDirecao = estaAscendente ? 'desc' : 'asc';

    tabela.querySelectorAll('.recpreco-th-ordenavel').forEach(function (outroTh) {
        outroTh.classList.remove('recpreco-ordenado-asc', 'recpreco-ordenado-desc');
    });
    th.classList.add(novaDirecao === 'asc' ? 'recpreco-ordenado-asc' : 'recpreco-ordenado-desc');

    var linhas = Array.from(tbody.querySelectorAll('tr'));

    linhas.sort(function (linhaA, linhaB) {
        var valorA = linhaA.children[indiceColuna].getAttribute('data-valor');
        var valorB = linhaB.children[indiceColuna].getAttribute('data-valor');

        var numA = parseFloat(valorA);
        var numB = parseFloat(valorB);
        var saoNumeros = !isNaN(numA) && !isNaN(numB);

        var comparacao;
        if (saoNumeros) {
            comparacao = numA - numB;
        } else {
            comparacao = valorA.localeCompare(valorB, 'pt-BR');
        }

        return novaDirecao === 'asc' ? comparacao : -comparacao;
    });

    linhas.forEach(function (linha) {
        tbody.appendChild(linha);
    });
}