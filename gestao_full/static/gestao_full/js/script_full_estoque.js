// gestao_full/static/gestao_full/js/script_full_estoque.js
//
// Tela "Full — Estoque no Full". PARTE 1 — só tela (não chama o servidor):
//   1) abrir/fechar a parte de baixo de um produto, com os cartões de Código ML (a seta da linha do produto) e "Abrir todos / Fechar todos";
//   2) abrir/fechar o painel dos ANÚNCIOS de um Código ML (o botão "N anúncios");
//   2b) abrir/fechar os 3 blocos "onde está o estoque" de um Código ML (a setinha ao lado do código, ou um clique no cabeçalho do cartão);
//   3) copiar o título ou o MLB de um anúncio (o ícone ao lado);
//   4) trocar a ordenação assim que a pessoa escolhe outra no seletor (vai para o endereço que a view já montou).
// Buscar, filtrar e paginar são links e um formulário normais: funcionam sem este arquivo.
//
// PARTE 2 — os BOTÕES DE ATUALIZAÇÃO (no fim do arquivo). REGRA DO MATHEUS: a tela nunca consulta o Mercado Livre sozinha; estes são os
// únicos caminhos até ele, e todos começam num CLIQUE:
//   5) "Atualizar" (um Código ML) e "Atualizar produto" (os Códigos dele, um por vez): o servidor consulta o ML e devolve o produto
//      redesenhado; o JS troca o bloco no lugar (a página não recarrega e o produto continua como estava, aberto OU fechado: o botão do
//      produto fica na própria linha, para atualizar sem abrir) e refaz a faixa de totais do topo;
//   6) "Fazer varredura completa": abre a janela de confirmação e, se a pessoa confirmar, o servidor varre todos os Códigos em segundo plano.
//      A tela só pergunta o andamento a cada 2 s, mostra a barra, deixa Parar e, no fim, mostra o resumo. (Ao abrir, ela também pergunta UMA
//      vez se já existe uma varredura rodando: isso só lê o cache do servidor, não toca o Mercado Livre.)

