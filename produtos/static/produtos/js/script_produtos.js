// * [RESUMO] → Script da tela de Produtos.
//              DataTables removido — filtros e paginação agora são
//              resolvidos no servidor (mesma arquitetura do Hub e da
//              Resumo de Critérios). Este arquivo cuida só de: toggle
//              de coluna, busca interna dos filtros, e abertura do
//              modal de detalhes (HTMX + Bootstrap).

// ================================================
// TOGGLE DE COLUNA
// ================================================

// * [EXPLICAÇÃO] → O id do botão é o número da coluna (1 = primeira,
//                  2 = segunda, etc — bate com a ordem das colunas na
//                  tabela). Esconde/mostra o <th> e todos os <td> dessa
//                  posição, em todas as linhas.
function alternar_coluna_produtos(botao) {
    var indice = parseInt(botao.id, 10);

    document.querySelectorAll('.produtos-tabela thead tr, .produtos-tabela tbody tr').forEach(function (linha) {
        var celula = linha.children[indice - 1];
        if (celula) celula.classList.toggle('coluna-oculta');
    });

    botao.classList.toggle('btn-ativo');
    botao.classList.toggle('btn-inativo');
}

// * [EXPLICAÇÃO] → Aplica o estado inicial (colunas que já nascem
//                  ocultas) lendo direto dos botões marcados como
//                  "not_active" no HTML — não repete os números em
//                  outro lugar, uma fonte só de verdade.
$(document).ready(function () {
    document.querySelectorAll('#painel-colunas .btn-inativo.not_active').forEach(function (botao) {
        var indice = parseInt(botao.id, 10);
        document.querySelectorAll('.produtos-tabela thead tr, .produtos-tabela tbody tr').forEach(function (linha) {
            var celula = linha.children[indice - 1];
            if (celula) celula.classList.add('coluna-oculta');
        });
    });
});

// ================================================
// BUSCA INTERNA DOS FILTROS (Marca, Categoria)
// ================================================

document.addEventListener('input', function (evento) {
    var campo = evento.target.closest('.filtro-busca-interna');
    if (!campo) return;

    var termo = campo.value.trim().toLowerCase();
    var lista = campo.closest('.filtro-subgrupo').querySelector('.filtro-opcoes-lista');

    lista.querySelectorAll('.filtro-opcao').forEach(function (opcao) {
        var texto = opcao.textContent.trim().toLowerCase();
        opcao.style.display = texto.indexOf(termo) !== -1 ? '' : 'none';
    });
});

// ================================================
// MODAL
// ================================================

// * [EXPLICAÇÃO] → Abre o modal do Bootstrap após o HTMX injetar o conteúdo.
//                  O setTimeout garante que o HTMX terminou o swap antes de abrir.
function abrirModal() {
    setTimeout(function () {
        var modal = new bootstrap.Modal(document.getElementById('modal-produto'));
        modal.show();
        inicializarPopoversDeCalculo();
    }, 100);
}

// * [EXPLICAÇÃO] → Popover não se auto-inicializa por atributo (diferente
//                  da Tab, que já vem com delegação global do próprio
//                  Bootstrap) — precisa de "new bootstrap.Popover(...)" por
//                  elemento, toda vez que o HTMX troca o conteúdo do modal
//                  (aba Impostos, ícone de calculadora em cada valor
//                  calculado). Reaproveita o mesmo timing do abrirModal.
function inicializarPopoversDeCalculo() {
    document.querySelectorAll('#aba-impostos [data-bs-toggle="popover"]').forEach(function (elemento) {
        new bootstrap.Popover(elemento);
    });
}