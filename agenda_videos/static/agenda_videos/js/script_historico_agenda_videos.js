// * [EXPLICAÇÃO] → Pills de resumo do modal de Histórico (26/07) — clicar
//                  filtra a trilha só pro status daquele pill; clicar de novo
//                  desfaz. Só JS puro, sem ida ao servidor — os dados já
//                  estão todos carregados na página, é só esconder/mostrar.
//                  Escopado a .modal-historico-caixa de propósito — o
//                  relatório geral também tem pills de resumo, mas eles
//                  moram dentro de um <summary>, e tornar eles clicáveis
//                  aqui entraria em conflito com o abrir/fechar do <details>.
document.body.addEventListener('click', function (evento) {
    var pill = evento.target.closest('[data-historico-pill]');
    if (!pill) return;

    var caixa = pill.closest('.modal-historico-caixa');
    if (!caixa) return;

    var lista = caixa.querySelector('.historico-lista');
    if (!lista) return;

    var tipo = pill.dataset.historicoPill;
    var jaAtivo = pill.classList.contains('historico-pill-ativo');

    caixa.querySelectorAll('[data-historico-pill]').forEach(function (p) {
        p.classList.remove('historico-pill-ativo');
    });
    lista.querySelectorAll('.historico-evento').forEach(function (item) {
        item.style.display = '';
    });

    if (!jaAtivo) {
        pill.classList.add('historico-pill-ativo');
        lista.querySelectorAll('.historico-evento').forEach(function (item) {
            if (!item.classList.contains('historico-evento--' + tipo)) {
                item.style.display = 'none';
            }
        });
    }
});

// * [EXPLICAÇÃO] → Expandir/colapsar o detalhe de "Replicado" (30/07) —
//                  mesmo padrão de delegação acima: só alterna uma classe,
//                  os MLBs já vêm carregados no HTML (nenhuma ida ao
//                  servidor).
document.body.addEventListener('click', function (evento) {
    var corpo = evento.target.closest('[data-historico-expandir]');
    if (!corpo) return;

    var item = corpo.closest('.historico-evento');
    if (!item) return;

    item.classList.toggle('historico-evento--aberto');
});