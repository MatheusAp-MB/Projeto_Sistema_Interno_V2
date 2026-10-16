/*
* [RESUMO] → JS da tela "Arquivos de referência". A conferência e o envio em si são HTMX puro (o servidor devolve o cartão
* novo). Este arquivo cuida de:
*   1) mover as janelas (auditoria, confirmação do envio, confirmação e resultado da atualização, visualizador) para o <body>;
*   2) "Escolher arquivo": abre o seletor de arquivos do formulário do cartão;
*   3) arrastar e soltar o arquivo no cartão;
*   4) recusar no navegador um arquivo grande demais (nem sobe pela rede);
*   5) "Ver auditoria": copia o relatório do cartão para a janela;
*   6) mostrar um aviso na tela quando algo falha (rede, erro do sistema, login do Drive) ou dá certo (envio);
*   7) "Enviar para o Drive": confirma numa janela e então manda o arquivo conferido;
*   8) não deixar a resposta atrasada do Drive apagar o arquivo que a pessoa conferiu enquanto o Drive ainda respondia;
*   9) "Atualizar o sistema com o Drive" (botão da barra de cima): confirma numa janela e então atualiza as tabelas de frete DA EMPRESA
*      SELECIONADA (só ela), UM arquivo de cada vez, mostrando o resultado de cada um na janela; ao terminar, os cartões de frete
*      consultam o Drive de novo para mostrar "Data da última atualização do sistema" e o selo "Em dia".
*  10) "Ver arquivo": abre a janela do visualizador (o arquivo do Drive vem por HTMX; o arquivo conferido sai da memória do navegador pelo
*      formulário escondido do cartão) e mostra na barra de fórmulas o conteúdo da célula clicada. A troca de aba e o "Como no Excel / Valor
*      bruto" são só CSS (botões de opção escondidos dentro do HTML do visualizador).
*
* * [DECISÃO, 16/10/2026] → Independência entre as empresas: a tela é de UMA empresa (data-arq-empresa na página). Cada pedido ao servidor
*   leva essa empresa e o servidor recusa se a selecionada mudou em outra aba (o aviso pede para recarregar). Nada aqui grava nas duas.
*
* * [EXPLICAÇÃO] → O envio precisa do MESMO arquivo que foi conferido, mas o cartão novo (trocado pelo HTMX depois da
*   conferência) não carrega o arquivo. Por isso, quando uma conferência dá certo, o arquivo fica guardado aqui na memória do
*   navegador (`conferidos`, por cartão); ao confirmar o envio ele é posto no formulário de envio do cartão. Nada vai para o
*   disco. Recarregar a página (F5) zera isso — e cada cartão volta a mostrar o que o Drive tem ("No Drive" ou "Sem arquivo no Drive").
* * [IMPORTANTE] → O servidor não confia nesta tela: confere o arquivo de novo antes de enviar ao Drive.
*/
(function () {
    'use strict';

    var pagina = document.querySelector('.arq-pagina');
    var LIMITE_EM_BYTES = pagina ? parseInt(pagina.dataset.arqLimiteBytes, 10) || 0 : 0;
    var LIMITE_EM_MB = pagina ? pagina.dataset.arqLimiteMb || '5' : '5';
    var NOME_DA_EMPRESA = pagina ? pagina.dataset.arqEmpresaNome || '' : '';   // "Magazine" / "Samvale": a empresa que esta tela mostra

    // Arquivos já conferidos com sucesso (id do cartão → File) e arquivos cuja conferência ainda está em andamento.
    var conferidos = new Map();
    var emConferencia = new Map();

    // ---------- 1) Janelas no <body> ----------
    var janela = document.getElementById('arq-modal-auditoria');
    var janelaDoEnvio = document.getElementById('arq-modal-envio');
    var janelaDaConfirmacao = document.getElementById('arq-modal-atualizar');
    var janelaDoResultado = document.getElementById('arq-modal-resultado');
    var janelaDoVisualizador = document.getElementById('arq-modal-visualizador');
    [janela, janelaDoEnvio, janelaDaConfirmacao, janelaDoResultado, janelaDoVisualizador].forEach(function (modal) {
        if (modal && modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
    });

    // ---------- 6) Aviso na tela ----------
    // tipo: (nada) = erro, vermelho · 'info' = "não deu / atenção", cinza · 'ok' = deu certo, verde.
    // link (opcional): {texto, url} — abre em outra aba para a pessoa não perder as conferências já feitas.
    function mostrarAviso(texto, tipo, link) {
        var antigo = document.querySelector('.arq-toast');
        if (antigo) { antigo.remove(); }
        var aviso = document.createElement('div');
        aviso.className = 'arq-toast' + (tipo === 'info' ? ' arq-toast--info' : '') + (tipo === 'ok' ? ' arq-toast--ok' : '');
        aviso.setAttribute('role', tipo === 'ok' ? 'status' : 'alert');
        aviso.title = 'Clique para fechar';
        aviso.appendChild(document.createTextNode(texto));
        if (link && link.url) {
            var atalho = document.createElement('a');
            atalho.className = 'arq-toast__link';
            atalho.href = link.url;
            atalho.target = '_blank';
            atalho.rel = 'noopener';
            atalho.textContent = link.texto || 'Abrir';
            atalho.addEventListener('click', function (evento) { evento.stopPropagation(); });
            aviso.appendChild(atalho);
        }
        aviso.addEventListener('click', function () { aviso.remove(); });
        document.body.appendChild(aviso);
        window.setTimeout(function () { aviso.remove(); }, link ? 15000 : 9000);
    }

    // Devolve {texto, link}: o servidor manda {"mensagem", "link"} quando o problema é dele ou do Drive.
    function mensagemDoErro(xhr) {
        try {
            var corpo = JSON.parse(xhr.responseText);
            if (corpo && corpo.mensagem) { return { texto: corpo.mensagem, link: corpo.link || null }; }
        } catch (erro) { /* resposta não era JSON */ }
        if (xhr.status === 403) {
            return { texto: 'O servidor recusou o envio (403). Recarregue a página e tente de novo.', link: null };
        }
        if (xhr.status === 413) {
            return { texto: 'O arquivo é grande demais para o servidor. Confira se é o arquivo certo.', link: null };
        }
        return { texto: 'O servidor respondeu com erro ' + xhr.status + '. Veja o terminal do servidor.', link: null };
    }

    document.body.addEventListener('htmx:responseError', function (evento) {
        var erro = mensagemDoErro(evento.detail.xhr);
        mostrarAviso(erro.texto, undefined, erro.link);
    });

    document.body.addEventListener('htmx:sendError', function () {
        mostrarAviso('Não foi possível falar com o servidor do sistema. Confira se ele está no ar.');
    });

    // O servidor avisa por cabeçalho (HX-Trigger → evento "arqAviso"): envio feito, ou envio recusado na conferência.
    document.body.addEventListener('arqAviso', function (evento) {
        var dados = evento.detail || {};
        if (dados.mensagem) { mostrarAviso(dados.mensagem, dados.tipo); }
    });

    // Chegou a resposta da CONFERÊNCIA, antes de o HTMX trocar o cartão (nesse instante o cartão ainda está na página, então o
    // evento chega até aqui — depois da troca o HTMX só avisa o elemento que já saiu da página, e ninguém ouve).
    // Conferência que deu certo: o arquivo fica guardado para o envio. Se falhou, o cartão segue com a conferência anterior.
    document.body.addEventListener('htmx:beforeSwap', function (evento) {
        var cartao = evento.detail.elt;
        var caminho = (evento.detail.pathInfo && evento.detail.pathInfo.requestPath) || '';
        if (!cartao || !cartao.classList || !cartao.classList.contains('arq-card') || caminho.indexOf('/auditar/') === -1) { return; }
        var id = cartao.dataset.arqId;
        if (emConferencia.has(id)) {
            if (evento.detail.shouldSwap) { conferidos.set(id, emConferencia.get(id)); }
            emConferencia.delete(id);
        }
    });

    // Resposta da consulta ao Drive que também troca o selo e a área de soltar do cartão (hx-swap-oob). Se a pessoa já conferiu um
    // arquivo neste cartão enquanto o Drive ainda respondia, o cartão tem `data-arq-com-arquivo` e a troca é cancelada: o arquivo
    // conferido nunca é coberto por uma resposta atrasada (a linha "No Drive agora" continua se atualizando normalmente).
    document.body.addEventListener('htmx:oobBeforeSwap', function (evento) {
        var alvo = evento.detail.target;
        var cartao = alvo && alvo.closest ? alvo.closest('.arq-card') : null;
        if (cartao && cartao.hasAttribute('data-arq-com-arquivo')) { evento.detail.shouldSwap = false; }
    });

    // Terminou um pedido. Quando deu certo o cartão antigo já saiu da página e isto não faz nada; quando deu errado o formulário
    // continua lá e precisa de limpeza.
    document.body.addEventListener('htmx:afterRequest', function (evento) {
        var formulario = evento.detail.elt;
        if (!formulario || !formulario.classList) { return; }

        if (formulario.classList.contains('arq-form')) {
            // Limpa o seletor, para a pessoa poder escolher o MESMO arquivo de novo (o navegador só avisa "mudou" quando o arquivo muda).
            var seletor = formulario.querySelector('.arq-input');
            if (seletor) { seletor.value = ''; }
        } else if (formulario.classList.contains('arq-form-envio')) {
            var seletorDoEnvio = formulario.querySelector('.arq-input-envio');
            if (seletorDoEnvio) { seletorDoEnvio.value = ''; }
            var cartao = formulario.closest('.arq-card');
            if (cartao) { cartao.classList.remove('arq-card--enviando'); }
        }
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
            return;
        }
        // Vai conferir: guarda o arquivo "em andamento" (só vira "conferido" se a conferência der certo — ver htmx:afterRequest).
        var cartao = seletor.closest('.arq-card');
        if (arquivo && cartao) { emConferencia.set(cartao.dataset.arqId, arquivo); }
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
            mostrarAviso('Esta planilha ainda não tem auditoria.', 'info');
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

    // ---------- 7) Enviar para o Drive ----------
    var idEmConfirmacao = null;

    function escrever(id, texto) {
        var elemento = document.getElementById(id);
        if (elemento) { elemento.textContent = texto; }
    }

    // 1º passo: o botão do cartão só ABRE a janela de confirmação, com o que vai acontecer.
    document.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-arq-enviar]');
        if (!botao || botao.disabled || !janelaDoEnvio) { return; }
        var cartao = botao.closest('.arq-card');
        if (!cartao || cartao.classList.contains('htmx-request')) { return; }

        var id = cartao.dataset.arqId;
        if (!conferidos.has(id)) {
            // Não deveria acontecer (o botão só aparece depois de uma conferência feita nesta página); protege contra um estado estranho.
            mostrarAviso('Esta tela não guardou o arquivo conferido. Escolha o arquivo de novo.', 'info');
            return;
        }

        var linhaDoDrive = cartao.querySelector('.arq-drive[data-arq-caminho]');
        var pasta = linhaDoDrive ? linhaDoDrive.dataset.arqCaminho : botao.dataset.arqPasta;
        var avisos = parseInt(botao.dataset.arqAvisos, 10) || 0;

        escrever('arq-envio-arquivo', (botao.dataset.arqNome || '') + (botao.dataset.arqTamanho ? ' · ' + botao.dataset.arqTamanho : ''));
        escrever('arq-envio-destino', pasta + ' › ' + botao.dataset.arqArquivoNoDrive);
        escrever('arq-envio-avisos', avisos
            ? avisos + (avisos === 1 ? ' aviso' : ' avisos') + ' (não impedem o envio — confira em “Ver auditoria”)'
            : 'nenhum');

        idEmConfirmacao = id;
        bootstrap.Modal.getOrCreateInstance(janelaDoEnvio).show();
    });

    // 2º passo: confirmou → põe o arquivo conferido no formulário de envio do cartão e dispara o envio (HTMX).
    function enviarAoDrive(id) {
        var cartao = document.getElementById('arq-card-' + id);
        var arquivo = conferidos.get(id);
        var formulario = cartao && cartao.querySelector('.arq-form-envio');
        if (!cartao || !formulario || !arquivo) {
            mostrarAviso('Não achei o arquivo conferido. Escolha o arquivo de novo.', 'info');
            return;
        }
        if (cartao.classList.contains('htmx-request')) { return; }

        // O navegador só guarda uma "referência" ao arquivo: se ele foi movido, apagado ou regravado depois da conferência, não dá para ler.
        arquivo.slice(0, 1).arrayBuffer().then(function () {
            var pacote = new DataTransfer();
            pacote.items.add(arquivo);
            formulario.querySelector('.arq-input-envio').files = pacote.files;
            cartao.classList.add('arq-card--enviando');
            htmx.trigger(formulario, 'arq-enviar');
        }, function () {
            mostrarAviso('O navegador não consegue mais ler o arquivo (ele foi movido, apagado ou alterado depois da conferência). Escolha o arquivo de novo.', 'info');
        });
    }

    var botaoConfirmar = document.getElementById('arq-envio-confirmar');
    if (botaoConfirmar) {
        botaoConfirmar.addEventListener('click', function () {
            var id = idEmConfirmacao;
            idEmConfirmacao = null;
            bootstrap.Modal.getOrCreateInstance(janelaDoEnvio).hide();
            if (id) { enviarAoDrive(id); }
        });
    }
    if (janelaDoEnvio) {
        // Fechou sem confirmar (Cancelar, X, Esc ou clique fora): esquece o pedido.
        janelaDoEnvio.addEventListener('hidden.bs.modal', function () { idEmConfirmacao = null; });
    }

    // ---------- 10) Ver arquivo ----------
    // * [EXPLICAÇÃO] → O botão "Ver arquivo" fica na área do cartão. No arquivo do Drive o próprio botão tem hx-get (o HTMX troca o miolo da janela);
    //   no arquivo conferido o botão só tem data-arq-ver="escolhido" e o JS manda o arquivo guardado em `conferidos` pelo formulário escondido
    //   (.arq-form-ver). Nos dois casos este código só abre a janela com "Abrindo o arquivo…" e cuida do que o HTMX não faz.
    var mioloDoVisualizador = document.getElementById('arq-viz-miolo');

    function avisoNoVisualizador(classe, icone, texto) {
        if (!mioloDoVisualizador) { return; }
        mioloDoVisualizador.textContent = '';
        var bloco = document.createElement('div');
        bloco.className = classe;
        var simbolo = document.createElement('i');
        simbolo.className = icone;
        simbolo.setAttribute('aria-hidden', 'true');
        bloco.appendChild(simbolo);
        bloco.appendChild(document.createTextNode(' ' + texto));
        mioloDoVisualizador.appendChild(bloco);
    }

    function abrirVisualizador(cartao) {
        if (!janelaDoVisualizador || !mioloDoVisualizador) { return; }
        document.getElementById('arq-modal-visualizador-titulo').textContent = 'Ver arquivo — ' + (cartao.dataset.nome || '');
        avisoNoVisualizador('arq-viz-carregando', 'fas fa-spinner fa-spin', 'Abrindo o arquivo…');
        celulaSelecionada = null;
        bootstrap.Modal.getOrCreateInstance(janelaDoVisualizador).show();
    }

    document.addEventListener('click', function (evento) {
        var botao = evento.target.closest ? evento.target.closest('[data-arq-ver]') : null;
        if (!botao || botao.disabled) { return; }
        var cartao = botao.closest('.arq-card');
        if (!cartao) { return; }
        abrirVisualizador(cartao);
        if (botao.dataset.arqVer !== 'escolhido') { return; }   // o arquivo do Drive é pedido pelo próprio botão (hx-get)

        var arquivo = conferidos.get(cartao.dataset.arqId);
        var formulario = cartao.querySelector('.arq-form-ver');
        var seletor = formulario && formulario.querySelector('.arq-input-ver');
        if (!arquivo || !seletor) {
            avisoNoVisualizador('arq-viz-carregando arq-viz-carregando--erro', 'fas fa-triangle-exclamation', 'Esta tela não guardou o arquivo escolhido. Escolha o arquivo de novo.');
            return;
        }
        // O navegador só guarda uma "referência" ao arquivo: se ele foi movido, apagado ou regravado depois da conferência, não dá para ler.
        arquivo.slice(0, 1).arrayBuffer().then(function () {
            var pacote = new DataTransfer();
            pacote.items.add(arquivo);
            seletor.files = pacote.files;
            htmx.trigger(formulario, 'arq-ver');
        }, function () {
            avisoNoVisualizador('arq-viz-carregando arq-viz-carregando--erro', 'fas fa-triangle-exclamation',
                'O navegador não consegue mais ler o arquivo (ele foi movido, apagado ou alterado depois da conferência). Escolha o arquivo de novo.');
        });
    });

    // O pedido falhou de vez (servidor fora do ar, erro 500): a janela diz isso em vez de ficar "abrindo" para sempre. O aviso com o motivo
    // já aparece pelo tratamento geral de erros desta tela.
    document.body.addEventListener('htmx:afterRequest', function (evento) {
        if (!mioloDoVisualizador || evento.detail.target !== mioloDoVisualizador || evento.detail.successful) { return; }
        avisoNoVisualizador('arq-viz-carregando arq-viz-carregando--erro', 'fas fa-triangle-exclamation',
            'Não consegui abrir o arquivo agora. O aviso na tela diz o motivo; feche esta janela e tente de novo.');
    });

    if (janelaDoVisualizador && mioloDoVisualizador) {
        // Fechou: solta a tabela da memória (o arquivo pode ter milhares de células).
        janelaDoVisualizador.addEventListener('hidden.bs.modal', function () {
            mioloDoVisualizador.textContent = '';
            celulaSelecionada = null;
        });
    }

    // Barra de fórmulas: clicar numa célula mostra o endereço (A1, B7…) e o conteúdo COMPLETO (a fórmula, se for fórmula; senão o valor guardado).
    // O texto vai para a barra por textContent (nunca como HTML).
    var celulaSelecionada = null;
    document.addEventListener('click', function (evento) {
        var celula = evento.target.closest ? evento.target.closest('.arq-viz__area td[data-c]') : null;
        if (!celula) { return; }
        if (celulaSelecionada && celulaSelecionada.classList) { celulaSelecionada.classList.remove('arq-viz__sel'); }
        celulaSelecionada = celula;
        celula.classList.add('arq-viz__sel');

        var linha = celula.parentElement ? celula.parentElement.dataset.r : '';
        var endereco = celula.dataset.o || ((celula.dataset.c || '') + (linha || ''));
        var bruto = celula.querySelector('.vb');
        var conteudo = celula.dataset.f || (bruto ? bruto.textContent : celula.textContent);
        var campoEndereco = document.getElementById('arq-viz-endereco');
        var campoConteudo = document.getElementById('arq-viz-conteudo-da-celula');
        if (campoEndereco) { campoEndereco.textContent = endereco; }
        if (campoConteudo) { campoConteudo.textContent = conteudo === '' ? '(célula vazia)' : conteudo; }
    });

    // ---------- 9) Atualizar o sistema com o Drive ----------
    // * [EXPLICAÇÃO] → O botão da barra só ABRE a confirmação. Confirmou: a janela de resultado ganha 1 linha "Aguardando" por arquivo
    //   (copiadas do <template>) e o JS dispara os arquivos UM DEPOIS DO OUTRO — cada linha manda o seu POST (HTMX) e se troca pelo
    //   resultado que o servidor devolve. Um arquivo com problema não impede os seguintes. Durante a atualização a janela não fecha.
    var atualizando = false;

    function avisarAntesDeSair(evento) {
        evento.preventDefault();
        evento.returnValue = '';
    }

    // Espera a linha terminar o pedido. O evento do HTMX é entregue à PRÓPRIA linha (mesmo depois de ela ser trocada pelo resultado).
    function atualizarUma(linha) {
        return new Promise(function (resolver) {
            linha.addEventListener('htmx:afterRequest', function (evento) {
                if (!evento.detail.successful) { marcarFalhaDaLinha(linha, evento.detail.xhr); }
                resolver();
            }, { once: true });
            htmx.trigger(linha, 'arq-atualizar');
        });
    }

    // O servidor recusou ou não respondeu direito (empresa trocada em outra aba, erro 500, rede caiu): a linha não foi trocada pelo
    // resultado, então ela mesma passa a dizer isso. Se o servidor mandou o motivo ({"mensagem"}), a linha mostra esse motivo
    // (ex.: "A empresa selecionada mudou… Nada foi gravado."); senão, mostra o texto geral abaixo.
    // O aviso com o motivo também aparece pelo tratamento geral de erros desta tela.
    function marcarFalhaDaLinha(linha, xhr) {
        linha.className = 'arq-atu arq-atu--falha_sistema';
        linha.dataset.arqStatus = 'falha_sistema';
        var topo = linha.querySelector('.arq-atu__topo');
        if (topo) {
            topo.querySelectorAll('.arq-pill').forEach(function (selo) { selo.remove(); });
            var selo = document.createElement('span');
            selo.className = 'arq-pill arq-pill--com_erros';
            selo.innerHTML = '<i class="fas fa-circle-xmark" aria-hidden="true"></i> ';
            selo.appendChild(document.createTextNode('Não deu certo'));
            topo.appendChild(selo);
        }
        var mensagem = document.createElement('p');
        mensagem.className = 'arq-atu__mensagem';
        var motivo = '';
        try {
            var corpo = JSON.parse(xhr.responseText);
            if (corpo && typeof corpo.mensagem === 'string') { motivo = corpo.mensagem; }
        } catch (erro) { /* resposta não era JSON (erro 500, rede caiu): vale o texto geral */ }
        mensagem.textContent = motivo || 'O servidor não respondeu direito a este arquivo. O aviso na tela diz o motivo. O sistema só muda quando o arquivo aparece como "Atualizado" — confira antes de tentar de novo.';
        linha.appendChild(mensagem);
    }

    function contarPorStatus(lista) {
        var contagem = {};
        lista.querySelectorAll('.arq-atu').forEach(function (linha) {
            var status = linha.dataset.arqStatus || 'pendente';
            contagem[status] = (contagem[status] || 0) + 1;
        });
        return contagem;
    }

    function terminarAtualizacao(lista) {
        var contagem = contarPorStatus(lista);
        var total = lista.querySelectorAll('.arq-atu').length;
        var certos = contagem.ok || 0;
        var resumo = document.getElementById('arq-atu-resumo');
        var texto;
        if (certos === total) {
            texto = total === 1 ? 'A tabela foi conferida e o sistema da ' + NOME_DA_EMPRESA + ' está em dia com ela.' : 'As ' + total + ' tabelas foram conferidas e o sistema da ' + NOME_DA_EMPRESA + ' está em dia com elas.';
            resumo.className = 'arq-atu-resumo arq-atu-resumo--ok';
        } else {
            texto = certos + ' de ' + total + (total === 1 ? ' tabela atualizada' : ' tabelas atualizadas') + ' — confira abaixo o que não entrou e o motivo.';
            resumo.className = 'arq-atu-resumo arq-atu-resumo--atencao';
        }
        resumo.textContent = texto;
        document.getElementById('arq-modal-resultado-titulo').textContent = 'Resultado da atualização — ' + NOME_DA_EMPRESA;
        document.getElementById('arq-resultado-fechar').disabled = false;
        document.getElementById('arq-resultado-x').disabled = false;
        atualizando = false;
        window.removeEventListener('beforeunload', avisarAntesDeSair);
        atualizarDatasDosCartoes();
    }

    // Depois da atualização, cada cartão de frete (bloco com data-arq-importavel) refaz a consulta ao Drive: é o mesmo clique do botão de
    // girar. Assim "Data da última atualização do sistema" e "Em dia" aparecem na hora, sem F5. Bloco ainda carregando não tem botão: ele
    // mesmo vai consultar e já traz as datas novas.
    function atualizarDatasDosCartoes() {
        document.querySelectorAll('.arq-drive-bloco[data-arq-importavel] .arq-drive__atualizar').forEach(function (botao) { botao.click(); });
    }

    function atualizarOSistema() {
        if (atualizando || !janelaDoResultado) { return; }
        var modelo = document.getElementById('arq-atu-modelo');
        var lista = document.getElementById('arq-atu-lista');
        if (!modelo || !lista) { return; }

        atualizando = true;
        window.addEventListener('beforeunload', avisarAntesDeSair);
        lista.innerHTML = modelo.innerHTML;
        htmx.process(lista);
        var resumo = document.getElementById('arq-atu-resumo');
        resumo.className = 'arq-atu-resumo';
        resumo.textContent = 'Lendo os arquivos do Drive e gravando no sistema da ' + NOME_DA_EMPRESA + ', um de cada vez. Não feche esta janela.';
        document.getElementById('arq-modal-resultado-titulo').textContent = 'Atualizando o sistema da ' + NOME_DA_EMPRESA + '…';
        document.getElementById('arq-resultado-fechar').disabled = true;
        document.getElementById('arq-resultado-x').disabled = true;
        bootstrap.Modal.getOrCreateInstance(janelaDoResultado).show();

        var cadeia = Promise.resolve();
        lista.querySelectorAll('.arq-atu').forEach(function (linha) {
            cadeia = cadeia.then(function () { return atualizarUma(linha); });
        });
        cadeia.then(function () { terminarAtualizacao(lista); });
    }

    var botaoAtualizar = document.getElementById('arq-btn-atualizar');
    if (botaoAtualizar && janelaDaConfirmacao) {
        botaoAtualizar.addEventListener('click', function () {
            if (atualizando) { return; }
            bootstrap.Modal.getOrCreateInstance(janelaDaConfirmacao).show();
        });
    }

    var botaoConfirmarAtualizacao = document.getElementById('arq-atualizar-confirmar');
    if (botaoConfirmarAtualizacao && janelaDaConfirmacao) {
        botaoConfirmarAtualizacao.addEventListener('click', function () {
            bootstrap.Modal.getOrCreateInstance(janelaDaConfirmacao).hide();
            atualizarOSistema();
        });
    }
})();
