/* gestao_ruptura/static/gestao_ruptura/js/script_ruptura.js
 *
 * [RESUMO] → Pequenos atalhos da tela "Ruptura de estoque". Nenhum deles é obrigatório: sem JavaScript a tela continua funcionando (é só preencher e clicar em
 *            "Calcular" / clicar nos links). Nada aqui chama o Mercado Livre nem o ERP: tudo é GET comum que só lê o banco.
 *
 *            1) Os atalhos de dias (7, 15, 30...), o seletor "Ver" (No Full / Fora do Full / Produto) e o checkbox "Considerar as unidades a caminho" refazem o cálculo na hora.
 *            2) Os seletores "Ordenar por" e "Por página" da lista (marcados com data-rup-ir) levam para o endereço que está no value da opção escolhida.
 *            3) Foto que não carrega (anúncio sem foto, link vencido) vira o quadradinho "sem foto", para a linha não ficar com o ícone de imagem quebrada.
 */
(function () {
    'use strict';

    // [1] Atalhos do formulário (existem na lista e no detalhe).
    var form = document.getElementById('rup-form');
    var campoDias = document.getElementById('rup-dias');

    function enviar() {
        if (!form) { return; }
        if (typeof form.requestSubmit === 'function') { form.requestSubmit(); } else { form.submit(); }
    }

    if (form && campoDias) {
        form.querySelectorAll('[data-dias]').forEach(function (botao) {
            botao.addEventListener('click', function () {
                campoDias.value = botao.getAttribute('data-dias');
                enviar();
            });
        });
    }

    if (form) {
        form.querySelectorAll('input[name="visao"]').forEach(function (opcao) {
            opcao.addEventListener('change', enviar);
        });
        // O checkbox "Considerar as unidades a caminho" também refaz o cálculo na hora.
        form.querySelectorAll('input[name="caminho"]').forEach(function (caixa) {
            caixa.addEventListener('change', enviar);
        });
    }

    // [2] Seletores que trocam de página: o value da opção já é o endereço pronto (montado no servidor, mantendo busca, filtro, ritmo e lead).
    document.querySelectorAll('select[data-rup-ir]').forEach(function (seletor) {
        seletor.addEventListener('change', function () {
            var destino = seletor.value;
            if (destino) { window.location.href = destino; }
        });
    });

    // [3] Foto quebrada → placeholder do mesmo tamanho (o CSS dá o tamanho pela classe, então a linha não muda de altura).
    function trocarPorPlaceholder(img) {
        if (!img || img.getAttribute('data-rup-sem-foto') === '1') { return; }
        var ehLista = img.classList.contains('cartao-anuncio-imagem');
        var ehDetalhe = img.classList.contains('rup-produto-imagem');
        if (!ehLista && !ehDetalhe) { return; }
        var vazio = document.createElement(ehLista ? 'div' : 'span');
        vazio.className = ehLista
            ? 'cartao-anuncio-imagem cartao-anuncio-imagem--vazia'
            : 'rup-produto-imagem rup-produto-imagem--vazia';
        vazio.setAttribute('data-rup-sem-foto', '1');
        if (ehLista) {
            vazio.setAttribute('role', 'img');
            vazio.setAttribute('aria-label', 'Sem foto');
        } else {
            vazio.setAttribute('aria-hidden', 'true');
        }
        vazio.innerHTML = ehLista ? '<i class="fas fa-image" aria-hidden="true"></i>' : '<i class="fas fa-box"></i>';
        if (img.parentNode) { img.parentNode.replaceChild(vazio, img); }
    }

    // O evento "error" de <img> não sobe na árvore; só dá para pegar na fase de captura.
    document.addEventListener('error', function (evento) {
        var alvo = evento.target;
        if (alvo && alvo.tagName === 'IMG') { trocarPorPlaceholder(alvo); }
    }, true);

    // Foto que já falhou antes deste script rodar.
    document.querySelectorAll('img.cartao-anuncio-imagem, img.rup-produto-imagem').forEach(function (img) {
        if (img.complete && img.naturalWidth === 0 && img.getAttribute('src')) { trocarPorPlaceholder(img); }
    });
})();
