/*
* [RESUMO] → JS da tela "Gestão de APIs".
* O botão Testar de cada cartão é HTMX puro (hx-post no HTML). Este arquivo cuida só de:
*   1) mover as 2 janelas (modais) para o <body>;
*   2) abrir "Ver detalhes" com o texto completo do cartão;
*   3) "Testar todas": testa uma conexão de cada vez, em fila;
*   4) mostrar um aviso na tela quando uma chamada falha (rede, erro do servidor).
*/
(function () {
    'use strict';

    // ---------- 1) Janelas no <body> ----------
    ['gapi-modal-detalhes', 'gapi-modal-problemas'].forEach(function (id) {
        var janela = document.getElementById(id);
        if (janela && janela.parentElement !== document.body) {
            document.body.appendChild(janela);
        }
    });

    // ---------- 4) Aviso de erro ----------
    function mostrarAviso(texto) {
        var antigo = document.querySelector('.gapi-toast');
        if (antigo) { antigo.remove(); }
        var aviso = document.createElement('div');
        aviso.className = 'gapi-toast';
        aviso.setAttribute('role', 'alert');
        aviso.textContent = texto;
        document.body.appendChild(aviso);
        window.setTimeout(function () { aviso.remove(); }, 9000);
    }

    function mensagemDoErro(xhr) {
        try {
            var corpo = JSON.parse(xhr.responseText);
            if (corpo && corpo.mensagem) { return corpo.mensagem; }
        } catch (erro) { /* resposta não era JSON */ }
        if (xhr.status === 403) {
            return 'O servidor recusou o teste (403). Recarregue a página e tente de novo.';
        }
        return 'O servidor respondeu com erro ' + xhr.status + '. Veja o terminal do servidor.';
    }

    document.body.addEventListener('htmx:responseError', function (evento) {
        mostrarAviso(mensagemDoErro(evento.detail.xhr));
    });

    document.body.addEventListener('htmx:sendError', function () {
        mostrarAviso('Não foi possível falar com o servidor do sistema. Confira se ele está no ar.');
    });

    // ---------- 2) Ver detalhes ----------
    document.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-gapi-detalhes]');
        if (!botao) { return; }
        var cartao = botao.closest('.gapi-card');
        var detalhes = cartao && cartao.querySelector('.gapi-card__detalhes');
        if (!detalhes) { return; }

        document.getElementById('gapi-modal-detalhes-titulo').textContent = cartao.dataset.nome || 'Detalhes';
        // O conteúdo vem do próprio HTML do servidor (já com os textos escapados), não de digitação.
        document.getElementById('gapi-modal-detalhes-corpo').innerHTML = detalhes.innerHTML;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('gapi-modal-detalhes')).show();
    });

    // ---------- 3) Testar todas ----------
    var botaoTodas = document.getElementById('gapi-btn-testar-todas');
    if (botaoTodas) {
        botaoTodas.addEventListener('click', async function () {
            if (botaoTodas.disabled) { return; }
            var rotulo = botaoTodas.querySelector('span');
            var textoOriginal = rotulo.textContent;

            // Lista fixada antes de começar: (id do cartão, endereço do teste).
            var fila = Array.prototype.map.call(
                document.querySelectorAll('.gapi-card [data-testar-url]'),
                function (botao) {
                    return { id: botao.closest('.gapi-card').id, url: botao.dataset.testarUrl };
                }
            );

            botaoTodas.disabled = true;
            try {
                for (var posicao = 0; posicao < fila.length; posicao++) {
                    rotulo.textContent = 'Testando ' + (posicao + 1) + ' de ' + fila.length + '…';
                    try {
                        // Cada teste troca o cartão pelo novo; faixa e tabela de eventos vêm junto.
                        await htmx.ajax('POST', fila[posicao].url, { target: '#' + fila[posicao].id, swap: 'outerHTML' });
                    } catch (erro) {
                        mostrarAviso('O teste de uma conexão não terminou. Os outros continuam.');
                    }
                }
            } finally {
                rotulo.textContent = textoOriginal;
                botaoTodas.disabled = false;
            }
        });
    }
})();
