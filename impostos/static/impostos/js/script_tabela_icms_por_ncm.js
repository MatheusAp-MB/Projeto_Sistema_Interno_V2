// * [RESUMO] → Script da tela de ICMS por NCM.
//              Gerencia a calculadora e o destaque da célula
//              correspondente na matriz — mesmo padrão da Tabela de
//              Frete do ML (script_tabela_frete_ml.js).

function limpar_destaque() {
    document.querySelectorAll('.destaque, .destaque-linha, .destaque-coluna').forEach(function(el) {
        el.classList.remove('destaque', 'destaque-linha', 'destaque-coluna');
    });
}

function ajustar_altura_grade() {
    var container = document.querySelector('.grade-container');
    if (!container) return;
    var distanciaDoTopo = container.getBoundingClientRect().top;
    var margemInferior = 24;
    container.style.maxHeight = (window.innerHeight - distanciaDoTopo - margemInferior) + 'px';
}

ajustar_altura_grade();
window.addEventListener('resize', ajustar_altura_grade);

// Função Objetivo: Rola o container até a célula ficar visível, descontando
// o espaço do cabeçalho fixo (topo) e da coluna do NCM fixa (esquerda).
// Explicação em detalhe: scrollIntoView() nativo não sabe que esses 2
// elementos são sticky — ele calcula a posição "crua" da célula, sem
// descontar o que fica coberto pelos painéis fixos, e erra a rolagem
// (às vezes nem rola). Por isso calculamos a rolagem manualmente aqui.
function rolar_para_celula(celula, container) {
    var thHeader = document.querySelector('.grade-tabela thead th');
    var tdNcm = document.querySelector('.grade-tabela td.col-ncm');
    if (!thHeader || !tdNcm) return;

    var alturaCabecalho = thHeader.getBoundingClientRect().height;
    var larguraColunaNcm = tdNcm.getBoundingClientRect().width;

    var containerRect = container.getBoundingClientRect();
    var celulaRect = celula.getBoundingClientRect();

    var areaVisivelTop = containerRect.top + alturaCabecalho;
    var areaVisivelLeft = containerRect.left + larguraColunaNcm;
    var areaVisivelBottom = containerRect.bottom;
    var areaVisivelRight = containerRect.right;

    var deltaX = 0;
    var deltaY = 0;

    if (celulaRect.left < areaVisivelLeft) {
        deltaX = celulaRect.left - areaVisivelLeft;
    } else if (celulaRect.right > areaVisivelRight) {
        deltaX = celulaRect.right - areaVisivelRight;
    }

    if (celulaRect.top < areaVisivelTop) {
        deltaY = celulaRect.top - areaVisivelTop;
    } else if (celulaRect.bottom > areaVisivelBottom) {
        deltaY = celulaRect.bottom - areaVisivelBottom;
    }

    if (deltaX !== 0 || deltaY !== 0) {
        container.scrollBy({ left: deltaX, top: deltaY, behavior: 'smooth' });
    }
}

function destacar_celula(ncm, uf) {
    limpar_destaque();

    var celula = document.querySelector(
        `td[data-ncm="${ncm}"][data-uf="${uf}"]`
    );
    if (!celula) return;

    celula.classList.add('destaque');

    var container = document.querySelector('.grade-container');
    if (container) {
        rolar_para_celula(celula, container);
    }

    var linha = celula.parentElement;
    var colIndex = Array.from(linha.children).indexOf(celula);
    Array.from(linha.children).slice(0, colIndex).forEach(function(td) {
        td.classList.add('destaque-linha');
    });

    var tabela = celula.closest('table');
    var linhaIndex = Array.from(tabela.querySelectorAll('tbody tr')).indexOf(linha);
    tabela.querySelectorAll('tbody tr').forEach(function(tr, i) {
        if (i < linhaIndex) {
            var td = tr.children[colIndex];
            if (td) td.classList.add('destaque-coluna');
        }
    });

    var ths = tabela.querySelectorAll('thead th');
    if (ths[colIndex]) ths[colIndex].classList.add('destaque');

    var tdsNcm = linha.querySelectorAll('td.col-ncm');
    tdsNcm.forEach(function(td) { td.classList.add('destaque'); });
}