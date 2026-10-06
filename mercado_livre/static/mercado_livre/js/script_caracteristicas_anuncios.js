// * [RESUMO] → Script da tela "Características dos anúncios" do ML.
//              REGRA: este script NUNCA chama a API do Mercado Livre por
//              conta própria. Abrir um produto, filtrar a tabela, digitar um
//              valor, "Revisar e enviar" ou recarregar só pedem dados ao
//              nosso servidor (que lê do banco). Os ÚNICOS gatilhos que fazem
//              o servidor consultar ou escrever no ML são:
//                1) o botão "Atualizar" de um produto;
//                2) o botão "Fazer varredura completa" (depois de confirmar);
//                3) o botão "Confirmar envio" da janela de envio.
//              NÃO existe rascunho: o que se digita em "Valor a enviar" vive
//              só nesta página; sem enviar, o digitado se perde.

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
    // "corpo" (opcional, só no POST) vai como JSON.
    function chamar_servidor(url, metodo, corpo) {
        var opcoes = {
            method: metodo,
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        };
        if (metodo === 'POST') {
            opcoes.headers['X-CSRFToken'] = obter_csrf();
            if (corpo !== undefined) {
                opcoes.headers['Content-Type'] = 'application/json';
                opcoes.body = JSON.stringify(corpo);
            }
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

    // "manter" (opcional) = lista de IDs de característica cujo valor digitado
    // deve continuar preenchido depois de recarregar a ficha. Sem ele, tudo que
    // estava digitado continua (ex.: depois de "Atualizar"). Depois de um envio,
    // só continua o que NÃO ficou aplicado no Mercado Livre.
    function carregar_ficha(produto, forcar, manter) {
        var corpo = produto.querySelector('.car-produto-corpo');
        if (!forcar && corpo.dataset.carregado === '1') return Promise.resolve();

        // Na recarga a ficha antiga continua na tela até a nova chegar: se a
        // recarga falhar, o que o usuário digitou não se perde.
        var primeira_carga = corpo.dataset.carregado !== '1';
        if (primeira_carga) corpo.innerHTML = '<p class="car-vazio">Carregando…</p>';

        return fetch(produto.dataset.urlFicha, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (resposta) {
            if (!resposta.ok) throw new Error('HTTP ' + resposta.status);
            return resposta.text();
        }).then(function (html) {
            var tabela_estava_aberta = !!corpo.querySelector('.car-tabela-toggle[aria-expanded="true"]');
            var botao_filtro_cards = corpo.querySelector('[data-acao="filtrar-cards"][aria-pressed="true"]');
            var filtro_cards_anterior = botao_filtro_cards ? botao_filtro_cards.dataset.filtro : 'todas';
            var valores_digitados = corpo.dataset.carregado === '1' ? coletar_valores(corpo) : {};
            if (manter) {
                Object.keys(valores_digitados).forEach(function (atributo) {
                    if (manter.indexOf(atributo) === -1) delete valores_digitados[atributo];
                });
            }

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
            aplicar_valores(corpo, valores_digitados);
            atualizar_barra_envio(produto);
        }).catch(function () {
            if (primeira_carga) {
                corpo.dataset.carregado = '0';
                corpo.innerHTML = '<p class="car-vazio">Não consegui carregar as características deste produto. ' +
                    'Feche e abra a linha para tentar de novo.</p>';
            } else {
                mostrar_aviso_produto(
                    produto,
                    'Não consegui recarregar as características agora. O que você digitou continua na tela; ' +
                    'clique em "Atualizar" para tentar de novo.',
                    'alerta'
                );
            }
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
    // VALOR A ENVIAR — o que o usuário digita vive SÓ nesta página
    // ================================================

    var envio_em_andamento = false;
    var produto_em_revisao = null;   // .car-produto cuja janela de envio está aberta
    var valores_em_revisao = null;   // o que foi digitado, exatamente como foi para a prévia
    var resultado_do_envio = null;   // {produto, dados} quando o envio terminou e a janela ainda está aberta
    var card_a_mostrar = null;       // primeiro card com erro, para rolar até ele ao fechar a janela

    function entrada_do_card(card, nome) {
        return card.querySelector('[data-entrada="' + nome + '"]');
    }

    // Função Objetivo: Lê o que foi preenchido num card. Devolve null quando o
    // card está vazio ("não mexer no Mercado Livre") ou não é editável.
    function ler_card(card) {
        if (card.dataset.editavel !== '1') return null;
        var tipo = card.dataset.tipo;

        if (tipo === 'lista') {
            var apertado = card.querySelector('.car-btn-simnao[aria-pressed="true"]');
            var seletor = entrada_do_card(card, 'valor_id');
            var valor_id = apertado ? apertado.dataset.valorId : (seletor ? seletor.value : '');
            return valor_id ? { valor_id: valor_id } : null;
        }
        if (tipo === 'numero_unidade') {
            var numero = entrada_do_card(card, 'numero').value.trim();
            var unidade = entrada_do_card(card, 'unidade').value;
            return numero ? { numero: numero, unidade: unidade } : null;
        }
        if (tipo === 'numero') {
            var so_numero = entrada_do_card(card, 'numero').value.trim();
            return so_numero ? { numero: so_numero } : null;
        }
        var texto = entrada_do_card(card, 'texto').value.trim();
        return texto ? { texto: texto } : null;
    }

    function preencher_card(card, valor) {
        var tipo = card.dataset.tipo;
        if (tipo === 'lista') {
            card.querySelectorAll('.car-btn-simnao').forEach(function (botao) {
                botao.setAttribute('aria-pressed', botao.dataset.valorId === valor.valor_id ? 'true' : 'false');
            });
            var seletor = entrada_do_card(card, 'valor_id');
            if (seletor) seletor.value = valor.valor_id || '';
        } else if (tipo === 'numero_unidade') {
            entrada_do_card(card, 'numero').value = valor.numero || '';
            if (valor.unidade) entrada_do_card(card, 'unidade').value = valor.unidade;
        } else if (tipo === 'numero') {
            entrada_do_card(card, 'numero').value = valor.numero || '';
        } else {
            entrada_do_card(card, 'texto').value = valor.texto || '';
        }
    }

    function limpar_card(card) {
        card.querySelectorAll('.car-btn-simnao').forEach(function (botao) {
            botao.setAttribute('aria-pressed', 'false');
        });
        card.querySelectorAll('.car-entrada').forEach(function (campo) {
            if (campo.tagName === 'SELECT') campo.selectedIndex = 0;
            else campo.value = '';
        });
    }

    function limpar_erro_do_card(card) {
        var area = card.querySelector('[data-campo="erro"]');
        if (area) {
            area.hidden = true;
            area.textContent = '';
        }
        card.classList.remove('car-card--com-erro');
    }

    // Função Objetivo: Deixa o card igual ao que está digitado: marcador
    // "Alterado, não enviado", botão "Desfazer" e contador de caracteres. Quem
    // digita de novo também apaga o erro que a revisão tinha marcado no card.
    function atualizar_card(card) {
        var alterado = ler_card(card) !== null;
        card.dataset.alterado = alterado ? '1' : '0';
        card.classList.toggle('car-card--alterado', alterado);

        var marca = card.querySelector('[data-campo="marca-alterado"]');
        if (marca) marca.hidden = !alterado;
        var desfazer = card.querySelector('[data-acao="limpar-campo"]');
        if (desfazer) desfazer.hidden = !alterado;

        var contador = card.querySelector('[data-campo="caracteres"]');
        if (contador) {
            var limite = Number(contador.dataset.limite);
            var n = Array.from(entrada_do_card(card, 'texto').value.trim()).length;
            contador.textContent = n + ' / ' + limite;
            contador.classList.toggle('car-caracteres--excedido', n > limite);
        }
        limpar_erro_do_card(card);
    }

    // Função Objetivo: {atributo_id: {valor_id|texto|numero|unidade}} só com os
    // cards preenchidos — é isso que vai para a prévia e para o envio.
    function coletar_valores(corpo) {
        var valores = {};
        corpo.querySelectorAll('.car-card').forEach(function (card) {
            var valor = ler_card(card);
            if (valor) valores[card.dataset.atributo] = valor;
        });
        return valores;
    }

    // Função Objetivo: Devolve ao card o que estava digitado (depois de a ficha
    // ser recarregada). Característica que não existe mais na ficha nova perde
    // o valor — não há onde colocá-lo.
    function aplicar_valores(corpo, valores) {
        corpo.querySelectorAll('.car-card').forEach(function (card) {
            var valor = valores[card.dataset.atributo];
            if (!valor || card.dataset.editavel !== '1') return;
            preencher_card(card, valor);
            atualizar_card(card);
        });
    }

    function atualizar_barra_envio(produto) {
        var corpo = produto.querySelector('.car-produto-corpo');
        var n = corpo.querySelectorAll('.car-card[data-alterado="1"]').length;
        var texto_barra = n
            ? n + (n === 1 ? ' campo alterado, ainda não enviado.' : ' campos alterados, ainda não enviados.')
            : 'Nenhum campo alterado. Campo vazio = não mexe no Mercado Livre.';

        corpo.querySelectorAll('[data-campo="contagem-alterados"]').forEach(function (area) {
            area.textContent = texto_barra;
            area.classList.toggle('car-envio-contagem--ativa', n > 0);
        });
        corpo.querySelectorAll('[data-acao="revisar-envio"], [data-acao="descartar-alteracoes"]').forEach(function (botao) {
            botao.disabled = n === 0 || envio_em_andamento;
        });

        var marcador = produto.querySelector('[data-campo="alterados-linha"]');
        marcador.hidden = n === 0;
        marcador.textContent = n
            ? '● ' + n + (n === 1 ? ' campo alterado, ainda não enviado' : ' campos alterados, ainda não enviados')
            : '';
        produto.classList.toggle('car-produto--com-alteracoes', n > 0);
    }

    // Função Objetivo: Põe a mensagem de erro de cada campo no card dele. Se o
    // card está escondido pelo filtro, volta o filtro para "Todas" (senão a
    // pessoa não veria o erro). Devolve o primeiro card com erro.
    function marcar_erros_dos_campos(corpo, erros) {
        var primeiro = null;
        var escondido = false;
        corpo.querySelectorAll('.car-card').forEach(function (card) {
            var mensagem = erros && erros[card.dataset.atributo];
            var area = card.querySelector('[data-campo="erro"]');
            if (!mensagem || !area) return;
            area.textContent = mensagem;
            area.hidden = false;
            card.classList.add('car-card--com-erro');
            if (card.hidden) escondido = true;
            if (!primeiro) primeiro = card;
        });
        if (escondido) {
            var todas = corpo.querySelector('[data-acao="filtrar-cards"][data-filtro="todas"]');
            if (todas) filtrar_cards(todas);
        }
        return primeiro;
    }

    function limpar_erros_dos_campos(corpo) {
        corpo.querySelectorAll('.car-card--com-erro').forEach(limpar_erro_do_card);
    }

    function ao_alterar_campo(evento) {
        if (!evento.target.matches || !evento.target.matches('.car-entrada')) return;
        var card = evento.target.closest('.car-card');
        if (!card) return;
        atualizar_card(card);
        atualizar_barra_envio(card.closest('.car-produto'));
    }

    function escolher_simnao(botao) {
        var card = botao.closest('.car-card');
        var ja_escolhido = botao.getAttribute('aria-pressed') === 'true';
        card.querySelectorAll('.car-btn-simnao').forEach(function (outro) {
            outro.setAttribute('aria-pressed', 'false');
        });
        // Apertar de novo na opção já escolhida tira a escolha ("não mexer").
        if (!ja_escolhido) botao.setAttribute('aria-pressed', 'true');
        atualizar_card(card);
        atualizar_barra_envio(card.closest('.car-produto'));
    }

    function limpar_campo(botao) {
        var card = botao.closest('.car-card');
        limpar_card(card);
        atualizar_card(card);
        atualizar_barra_envio(card.closest('.car-produto'));
    }

    function descartar_alteracoes(botao) {
        var produto = botao.closest('.car-produto');
        var cards = produto.querySelectorAll('.car-card[data-alterado="1"]');
        if (!cards.length) return;
        var pergunta = 'Descartar ' + cards.length + (cards.length === 1 ? ' campo alterado' : ' campos alterados') +
            ' deste produto? O que foi digitado será perdido.';
        if (!window.confirm(pergunta)) return;
        cards.forEach(function (card) {
            limpar_card(card);
            atualizar_card(card);
        });
        atualizar_barra_envio(produto);
    }

    // ================================================
    // JANELA DO ENVIO: prévia ("Revisar e enviar") e resultado ("Confirmar envio")
    // ================================================

    function obter_janela_envio() {
        var elemento = document.getElementById('car-modal-envio');
        return window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(elemento) : null;
    }

    // modo: 'revisao' (prévia, ainda sem enviar nada) ou 'resultado' (depois do envio).
    function mostrar_janela_envio(modo, html, pode_confirmar) {
        document.getElementById('car-modal-envio-titulo').textContent = modo === 'resultado' ? 'Resultado do envio' : 'Revisar o envio';
        document.getElementById('car-modal-envio-corpo').innerHTML = html;
        definir_estado_janela('', '');

        var confirmar = document.getElementById('car-modal-envio-confirmar');
        confirmar.hidden = !(modo === 'revisao' && pode_confirmar);
        confirmar.disabled = false;
        var cancelar = document.getElementById('car-modal-envio-cancelar');
        cancelar.disabled = false;
        cancelar.textContent = modo === 'resultado' ? 'Fechar' : 'Cancelar';
        document.getElementById('car-modal-envio-x').disabled = false;

        var janela = obter_janela_envio();
        if (janela) janela.show();
    }

    // tipo: '' (aviso neutro) ou 'erro'. texto vazio esconde a faixa.
    function definir_estado_janela(texto, tipo) {
        var area = document.getElementById('car-modal-envio-estado');
        area.textContent = texto;
        area.className = 'car-modal-envio-estado' + (tipo ? ' car-modal-envio-estado--' + tipo : '');
        area.hidden = !texto;
    }

    function definir_janela_ocupada(ocupada) {
        document.getElementById('car-modal-envio-confirmar').disabled = ocupada;
        document.getElementById('car-modal-envio-cancelar').disabled = ocupada;
        document.getElementById('car-modal-envio-x').disabled = ocupada;
    }

    function revisar_envio(botao) {
        var produto = botao.closest('.car-produto');
        var corpo = produto.querySelector('.car-produto-corpo');
        var valores = coletar_valores(corpo);
        if (!Object.keys(valores).length) return;

        limpar_erros_dos_campos(corpo);
        corpo.querySelectorAll('[data-acao="revisar-envio"]').forEach(function (b) { b.disabled = true; });
        mostrar_aviso_produto(produto, 'Montando a prévia do envio…', '');

        chamar_servidor(produto.dataset.urlRevisar, 'POST', { valores: valores }).then(function (resposta) {
            var dados = resposta.dados || {};
            if (!resposta.ok || !dados.ok) {
                mostrar_aviso_produto(produto, dados.mensagem || 'Não consegui montar a prévia do envio.', 'erro');
                return;
            }
            mostrar_aviso_produto(produto, '', '');
            card_a_mostrar = marcar_erros_dos_campos(corpo, dados.erros_por_campo);
            produto_em_revisao = produto;
            valores_em_revisao = valores;
            mostrar_janela_envio('revisao', dados.html, dados.pode_enviar);
        }).catch(function () {
            mostrar_aviso_produto(produto, 'Perdi a conexão com o servidor. Tente de novo.', 'erro');
        }).then(function () {
            atualizar_barra_envio(produto);
        });
    }

    // Função Objetivo: "Confirmar envio" — o ÚNICO ponto desta tela que manda
    // dados ao Mercado Livre (via nosso servidor). Reenvia ao servidor os mesmos
    // valores da prévia; o servidor confere tudo de novo antes de enviar.
    function confirmar_envio() {
        if (envio_em_andamento || !produto_em_revisao || !valores_em_revisao) return;
        var produto = produto_em_revisao;
        var corpo = produto.querySelector('.car-produto-corpo');
        var confirmar = document.getElementById('car-modal-envio-confirmar');

        envio_em_andamento = true;
        definir_janela_ocupada(true);
        definir_estado_janela('Enviando ao Mercado Livre e lendo de volta… não feche esta janela.', '');
        atualizar_barra_envio(produto);

        chamar_servidor(produto.dataset.urlEnviar, 'POST', { valores: valores_em_revisao }).then(function (resposta) {
            var dados = resposta.dados || {};
            if (!resposta.ok || !dados.ok) {
                // Nada foi enviado quando o servidor recusa antes (409, 422, 404); só 500 deixa dúvida.
                if (dados.erros_por_campo) card_a_mostrar = marcar_erros_dos_campos(corpo, dados.erros_por_campo);
                definir_estado_janela(dados.mensagem || 'Não consegui enviar.', 'erro');
                confirmar.hidden = resposta.status !== 409;
                return;
            }
            resultado_do_envio = { produto: produto, dados: dados };
            valores_em_revisao = null;
            aplicar_resumo_na_linha(produto, dados.resumo);
            mostrar_janela_envio('resultado', dados.html, false);
        }).catch(function () {
            definir_estado_janela(
                'Perdi a conexão com o servidor. Não sei se o envio chegou ao Mercado Livre: feche esta janela e ' +
                'clique em "Atualizar" no produto para conferir.', 'erro'
            );
            confirmar.hidden = true;
        }).then(function () {
            envio_em_andamento = false;
            document.getElementById('car-modal-envio-cancelar').disabled = false;
            document.getElementById('car-modal-envio-x').disabled = false;
            confirmar.disabled = false;
            atualizar_barra_envio(produto);
        });
    }

    // Ao fechar a janela: se houve envio, recarrega a ficha (o banco já tem o que
    // o Mercado Livre devolveu) mantendo digitado só o que NÃO ficou aplicado.
    function ao_fechar_janela_envio() {
        document.getElementById('car-modal-envio-corpo').innerHTML = '';
        definir_estado_janela('', '');

        if (resultado_do_envio) {
            var produto = resultado_do_envio.produto;
            var dados = resultado_do_envio.dados;
            resultado_do_envio = null;
            mostrar_aviso_produto(produto, dados.mensagem, dados.todos_ok ? 'ok' : 'alerta');
            carregar_ficha(produto, true, dados.pendentes || []);
        } else if (card_a_mostrar) {
            card_a_mostrar.scrollIntoView({ block: 'center' });
        }
        card_a_mostrar = null;
        produto_em_revisao = null;
        valores_em_revisao = null;
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
        else if (acao === 'escolher-simnao') escolher_simnao(alvo);
        else if (acao === 'limpar-campo') limpar_campo(alvo);
        else if (acao === 'descartar-alteracoes') descartar_alteracoes(alvo);
        else if (acao === 'revisar-envio') revisar_envio(alvo);
    });

    pagina.addEventListener('input', ao_alterar_campo);
    pagina.addEventListener('change', ao_alterar_campo);

    document.getElementById('car-modal-confirmar').addEventListener('click', iniciar_varredura);
    document.getElementById('car-modal-envio-confirmar').addEventListener('click', confirmar_envio);
    document.getElementById('car-modal-envio').addEventListener('hidden.bs.modal', ao_fechar_janela_envio);

    // Sem rascunho, o digitado só existe nesta página: avisa antes de sair com
    // campos alterados (ou com um envio em andamento).
    window.addEventListener('beforeunload', function (evento) {
        if (!envio_em_andamento && !pagina.querySelector('.car-card[data-alterado="1"]')) return;
        evento.preventDefault();
        evento.returnValue = '';
    });

    document.getElementById('car-resultado-recarregar').addEventListener('click', function () {
        window.location.reload();
    });

    // Ao abrir a página: só PERGUNTA ao servidor se há varredura em andamento
    // (lê o cache do servidor; não chama o Mercado Livre).
    consultar_status();
})();
