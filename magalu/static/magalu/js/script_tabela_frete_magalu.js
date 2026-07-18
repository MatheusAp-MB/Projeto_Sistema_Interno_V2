// * [RESUMO] → Script da tela de tabela de frete do Magalu.
//              Gerencia a calculadora e o destaque da linha/coluna
//              correspondente na lista — mais simples que o do ML
//              (lista, não matriz).

function limpar_destaque() {
    document.querySelectorAll('.destaque, .destaque-linha').forEach(function(el) {
        el.classList.remove('destaque', 'destaque-linha');
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

function destacar_linha(peso_min, reputacao) {
    limpar_destaque();

    var linha = document.querySelector(`tr[data-peso-min="${peso_min}"]`);
    if (!linha) return;

    linha.scrollIntoView({ behavior: 'smooth', block: 'center' });

    // * [EXPLICAÇÃO] → Só marca as colunas de peso (sinal de "essa é a
    //                  linha", sem colorir fundo) — o destaque de cor
    //                  de verdade fica só na célula do valor calculado.
    linha.querySelectorAll('td.col-peso').forEach(function(td) {
        td.classList.add('destaque-linha');
    });

    var celula = linha.querySelector(`td[data-reputacao="${reputacao}"]`);
    if (celula) celula.classList.add('destaque');
}