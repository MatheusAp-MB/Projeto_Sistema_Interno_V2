// mercado_livre/static/mercado_livre/js/script_categorias_ml.js
//
// * [RESUMO] → Tela de Categorias ML. Buscar e carregar filhos/detalhe
//              já é feito pelo HTMX (hx-get direto nos elementos, ver
//              os parciais). Este arquivo cuida do que é puramente
//              visual e não pede nada ao servidor:
//              - abrir/fechar um card já carregado (conteúdo fica em
//                cache no DOM — só é buscado 1 vez, hx-trigger="click
//                once");
//              - acordeão exclusivo: abrir um card fecha o irmão que
//                estava aberto no MESMO grupo (mesma grade), em
//                qualquer nível — evita vários ramos abertos ao mesmo
//                tempo brigando por espaço na tela;
//              - "Recolher tudo".

function alternarCategoria(botao) {
    var alvo = document.getElementById('fc-' + botao.dataset.cardId);
    if (!alvo) return;

    var vaiAbrir = alvo.hidden;

    // Acordeão exclusivo: antes de abrir, fecha qualquer irmão do
    // MESMO grupo que já esteja aberto (":scope >" pega só os cards
    // direto dentro dessa grade — não mexe em ramos de outras
    // categorias, mesmo que estejam abertos em outro lugar da tela).
    if (vaiAbrir) {
        var grade = botao.closest('.grade-categorias');
        if (grade) {
            grade.querySelectorAll(':scope > .cartao-cat.expandido').forEach(function (irmao) {
                if (irmao !== botao) fecharCategoria(irmao);
            });
        }
    }

    alvo.hidden = !vaiAbrir;
    botao.classList.toggle('expandido', vaiAbrir);
    var chevron = botao.querySelector('.chevron');
    if (chevron) chevron.classList.toggle('aberto', vaiAbrir);
}

function fecharCategoria(botao) {
    var alvo = document.getElementById('fc-' + botao.dataset.cardId);
    if (alvo) alvo.hidden = true;
    botao.classList.remove('expandido');
    var chevron = botao.querySelector('.chevron');
    if (chevron) chevron.classList.remove('aberto');
}

function recolherTudoCategorias() {
    document.querySelectorAll('#categorias-conteudo .grupo-filhos:not([hidden])').forEach(function (div) {
        div.hidden = true;
    });
    document.querySelectorAll('#categorias-conteudo .cartao-cat.expandido').forEach(function (botao) {
        botao.classList.remove('expandido');
        var chevron = botao.querySelector('.chevron');
        if (chevron) chevron.classList.remove('aberto');
    });
}