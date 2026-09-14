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
    // 14/09/2026 — trocado de td.col-ncm pra td.col-cst: desde a 6b, o
    // bloco fixo à esquerda não é mais só o NCM (100px) — é
    // NCM+Origem+CST juntos (~260px). Medir só a largura do NCM
    // subestimava a área coberta, e a rolagem parava cedo demais,
    // deixando a célula alvo escondida atrás de Origem/CST sempre que
    // precisava voltar pra esquerda. td.col-cst é sempre a última
    // coluna do bloco fixo (nunca tem rowspan, existe em toda linha),
    // então a borda direita dela já É o limite real da área visível —
    // sem precisar somar larguras na mão, e sem quebrar de novo se o
    // bloco fixo mudar no futuro.
    var tdCst = document.querySelector('.grade-tabela td.col-cst');
    if (!thHeader || !tdCst) return;

    var alturaCabecalho = thHeader.getBoundingClientRect().height;

    var containerRect = container.getBoundingClientRect();
    var celulaRect = celula.getBoundingClientRect();

    // A borda "crua" do getBoundingClientRect() inclui o espaço da barra
    // de rolagem (ela não sabe que aquele espaço não é conteúdo visível).
    // clientWidth/clientHeight e clientLeft/clientTop já descontam a
    // barra e as bordas — por isso usamos eles pra achar o limite real
    // da área visível, em vez de containerRect.right/bottom direto.
    var areaVisivelTop = containerRect.top + alturaCabecalho;
    var areaVisivelLeft = tdCst.getBoundingClientRect().right;
    var areaVisivelBottom = containerRect.top + container.clientTop + container.clientHeight;
    var areaVisivelRight = containerRect.left + container.clientLeft + container.clientWidth;

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

// Função Objetivo: Destaca a célula da matriz correspondente ao resultado
// da calculadora (linha, coluna, rótulos NCM/Origem/CST e cabeçalho).
// Explicação em detalhe: 14/09/2026 (6b) — trocado de índice de posição
// pra busca por data-col (rowspan quebra a contagem de posição). 14/09/2026
// (6c) — assinatura ganha origem/cst: a busca da célula agora casa pelos
// 4 campos (NCM+Origem+CST+UF), não só NCM+UF — sem isso, um NCM com mais
// de 1 grupo (CST/Origem diferentes) destacava sempre a 1ª célula
// encontrada, ignorando qual grupo o usuário realmente consultou (mesmo
// bug de sobrescrita silenciosa da calculadora, agora corrigido também no
// destaque). origem chega já no formato usado no data-origem da matriz
// (valor real, ou o sentinela __NULL__ pra Origem em branco).
function destacar_celula(ncm, origem, cst, uf) {
    limpar_destaque();

    var celula = document.querySelector(
        `td[data-ncm="${ncm}"][data-origem="${origem}"][data-cst="${cst}"][data-uf="${uf}"]`
    );
    if (!celula) return;

    celula.classList.add('destaque');

    var container = document.querySelector('.grade-container');
    if (container) {
        rolar_para_celula(celula, container);
    }

    var colAlvo = celula.dataset.col;
    var linha = celula.parentElement;

    // destaque-linha: toda célula da MESMA linha que vem ANTES da coluna
    // alvo, na ordem em que aparece no HTML (não depende de índice fixo).
    var vistaColunaAlvo = false;
    Array.from(linha.children).forEach(function(td) {
        if (td.dataset.col === colAlvo) {
            vistaColunaAlvo = true;
            return;
        }
        if (!vistaColunaAlvo) td.classList.add('destaque-linha');
    });

    // destaque-coluna: mesma coluna (mesmo data-col) nas linhas ACIMA.
    var tabela = celula.closest('table');
    var linhasCorpo = Array.from(tabela.querySelectorAll('tbody tr'));
    var linhaIndex = linhasCorpo.indexOf(linha);
    linhasCorpo.forEach(function(tr, i) {
        if (i < linhaIndex) {
            var td = tr.querySelector(`[data-col="${colAlvo}"]`);
            if (td) td.classList.add('destaque-coluna');
        }
    });

    var ths = tabela.querySelectorAll('thead th');
    ths.forEach(function(th) {
        if (th.dataset.col === colAlvo) th.classList.add('destaque');
    });

    // Rótulos do grupo (NCM/Origem/CST): com rowspan, a linha clicada pode
    // não ser a "dona" da célula mesclada — sobe linha por linha até
    // achar quem realmente renderiza aquele rótulo (mesma busca "pra
    // trás" descrita no Mockup 2 aprovado).
    ['ncm', 'origem', 'cst'].forEach(function(colRotulo) {
        var i = linhaIndex;
        while (i >= 0) {
            var td = linhasCorpo[i].querySelector(`[data-col="${colRotulo}"]`);
            if (td) {
                td.classList.add('destaque');
                break;
            }
            i--;
        }
    });
}