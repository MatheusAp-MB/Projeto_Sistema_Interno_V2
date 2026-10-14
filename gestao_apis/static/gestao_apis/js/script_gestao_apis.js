/*
* [RESUMO] → JS da tela "Gestão de APIs".
* O botão Testar de cada cartão é HTMX puro (hx-post no HTML) — menos o do Agente, que o servidor não alcança
* (ele roda no computador de quem usa). Este arquivo cuida de:
*   1) mover as 2 janelas (modais) para o <body>;
*   2) abrir "Ver detalhes" com o texto completo do cartão;
*   3) "Testar todas": testa uma conexão de cada vez, em fila;
*   4) mostrar um aviso na tela quando uma chamada falha (rede, erro do servidor);
*   5) Testar do Agente: o navegador chama o agente do computador (/ping) e manda o resultado para o servidor;
*   6) botões de ação em formulário (ex.: Renovar autorização, que abre o Google numa janela pequena e espera ela
*      terminar) e o aviso que o servidor deixa na tela.
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

    // ---------- 5) Teste que o navegador faz (Agente do computador) ----------
    // O servidor não consegue chamar o agente (ele só escuta neste computador, em 127.0.0.1). Então o navegador
    // chama o /ping do agente e manda a resposta para o servidor junto do clique (campo "ping"); quem monta o
    // resultado do cartão é o servidor. O texto abaixo nunca leva token: o agente não devolve a chave.
    // A espera tem que ser MAIOR que a do agente ao chamar o sistema (8 s) — e bate com o texto do servidor (12 s).
    var ESPERA_MAXIMA_DO_PING_MS = 12000;

    async function pingarAgenteLocal(urlDoPing, empresa) {
        var resultado = { alcancou: false, motivo: 'sem_resposta' };
        var controle = new AbortController();
        var cronometro = window.setTimeout(function () { controle.abort(); }, ESPERA_MAXIMA_DO_PING_MS);
        try {
            var resposta = await fetch(urlDoPing + '?empresa=' + encodeURIComponent(empresa || ''), {
                method: 'GET', cache: 'no-store', signal: controle.signal,
            });
            resultado = { alcancou: true, status: resposta.status };
            if (resposta.ok) {
                try { resultado.corpo = await resposta.json(); } catch (erro) { /* não era JSON */ }
            }
        } catch (erro) {
            // Fechado, bloqueado pelo navegador ou sem resposta a tempo (o navegador não diz qual dos dois primeiros).
            resultado = { alcancou: false, motivo: (erro && erro.name === 'AbortError') ? 'tempo_esgotado' : 'sem_resposta' };
        } finally {
            window.clearTimeout(cronometro);
        }
        return JSON.stringify(resultado);
    }

    document.addEventListener('click', async function (evento) {
        var botao = evento.target.closest('[data-gapi-ping-local]');
        if (!botao || botao.disabled) { return; }
        var cartao = botao.closest('.gapi-card');
        var idDoCartao = cartao.id;
        botao.disabled = true;
        cartao.classList.add('htmx-request');   // mostra o "Testando…" por cima do cartão
        try {
            var ping = await pingarAgenteLocal(botao.dataset.pingUrl, botao.dataset.empresa);
            await htmx.ajax('POST', botao.dataset.testarUrl, {
                target: '#' + idDoCartao, swap: 'outerHTML', values: { ping: ping },
            });
        } catch (erro) {
            mostrarAviso('O teste do agente não terminou. Tente de novo.');
        } finally {
            // Se o teste deu certo o cartão já foi trocado por um novo (sem a marca e com o botão liberado).
            var atual = document.getElementById(idDoCartao);
            if (atual) {
                atual.classList.remove('htmx-request');
                var novo = atual.querySelector('[data-gapi-ping-local]');
                if (novo) { novo.disabled = false; }
            }
        }
    });

    // ---------- 6) Botões de ação (formulário) + aviso do servidor ----------
    // Botão que leva ao Google (Renovar autorização), com data-gapi-situacao-url no formulário:
    //   - abre o login do Google numa JANELA PEQUENA (como a do "escolher conta"), sem tirar a pessoa da tela;
    //   - a janela não consegue avisar esta página (o servidor manda Cross-Origin-Opener-Policy: same-origin), então esta
    //     página PERGUNTA ao servidor, a cada 1,5 s, se a janela terminou; quando termina, recarrega e mostra o aviso;
    //   - se o navegador bloquear a janela, vale o caminho comum: a própria página vai ao Google e volta.
    // Os outros formulários de ação levam a página inteira: o botão desliga ao enviar (evita 2 cliques seguidos). Se a
    // pessoa voltar pelo botão "voltar" do navegador, a página pode vir do cache com o botão ainda desligado — o
    // 'pageshow' devolve o texto e liga de novo.
    var NOME_DA_JANELA_DO_GOOGLE = 'gapi_google';
    var INTERVALO_DA_ESPERA_MS = 1500;
    var LIMITE_DA_ESPERA_MS = 11 * 60 * 1000;   // um pouco mais que os 10 minutos de validade do pedido no servidor
    var esperaDaJanela = null;

    function pararEsperaDaJanela() {
        if (esperaDaJanela !== null) {
            window.clearInterval(esperaDaJanela);
            esperaDaJanela = null;
        }
    }

    function restaurarBotao(botao, texto) {
        if (texto.dataset.original) { texto.textContent = texto.dataset.original; }
        botao.disabled = false;
    }

    function esperarOFimDaJanela(urlDaSituacao, botao, texto) {
        pararEsperaDaJanela();
        texto.textContent = 'Aguardando…';
        var limite = Date.now() + LIMITE_DA_ESPERA_MS;
        var consultando = false;
        esperaDaJanela = window.setInterval(async function () {
            if (consultando) { return; }
            if (Date.now() > limite) {
                pararEsperaDaJanela();
                restaurarBotao(botao, texto);
                return;
            }
            consultando = true;
            try {
                var resposta = await fetch(urlDaSituacao, {
                    credentials: 'same-origin', cache: 'no-store', headers: { 'Accept': 'application/json' },
                });
                if (resposta.ok) {
                    var dados = await resposta.json();
                    if (dados.concluido) {
                        // A janela terminou: recarregar mostra o aviso e o cartão já atualizado.
                        pararEsperaDaJanela();
                        window.location.reload();
                    } else if (!dados.aguardando) {
                        pararEsperaDaJanela();
                        restaurarBotao(botao, texto);
                    }
                }
            } catch (erro) {
                // Queda passageira de rede: tenta de novo no próximo ciclo.
            } finally {
                consultando = false;
            }
        }, INTERVALO_DA_ESPERA_MS);
    }

    function abrirOGoogleEmJanelaPequena(formulario, botao, texto) {
        var largura = 520;
        var altura = 700;
        var esquerda = Math.max(0, Math.round((window.screenX || 0) + ((window.outerWidth || largura) - largura) / 2));
        var topo = Math.max(0, Math.round((window.screenY || 0) + ((window.outerHeight || altura) - altura) / 3));
        // O nome fixo faz um 2º clique reaproveitar a janela que ainda estiver aberta, em vez de empilhar várias.
        var janela = window.open('', NOME_DA_JANELA_DO_GOOGLE,
            'popup=yes,width=' + largura + ',height=' + altura + ',left=' + esquerda + ',top=' + topo + ',resizable=yes,scrollbars=yes');
        var campoModo = formulario.querySelector('input[name="modo"]');

        if (!janela) {
            // O navegador bloqueou a janela: caminho comum (a página inteira vai ao Google e volta).
            if (campoModo) { campoModo.remove(); }
            formulario.removeAttribute('target');
            botao.disabled = true;
            texto.textContent = 'Abrindo o Google…';
            formulario.submit();
            return;
        }

        if (!campoModo) {
            campoModo = document.createElement('input');
            campoModo.type = 'hidden';
            campoModo.name = 'modo';
            formulario.appendChild(campoModo);
        }
        campoModo.value = 'janela';
        formulario.target = NOME_DA_JANELA_DO_GOOGLE;
        formulario.submit();
        try { janela.focus(); } catch (erro) { /* sem foco: a janela abre do mesmo jeito */ }

        // Desligado só por instantes (clique duplo); depois pode ser clicado de novo para reabrir a janela.
        botao.disabled = true;
        window.setTimeout(function () { botao.disabled = false; }, 4000);
        esperarOFimDaJanela(formulario.getAttribute('data-gapi-situacao-url'), botao, texto);
    }

    document.addEventListener('submit', function (evento) {
        var formulario = evento.target.closest ? evento.target.closest('.gapi-acao-form') : null;
        if (!formulario) { return; }
        var botao = formulario.querySelector('button[type="submit"]');
        var texto = botao && botao.querySelector('.gapi-btn__texto');
        if (!botao || !texto) { return; }
        if (!texto.dataset.original) { texto.dataset.original = texto.textContent; }

        if (formulario.hasAttribute('data-gapi-situacao-url')) {
            evento.preventDefault();
            abrirOGoogleEmJanelaPequena(formulario, botao, texto);
            return;
        }
        window.setTimeout(function () {
            botao.disabled = true;
            texto.textContent = 'Abrindo o Google…';
        }, 0);
    });

    // Página recarregada (ou aberta de novo) com a janela do Google ainda aberta: volta a esperar por ela.
    if (document.querySelector('[data-gapi-janela-aguardando]')) {
        var formularioEmEspera = document.querySelector('.gapi-acao-form[data-gapi-situacao-url]');
        var botaoEmEspera = formularioEmEspera && formularioEmEspera.querySelector('button[type="submit"]');
        var textoEmEspera = botaoEmEspera && botaoEmEspera.querySelector('.gapi-btn__texto');
        if (textoEmEspera) {
            if (!textoEmEspera.dataset.original) { textoEmEspera.dataset.original = textoEmEspera.textContent; }
            esperarOFimDaJanela(formularioEmEspera.getAttribute('data-gapi-situacao-url'), botaoEmEspera, textoEmEspera);
        }
    }

    window.addEventListener('pageshow', function (evento) {
        if (!evento.persisted) { return; }
        document.querySelectorAll('.gapi-acao-form .gapi-btn__texto[data-original]').forEach(function (texto) {
            texto.textContent = texto.dataset.original;
            texto.closest('button').disabled = false;
        });
    });

    var avisoDoServidor = document.querySelector('[data-gapi-aviso]');
    if (avisoDoServidor) {
        avisoDoServidor.addEventListener('click', function () { avisoDoServidor.remove(); });
        window.setTimeout(function () { avisoDoServidor.remove(); }, 30000);
    }

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
                    return {
                        id: botao.closest('.gapi-card').id,
                        url: botao.dataset.testarUrl,
                        // Só o Agente: o navegador precisa chamar o agente do computador antes de pedir o teste.
                        pingLocal: botao.hasAttribute('data-gapi-ping-local')
                            ? { url: botao.dataset.pingUrl, empresa: botao.dataset.empresa }
                            : null,
                    };
                }
            );

            botaoTodas.disabled = true;
            try {
                for (var posicao = 0; posicao < fila.length; posicao++) {
                    rotulo.textContent = 'Testando ' + (posicao + 1) + ' de ' + fila.length + '…';
                    try {
                        // Cada teste troca o cartão pelo novo; faixa e tabela de eventos vêm junto.
                        var item = fila[posicao];
                        var contexto = { target: '#' + item.id, swap: 'outerHTML' };
                        if (item.pingLocal) {
                            contexto.values = { ping: await pingarAgenteLocal(item.pingLocal.url, item.pingLocal.empresa) };
                        }
                        await htmx.ajax('POST', item.url, contexto);
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
