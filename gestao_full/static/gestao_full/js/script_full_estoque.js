// gestao_full/static/gestao_full/js/script_full_estoque.js
//
// Tela "Full — Estoque no Full". Faz só duas coisas, e nenhuma delas chama o servidor sozinha:
//   1) abrir/fechar as linhas de Código ML de um produto (a seta da primeira coluna) e "Abrir todos / Fechar todos";
//   2) trocar a ordenação assim que a pessoa escolhe outra no seletor (vai para o endereço que a view já montou).
// Buscar, filtrar e paginar são links e um formulário normais: funcionam sem este arquivo.

(function () {
    'use strict';

    const pagina = document.querySelector('.est-pagina');
    if (!pagina) {
        return;
    }

    // Função Objetivo: Abre ou fecha as linhas de Código ML de UM produto (o <tbody> dele) e acerta o aria-expanded da seta.
    function definirAberto(grupo, aberto) {
        const botao = grupo.querySelector('.est-toggle');
        if (botao) {
            botao.setAttribute('aria-expanded', aberto ? 'true' : 'false');
        }
        grupo.querySelectorAll('.est-linha-codigo').forEach(function (linha) {
            linha.hidden = !aberto;
        });
    }

    pagina.addEventListener('click', function (evento) {
        const seta = evento.target.closest('.est-toggle');
        if (seta && pagina.contains(seta)) {
            const grupo = seta.closest('.est-grupo');
            if (grupo) {
                definirAberto(grupo, seta.getAttribute('aria-expanded') !== 'true');
            }
            return;
        }

        const botao = evento.target.closest('[data-acao]');
        if (botao && pagina.contains(botao)) {
            const abrir = botao.dataset.acao === 'abrir-todos';
            pagina.querySelectorAll('.est-grupo').forEach(function (grupo) {
                definirAberto(grupo, abrir);
            });
        }
    });

    // O valor de cada opção já é o endereço completo (com a busca e o filtro de agora), montado pela view.
    pagina.addEventListener('change', function (evento) {
        const seletor = evento.target.closest('select[data-navegar]');
        if (seletor && seletor.value) {
            window.location.href = seletor.value;
        }
    });
})();