(function () {
    'use strict';

    const pagina = document.querySelector('.est-pagina');
    if (!pagina) {
        return;
    }

    // Função Objetivo: Abre ou fecha a parte de baixo de UM produto (motivos do indisponível + cartões de Código ML), acerta o aria-expanded
    //                  da seta e liga/desliga o destaque azul do produto aberto (classe est-bloco--aberto).
    function definirAberto(grupo, aberto) {
        const botao = grupo.querySelector('.est-toggle');
        if (botao) {
            botao.setAttribute('aria-expanded', aberto ? 'true' : 'false');
        }
        const corpo = grupo.querySelector('.est-corpo');
        if (corpo) {
            corpo.hidden = !aberto;
        }
        grupo.classList.toggle('est-bloco--aberto', aberto);
        // Fechou o produto: os anúncios dos Códigos e os blocos "onde está o estoque" também se escondem. Ao reabrir, eles voltam fechados.
        if (!aberto) {
            grupo.querySelectorAll('.est-anuncios, .est-locais').forEach(function (painel) {
                painel.hidden = true;
            });
            grupo.querySelectorAll('.est-anuncios-toggle, .est-locais-toggle').forEach(function (botao) {
                botao.setAttribute('aria-expanded', 'false');
            });
        }
    }

    // Função Objetivo: Abre ou fecha os 3 blocos "onde está o estoque" de UM cartão de Código ML (o botão é a setinha do cabeçalho do cartão).
    function alternarLocais(botao) {
        const painel = document.getElementById(botao.getAttribute('aria-controls'));
        if (!painel) {
            return;
        }
        const abrir = botao.getAttribute('aria-expanded') !== 'true';
        botao.setAttribute('aria-expanded', abrir ? 'true' : 'false');
        painel.hidden = !abrir;
    }

    // * [EXPLICAÇÃO] → navigator.clipboard só existe em contexto seguro (HTTPS ou localhost). Acessando pelo IP da rede local por
    //                  HTTP puro, essa API nem existe — o método antigo (execCommand) é o plano B, que funciona em qualquer contexto.
    function copiarTexto(texto) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(texto);
        }
        return new Promise(function (resolve, reject) {
            const campo = document.createElement('textarea');
            campo.value = texto;
            campo.classList.add('est-copia-oculta');
            document.body.appendChild(campo);
            campo.focus();
            campo.select();
            try {
                document.execCommand('copy');
                resolve();
            } catch (erro) {
                reject(erro);
            } finally {
                document.body.removeChild(campo);
            }
        });
    }

    pagina.addEventListener('click', function (evento) {
        const atualizar = evento.target.closest('[data-est-atualizar]');
        if (atualizar && pagina.contains(atualizar)) {
            cliqueAtualizar(atualizar);
            return;
        }

        const copiar = evento.target.closest('.cartao-anuncio-copiar');
        if (copiar && pagina.contains(copiar)) {
            const valor = copiar.getAttribute('data-copiar');
            if (valor) {
                copiarTexto(valor).then(function () {
                    const icone = copiar.querySelector('i');
                    copiar.classList.add('copiado');
                    if (icone) {
                        icone.classList.replace('fa-copy', 'fa-check');
                    }
                    setTimeout(function () {
                        copiar.classList.remove('copiado');
                        if (icone) {
                            icone.classList.replace('fa-check', 'fa-copy');
                        }
                    }, 1200);
                }).catch(function () { /* sem permissão para copiar: nada a fazer */ });
            }
            return;
        }

        const anuncios = evento.target.closest('.est-anuncios-toggle');
        if (anuncios && pagina.contains(anuncios)) {
            const painel = document.getElementById(anuncios.getAttribute('aria-controls'));
            if (painel) {
                const abrir = anuncios.getAttribute('aria-expanded') !== 'true';
                anuncios.setAttribute('aria-expanded', abrir ? 'true' : 'false');
                painel.hidden = !abrir;
            }
            return;
        }

        const locais = evento.target.closest('.est-locais-toggle');
        if (locais && pagina.contains(locais)) {
            alternarLocais(locais);
            return;
        }

        // Clicar numa parte "vazia" do cabeçalho do cartão também abre/fecha (botões, links, o próprio código ML — que a pessoa costuma selecionar
        // para copiar — e texto que ela está selecionando não contam).
        const cabecalho = evento.target.closest('.est-codigo-topo--abre');
        if (cabecalho && pagina.contains(cabecalho)) {
            const selecionado = window.getSelection ? String(window.getSelection()) : '';
            if (!evento.target.closest('button, a, input, select, textarea, code') && selecionado === '') {
                const botaoLocais = cabecalho.querySelector('.est-locais-toggle');
                if (botaoLocais) {
                    alternarLocais(botaoLocais);
                }
            }
            return;
        }

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

    // =================================================================================================================================
    // PARTE 2 — BOTÕES DE ATUALIZAÇÃO
    // =================================================================================================================================
    const enderecos = {
        atualizar: pagina.dataset.urlAtualizar,
        faixa: pagina.dataset.urlFaixa,
        iniciar: pagina.dataset.urlVarreduraIniciar,
        status: pagina.dataset.urlVarreduraStatus,
        parar: pagina.dataset.urlVarreduraParar
    };
    const INTERVALO_STATUS_MS = 2000;
    const SEGUNDOS_AVISO_OK = 6;
    const SEGUNDOS_AVISO_ATENCAO = 14;

    // Só UMA coisa por vez: "operacao" = um Atualizar (Código ou produto) em andamento; "varrendo" = a varredura completa rodando.
    let operacao = null;
    let varrendo = false;
    let temporizadorStatus = null;
    let temporizadorAviso = null;
    let falhasSeguidasDeStatus = 0;

    function porId(id) {
        return document.getElementById(id);
    }

    function plural(n, singular, pluralTexto) {
        return n === 1 ? singular : pluralTexto;
    }

    function formatarNumero(n) {
        return Number(n || 0).toLocaleString('pt-BR');
    }

    function csrf() {
        const campo = document.querySelector('#est-csrf input[name="csrfmiddlewaretoken"]');
        return campo ? campo.value : '';
    }

    // Função Objetivo: Chama o servidor e devolve {ok, status, dados} (dados = o JSON, ou {} se a resposta não for JSON). Só rejeita se a
    //                  rede falhar (sem conexão, servidor fora do ar).
    function chamar(url, metodo, corpo) {
        const opcoes = { method: metodo, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json' } };
        if (corpo !== undefined) {
            opcoes.headers['Content-Type'] = 'application/json';
            opcoes.body = JSON.stringify(corpo);
        }
        return fetch(url, opcoes).then(function (resposta) {
            return resposta.json().catch(function () { return {}; }).then(function (dados) {
                return { ok: resposta.ok, status: resposta.status, dados: dados };
            });
        });
    }

    // ---------- aviso flutuante ----------
    const ICONES_AVISO = { ok: 'fa-circle-check', aviso: 'fa-triangle-exclamation', erro: 'fa-circle-xmark', info: 'fa-circle-info' };

    // tipo: 'ok' (some sozinho), 'aviso' (some mais devagar), 'erro' (fica até a pessoa fechar), 'info' (some sozinho)
    function avisar(texto, tipo) {
        const caixa = porId('est-aviso');
        if (!caixa) {
            return;
        }
        clearTimeout(temporizadorAviso);
        caixa.className = 'est-aviso est-aviso--' + tipo;
        porId('est-aviso-texto').textContent = texto;
        porId('est-aviso-icone').className = 'fas est-aviso-icone ' + ICONES_AVISO[tipo];
        caixa.hidden = false;
        if (tipo !== 'erro') {
            temporizadorAviso = setTimeout(function () { caixa.hidden = true; }, (tipo === 'aviso' ? SEGUNDOS_AVISO_ATENCAO : SEGUNDOS_AVISO_OK) * 1000);
        }
    }

    function fecharAviso() {
        clearTimeout(temporizadorAviso);
        const caixa = porId('est-aviso');
        if (caixa) {
            caixa.hidden = true;
        }
    }

    // ---------- travas e estado dos botões ----------
    // Função Objetivo: Põe o botão em "trabalhando" (ícone girando e texto novo) ou volta ao normal. O texto de antes fica guardado no próprio botão.
    function pintarBotao(botao, trabalhando, texto) {
        const rotulo = botao.querySelector('.est-btn-texto');
        const icone = botao.querySelector('i');
        if (rotulo && !botao.dataset.rotulo) {
            botao.dataset.rotulo = rotulo.textContent.trim();
        }
        if (rotulo) {
            rotulo.textContent = trabalhando ? texto : botao.dataset.rotulo;
        }
        if (icone) {
            icone.classList.toggle('fa-spin', trabalhando);
        }
        botao.classList.toggle('est-btn--ocupado', trabalhando);
    }

    // Função Objetivo: O botão que está trabalhando agora (se o bloco do produto foi redesenhado, acha o equivalente no bloco novo).
    function botaoDaOperacao() {
        const bloco = operacao ? porId(operacao.blocoId) : null;
        if (!bloco) {
            return null;
        }
        if (operacao.tipo === 'produto') {
            return bloco.querySelector('[data-est-atualizar="produto"]');
        }
        return Array.prototype.find.call(bloco.querySelectorAll('[data-est-atualizar="codigo"]'), function (botao) {
            return botao.dataset.codigo === operacao.codigo;
        }) || null;
    }

    // Função Objetivo: Acerta TODOS os botões de atualizar (e o da varredura) conforme o que está rodando. Roda de novo depois de qualquer
    //                  redesenho, porque os botões do bloco novo nascem sem trava.
    function aplicarTrava() {
        const bloqueado = Boolean(operacao) || varrendo;
        pagina.querySelectorAll('[data-est-atualizar]').forEach(function (botao) {
            botao.disabled = bloqueado;
            pintarBotao(botao, false);
        });
        const varredura = porId('est-btn-varredura');
        if (varredura) {
            varredura.disabled = bloqueado;
        }
        const ativo = botaoDaOperacao();
        if (ativo) {
            pintarBotao(ativo, true, operacao.texto);
        }
    }

    function definirOperacao(nova) {
        operacao = nova;
        aplicarTrava();
    }

    function mudarTextoDaOperacao(texto) {
        operacao.texto = texto;
        aplicarTrava();
    }

    // ---------- redesenho no lugar ----------
    // Função Objetivo: Troca o bloco do produto pelo HTML novo que o servidor mandou. Guarda e devolve o que a pessoa tinha aberto dentro
    //                  (o painel de anúncios e os blocos "onde está o estoque" de cada Código, achados pelo CÓDIGO e não pela posição, porque a
    //                  ordem dos cartões pode mudar quando o número muda). O produto novo volta ao estado em que estava (aberto ou fechado: quem atualizou pela linha fechada não
    //                  quer vê-lo abrir) e pisca uma vez para mostrar onde mexeu.
    function trocarProduto(id, html) {
        const atual = porId(id);
        const molde = document.createElement('template');
        molde.innerHTML = (html || '').trim();
        const novo = molde.content.firstElementChild;
        if (!atual || !novo) {
            return null;
        }
        const comAnunciosAbertos = [];
        const comLocaisAbertos = [];
        atual.querySelectorAll('.est-codigo-cartao').forEach(function (cartao) {
            if (cartao.querySelector('.est-anuncios-toggle[aria-expanded="true"]')) {
                comAnunciosAbertos.push(cartao.querySelector('.est-codigo-valor').textContent.trim());
            }
            if (cartao.querySelector('.est-locais-toggle[aria-expanded="true"]')) {
                comLocaisAbertos.push(cartao.querySelector('.est-codigo-valor').textContent.trim());
            }
        });
        const estavaAberto = atual.classList.contains('est-bloco--aberto');
        atual.replaceWith(novo);
        definirAberto(novo, estavaAberto);
        novo.querySelectorAll('.est-codigo-cartao').forEach(function (cartao) {
            const codigo = cartao.querySelector('.est-codigo-valor').textContent.trim();
            if (comAnunciosAbertos.indexOf(codigo) !== -1) {
                const botao = cartao.querySelector('.est-anuncios-toggle');
                const painel = botao ? porId(botao.getAttribute('aria-controls')) : null;
                if (botao && painel) {
                    botao.setAttribute('aria-expanded', 'true');
                    painel.hidden = false;
                }
            }
            if (comLocaisAbertos.indexOf(codigo) !== -1) {
                const botaoLocais = cartao.querySelector('.est-locais-toggle');
                const painelLocais = botaoLocais ? porId(botaoLocais.getAttribute('aria-controls')) : null;
                if (botaoLocais && painelLocais) {
                    botaoLocais.setAttribute('aria-expanded', 'true');
                    painelLocais.hidden = false;
                }
            }
        });
        novo.classList.add('est-bloco--atualizado');
        novo.addEventListener('animationend', function () { novo.classList.remove('est-bloco--atualizado'); }, { once: true });
        return novo;
    }

    // Função Objetivo: Refaz a faixa de totais do topo com o que o banco tem agora (a mesma lista da tela, pela query string).
    function atualizarFaixa() {
        return chamar(enderecos.faixa + window.location.search, 'GET').then(function (resposta) {
            const molde = document.createElement('template');
            molde.innerHTML = ((resposta.dados && resposta.dados.html) || '').trim();
            const nova = molde.content.firstElementChild;
            const atual = porId('est-resumo');
            if (resposta.ok && nova && atual) {
                atual.replaceWith(nova);
                aplicarTrava();
            }
        }).catch(function () { /* a faixa fica como estava; recarregar a página a refaz */ });
    }

    // ---------- atualizar um Código ML / um produto ----------
    // Função Objetivo: Consulta UM Código no servidor e redesenha o produto. Devolve (sempre, sem rejeitar) {ok, mensagem, falhas, interromper}.
    function consultarCodigo(blocoId, codigo) {
        const bloco = porId(blocoId);
        if (!bloco) {
            return Promise.resolve({ ok: false, mensagem: 'O produto saiu da tela. Recarregue a página.', interromper: true });
        }
        return chamar(enderecos.atualizar, 'POST', { codigo: codigo, sku: bloco.dataset.sku || '', indice: bloco.dataset.indice || '' }).then(function (resposta) {
            const dados = resposta.dados || {};
            if (!resposta.ok || !dados.ok) {
                return { ok: false, mensagem: dados.mensagem || 'Não consegui consultar o Mercado Livre. Tente de novo.', interromper: Boolean(dados.interromper) };
            }
            const novo = dados.html ? trocarProduto(blocoId, dados.html) : null;
            return { ok: true, mensagem: dados.mensagem, falhas: dados.falhas || 0, redesenhou: Boolean(novo) };
        }).catch(function () {
            return { ok: false, mensagem: 'Não consegui falar com o servidor. Confira a conexão e tente de novo.', interromper: true };
        });
    }

    function atualizarUmCodigo(botao) {
        const bloco = botao.closest('.est-grupo');
        const codigo = botao.dataset.codigo;
        definirOperacao({ blocoId: bloco.id, tipo: 'codigo', codigo: codigo, texto: 'Atualizando…' });
        return consultarCodigo(bloco.id, codigo).then(function (resultado) {
            const feito = resultado.ok;
            definirOperacao(null);
            if (!feito) {
                avisar('Código ' + codigo + ': ' + resultado.mensagem, 'erro');
                return;
            }
            avisar(resultado.mensagem + (resultado.redesenhou ? '' : ' Recarregue a página para ver o número novo.'), resultado.falhas ? 'aviso' : 'ok');
            return atualizarFaixa();
        });
    }

    function atualizarUmProduto(botao) {
        const bloco = botao.closest('.est-grupo');
        const blocoId = bloco.id;
        const sku = bloco.dataset.sku || '';
        const quem = sku ? 'SKU ' + sku : 'Produto';
        const codigos = Array.prototype.map.call(bloco.querySelectorAll('.est-codigo-valor'), function (elemento) { return elemento.textContent.trim(); });
        const total = codigos.length;
        const balanco = { consultados: 0, comAviso: 0, falhas: [], parou: '' };
        // O botão fica pequeno, na linha do produto: com vários Códigos mostra só o passo ("2 de 3…"), com um só mostra "Atualizando…".
        const textoDoPasso = function (i) { return total > 1 ? (i + 1) + ' de ' + total + '…' : 'Atualizando…'; };
        definirOperacao({ blocoId: blocoId, tipo: 'produto', codigo: '', texto: textoDoPasso(0) });

        // Um Código por vez, em fila. Só o acesso recusado (ou a rede) interrompe a fila: erro de um Código não impede os outros.
        function proximo(i) {
            if (i >= total) {
                return Promise.resolve();
            }
            mudarTextoDaOperacao(textoDoPasso(i));
            return consultarCodigo(blocoId, codigos[i]).then(function (resultado) {
                if (resultado.ok) {
                    balanco.consultados += 1;
                    if (resultado.falhas) {
                        balanco.comAviso += 1;
                    }
                } else {
                    balanco.falhas.push({ codigo: codigos[i], mensagem: resultado.mensagem });
                    if (resultado.interromper) {
                        balanco.parou = codigos[i];
                        return undefined;
                    }
                }
                return proximo(i + 1);
            });
        }

        return proximo(0).then(function () {
            definirOperacao(null);
            const quantos = balanco.consultados + ' de ' + total + ' ' + plural(total, 'Código ML consultado', 'Códigos ML consultados');
            if (balanco.parou) {
                const ultima = balanco.falhas[balanco.falhas.length - 1];
                avisar(quem + ': parei no Código ' + balanco.parou + ' (' + quantos + '). ' + ultima.mensagem, 'erro');
            } else if (balanco.falhas.length) {
                const lista = balanco.falhas.slice(0, 2).map(function (falha) { return falha.codigo + ' — ' + falha.mensagem; }).join(' | ');
                const resto = balanco.falhas.length > 2 ? ' (e mais ' + (balanco.falhas.length - 2) + ')' : '';
                avisar(quem + ' atualizado em parte: ' + quantos + '. Não consegui: ' + lista + resto, 'aviso');
            } else if (balanco.comAviso) {
                avisar(quem + ' atualizado: ' + quantos + '; em ' + balanco.comAviso + ' o Mercado Livre não devolveu tudo (o erro aparece no próprio Código).', 'aviso');
            } else {
                avisar(quem + ' atualizado: ' + quantos + '.', 'ok');
            }
            if (balanco.consultados) {
                return atualizarFaixa();
            }
            return undefined;
        });
    }

    function cliqueAtualizar(botao) {
        if (botao.disabled || operacao || varrendo) {
            return;
        }
        fecharAviso();
        if (botao.dataset.estAtualizar === 'produto') {
            atualizarUmProduto(botao);
        } else {
            atualizarUmCodigo(botao);
        }
    }

    // ---------- varredura completa ----------
    function esconderVarredura() {
        porId('est-varredura').hidden = true;
    }

    // "faltam cerca de 8 min" — estimado pelo ritmo até agora; só aparece depois de uns Códigos, para não chutar com pouco dado.
    function textoDeFaltam(estado) {
        const feitos = estado.atual || 0;
        const decorrido = estado.decorrido || 0;
        if (feitos < 5 || decorrido < 10 || !estado.total) {
            return '';
        }
        const segundos = (decorrido / feitos) * (estado.total - feitos);
        const minutos = Math.ceil(segundos / 60);
        if (minutos <= 1) {
            return 'falta menos de 1 min';
        }
        if (minutos < 90) {
            return 'faltam cerca de ' + minutos + ' min';
        }
        return 'faltam cerca de ' + Math.floor(minutos / 60) + ' h ' + (minutos % 60) + ' min';
    }

    function mostrarProgresso(estado) {
        const caixa = porId('est-varredura');
        const total = estado.total || 0;
        const feitos = estado.atual || 0;
        porId('est-varredura-rotulo').textContent = estado.rotulo || 'Consultando o Mercado Livre';
        let numeros = total ? formatarNumero(feitos) + ' de ' + formatarNumero(total) + ' ' + plural(total, 'Código ML', 'Códigos ML') : '';
        if (estado.n_falhas) {
            numeros += ' · ' + estado.n_falhas + ' ' + plural(estado.n_falhas, 'falha', 'falhas');
        }
        porId('est-varredura-numeros').textContent = numeros;
        const barra = porId('est-varredura-barra');
        if (total) {
            barra.max = total;
            barra.value = feitos;
        } else {
            barra.removeAttribute('value');
        }
        const partes = [];
        if (estado.codigo) {
            partes.push('Último consultado: ' + estado.codigo);
        }
        const faltam = textoDeFaltam(estado);
        if (faltam) {
            partes.push(faltam);
        }
        porId('est-varredura-dica').textContent = partes.length
            ? partes.join(' · ') + '. Você pode continuar nesta tela; os botões Atualizar ficam bloqueados até terminar.'
            : 'Você pode continuar nesta tela. Enquanto a varredura roda, os botões Atualizar ficam bloqueados.';
        const parar = porId('est-varredura-parar');
        parar.disabled = Boolean(estado.parando);
        caixa.hidden = false;
        porId('est-resultado').hidden = true;
    }

    function mostrarResultado(estado) {
        const caixa = porId('est-resultado');
        let tipo = 'ok';
        if (estado.status === 'erro') {
            tipo = 'erro';
        } else if (estado.com_falhas || estado.interrompida) {
            tipo = 'atencao';
        }
        caixa.className = 'est-resultado est-resultado--' + tipo;
        porId('est-resultado-icone').className = 'fas est-resultado-icone ' + { ok: 'fa-circle-check', atencao: 'fa-triangle-exclamation', erro: 'fa-circle-xmark' }[tipo];
        // A lista de baixo não se mexe sozinha durante/depois da varredura (a pessoa pode estar lendo): diz isso e oferece o botão de recarregar.
        const aviso = estado.status === 'concluido' && estado.consultados ? ' A lista abaixo ainda mostra os números de antes: clique em Recarregar a lista.' : '';
        porId('est-resultado-texto').textContent = (estado.mensagem || '') + aviso;

        const detalhe = porId('est-resultado-falhas');
        const lista = porId('est-resultado-falhas-lista');
        lista.textContent = '';
        const falhas = estado.falhas || [];
        if (falhas.length) {
            porId('est-resultado-falhas-titulo').textContent = 'Ver os ' + plural(estado.n_falhas, 'que falhou', 'que falharam') + ' (' + estado.n_falhas + ')';
            falhas.forEach(function (falha) {
                const item = document.createElement('li');
                const codigo = document.createElement('strong');
                codigo.textContent = falha.codigo;
                item.appendChild(codigo);
                item.appendChild(document.createTextNode(' — ' + falha.mensagem));
                lista.appendChild(item);
            });
            if (estado.n_falhas > falhas.length) {
                const resto = document.createElement('li');
                resto.textContent = '… e mais ' + (estado.n_falhas - falhas.length) + '.';
                lista.appendChild(resto);
            }
            detalhe.hidden = false;
        } else {
            detalhe.hidden = true;
        }
        caixa.hidden = false;
    }

    function agendarStatus() {
        clearTimeout(temporizadorStatus);
        temporizadorStatus = setTimeout(perguntarStatus, INTERVALO_STATUS_MS);
    }

    // Função Objetivo: Pergunta ao servidor como está a varredura e acerta a tela: rodando = barra e travas; terminou/erro = resumo; nada = limpa.
    function perguntarStatus() {
        return chamar(enderecos.status, 'GET').then(function (resposta) {
            falhasSeguidasDeStatus = 0;
            const estado = resposta.dados || {};
            if (estado.status === 'rodando') {
                varrendo = true;
                aplicarTrava();
                mostrarProgresso(estado);
                agendarStatus();
                return;
            }
            const estavaVarrendo = varrendo;
            varrendo = false;
            aplicarTrava();
            esconderVarredura();
            if (estado.status === 'concluido' || estado.status === 'erro') {
                mostrarResultado(estado);
            } else if (estavaVarrendo) {
                avisar('A varredura terminou, mas não consegui ler o resultado. Recarregue a lista.', 'aviso');
            }
        }).catch(function () {
            // Sem conexão com o servidor: a varredura continua lá; a tela tenta de novo (e avisa na barra) em vez de dar a varredura por perdida.
            falhasSeguidasDeStatus += 1;
            if (varrendo) {
                porId('est-varredura-dica').textContent = 'Perdi a conexão com o servidor; tentando de novo… (a varredura continua rodando lá).';
                agendarStatus();
            }
        });
    }

    function fecharJanelaDeConfirmacao() {
        const elemento = porId('est-modal-varredura');
        const janela = elemento && window.bootstrap ? window.bootstrap.Modal.getInstance(elemento) : null;
        if (janela) {
            janela.hide();
        }
    }

    function confirmarVarredura() {
        const botao = porId('est-modal-confirmar');
        botao.disabled = true;
        chamar(enderecos.iniciar, 'POST', {}).then(function (resposta) {
            fecharJanelaDeConfirmacao();
            const estado = resposta.dados || {};
            if (!resposta.ok || estado.status !== 'rodando') {
                avisar(estado.mensagem || 'Não consegui começar a varredura. Tente de novo.', 'erro');
                return;
            }
            varrendo = true;
            aplicarTrava();
            mostrarProgresso(estado);
            agendarStatus();
        }).catch(function () {
            fecharJanelaDeConfirmacao();
            avisar('Não consegui falar com o servidor. Confira a conexão e tente de novo.', 'erro');
        }).then(function () {
            botao.disabled = false;
        });
    }

    function pararVarredura() {
        const botao = porId('est-varredura-parar');
        botao.disabled = true;
        chamar(enderecos.parar, 'POST', {}).then(function (resposta) {
            const estado = resposta.dados || {};
            if (estado.status === 'rodando') {
                mostrarProgresso(estado);
            }
            // Se já tinha terminado (status "ocioso"), a próxima pergunta de status mostra o resultado.
            perguntarStatus();
        }).catch(function () {
            botao.disabled = false;
            avisar('Não consegui falar com o servidor para parar a varredura. Tente de novo.', 'erro');
        });
    }

    // ---------- ligações ----------
    const confirmar = porId('est-modal-confirmar');
    if (confirmar) {
        confirmar.addEventListener('click', confirmarVarredura);
    }
    const parar = porId('est-varredura-parar');
    if (parar) {
        parar.addEventListener('click', pararVarredura);
    }
    const recarregar = porId('est-resultado-recarregar');
    if (recarregar) {
        recarregar.addEventListener('click', function () { window.location.reload(); });
    }
    const fecharResultado = porId('est-resultado-fechar');
    if (fecharResultado) {
        fecharResultado.addEventListener('click', function () { porId('est-resultado').hidden = true; });
    }
    const fecharAvisoBotao = porId('est-aviso-fechar');
    if (fecharAvisoBotao) {
        fecharAvisoBotao.addEventListener('click', fecharAviso);
    }

    // Ao abrir a tela: já existe uma varredura rodando (começada antes, em outra aba, ou antes de recarregar)? Só pergunta ao servidor (cache).
    if (porId('est-varredura')) {
        perguntarStatus();
    }
})();
