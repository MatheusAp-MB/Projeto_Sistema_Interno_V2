// * [RESUMO] → Script da tela de produtos.
//              Inicializa o DataTables e gerencia modal, filtros e toggle do SearchPanes.

// ================================================
// DATATABLES
// ================================================
$(document).ready(function () {
    inicializar_tabela('#tabela-produtos', {
        autoWidth: true,
        dom: 'Plfrtip',
        searchPanes: {
            layout: 'columns-4',
            threshold: 1,
        },
        columnDefs: [
            { type: 'pt-string', targets: [1, 2, 3, 4, 5, 7, 15, 26] },
            {
                targets: 0,
                render: function (data, type, row) {
                    if (type === 'display') {
                        return data;
                    }
                    return data.indexOf('miniatura-vazia') === -1 ? 'Com foto' : 'Sem foto';
                },
                searchPanes: {
                    show: true,
                    options: [
                        {
                            label: 'Com foto',
                            value: function (rowData, rowIdx) {
                                return String(rowData[0]).indexOf('miniatura-vazia') === -1;
                            }
                        },
                        {
                            label: 'Sem foto',
                            value: function (rowData, rowIdx) {
                                return String(rowData[0]).indexOf('miniatura-vazia') !== -1;
                            }
                        }
                    ]
                }
            },
            { searchPanes: { show: true }, targets: '_all' },
        ]
    });

    // * [EXPLICAÇÃO] → Atualiza o texto de filtros ativos a cada redraw da tabela.
    $('#tabela-produtos').on('draw.dt', function () {
        atualizar_filtros_ativos();
    });

    // * [EXPLICAÇÃO] → Abre o painel brevemente para o SearchPanes calcular
    //                  as larguras corretamente, depois recolhe e esconde.
    setTimeout(function () {
        $('.dtsp-panesContainer').show();
        $(window).trigger('resize');
        setTimeout(function () {
            $('.dtsp-panesContainer').hide();
        }, 100);
    }, 200);
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
    }, 100);
}

// ================================================
// TOGGLE DO SEARCHPANES
// ================================================

// * [EXPLICAÇÃO] → Controla a visibilidade do painel de filtros SearchPanes.
var filtrosAbertos = false;

function toggle_filtros() {
    var painel = document.querySelector('.dtsp-panesContainer');
    var caret = document.getElementById('btn-filtros-caret');

    if (filtrosAbertos) {
        $(painel).hide();
        caret.textContent = '▼';
        filtrosAbertos = false;
    } else {
        $(painel).show();
        caret.textContent = '▲';
        filtrosAbertos = true;
        $(window).trigger('resize');

        // * [EXPLICAÇÃO] → Recolhe todos os painéis individuais clicando no botão ^
        //                  de cada um. O delay garante que o resize foi processado.
        setTimeout(function () {
            $('.dtsp-collapseButton').each(function () {
                var pane = $(this).closest('.dtsp-searchPane');
                var temFiltroAtivo = pane.find('tr.selected').length > 0;
                var estaAberto = !pane.find('.dataTables_scrollBody').is(':hidden');

                if (estaAberto && !temFiltroAtivo) {
                    $(this).trigger('click');
                }
            });
        }, 100);
    }
}
// ================================================
// FILTROS ATIVOS
// ================================================

// * [EXPLICAÇÃO] → Lê os painéis do SearchPanes e monta a string de filtros ativos.
//                  Exibe no formato: Filtros ativos → Marca = ORTHO | Categoria = SAÚDE
function atualizar_filtros_ativos() {
    var filtros = [];

    $('.dtsp-searchPane').each(function () {
        var coluna = $(this).find('.dtsp-search').attr('placeholder');
        var valores = [];

        $(this).find('tr.selected .dtsp-name').each(function () {
            valores.push($(this).attr('title') || $(this).text());
        });

        if (valores.length > 0) {
            filtros.push('<strong>' + coluna + '</strong> = ' + valores.join(', '));
        }
    });

    var texto = document.getElementById('filtros-ativos-texto');
    if (filtros.length > 0) {
        texto.innerHTML = 'Filtros ativos → ' + filtros.join(' &nbsp;|&nbsp; ');
    } else {
        texto.textContent = 'Nenhum filtro ativo';
    }
}