// * [RESUMO] → Funções compartilhadas do DataTables.
//              Usadas por todas as telas que utilizam tabelas no sistema.

// * [EXPLICAÇÃO] → ID da tabela ativa na página — usado pelas funções de coluna.
var TABELA_ATIVA = null;

// ================================================
// INICIALIZAÇÃO
// ================================================

// * [EXPLICAÇÃO] → Comparador personalizado para ordenação de strings.
//                  Remove acentos antes de comparar — garante que "Ó" venha
//                  junto de "O" e não após "Z". Vazios sempre vêm primeiro.
jQuery.extend(jQuery.fn.dataTableExt.oSort, {
    'pt-string-asc': function (a, b) {
        if (a === '' || a === null) return -1;
        if (b === '' || b === null) return 1;
        a = a.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
        b = b.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
        return a < b ? -1 : a > b ? 1 : 0;
    },
    'pt-string-desc': function (a, b) {
        if (a === '' || a === null) return 1;
        if (b === '' || b === null) return -1;
        a = a.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
        b = b.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
        return a < b ? 1 : a > b ? -1 : 0;
    }
});

// * [EXPLICAÇÃO] → Inicializa o DataTables com configurações padrão em português.
//                  Cada página passa suas próprias opções que sobrescrevem o padrão.
function inicializar_tabela(tableId, opcoes) {
    TABELA_ATIVA = tableId;

    var config = Object.assign({
        // scrollX: true,
        autoWidth: false,
        language: {
            emptyTable: 'Nenhum registro encontrado',
            info: 'Mostrando _START_ até _END_ de _TOTAL_ registros',
            infoEmpty: 'Mostrando 0 até 0 de 0 registros',
            infoFiltered: '(filtrado de _MAX_ registros no total)',
            lengthMenu: 'Exibir _MENU_ resultados por página',
            loadingRecords: 'Carregando...',
            processing: 'Processando...',
            search: 'Buscar:',
            zeroRecords: 'Nenhum registro encontrado',
            paginate: {
                first: 'Primeiro',
                last: 'Último',
                next: 'Próximo',
                previous: 'Anterior'
            },
            searchPanes: {
                clearMessage: 'Limpar',
                collapse: 'Filtros',
                count: '{total}',
                countFiltered: '{shown} de {total}',
                emptyMessage: 'Sem dados',
                loadMessage: 'Carregando...',
                title: 'Filtros Ativos - %d',
                collapseMessage: 'Recolher tudo',
                showMessage: 'Mostrar tudo',
                clearMessage: 'Limpar tudo'
            },
        }
    }, opcoes);

    // * [EXPLICAÇÃO] → Após inicializar, aplica a visibilidade inicial das colunas
    //                  baseada nos botões marcados como not_active.
    config.initComplete = function () {
        var botoes = document.getElementsByClassName('not_active');
        for (const botao of botoes) {
            fnShowHide(botao.id, false);
        }
        if (opcoes && opcoes.initComplete) {
            opcoes.initComplete.call(this);
        }
    };

    $(tableId).DataTable(config);
}

// ================================================
// VISIBILIDADE DE COLUNAS
// ================================================

// * [EXPLICAÇÃO] → Mostra ou oculta uma coluna pelo índice do botão.
//                  O índice do botão corresponde ao número da coluna (1-based).
function fnShowHide(iCol, toggle = null) {
    var colIndex = parseInt(iCol) - 1;
    var oTable = $(TABELA_ATIVA).dataTable();

    if (toggle === null) {
        var bVis = oTable.fnSettings().aoColumns[colIndex].bVisible;
        oTable.fnSetColumnVis(colIndex, !bVis);
    } else {
        oTable.fnSetColumnVis(colIndex, toggle);
    }
}

// * [EXPLICAÇÃO] → Alterna o estado do botão entre active/not_active
//                  e chama fnShowHide para atualizar a visibilidade da coluna.
function mudar(botao) {
    if (botao.classList.contains('btn-ativo')) {
        botao.classList.remove('btn-ativo');
        botao.classList.add('btn-inativo', 'not_active');
    } else {
        botao.classList.remove('btn-inativo', 'not_active');
        botao.classList.add('btn-ativo');
    }
    fnShowHide(botao.id);
}

// ================================================
// PAINEL DE COLUNAS
// ================================================

// * [EXPLICAÇÃO] → Mostra ou oculta o painel de opções de colunas.
var painelAberto = false;

function opcoes_exibicao() {
    var painel = document.getElementById('painel-colunas');
    if (painelAberto) {
        painel.style.display = 'none';
        painelAberto = false;
    } else {
        painel.style.display = 'block';
        painelAberto = true;
    }
}