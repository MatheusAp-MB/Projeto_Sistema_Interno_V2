// * [RESUMO] → Script da tela "Características dos anúncios" do ML.
//              REGRA: este script NUNCA chama a API do Mercado Livre por
//              conta própria. Abrir um produto, filtrar a tabela ou
//              recarregar só pedem dados ao nosso servidor (que lê do banco).
//              Os ÚNICOS gatilhos que fazem o servidor consultar o ML são:
//                1) o botão "Atualizar" de um produto;
//                2) o botão "Fazer varredura completa" (depois de confirmar).

(function () {
    var pagina = document.querySelector('.car-pagina');
    if (!pagina) return;

    var INTERVALO_STATUS_MS = 2000;
    var MAX_FALHAS_SEGUIDAS_STATUS = 5;

    var varredura_rodando = false;
    var falhas_seguidas_status = 0;
    var temporizador_status = null;

    // ================================================
    // UTILITÁRIOS
    // ================================================

    function obter_csrf() {
        var campo = document.querySelector('#car-csrf input[name="csrfmiddlewaretoken"]');
        return campo ? campo.value : '';
    }

    function formatar_numero(valor) {
        return Number(valor).toLocaleString('pt-BR');
    }

    // Função Objetivo: GET/POST que devolve {ok, status, dados}. Nunca lança
    // para HTTP de erro (409, 502...): a tela precisa ler a mensagem do servidor.
    function chamar_servidor(url, metodo) {
        var opcoes = {
            method: metodo,
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        };
        if (metodo === 'POST') {
            opcoes.headers['X-CSRFToken'] = obter_csrf();
        }
        return fetch(url, opcoes).then(function (resposta) {
            return resposta.json().catch(function () { return {}; }).then(function (dados) {
                return { ok: resposta.ok, status: resposta.status, dados: dados };
            });
        });
    }

    // ================================================
    // LISTA: abrir/fechar um produto (lê só do banco)
    // ================================================

    function carregar_ficha(produto, forcar) {
        var corpo = produto.querySelector('.car-produto-corpo');
        if (!forcar && corpo.dataset.carregado === '1') return Promise.resolve();

        var tabela_estava_aberta = !!corpo.querySelector('.car-tabela-toggle[aria-expanded="true"]');
        var botao_filtro_cards = corpo.querySelector('[data-acao="filtrar-cards"][aria-pressed="true"]');
        var filtro_cards_anterior = botao_filtro_cards ? botao_filtro_cards.dataset.filtro : 'todas';
        corpo.innerHTML = '<p class="car-vazio">Carregando…</p>';

        return fetch(produto.dataset.urlFicha, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (resposta) {
            if (!resposta.ok) throw new Error('HTTP ' + resposta.status);
            return resposta.text();
        }).then(function (html) {
            corpo.innerHTML = html;
            corpo.dataset.carregado = '1';
            if (tabela_estava_aberta) {
                var botao = corpo.querySelector('[data-acao="alternar-tabela"]');
                if (botao) alternar_tabela(botao);
            }
            if (filtro_cards_anterior !== 'todas') {
                var botao_cards = corpo.querySelector('[data-acao="filtrar-cards"][data-filtro="' + filtro_cards_anterior + '"]');
                if (botao_cards) filtrar_cards(botao_cards);
            }
        }).catch(function () {
            corpo.dataset.carregado = '0';
            corpo.innerHTML = '<p class="car-vazio">Não consegui carregar as características deste produto. ' +
                'Feche e abra a linha para tentar de novo.</p>';
        });
    }

    function alternar_produto(botao) {
        var produto = botao.closest('.car-produto');
        var corpo = produto.querySelector('.car-produto-corpo');
        var vai_abrir = botao.getAttribute('aria-expanded') !== 'true';

        botao.setAttribute('aria-expanded', vai_abrir ? 'true' : 'false');
        corpo.hidden = !vai_abrir;
        produto.classList.toggle('car-produto--aberto', vai_abrir);
        if (vai_abrir) carregar_ficha(produto, false);
    }

    // ================================================
    // FICHA: linha que expande (tabela de anúncios) e filtro da tabela
    // ================================================

    function alternar_tabela(botao) {
        var painel = document.getElementById(botao.getAttribute('aria-controls'));
        if (!painel) return;
        var vai_abrir = botao.getAttribute('aria-expanded') !== 'true';
        botao.setAttribute('aria-expanded', vai_abrir ? 'true' : 'false');
        painel.hidden = !vai_abrir;
    }

    function filtrar_tabela(botao) {
        var painel = botao.closest('.car-tabela-painel');
        var filtro = botao.dataset.filtro;
        var algum_visivel = false;

        painel.querySelectorAll('[data-acao="filtrar-tabela"]').forEach(function (outro) {
            var ativo = outro === botao;
            outro.classList.toggle('car-chip-filtro--ativo', ativo);
            outro.setAttribute('aria-pressed', ativo ? 'true' : 'false');
        });

        painel.querySelectorAll('tbody tr').forEach(function (linha) {
            var mostrar = true;
            if (filtro === 'branco') mostrar = linha.dataset.branco === '1';
            if (filtro === 'nao-lido') mostrar = linha.dataset.lido === '0';
            linha.hidden = !mostrar;
            if (mostrar) algum_visivel = true;
        });

        painel.querySelector('.car-tabela-vazia').hidden = algum_visivel;
    }

    // Filtro dos cards da ficha: "Todas", "Pedem atenção" ou "Obrigatórias".
    // Só esconde/mostra cards que já estão na página (não consulta nada).
    function filtrar_cards(botao) {
        var secao = botao.closest('.car-secao-cards');
        var filtro = botao.dataset.filtro;
        var algum_visivel = false;

        secao.querySelectorAll('[data-acao="filtrar-cards"]').forEach(function (outro) {
            var ativo = outro === botao;
            outro.classList.toggle('car-chip-filtro--ativo', ativo);
            outro.setAttribute('aria-pressed', ativo ? 'true' : 'false');
        });

        secao.querySelectorAll('.car-card').forEach(function (card) {
            var mostrar = true;
            if (filtro === 'atencao') mostrar = card.dataset.atencao === '1';
            if (filtro === 'obrigatorias') mostrar = card.dataset.obrigatorio === '1';
            card.hidden = !mostrar;
            if (mostrar) algum_visivel = true;
        });

        secao.querySelector('.car-cards-vazio').hidden = algum_visivel;
    }

    // ================================================
    // BOTÃO "ATUALIZAR" (1 produto) — lê a API do ML
    // ================================================

    function mostrar_aviso_produto(produto, texto, tipo) {
        var aviso = produto.querySelector('[data-campo="aviso"]');
        aviso.textContent = texto;
        aviso.className = 'car-produto-aviso' + (tipo ? ' car-produto-aviso--' + tipo : '');
        aviso.hidden = !texto;
    }

    function aplicar_resumo_na_linha(produto, resumo) {
        var pilula = produto.querySelector('[data-campo="estado"]');
        pilula.textContent = resumo.estado_rotulo;
        pilula.className = 'car-pilula ' + resumo.estado_classe;
        produto.querySelector('[data-campo="lidos"]').textContent = resumo.n_lidos + ' de ' + resumo.n_anuncios + (resumo.n_anuncios === 1 ? ' lido' : ' lidos');
        produto.querySelector('[data-campo="ultima"]').textContent = resumo.ultima_leitura || '—';

        var barra = produto.querySelector('[data-campo="barra"]');
        barra.max = resumo.n_anuncios;
        barra.value = resumo.n_lidos;

        // A faixa colorida da esquerda acompanha o estado (nunca/parcial/completa).
        ['nunca', 'parcial', 'completa'].forEach(function (estado) {
            produto.classList.toggle('car-produto--' + estado, estado === resumo.estado);
        });
    }

    function descrever_falhas(falhas) {
        return (falhas || []).map(function (falha) {
            return (falha.id || falha.tipo) + ': ' + falha.erro;
        }).join('\n');
    }

    function atualizar_produto(botao) {
        if (varredura_rodando) return;
        var produto = botao.closest('.car-produto');
        var texto_botao = botao.querySelector('.car-btn-texto');
        var texto_original = texto_botao.textContent;

        botao.disabled = true;
        botao.classList.add('car-btn--lendo');
        texto_botao.textContent = 'Lendo…';
        mostrar_aviso_produto(produto, 'Consultando o Mercado Livre…', '');

        chamar_servidor(produto.dataset.urlAtualizar, 'POST').then(function (resposta) {
            var dados = resposta.dados || {};
            if (!resposta.ok || !dados.ok) {
                mostrar_aviso_produto(produto, dados.mensagem || 'Não consegui atualizar este produto.', 'erro');
                return;
            }
            aplicar_resumo_na_linha(produto, dados.resumo);
            var falhas = descrever_falhas(dados.falhas);
            mostrar_aviso_produto(
                produto,
                dados.mensagem + (falhas ? '\n' + falhas : ''),
                falhas ? 'alerta' : 'ok'
            );
            var corpo = produto.querySelector('.car-produto-corpo');
            if (corpo.dataset.carregado === '1' && !corpo.hidden) {
                return carregar_ficha(produto, true);
            }
            corpo.dataset.carregado = '0';
        }).catch(function () {
            mostrar_aviso_produto(produto, 'Perdi a conexão com o servidor. Tente de novo.', 'erro');
        }).then(function () {
            texto_botao.textContent = texto_original;
            botao.classList.remove('car-btn--lendo');
            botao.disabled = varredura_rodando;
        });
    }

    // ================================================
    // BOTÃO "FAZER VARREDURA COMPLETA" — lê a API do ML
    // ================================================

    function definir_botoes_bloqueados(bloqueado) {
        var botao_varredura = document.getElementById('car-btn-varredura');
        botao_varredura.disabled = bloqueado;
        document.querySelectorAll('[data-acao="atualizar-produto"]').forEach(function (botao) {
            botao.disabled = bloqueado;
        });
    }

    function mostrar_progresso(estado) {
        var bloco = document.getElementById('car-progresso');
        var barra = document.getElementById('car-barra');
        bloco.hidden = false;

        document.getElementById('car-progresso-rotulo').textContent = estado.rotulo || 'Lendo';
        if (estado.total) {
            barra.max = estado.total;
            barra.value = estado.atual || 0;
            document.getElementById('car-progresso-numeros').textContent =
                formatar_numero(estado.atual || 0) + ' de ' + formatar_numero(estado.total);
        } else {
            barra.removeAttribute('value');
            document.getElementById('car-progresso-numeros').textContent = '';
        }
    }

    function mostrar_resultado(texto, tipo, com_recarregar) {
        var bloco = document.getElementById('car-resultado');
        bloco.className = 'car-resultado' + (tipo ? ' car-resultado--' + tipo : '');
        document.getElementById('car-resultado-texto').textContent = texto;
        document.getElementById('car-resultado-recarregar').hidden = !com_recarregar;
        bloco.hidden = false;
    }

    function encerrar_varredura(estado) {
        varredura_rodando = false;
        clearTimeout(temporizador_status);
        document.getElementById('car-progresso').hidden = true;
        definir_botoes_bloqueados(false);

        if (estado.status === 'concluido') {
            mostrar_resultado(estado.mensagem, estado.com_falhas ? 'alerta' : 'ok', true);
        } else {
            mostrar_resultado(estado.mensagem || 'A varredura terminou com erro.', 'erro', false);
        }
    }

    function tratar_estado_varredura(estado) {
        if (estado.status === 'rodando') {
            varredura_rodando = true;
            definir_botoes_bloqueados(true);
            document.getElementById('car-resultado').hidden = true;
            mostrar_progresso(estado);
            agendar_consulta_status();
        } else if (estado.status === 'concluido' || estado.status === 'erro') {
            encerrar_varredura(estado);
        }
        // 'ocioso': nada rodando, nada a mostrar.
    }

    function consultar_status() {
        chamar_servidor(pagina.dataset.urlVarreduraStatus, 'GET').then(function (resposta) {
            falhas_seguidas_status = 0;
            tratar_estado_varredura(resposta.dados || {});
        }).catch(function () {
            falhas_seguidas_status += 1;
            if (falhas_seguidas_status >= MAX_FALHAS_SEGUIDAS_STATUS) {
                varredura_rodando = false;
                definir_botoes_bloqueados(false);
                mostrar_resultado(
                    'Perdi a conexão com o servidor. Se a varredura já tinha começado, ela continua rodando lá; ' +
                    'recarregue a página para ver o andamento.',
                    'alerta', true
                );
                return;
            }
            agendar_consulta_status();
        });
    }

    function agendar_consulta_status() {
        clearTimeout(temporizador_status);
        temporizador_status = setTimeout(consultar_status, INTERVALO_STATUS_MS);
    }

    function iniciar_varredura() {
        var modal_elemento = document.getElementById('car-modal-varredura');
        var modal = window.bootstrap ? window.bootstrap.Modal.getInstance(modal_elemento) : null;
        if (modal) modal.hide();

        definir_botoes_bloqueados(true);
        document.getElementById('car-resultado').hidden = true;
        mostrar_progresso({ rotulo: 'Preparando a leitura', total: null });

        chamar_servidor(pagina.dataset.urlVarreduraIniciar, 'POST').then(function (resposta) {
            if (!resposta.ok) {
                definir_botoes_bloqueados(false);
                document.getElementById('car-progresso').hidden = true;
                mostrar_resultado((resposta.dados && resposta.dados.mensagem) || 'Não consegui iniciar a varredura.', 'erro', false);
                return;
            }
            tratar_estado_varredura(resposta.dados);
        }).catch(function () {
            definir_botoes_bloqueados(false);
            document.getElementById('car-progresso').hidden = true;
            mostrar_resultado('Perdi a conexão com o servidor. A varredura não foi iniciada.', 'erro', false);
        });
    }

    // ================================================
    // EVENTOS (delegação: valem também para o que entra depois, via fetch)
    // ================================================

    pagina.addEventListener('click', function (evento) {
        var alvo = evento.target.closest('[data-acao]');
        if (!alvo || !pagina.contains(alvo)) return;

        var acao = alvo.dataset.acao;
        if (acao === 'alternar-produto') alternar_produto(alvo);
        else if (acao === 'atualizar-produto') atualizar_produto(alvo);
        else if (acao === 'alternar-tabela') alternar_tabela(alvo);
        else if (acao === 'filtrar-tabela') filtrar_tabela(alvo);
        else if (acao === 'filtrar-cards') filtrar_cards(alvo);
    });

    document.getElementById('car-modal-confirmar').addEventListener('click', iniciar_varredura);

    document.getElementById('car-resultado-recarregar').addEventListener('click', function () {
        window.location.reload();
    });

    // Ao abrir a página: só PERGUNTA ao servidor se há varredura em andamento
    // (lê o cache do servidor; não chama o Mercado Livre).
    consultar_status();
})();
