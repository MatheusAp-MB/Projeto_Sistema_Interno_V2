// * [RESUMO] → Script da tela "Características dos anúncios" do ML.
//              REGRA: este script NUNCA chama a API do Mercado Livre por
//              conta própria. Abrir um produto, filtrar, abrir os detalhes de
//              um campo, digitar um valor, "Revisar e enviar" ou recarregar só
//              pedem dados ao nosso servidor (que lê do banco). Os ÚNICOS
//              gatilhos que fazem o servidor consultar ou escrever no ML são:
//                1) o botão "Atualizar" de um produto;
//                2) o botão "Fazer varredura completa" (depois de confirmar);
//                3) o botão "Confirmar envio" da janela de envio.
//              NÃO existe rascunho: o que se digita em "Valor a enviar" vive
//              só nesta página; sem enviar, o digitado se perde.
//              A IA ainda NÃO está conectada: os lugares dela (sugestão no
//              card, custo e tokens no painel do topo da ficha, "Entrada e saída") existem, mas
//              mostram "—" / "ainda não conectada" — nenhum número inventado.
//              As explicações de "passar o mouse" (title) viram um balão
//              padronizado da tela (car-dica) — ver a seção DICAS.

(function () {
    'use strict';

    var pagina = document.querySelector('.car-pagina');
    if (!pagina) return;

    var INTERVALO_STATUS_MS = 2000;
    var MAX_FALHAS_SEGUIDAS_STATUS = 5;

    var varredura_rodando = false;
    var varredura_vista_rodando = false;   // esta página viu a varredura rodar (para somar as chamadas dela)
    var falhas_seguidas_status = 0;
    var temporizador_status = null;

    var envio_em_andamento = false;
    var produto_em_revisao = null;   // .car-produto cuja janela de envio está aberta
    var valores_em_revisao = null;   // o que foi digitado, exatamente como foi para a prévia
    var origens_em_revisao = null;   // de onde veio cada valor da prévia {atributo: origem}
    var resultado_do_envio = null;   // {produto, dados, enviados} quando o envio terminou e a janela ainda está aberta
    var card_a_mostrar = null;       // primeiro card com erro, para rolar até ele ao fechar a janela

    var estado_visual = {};          // por SKU: filtro, grupos recolhidos e tabela (para a recarga da ficha)
    var gaveta = { fundo: null, anterior: null, card: null };

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

    function criar(tag, classe, texto) {
        var no = document.createElement(tag);
        if (classe) no.className = classe;
        if (texto !== undefined && texto !== null) no.textContent = texto;
        return no;
    }

    function juntar_espacos(texto) {
        return (texto || '').replace(/\s+/g, ' ').trim();
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

    // Memória da aba (sessionStorage), sempre dentro de try/catch: pode estar
    // bloqueada. A tela funciona igual sem ela.
    function ler_armazenado(chave, padrao) {
        try {
            var texto = window.sessionStorage.getItem(chave);
            return texto ? JSON.parse(texto) : padrao;
        } catch (erro) {
            return padrao;
        }
    }

    function gravar_armazenado(chave, valor) {
        try {
            window.sessionStorage.setItem(chave, JSON.stringify(valor));
        } catch (erro) { /* sem memória da aba: segue sem ela */ }
    }

    function anunciar(texto) {
        var area = document.getElementById('car-anunciador');
        if (area) area.textContent = texto;
    }

    // ================================================
    // CHAMADAS À API GASTAS NESTA SESSÃO
    // ================================================
    // O número de cada operação vem do SERVIDOR (requisições HTTP reais, com
    // novas tentativas). Aqui só se soma o que esta aba viu acontecer.

    var sessao = ler_armazenado('car-sessao', null) || { atualizar: 0, varredura: 0, envio: 0 };

    function desenhar_sessao() {
        var bloco = document.getElementById('car-sessao-chamadas');
        if (!bloco) return;
        var total = (sessao.atualizar || 0) + (sessao.varredura || 0) + (sessao.envio || 0);
        var partes = [];
        if (sessao.varredura) partes.push('varredura ' + formatar_numero(sessao.varredura));
        if (sessao.atualizar) partes.push('Atualizar ' + formatar_numero(sessao.atualizar));
        if (sessao.envio) partes.push('envio ' + formatar_numero(sessao.envio));
        bloco.querySelector('[data-campo="sessao-total"]').textContent = formatar_numero(total);
        bloco.querySelector('[data-campo="sessao-detalhe"]').textContent = partes.length ? '(' + partes.join(' · ') + ')' : '';
    }

    function registrar_chamadas(tipo, quantidade) {
        var n = Number(quantidade) || 0;
        if (!n) return;
        sessao[tipo] = (sessao[tipo] || 0) + n;
        gravar_armazenado('car-sessao', sessao);
        desenhar_sessao();
    }

    // ================================================
    // LISTA: abrir/fechar um produto (lê só do banco)
    // ================================================

    // Guarda o que é "só visual" da ficha (filtro dos cards, grupos recolhidos,
    // tabela aberta e o campo escolhido nela) para devolver depois da recarga.
    function guardar_estado_visual(produto) {
        var ficha = produto.querySelector('.car-ficha');
        if (!ficha) return;
        var botao_filtro = ficha.querySelector('[data-acao="filtrar-cards"][aria-pressed="true"]');
        var botao_tabela = ficha.querySelector('[data-acao="alternar-tabela"]');
        var seletor = ficha.querySelector('[data-acao-mudar="campo-tabela"]');
        var filtro_tabela = ficha.querySelector('[data-acao="filtrar-tabela"][aria-pressed="true"]');
        estado_visual[produto.dataset.sku] = {
            filtro: botao_filtro ? botao_filtro.dataset.filtro : null,
            grupos_fechados: Array.from(ficha.querySelectorAll('.car-grupo-toggle[aria-expanded="false"]')).map(function (botao) {
                return botao.closest('.car-grupo').dataset.grupo;
            }),
            tabela_aberta: !!botao_tabela && botao_tabela.getAttribute('aria-expanded') === 'true',
            campo_tabela: seletor ? seletor.value : null,
            filtro_tabela: filtro_tabela ? filtro_tabela.dataset.filtro : null
        };
    }

    function restaurar_estado_visual(produto) {
        var ficha = produto.querySelector('.car-ficha');
        if (!ficha) return;
        var guardado = estado_visual[produto.dataset.sku] || {};

        var seletor = ficha.querySelector('[data-acao-mudar="campo-tabela"]');
        if (seletor && guardado.campo_tabela && seletor.querySelector('option[value="' + guardado.campo_tabela + '"]')) {
            seletor.value = guardado.campo_tabela;
            mostrar_coluna_da_tabela(seletor);
        }
        var botao_tabela = ficha.querySelector('[data-acao="alternar-tabela"]');
        if (botao_tabela && guardado.tabela_aberta) alternar_tabela(botao_tabela);
        if (guardado.filtro_tabela && guardado.filtro_tabela !== 'todos') {
            var botao_ft = ficha.querySelector('[data-acao="filtrar-tabela"][data-filtro="' + guardado.filtro_tabela + '"]');
            if (botao_ft) filtrar_tabela(botao_ft);
        }

        (guardado.grupos_fechados || []).forEach(function (id) {
            var grupo = ficha.querySelector('.car-grupo[data-grupo="' + id + '"]');
            var botao = grupo && grupo.querySelector('[data-acao="alternar-grupo"]');
            if (botao) alternar_grupo(botao);
        });

        var filtro = guardado.filtro || ficha.dataset.filtroInicial || 'todos';
        var botao_cards = ficha.querySelector('[data-acao="filtrar-cards"][data-filtro="' + filtro + '"]') ||
            ficha.querySelector('[data-acao="filtrar-cards"][data-filtro="todos"]');
        if (botao_cards) filtrar_cards(botao_cards);
    }

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
            var recarga = corpo.dataset.carregado === '1';
            if (recarga) guardar_estado_visual(produto);
            var digitados = recarga ? coletar_digitados(corpo) : {};
            if (manter) {
                Object.keys(digitados).forEach(function (atributo) {
                    if (manter.indexOf(atributo) === -1) delete digitados[atributo];
                });
            }

            corpo.innerHTML = html;
            corpo.dataset.carregado = '1';
            // O "Ver produto" da ficha usa HTMX: o conteúdo novo precisa ser apresentado a ele.
            if (window.htmx && typeof window.htmx.process === 'function') window.htmx.process(corpo);

            aplicar_memoria_de_envio(produto);
            aplicar_digitados(corpo, digitados);
            restaurar_estado_visual(produto);
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
    // FICHA: tabela de anúncios (1 campo por vez) e filtros dos cards
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

    // A tabela mostra 1 característica por vez: o seletor "Campo" troca a coluna.
    function mostrar_coluna_da_tabela(seletor) {
        var painel = seletor.closest('.car-tabela-painel');
        var atributo = seletor.value;
        painel.querySelectorAll('th[data-atributo], td[data-atributo]').forEach(function (celula) {
            celula.hidden = celula.dataset.atributo !== atributo;
        });
    }

    function alternar_grupo(botao) {
        var grupo = botao.closest('.car-grupo');
        var grade = grupo.querySelector('.car-cards-grade');
        var vai_abrir = botao.getAttribute('aria-expanded') !== 'true';
        botao.setAttribute('aria-expanded', vai_abrir ? 'true' : 'false');
        grade.hidden = !vai_abrir;
    }

    function card_passa_no_filtro(card, filtro) {
        if (filtro === 'resolver') return card.dataset.resolver === '1';
        if (filtro === 'obrigatorios') return card.dataset.obrigatorio === '1';
        if (filtro === 'vazios') return card.dataset.estado === 'vazio';
        if (filtro === 'preparados') return card.dataset.alterado === '1';
        return true;   // 'todos'
    }

    // Filtro dos cards: só esconde/mostra cards que já estão na página (não
    // consulta nada). É aplicado ao CLICAR no filtro — digitar num card não faz
    // o card sumir nem mudar de lugar no meio da edição.
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
            var mostrar = card_passa_no_filtro(card, filtro);
            card.hidden = !mostrar;
            if (mostrar) algum_visivel = true;
        });

        // O grupo (Características principais, Outros...) some junto quando o
        // filtro esconde todos os cards dele; senão mostra quantos sobraram.
        secao.querySelectorAll('.car-grupo').forEach(function (grupo) {
            var n = grupo.querySelectorAll('.car-card:not([hidden])').length;
            grupo.hidden = n === 0;
            var campo = grupo.querySelector('[data-campo="grupo-filtro"]');
            if (campo) campo.textContent = n;
        });

        secao.querySelector('.car-cards-vazio').hidden = algum_visivel;
        anunciar(algum_visivel ? '' : 'Nenhum campo neste filtro.');
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
        if (varredura_rodando || envio_em_andamento) return;
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
            registrar_chamadas('atualizar', dados.chamadas);
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

        // Só soma na sessão uma varredura que esta página viu rodar (o servidor
        // entrega o resultado final uma única vez).
        if (varredura_vista_rodando) registrar_chamadas('varredura', estado.chamadas);
        varredura_vista_rodando = false;

        if (estado.status === 'concluido') {
            mostrar_resultado(estado.mensagem, estado.com_falhas ? 'alerta' : 'ok', true);
        } else {
            mostrar_resultado(estado.mensagem || 'A varredura terminou com erro.', 'erro', false);
        }
    }

    function tratar_estado_varredura(estado) {
        if (estado.status === 'rodando') {
            varredura_rodando = true;
            varredura_vista_rodando = true;
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

    // ORIGEM do valor de um card: de onde veio o que está no campo. Aparece no
    // card, na janela "Revisar o envio" e, depois de enviado, na memória desta aba.
    var TEXTO_ORIGEM = {
        usuario: '✎ Digitado por você · não enviado',
        existente: '⧉ Copiado de um anúncio · não enviado',
        ia: '✦ Sugestão da IA aceita · não enviada',
        'ia-editada': '✦ Sugestão da IA, editada por você · não enviada'
    };
    var TEXTO_ORIGEM_CURTO = {
        usuario: '✎ Digitado por você',
        existente: '⧉ Copiado de um anúncio',
        ia: '✦ Sugestão da IA (aceita)',
        'ia-editada': '✦ Sugestão da IA, editada por você'
    };
    var TEXTO_ORIGEM_ENVIADA = {
        usuario: '✔ Enviado nesta sessão · digitado por você',
        existente: '✔ Enviado nesta sessão · copiado de um anúncio',
        ia: '✔ Enviado nesta sessão · sugestão da IA',
        'ia-editada': '✔ Enviado nesta sessão · sugestão da IA editada'
    };

    // Memória (desta aba) do que foi enviado e de onde veio: {sku: {atributo: origem}}.
    // Depois do envio a ficha recarrega e o campo volta vazio (o valor agora é o
    // do próprio ML); a origem fica anotada no card para não se perder.
    var memoria_de_envio = ler_armazenado('car-enviados', {});

    function aplicar_memoria_de_envio(produto) {
        var memoria = memoria_de_envio[produto.dataset.sku];
        if (!memoria) return;
        produto.querySelectorAll('.car-card').forEach(function (card) {
            var origem = memoria[card.dataset.atributo];
            if (!origem) return;
            card.dataset.origemEnviada = origem;
            desenhar_origem(card);
        });
    }

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

    // Texto legível do valor digitado (para a gaveta).
    function descrever_valor(card, valor) {
        if (!valor) return '';
        if (valor.valor_id !== undefined) {
            var botao = card.querySelector('.car-btn-simnao[data-valor-id="' + valor.valor_id + '"]');
            if (botao) return botao.dataset.texto;
            var opcao = card.querySelector('select[data-entrada="valor_id"] option[value="' + valor.valor_id + '"]');
            return opcao ? opcao.textContent : valor.valor_id;
        }
        if (valor.numero !== undefined) return valor.numero + (valor.unidade ? ' ' + valor.unidade : '');
        return valor.texto || '';
    }

    function limpar_erro_do_card(card) {
        var area = card.querySelector('[data-campo="erro"]');
        if (area) {
            area.hidden = true;
            area.textContent = '';
        }
        card.classList.remove('car-card--com-erro');
    }

    // Escreve na linha "de onde veio" do card (só cards editáveis).
    function desenhar_origem(card) {
        if (card.dataset.editavel !== '1') return;
        var rotulo = card.querySelector('[data-campo="origem"]');
        if (!rotulo) return;
        var origem = card.dataset.origem;
        if (origem && TEXTO_ORIGEM[origem]) rotulo.textContent = TEXTO_ORIGEM[origem];
        else if (card.dataset.origemEnviada && TEXTO_ORIGEM_ENVIADA[card.dataset.origemEnviada]) rotulo.textContent = TEXTO_ORIGEM_ENVIADA[card.dataset.origemEnviada];
        else rotulo.textContent = '— Não mexer neste campo';
    }

    // Função Objetivo: Deixa o card igual ao que está digitado: marcador
    // "Alterado", botão "Desfazer", contador de caracteres e a ORIGEM do valor.
    // "origem_nova" (opcional) diz de onde veio o valor posto por um botão
    // ("existente", "ia"); sem ele, a origem é deduzida: quem digita sobre uma
    // sugestão da IA a deixa "editada"; o resto é "digitado por você".
    function atualizar_card(card, origem_nova) {
        var alterado = ler_card(card) !== null;
        card.dataset.alterado = alterado ? '1' : '0';
        card.classList.toggle('car-card--alterado', alterado);

        var marca = card.querySelector('[data-campo="marca-alterado"]');
        if (marca) marca.dataset.ativo = alterado ? '1' : '0';
        var desfazer = card.querySelector('[data-acao="limpar-campo"]');
        if (desfazer) desfazer.hidden = !alterado;

        var contador = card.querySelector('[data-campo="caracteres"]');
        if (contador) {
            var limite = Number(contador.dataset.limite);
            var n = Array.from(entrada_do_card(card, 'texto').value.trim()).length;
            contador.textContent = n + '/' + limite;
            contador.classList.toggle('car-caracteres--excedido', n > limite);
        }

        var origem = '';
        if (alterado) {
            if (origem_nova) origem = origem_nova;
            else if (card.dataset.origem === 'ia' || card.dataset.origem === 'ia-editada') origem = 'ia-editada';
            else origem = 'usuario';
        }
        card.dataset.origem = origem;
        desenhar_origem(card);
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

    // Igual a coletar_valores, mas guardando também a origem de cada valor.
    function coletar_digitados(corpo) {
        var digitados = {};
        corpo.querySelectorAll('.car-card').forEach(function (card) {
            var valor = ler_card(card);
            if (valor) digitados[card.dataset.atributo] = { valor: valor, origem: card.dataset.origem || 'usuario' };
        });
        return digitados;
    }

    function coletar_origens(corpo) {
        var origens = {};
        corpo.querySelectorAll('.car-card[data-alterado="1"]').forEach(function (card) {
            origens[card.dataset.atributo] = card.dataset.origem || 'usuario';
        });
        return origens;
    }

    // Função Objetivo: Devolve ao card o que estava digitado (depois de a ficha
    // ser recarregada). Característica que não existe mais na ficha nova perde
    // o valor — não há onde colocá-lo.
    function aplicar_digitados(corpo, digitados) {
        corpo.querySelectorAll('.car-card').forEach(function (card) {
            var item = digitados[card.dataset.atributo];
            if (!item || card.dataset.editavel !== '1') return;
            preencher_card(card, item.valor);
            atualizar_card(card, item.origem);
        });
    }

    function atualizar_barra_envio(produto) {
        var corpo = produto.querySelector('.car-produto-corpo');
        var n = corpo.querySelectorAll('.car-card[data-alterado="1"]').length;

        corpo.querySelectorAll('[data-campo="contagem-texto"]').forEach(function (area) {
            area.textContent = n
                ? n + (n === 1 ? ' campo preparado' : ' campos preparados') + ' · nada foi enviado ainda'
                : 'Nenhum campo preparado';
        });
        corpo.querySelectorAll('[data-campo="contagem-nota"]').forEach(function (area) {
            area.textContent = n
                ? 'Sair sem enviar descarta o que foi digitado · "Revisar e enviar" mostra como fica antes de enviar'
                : 'Campo vazio = não mexe no Mercado Livre';
        });
        corpo.querySelectorAll('[data-campo="texto-revisar"]').forEach(function (area) {
            area.textContent = n ? 'Revisar e enviar (' + n + ')' : 'Revisar e enviar';
        });
        corpo.querySelectorAll('[data-acao="revisar-envio"], [data-acao="descartar-alteracoes"]').forEach(function (botao) {
            botao.disabled = n === 0 || envio_em_andamento;
        });
        corpo.querySelectorAll('[data-campo="n-preparados"]').forEach(function (area) {
            area.textContent = n;
        });

        var marcador = produto.querySelector('[data-campo="alterados-linha"]');
        marcador.hidden = n === 0;
        marcador.textContent = n
            ? '✎ ' + n + (n === 1 ? ' campo preparado, não enviado' : ' campos preparados, não enviados')
            : '';
        produto.classList.toggle('car-produto--com-alteracoes', n > 0);
    }

    // Função Objetivo: Põe a mensagem de erro de cada campo no card dele. Se o
    // card está escondido pelo filtro, volta o filtro para "Todos" (senão a
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
            var todos = corpo.querySelector('[data-acao="filtrar-cards"][data-filtro="todos"]');
            if (todos) filtrar_cards(todos);
        }
        return primeiro;
    }

    function limpar_erros_dos_campos(corpo) {
        corpo.querySelectorAll('.car-card--com-erro').forEach(limpar_erro_do_card);
    }

    function ao_alterar_campo(evento) {
        var alvo = evento.target;
        if (!alvo.matches) return;
        if (alvo.matches('[data-acao-mudar="campo-tabela"]')) {
            mostrar_coluna_da_tabela(alvo);
            return;
        }
        if (!alvo.matches('.car-entrada')) return;
        var card = alvo.closest('.car-card');
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
        var pergunta = 'Descartar ' + cards.length + (cards.length === 1 ? ' campo preparado' : ' campos preparados') +
            ' deste produto? O que foi digitado será perdido.';
        if (!window.confirm(pergunta)) return;
        cards.forEach(function (card) {
            limpar_card(card);
            atualizar_card(card);
        });
        atualizar_barra_envio(produto);
    }

    // "Aceitar" da sugestão da IA — RESERVADO: a IA ainda não está conectada e o
    // botão fica escondido. Quando houver sugestão, o back-end deixa o valor em
    // card.dataset.sugestaoIa (JSON no mesmo formato de ler_card) e este botão
    // o coloca no campo, marcando a origem como "ia" (e não "digitado por você").
    function aceitar_ia(botao) {
        var card = botao.closest('.car-card');
        if (!card || !card.dataset.sugestaoIa) return;
        var valor = null;
        try { valor = JSON.parse(card.dataset.sugestaoIa); } catch (erro) { valor = null; }
        if (!valor) return;
        preencher_card(card, valor);
        atualizar_card(card, 'ia');
        atualizar_barra_envio(card.closest('.car-produto'));
    }

    // "Usar este valor" (na gaveta): copia para "Valor a enviar" um valor que já
    // existe nos anúncios. Não chama nada; só preenche o campo e marca a origem.
    function usar_valor(botao) {
        var card = gaveta.card;
        if (!card || card.dataset.editavel !== '1') return;
        var tipo = card.dataset.tipo;
        var texto = botao.dataset.texto || '';
        var valor_id = botao.dataset.valorId || '';
        var valor = null;

        if (tipo === 'lista') {
            var seletor = entrada_do_card(card, 'valor_id');
            var botao_simnao = card.querySelector('.car-btn-simnao[data-valor-id="' + valor_id + '"]');
            var achado = valor_id;
            if (!botao_simnao && seletor) {
                var opcao = valor_id ? seletor.querySelector('option[value="' + valor_id + '"]') : null;
                if (!opcao) {
                    opcao = Array.from(seletor.options).filter(function (o) { return o.textContent === texto; })[0];
                }
                achado = opcao ? opcao.value : '';
            }
            if (achado) valor = { valor_id: achado };
        } else if (tipo === 'numero_unidade') {
            var partes = texto.match(/^\s*([0-9]+(?:[.,][0-9]+)?)\s*(.*)$/);
            if (partes) {
                valor = { numero: partes[1] };
                var unidade = partes[2].trim();
                var campo_unidade = entrada_do_card(card, 'unidade');
                if (unidade && campo_unidade && Array.from(campo_unidade.options).some(function (o) { return o.value === unidade; })) {
                    valor.unidade = unidade;
                }
            }
        } else if (tipo === 'numero') {
            var so_numero = texto.match(/^\s*([0-9]+(?:[.,][0-9]+)?)/);
            if (so_numero) valor = { numero: so_numero[1] };
        } else {
            valor = { texto: texto };
        }

        if (!valor) {
            anunciar('Não consegui copiar este valor para o campo. Digite-o no card.');
            return;
        }
        preencher_card(card, valor);
        atualizar_card(card, 'existente');
        atualizar_barra_envio(card.closest('.car-produto'));
        fechar_gaveta(true);
        anunciar('Valor copiado para ' + (card.dataset.label || 'o campo') + '.');
        var primeiro = card.querySelector('.car-entrada, .car-btn-simnao');
        if (primeiro) primeiro.focus();
    }

    // ================================================
    // GAVETA DE DETALHES DO CAMPO e painel "Entrada e saída da IA"
    // ================================================
    // Tudo aqui é montado com o que a página JÁ tem (o <template> do card e a
    // tabela de anúncios da ficha). Não consulta nada.

    function abrir_gaveta(opcoes) {
        fechar_gaveta(false);
        var raiz = document.getElementById('car-overlay-root');
        var fundo = criar('div', 'car-gaveta-fundo');
        var painel = criar('aside', 'car-gaveta' + (opcoes.larga ? ' car-gaveta--larga' : ''));
        painel.setAttribute('role', 'dialog');
        painel.setAttribute('aria-modal', 'true');
        painel.setAttribute('aria-labelledby', 'car-gaveta-titulo');
        painel.tabIndex = -1;

        var cab = criar('header', 'car-gaveta-cab');
        var texto = criar('div');
        var titulo = criar('h3', '', opcoes.titulo);
        titulo.id = 'car-gaveta-titulo';
        texto.appendChild(titulo);
        var sub = criar('p', 'car-gaveta-sub');
        (opcoes.sub || []).forEach(function (item) { sub.appendChild(item); });
        texto.appendChild(sub);
        var fechar = criar('button', 'car-gaveta-x');
        fechar.type = 'button';
        fechar.dataset.acao = 'fechar-gaveta';
        fechar.setAttribute('aria-label', 'Fechar os detalhes');
        fechar.innerHTML = '<i class="fas fa-xmark" aria-hidden="true"></i>';
        cab.appendChild(texto);
        cab.appendChild(fechar);

        painel.appendChild(cab);
        painel.appendChild(opcoes.corpo);
        fundo.appendChild(painel);
        fundo.addEventListener('click', function (evento) {
            if (evento.target === fundo) fechar_gaveta(true);
        });
        raiz.appendChild(fundo);

        gaveta.fundo = fundo;
        gaveta.anterior = document.activeElement;
        gaveta.card = opcoes.card || null;
        painel.focus();
        anunciar('Aberto: ' + opcoes.titulo);
    }

    function fechar_gaveta(devolver_foco) {
        if (!gaveta.fundo) return;
        gaveta.fundo.remove();
        var anterior = gaveta.anterior;
        gaveta.fundo = null;
        gaveta.anterior = null;
        gaveta.card = null;
        if (devolver_foco && anterior && document.contains(anterior) && anterior.focus) anterior.focus();
    }

    // Esc fecha; Tab fica preso dentro da gaveta enquanto ela está aberta.
    function ao_teclar(evento) {
        if (!gaveta.fundo) return;
        // Um modal do Bootstrap aberto por cima (ex.: cadastro do produto) cuida do próprio Esc.
        if (document.querySelector('.modal.show')) return;
        if (evento.key === 'Escape') {
            evento.preventDefault();
            fechar_gaveta(true);
            return;
        }
        if (evento.key !== 'Tab') return;
        var focaveis = Array.from(gaveta.fundo.querySelectorAll(
            'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex="0"]'
        )).filter(function (no) { return no.offsetParent !== null; });
        var painel = gaveta.fundo.querySelector('.car-gaveta');
        if (!focaveis.length) {
            evento.preventDefault();
            painel.focus();
            return;
        }
        var primeiro = focaveis[0];
        var ultimo = focaveis[focaveis.length - 1];
        var ativo = document.activeElement;
        if (evento.shiftKey && (ativo === primeiro || ativo === painel)) {
            evento.preventDefault();
            ultimo.focus();
        } else if (!evento.shiftKey && ativo === ultimo) {
            evento.preventDefault();
            primeiro.focus();
        }
    }

    function bloco_do_que_foi_preparado(card) {
        var bloco = criar('section', 'car-gaveta-bloco');
        bloco.appendChild(criar('h4', '', 'Valor a enviar'));
        var valor = ler_card(card);
        if (card.dataset.editavel !== '1') {
            bloco.appendChild(criar('p', 'car-gaveta-nota', 'Este campo não é editado aqui — não vai nada para o Mercado Livre.'));
        } else if (valor) {
            var linha = criar('p', 'car-gaveta-nota');
            linha.appendChild(criar('strong', '', descrever_valor(card, valor)));
            linha.appendChild(document.createElement('br'));
            linha.appendChild(document.createTextNode(TEXTO_ORIGEM[card.dataset.origem] || TEXTO_ORIGEM.usuario));
            bloco.appendChild(linha);
        } else {
            bloco.appendChild(criar('p', 'car-gaveta-nota', 'Nada preparado: o campo está vazio e o Mercado Livre não será tocado.'));
        }
        return bloco;
    }

    // "Anúncio por anúncio": lê a coluna deste campo da tabela da ficha (que já
    // está na página, mesmo com a tabela recolhida).
    function bloco_dos_anuncios(card, produto) {
        var atributo = card.dataset.atributo;
        var linhas = produto.querySelectorAll('.car-tabela:not(.car-tabela-categorias) tbody tr');
        var bloco = criar('section', 'car-gaveta-bloco');
        var cab = criar('h4', '', 'Anúncio por anúncio ');
        cab.appendChild(criar('small', '', '· ' + linhas.length));
        bloco.appendChild(cab);
        if (!linhas.length) {
            bloco.appendChild(criar('p', 'car-gaveta-nota', 'Nenhum anúncio na tabela.'));
            return bloco;
        }

        var rolagem = criar('div', 'car-gaveta-rolagem');
        var tabela = criar('table', 'car-mini-tabela');
        var cabecalho = criar('thead');
        var linha_cab = criar('tr');
        ['Anúncio', 'Hoje no ML'].forEach(function (rotulo) { linha_cab.appendChild(criar('th', '', rotulo)); });
        cabecalho.appendChild(linha_cab);
        tabela.appendChild(cabecalho);

        var corpo = criar('tbody');
        linhas.forEach(function (tr) {
            var seletor = 'td[data-atributo="' + (window.CSS && CSS.escape ? CSS.escape(atributo) : atributo) + '"]';
            var celula = tr.querySelector(seletor);
            var linha = criar('tr');

            var td_mlb = criar('td');
            var origem_link = tr.querySelector('.car-col-mlb a');
            var mlb = juntar_espacos(tr.querySelector('.car-col-mlb') ? tr.querySelector('.car-col-mlb').textContent : '');
            if (origem_link) {
                var link = criar('a');
                link.href = origem_link.href;
                link.target = '_blank';
                link.rel = 'noopener';
                link.appendChild(criar('code', '', mlb));
                td_mlb.appendChild(link);
            } else {
                td_mlb.appendChild(criar('code', '', mlb));
            }
            var categoria = tr.querySelector('.car-col-categoria');
            if (categoria) td_mlb.appendChild(criar('small', 'car-mini-categoria', juntar_espacos(categoria.textContent)));
            linha.appendChild(td_mlb);

            var estado = 'valor';
            if (celula) {
                var achado = (celula.className.match(/car-cel--([a-z_]+)/) || [])[1];
                if (achado) estado = achado;
            }
            linha.appendChild(criar('td', 'car-previa-hoje car-previa-hoje--' + estado, celula ? juntar_espacos(celula.textContent) : '—'));
            corpo.appendChild(linha);
        });
        tabela.appendChild(corpo);
        rolagem.appendChild(tabela);
        bloco.appendChild(rolagem);
        return bloco;
    }

    function abrir_detalhe(botao) {
        var card = botao.closest('.car-card');
        var produto = card.closest('.car-produto');
        var modelo = card.querySelector('template[data-modelo="detalhe"]');

        var corpo = criar('div', 'car-gaveta-corpo');
        corpo.appendChild(bloco_do_que_foi_preparado(card));
        if (modelo) corpo.appendChild(modelo.content.cloneNode(true));
        corpo.appendChild(bloco_dos_anuncios(card, produto));

        var nivel = card.querySelector('.car-nivel');
        abrir_gaveta({
            titulo: card.dataset.label || card.dataset.atributo,
            sub: [
                criar('code', '', card.dataset.atributo),
                criar('span', '', nivel ? nivel.textContent : '')
            ],
            corpo: corpo,
            card: card
        });
    }

    // "Entrada e saída": o que foi enviado à IA e o que ela devolveu. A IA ainda
    // não está conectada, então não há nada a mostrar — e a tela diz isso, sem
    // inventar números. Quando houver chamada, o back-end publica o registro em
    // window.carUltimaChamadaIA = {entrada, saida, tokens_entrada, tokens_saida, custo_usd}.
    function orcamento_ia() {
        var barra = document.querySelector('.car-barra-ia');
        return (barra && barra.dataset.orcamento) || '—';
    }

    function abrir_io_ia() {
        var registro = window.carUltimaChamadaIA || null;
        var corpo = criar('div', 'car-gaveta-corpo');

        if (!registro) {
            corpo.appendChild(criar('p', 'car-gaveta-aviso',
                'A IA ainda não está conectada: nenhuma chamada foi feita, então não há o que mostrar. ' +
                'Quando ela for ligada, aqui aparecem o texto exato enviado à IA, o que ela devolveu, o custo e os tokens.'));
        }

        var metricas = criar('section', 'car-gaveta-bloco');
        metricas.appendChild(criar('h4', '', 'Última chamada'));
        var grade = criar('div', 'car-io-metricas');
        [
            ['Custo da última chamada', registro && registro.custo_usd !== undefined ? 'US$ ' + registro.custo_usd : '—'],
            ['Gasto no mês (de US$ ' + orcamento_ia() + ')', registro && registro.gasto_mes_usd !== undefined ? 'US$ ' + registro.gasto_mes_usd : '—'],
            ['Tokens da última · entrada', registro && registro.tokens_entrada !== undefined ? formatar_numero(registro.tokens_entrada) : '—'],
            ['Tokens da última · saída', registro && registro.tokens_saida !== undefined ? formatar_numero(registro.tokens_saida) : '—'],
            ['Tokens do mês · entrada', registro && registro.tokens_entrada_mes !== undefined ? formatar_numero(registro.tokens_entrada_mes) : '—'],
            ['Tokens do mês · saída', registro && registro.tokens_saida_mes !== undefined ? formatar_numero(registro.tokens_saida_mes) : '—']
        ].forEach(function (par) {
            var item = criar('div', 'car-io-metrica');
            item.appendChild(criar('b', '', par[1]));
            item.appendChild(criar('small', '', par[0]));
            grade.appendChild(item);
        });
        metricas.appendChild(grade);
        corpo.appendChild(metricas);

        [['Enviado à IA (entrada)', registro && registro.entrada], ['Devolvido pela IA (saída)', registro && registro.saida]].forEach(function (par) {
            var bloco = criar('section', 'car-gaveta-bloco');
            bloco.appendChild(criar('h4', '', par[0]));
            var tem = par[1] !== null && par[1] !== undefined && par[1] !== false;
            var pre = criar('pre', 'car-io-json' + (tem ? '' : ' car-io-json--vazio'),
                tem ? (typeof par[1] === 'string' ? par[1] : JSON.stringify(par[1], null, 2)) : 'Nenhuma chamada à IA foi feita ainda.');
            bloco.appendChild(pre);
            corpo.appendChild(bloco);
        });

        abrir_gaveta({
            titulo: 'Entrada e saída da IA',
            sub: [criar('span', '', registro ? 'Registro da última chamada' : 'IA ainda não conectada')],
            corpo: corpo,
            larga: true
        });
    }

    // ================================================
    // JANELA DO ENVIO: prévia ("Revisar e enviar") e resultado ("Confirmar envio")
    // ================================================

    function obter_janela_envio() {
        var elemento = document.getElementById('car-modal-envio');
        return window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(elemento) : null;
    }

    // Preenche a coluna "Origem" da prévia com o que a tela sabe de cada valor.
    function preencher_origens_da_previa(origens) {
        document.querySelectorAll('#car-modal-envio-corpo [data-origem-de]').forEach(function (pilula) {
            var origem = origens && origens[pilula.dataset.origemDe];
            if (!origem || !TEXTO_ORIGEM_CURTO[origem]) return;
            pilula.textContent = TEXTO_ORIGEM_CURTO[origem];
            pilula.classList.toggle('car-pilula--ia', origem === 'ia' || origem === 'ia-editada');
        });
    }

    // modo: 'revisao' (prévia, ainda sem enviar nada) ou 'resultado' (depois do envio).
    function mostrar_janela_envio(modo, html, pode_confirmar) {
        document.getElementById('car-modal-envio-titulo').textContent = modo === 'resultado' ? 'Resultado do envio' : 'Revisar o envio';
        document.getElementById('car-modal-envio-corpo').innerHTML = html;
        if (modo === 'revisao') preencher_origens_da_previa(origens_em_revisao);
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
        var origens = coletar_origens(corpo);

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
            origens_em_revisao = origens;
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
        var enviados = valores_em_revisao;

        envio_em_andamento = true;
        definir_janela_ocupada(true);
        definir_estado_janela('Enviando ao Mercado Livre e lendo de volta… não feche esta janela.', '');
        atualizar_barra_envio(produto);

        chamar_servidor(produto.dataset.urlEnviar, 'POST', { valores: enviados }).then(function (resposta) {
            var dados = resposta.dados || {};
            if (!resposta.ok || !dados.ok) {
                // Nada foi enviado quando o servidor recusa antes (409, 422, 404); só 500 deixa dúvida.
                if (dados.erros_por_campo) card_a_mostrar = marcar_erros_dos_campos(corpo, dados.erros_por_campo);
                definir_estado_janela(dados.mensagem || 'Não consegui enviar.', 'erro');
                confirmar.hidden = resposta.status !== 409;
                return;
            }
            registrar_chamadas('envio', dados.chamadas);
            anotar_envio_na_memoria(produto, enviados, dados.pendentes || []);
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

    // Anota (nesta aba) de onde veio cada valor que FICOU aplicado no ML, para o
    // card continuar dizendo "enviado · sugestão da IA / digitado por você".
    function anotar_envio_na_memoria(produto, enviados, pendentes) {
        var sku = produto.dataset.sku;
        var memoria = memoria_de_envio[sku] || {};
        Object.keys(enviados).forEach(function (atributo) {
            if (pendentes.indexOf(atributo) !== -1) return;
            memoria[atributo] = (origens_em_revisao && origens_em_revisao[atributo]) || 'usuario';
        });
        memoria_de_envio[sku] = memoria;
        gravar_armazenado('car-enviados', memoria_de_envio);
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
        origens_em_revisao = null;
    }

    // ================================================
    // DICAS (o balãozinho que aparece ao passar o mouse)
    // ================================================
    // * [EXPLICAÇÃO] → O balão nativo do navegador (atributo "title") não aceita
    //   estilo: sai preto, com letra branca, diferente em cada navegador. Então,
    //   para todo elemento desta tela que tem "title" (inclusive o que entra
    //   depois, via fetch), o script passa o texto para "data-dica" e mostra UM
    //   balão próprio (classe car-dica), sempre com o mesmo visual. Sem o script,
    //   o "title" continua lá e o balão do navegador funciona como antes.
    //   Elementos com "data-dica-cortado" só mostram o balão quando o texto está
    //   realmente cortado na tela (o balão então mostra o texto inteiro).
    var dica = { no: null, alvo: null, pendente: null, espera: null, x: 0 };

    function dica_no() {
        if (!dica.no) {
            dica.no = criar('div', 'car-dica');
            dica.no.id = 'car-dica';
            dica.no.setAttribute('role', 'tooltip');
            pagina.appendChild(dica.no);
        }
        return dica.no;
    }

    function adotar_titulo(no) {
        var texto = no.getAttribute('title');
        if (texto === null) return;
        no.removeAttribute('title');
        texto = texto.trim();
        if (!texto) return;
        no.setAttribute('data-dica', texto);
        // Sem o "title", um botão só com ícone ficaria sem nome para o leitor de tela.
        if (!no.hasAttribute('aria-label') && !no.hasAttribute('aria-labelledby') && !juntar_espacos(no.textContent)) {
            no.setAttribute('aria-label', texto);
        }
    }

    function adotar_titulos_em(raiz) {
        if (raiz.hasAttribute('title')) adotar_titulo(raiz);
        raiz.querySelectorAll('[title]').forEach(adotar_titulo);
    }

    function alvo_da_dica(no) {
        return no && no.closest ? no.closest('[data-dica]') : null;
    }

    function fechar_dica() {
        window.clearTimeout(dica.espera);
        dica.pendente = null;
        if (dica.no) dica.no.classList.remove('car-dica--visivel');
        if (dica.alvo) {
            dica.alvo.removeAttribute('aria-describedby');
            dica.alvo = null;
        }
    }

    function abrir_dica(alvo) {
        dica.pendente = null;
        if (!alvo.isConnected) return;
        if (alvo.hasAttribute('data-dica-cortado') &&
            !(alvo.scrollWidth > alvo.clientWidth + 1 || alvo.scrollHeight > alvo.clientHeight + 1)) {
            return;
        }
        var texto = alvo.getAttribute('data-dica');
        if (!texto) return;

        var no = dica_no();
        if (dica.alvo && dica.alvo !== alvo) dica.alvo.removeAttribute('aria-describedby');
        no.textContent = texto;
        no.classList.remove('car-dica--abaixo');
        no.style.left = '0px';
        no.style.top = '0px';

        var r = alvo.getBoundingClientRect();
        var largura = no.offsetWidth;
        var altura = no.offsetHeight;
        var margem = 8;
        var folga = 10;
        // Elemento largo (barra, cabeçalho): o balão aponta para onde o mouse está.
        var ancora = r.left + r.width / 2;
        if (r.width > 260 && dica.x) ancora = Math.min(Math.max(dica.x, r.left + 12), r.right - 12);

        var esquerda = Math.max(margem, Math.min(ancora - largura / 2, window.innerWidth - largura - margem));
        var abaixo = r.top - altura - folga < margem;
        var topo = abaixo ? r.bottom + folga : r.top - altura - folga;
        topo = Math.max(margem, Math.min(topo, window.innerHeight - altura - margem));

        no.classList.toggle('car-dica--abaixo', abaixo);
        no.style.left = Math.round(esquerda) + 'px';
        no.style.top = Math.round(topo) + 'px';
        no.style.setProperty('--seta-x', Math.round(Math.min(Math.max(ancora - esquerda, 16), largura - 16)) + 'px');
        no.classList.add('car-dica--visivel');
        alvo.setAttribute('aria-describedby', 'car-dica');
        dica.alvo = alvo;
    }

    // Com um balão já aberto, o próximo aparece na hora; do zero, espera um instante
    // (para não piscar enquanto o mouse só passa por cima).
    function agendar_dica(alvo, imediato) {
        window.clearTimeout(dica.espera);
        dica.pendente = alvo;
        if (imediato) {
            abrir_dica(alvo);
            return;
        }
        dica.espera = window.setTimeout(function () { abrir_dica(alvo); }, 220);
    }

    function iniciar_dicas() {
        adotar_titulos_em(pagina);

        new MutationObserver(function (mutacoes) {
            mutacoes.forEach(function (mutacao) {
                if (mutacao.type === 'attributes') {
                    adotar_titulo(mutacao.target);
                    return;
                }
                mutacao.addedNodes.forEach(function (no) {
                    if (no.nodeType === 1) adotar_titulos_em(no);
                });
            });
        }).observe(pagina, { childList: true, subtree: true, attributes: true, attributeFilter: ['title'] });

        pagina.addEventListener('mouseover', function (evento) {
            dica.x = evento.clientX;
            var alvo = alvo_da_dica(evento.target);
            if (!alvo || alvo === dica.alvo || alvo === dica.pendente) return;
            agendar_dica(alvo, !!dica.alvo);
        });

        pagina.addEventListener('mouseout', function (evento) {
            var alvo = alvo_da_dica(evento.target);
            if (!alvo) return;
            if (evento.relatedTarget && alvo.contains(evento.relatedTarget)) return;
            fechar_dica();
        });

        // Teclado: ao chegar com Tab num elemento com explicação, o balão aparece.
        pagina.addEventListener('focusin', function (evento) {
            var alvo = alvo_da_dica(evento.target);
            if (!alvo) return;
            var pelo_teclado = true;
            try { pelo_teclado = evento.target.matches(':focus-visible'); } catch (erro) { /* navegador antigo */ }
            if (pelo_teclado) agendar_dica(alvo, true);
        });
        pagina.addEventListener('focusout', fechar_dica);

        document.addEventListener('scroll', fechar_dica, true);
        document.addEventListener('pointerdown', fechar_dica, true);
        document.addEventListener('keydown', function (evento) {
            if (evento.key === 'Escape') fechar_dica();
        }, true);
        window.addEventListener('blur', fechar_dica);
        window.addEventListener('resize', fechar_dica);
    }

    // ================================================
    // EVENTOS (delegação: valem também para o que entra depois, via fetch)
    // ================================================

    var ACOES = {
        'alternar-produto': alternar_produto,
        'atualizar-produto': atualizar_produto,
        'alternar-tabela': alternar_tabela,
        'filtrar-tabela': filtrar_tabela,
        'filtrar-cards': filtrar_cards,
        'alternar-grupo': alternar_grupo,
        'abrir-detalhe': abrir_detalhe,
        'usar-valor': usar_valor,
        'aceitar-ia': aceitar_ia,
        'escolher-simnao': escolher_simnao,
        'limpar-campo': limpar_campo,
        'descartar-alteracoes': descartar_alteracoes,
        'revisar-envio': revisar_envio,
        'abrir-io-ia': abrir_io_ia,
        'fechar-gaveta': function () { fechar_gaveta(true); }
    };

    function e_controle(no) {
        return !!no.closest('button, a, input, select, textarea, summary, label, details, [data-acao]');
    }

    pagina.addEventListener('click', function (evento) {
        var alvo = evento.target.closest('[data-acao]');
        if (alvo && pagina.contains(alvo)) {
            var funcao = ACOES[alvo.dataset.acao];
            if (funcao && !alvo.disabled) funcao(alvo);
            return;
        }
        // Clicar no espaço vazio da linha do produto também abre/fecha a ficha.
        var linha = evento.target.closest('.car-produto-linha');
        if (linha && pagina.contains(linha) && !e_controle(evento.target)) {
            var toggle = linha.querySelector('[data-acao="alternar-produto"]');
            if (toggle) alternar_produto(toggle);
        }
    });

    pagina.addEventListener('input', ao_alterar_campo);
    pagina.addEventListener('change', ao_alterar_campo);
    document.addEventListener('keydown', ao_teclar);

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

    iniciar_dicas();
    desenhar_sessao();

    // Ao abrir a página: só PERGUNTA ao servidor se há varredura em andamento
    // (lê o cache do servidor; não chama o Mercado Livre).
    consultar_status();
})();
