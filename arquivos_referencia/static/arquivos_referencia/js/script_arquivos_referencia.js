/*
* [RESUMO] → JS da tela "Arquivos de referência". A conferência em si é HTMX puro (o formulário de cada cartão manda o
* arquivo ao escolher/soltar e o servidor devolve o cartão novo). Este arquivo cuida de:
*   1) mover a janela da auditoria para o <body>;
*   2) "Escolher arquivo": abre o seletor de arquivos do formulário do cartão;
*   3) arrastar e soltar o arquivo no cartão;
*   4) recusar no navegador um arquivo grande demais (nem sobe pela rede);
*   5) "Ver auditoria": copia o relatório do cartão para a janela;
*   6) mostrar um aviso na tela quando algo falha (rede, erro do sistema).
*/
(function () {
    'use strict';

    var pagina = document.querySelector('.arq-pagina');
    var LIMITE_EM_BYTES = pagina ? parseInt(pagina.dataset.arqLimiteBytes, 10) || 0 : 0;
    var LIMITE_EM_MB = pagina ? pagina.dataset.arqLimiteMb || '5' : '5';

    // ---------- 1) Janela no <body> ----------
    var janela = document.getElementById('arq-modal-auditoria');
    if (janela && janela.parentElement !== document.body) {
        document.body.appendChild(janela);
    }

    // ---------- 6) Aviso na tela ----------
    function mostrarAviso(texto, tipo) {
        var antigo = document.querySelector('.arq-toast');
        if (antigo) { antigo.remove(); }
        var aviso = document.createElement('div');
        aviso.className = 'arq-toast' + (tipo === 'info' ? ' arq-toast--info' : '');
        aviso.setAttribute('role', 'alert');
        aviso.title = 'Clique para fechar';
        aviso.textContent = texto;
        aviso.addEventListener('click', function () { aviso.remove(); });
        document.body.appendChild(aviso);
        window.setTimeout(function () { aviso.remove(); }, 9000);
    }

    function mensagemDoErro(xhr) {
        try {
            var corpo = JSON.parse(xhr.responseText);
            if (corpo && corpo.mensagem) { return corpo.mensagem; }
        } catch (erro) { /* resposta não era JSON */ }
        if (xhr.status === 403) {
            return 'O servidor recusou o envio (403). Recarregue a página e tente de novo.';
        }
        if (xhr.status === 413) {
            return 'O arquivo é grande demais para o servidor. Confira se é o arquivo certo.';
        }
        return 'O servidor respondeu com erro ' + xhr.status + '. Veja o terminal do servidor.';
    }

    document.body.addEventListener('htmx:responseError', function (evento) {
        mostrarAviso(mensagemDoErro(evento.detail.xhr));
    });

    document.body.addEventListener('htmx:sendError', function () {
        mostrarAviso('Não foi possível falar com o servidor do sistema. Confira se ele está no ar.');
    });

    // Terminou (deu certo ou não): limpa o seletor, para a pessoa poder escolher o MESMO arquivo de novo (o navegador só
    // avisa "mudou" quando o arquivo muda). Se deu certo, o cartão antigo já foi trocado e isto não faz nada.
    document.body.addEventListener('htmx:afterRequest', function (evento) {
        var formulario = evento.detail.elt;
        var seletor = formulario && formulario.querySelector ? formulario.querySelector('.arq-input') : null;
        if (seletor) { seletor.value = ''; }
    });

    // ---------- 2) Escolher arquivo ----------
    document.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-arq-escolher]');
        if (!botao || botao.disabled) { return; }
        var seletor = botao.closest('.arq-form').querySelector('.arq-input');
        if (seletor) { seletor.click(); }
    });

    // ---------- 4) Arquivo grande demais: barra aqui, antes de subir ----------
    // Capture no document: roda antes do HTMX (que escuta o "change" no formulário) e, ao parar a propagação, impede o envio.
    document.addEventListener('change', function (evento) {
        var seletor = evento.target;
        if (!seletor.classList || !seletor.classList.contains('arq-input')) { return; }
        var arquivo = seletor.files && seletor.files[0];
        if (arquivo && LIMITE_EM_BYTES && arquivo.size > LIMITE_EM_BYTES) {
            evento.stopPropagation();
            seletor.value = '';
            mostrarAviso('O arquivo tem mais de ' + LIMITE_EM_MB + ' MB — grande demais para uma tabela de referência. Confira se é o arquivo certo.', 'info');
        }
    }, true);

    // ---------- 3) Arrastar e soltar ----------
    function temArquivos(evento) {
        var tipos = evento.dataTransfer && evento.dataTransfer.types;
        return !!tipos && Array.prototype.indexOf.call(tipos, 'Files') !== -1;
    }

    document.addEventListener('dragover', function (evento) {
        if (!temArquivos(evento)) { return; }
        // Sem isto o navegador abriria o arquivo solto fora de um cartão, tirando a pessoa da tela.
        evento.preventDefault();
        var cartao = evento.target.closest ? evento.target.closest('.arq-card') : null;
        if (cartao && !cartao.classList.contains('htmx-request')) {
            cartao.classList.add('arq-card--soltando');
            evento.dataTransfer.dropEffect = cartao.hasAttribute('data-arq-soltar') ? 'copy' : 'none';
        }
    });

    document.addEventListener('dragleave', function (evento) {
        var cartao = evento.target.closest ? evento.target.closest('.arq-card') : null;
        if (cartao && !cartao.contains(evento.relatedTarget)) {
            cartao.classList.remove('arq-card--soltando');
        }
    });

    document.addEventListener('drop', function (evento) {
        if (!temArquivos(evento)) { return; }
        evento.preventDefault();
        document.querySelectorAll('.arq-card--soltando').forEach(function (c) { c.classList.remove('arq-card--soltando'); });

        var cartao = evento.target.closest ? evento.target.closest('.arq-card') : null;
        if (!cartao || cartao.classList.contains('htmx-request')) { return; }
        if (!cartao.hasAttribute('data-arq-soltar')) {
            mostrarAviso('Esta planilha ainda não tem auditoria — ela chega na próxima etapa.', 'info');
            return;
        }
        var arquivos = evento.dataTransfer.files;
        if (!arquivos || arquivos.length !== 1) {
            mostrarAviso('Solte um arquivo de cada vez.', 'info');
            return;
        }
        var seletor = cartao.querySelector('.arq-input');
        if (!seletor) { return; }
        seletor.files = arquivos;
        // Mesmo caminho de "Escolher arquivo": o "change" põe o HTMX para enviar.
        seletor.dispatchEvent(new Event('change', { bubbles: true }));
    });

    // ---------- 5) Ver auditoria ----------
    document.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-arq-ver-auditoria]');
        if (!botao || botao.disabled) { return; }
        var cartao = botao.closest('.arq-card');
        var auditoria = cartao && cartao.querySelector('.arq-card__auditoria');
        if (!auditoria) { return; }

        document.getElementById('arq-modal-auditoria-titulo').textContent = 'Auditoria — ' + (cartao.dataset.nome || '');
        // O conteúdo vem do próprio HTML do servidor (já com os textos escapados), não de digitação.
        document.getElementById('arq-modal-auditoria-corpo').innerHTML = auditoria.innerHTML;
        bootstrap.Modal.getOrCreateInstance(janela).show();
    });
})();
