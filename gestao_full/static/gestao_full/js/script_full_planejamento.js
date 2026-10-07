// * [RESUMO] → Script da tela final "Full — Planejamento de envios" do ML.
//              REGRA: este script NUNCA chama a API do Mercado Livre por conta própria. Buscar um produto,
//              abrir/fechar blocos e copiar um código só falam com o nosso servidor (que lê o banco e o
//              arquivo detalhes_mlbs.json). Só 2 botões fazem o servidor consultar o ML, e só quando a pessoa clica:
//              "Consultar no Mercado Livre" / "Consultar de novo" (1 Código ML) e "Sincronizar" (o topo do produto:
//              repete a mesma consulta, um por vez, para TODOS os Códigos ML daquele produto).

(function () {
    var pagina = document.querySelector('.plan-pagina');
    if (!pagina) return;

    // ================================================
    // COPIAR UM CÓDIGO (mesmo gesto do Hub de Anúncios)
    // ================================================

    // * [EXPLICAÇÃO] → navigator.clipboard só existe em contexto seguro (HTTPS ou localhost). Acessando
    //                  pelo IP da rede local por HTTP puro, essa API nem existe — o método antigo
    //                  (execCommand) é o plano B, que funciona em qualquer contexto.
    function copiar_texto(texto) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(texto);
        }
        return new Promise(function (resolve, reject) {
            var campo = document.createElement('textarea');
            campo.value = texto;
            campo.classList.add('plan-copia-oculta');
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
        var icone = evento.target.closest('.icone-copiar');
        if (!icone) return;

        evento.preventDefault();
        var valor = icone.getAttribute('data-copiar');
        if (!valor) return;

        copiar_texto(valor).then(function () {
            icone.classList.remove('fa-copy');
            icone.classList.add('fa-check', 'copiado');
            setTimeout(function () {
                icone.classList.remove('fa-check', 'copiado');
                icone.classList.add('fa-copy');
            }, 1200);
        });
    });

    // ================================================
    // RECOLHER / EXPANDIR UM CÓDIGO ML (clicar no topo do cartão)
    // ================================================

    // Função Objetivo: Recolhe ou expande o corpo de 1 cartão de Código ML. "forcar" = true expande, false recolhe;
    // sem argumento, inverte o estado atual. Quem lê a tela com leitor de tela é avisado pelo aria-expanded.
    function alternar_cartao(cartao, forcar) {
        var corpo = cartao.querySelector('.plan-codigo-corpo');
        var seta = cartao.querySelector('.plan-codigo-alternar');
        if (!corpo) return;
        var expandir = (typeof forcar === 'boolean') ? forcar : corpo.hidden;
        corpo.hidden = !expandir;
        cartao.classList.toggle('plan-codigo--recolhido', !expandir);
        if (seta) seta.setAttribute('aria-expanded', expandir ? 'true' : 'false');
    }

    // * [EXPLICAÇÃO] → O topo inteiro é clicável, MENOS o que já tem uma função própria (o botão "Consultar de novo",
    //                  o ícone de copiar o código e links). Clique duplo (selecionar o código para copiar) não pode
    //                  recolher o cartão: o 1º clique recolhe, o 2º é ignorado e o evento dblclick desfaz o 1º.
    function clique_no_topo(evento) {
        var topo = evento.target.closest('.plan-codigo-topo');
        if (!topo || evento.target.closest('a, .icone-copiar, [data-acao]')) return null;
        return topo.closest('.plan-codigo');
    }

    pagina.addEventListener('click', function (evento) {
        var cartao = clique_no_topo(evento);
        if (!cartao || evento.detail > 1) return;
        alternar_cartao(cartao);
    });

    pagina.addEventListener('dblclick', function (evento) {
        var cartao = clique_no_topo(evento);
        if (cartao) alternar_cartao(cartao);
    });

    // Quem chega por um link para um Código ML (a faixa "N Códigos ML deste produto" ou um endereço com #) precisa
    // ver o cartão aberto: se ele estava recolhido, abre.
    function abrir_cartao_do_endereco() {
        var id = decodeURIComponent(window.location.hash.replace('#', ''));
        var cartao = id ? document.getElementById(id) : null;
        if (cartao && cartao.classList.contains('plan-codigo')) alternar_cartao(cartao, true);
    }

    pagina.addEventListener('click', function (evento) {
        var link = evento.target.closest('.plan-codigos-nav-item');
        if (!link) return;
        var cartao = document.getElementById((link.getAttribute('href') || '').replace('#', ''));
        if (cartao) alternar_cartao(cartao, true);
    });
    window.addEventListener('hashchange', abrir_cartao_do_endereco);
    abrir_cartao_do_endereco();

    // ================================================
    // CONSULTAR NO MERCADO LIVRE (os únicos botões que chamam o ML)
    // ================================================

    // true enquanto uma consulta (de 1 Código ML ou de um produto inteiro) está rodando: nenhum outro botão de consulta
    // funciona até ela terminar — assim nunca há duas consultas do mesmo código ao mesmo tempo.
    var ocupado = false;

    function obter_csrf() {
        var campo = document.querySelector('#plan-csrf input[name="csrfmiddlewaretoken"]');
        return campo ? campo.value : '';
    }

    // Função Objetivo: POST que devolve {ok, status, dados}. Nunca lança para HTTP de erro (409, 502...):
    // a tela precisa ler a mensagem do servidor. O corpo vai como JSON.
    function chamar_servidor(url, corpo) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': obter_csrf(),
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(corpo)
        }).then(function (resposta) {
            return resposta.json().catch(function () { return {}; }).then(function (dados) {
                return { ok: resposta.ok, status: resposta.status, dados: dados };
            });
        });
    }

    // Função Objetivo: Liga/desliga TODOS os botões que consultam o ML (os dos cartões e os "Sincronizar" dos produtos).
    function travar_botoes(travar) {
        pagina.querySelectorAll('[data-acao="consultar"], [data-acao="sincronizar"]').forEach(function (botao) {
            botao.disabled = travar;
        });
    }

    // Função Objetivo: Pede ao servidor a consulta de 1 Código ML (o servidor é quem fala com o ML) e devolve SEMPRE
    // uma Promise que dá certo, com {salvou, falhas, interromper, mensagem}:
    //   salvou     = a consulta foi gravada no banco (mesmo que o ML tenha recusado 1 das chamadas: "falhas" diz quantas);
    //   interromper = não adianta tentar o próximo código (o ML recusou o acesso — 502 — ou o servidor não respondeu).
    function consultar_codigo(codigo) {
        return chamar_servidor(pagina.dataset.urlConsultar, { codigo: codigo }).then(function (resposta) {
            if (resposta.ok && resposta.dados.ok) {
                return { salvou: true, falhas: resposta.dados.falhas || 0, interromper: false, mensagem: resposta.dados.mensagem };
            }
            return {
                salvou: false, falhas: 0, interromper: resposta.status === 502,
                mensagem: resposta.dados.mensagem || 'Não consegui consultar o Mercado Livre. Tente de novo.'
            };
        }).catch(function () {
            return {
                salvou: false, falhas: 0, interromper: true,
                mensagem: 'Não consegui falar com o servidor. Confira a conexão e tente de novo.'
            };
        });
    }

    // ---------- 1 Código ML (botão do cartão) ----------

    // tipo: 'ok' | 'erro' | '' (informação)
    function mostrar_resultado(cartao, texto, tipo) {
        var caixa = cartao.querySelector('[data-resultado]');
        if (!caixa) return;
        caixa.textContent = texto;
        caixa.classList.remove('plan-codigo-resultado--ok', 'plan-codigo-resultado--erro');
        if (tipo) caixa.classList.add('plan-codigo-resultado--' + tipo);
        caixa.hidden = false;
    }

    pagina.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-acao="consultar"]');
        if (!botao || botao.disabled || ocupado) return;

        var cartao = botao.closest('.plan-codigo');
        var codigo = botao.getAttribute('data-codigo');
        if (!cartao || !codigo) return;

        ocupado = true;
        travar_botoes(true);
        alternar_cartao(cartao, true);   // o aviso "Consultando..." fica dentro do corpo: ele precisa estar à vista
        mostrar_resultado(cartao, 'Consultando o Mercado Livre para ' + codigo + '...', '');

        consultar_codigo(codigo).then(function (resultado) {
            if (resultado.salvou) {
                mostrar_resultado(cartao, resultado.mensagem + ' Atualizando a tela...', 'ok');
                // A consulta já foi salva no banco: recarrega a MESMA página (mesma busca), que só lê do banco.
                window.location.reload();
                return;
            }
            mostrar_resultado(cartao, resultado.mensagem, 'erro');
            ocupado = false;
            travar_botoes(false);
        });
    });

    // ---------- Todos os Códigos ML de 1 produto (botão "Sincronizar" do topo) ----------

    var ICONES_DA_LINHA = {
        espera: 'far fa-circle',
        andando: 'fas fa-spinner fa-spin',
        ok: 'fas fa-circle-check',
        aviso: 'fas fa-triangle-exclamation',
        erro: 'fas fa-circle-xmark'
    };

    // Função Objetivo: Cria a linha de 1 Código ML na lista de andamento (ícone + código + texto). Só textContent:
    // nada que veio do servidor entra como HTML.
    function criar_linha_do_codigo(codigo) {
        var item = document.createElement('li');
        var icone = document.createElement('i');
        var rotulo = document.createElement('span');
        var texto = document.createElement('span');
        icone.setAttribute('aria-hidden', 'true');
        rotulo.className = 'plan-sync-item-codigo';
        rotulo.textContent = codigo;
        texto.className = 'plan-sync-item-texto';
        item.appendChild(icone);
        item.appendChild(rotulo);
        item.appendChild(texto);
        return item;
    }

    // estado: 'espera' | 'andando' | 'ok' | 'aviso' | 'erro'
    function marcar_linha(item, estado, texto) {
        item.className = 'plan-sync-item plan-sync-item--' + estado;
        item.querySelector('i').className = ICONES_DA_LINHA[estado];
        item.querySelector('.plan-sync-item-texto').textContent = texto;
    }

    // tipo: 'ok' | 'aviso' | 'erro' | '' (andamento)
    function mostrar_andamento(caixa, texto, tipo) {
        caixa.querySelector('[data-sync-resumo]').textContent = texto;
        caixa.classList.remove('plan-sync--ok', 'plan-sync--aviso', 'plan-sync--erro');
        if (tipo) caixa.classList.add('plan-sync--' + tipo);
        caixa.hidden = false;
    }

    function plural(n, singular, plural_) {
        return n + ' ' + (n === 1 ? singular : plural_);
    }

    // Função Objetivo: Consulta, UM DE CADA VEZ e na ordem em que aparecem na tela, todos os Códigos ML do produto.
    // Um código com problema (409 já em consulta, 422, 500, falha parcial) não impede o próximo; só o ML recusar o
    // acesso (502) ou o servidor sumir interrompe tudo, porque nenhuma chamada seguinte funcionaria. No fim:
    //   tudo certo            → recarrega a página (que só lê o banco);
    //   algo gravado + falha  → mostra o resumo e deixa o botão "Atualizar a tela" para quando a pessoa terminar de ler;
    //   nada gravado          → mostra os motivos e libera os botões.
    function sincronizar_produto(botao) {
        var produto = botao.closest('.plan-produto');
        var caixa = produto ? produto.querySelector('[data-sync]') : null;
        var cartoes = produto ? Array.prototype.slice.call(produto.querySelectorAll('.plan-codigo')) : [];
        if (!caixa || !cartoes.length) return;

        var lista = caixa.querySelector('[data-sync-lista]');
        var recarregar = caixa.querySelector('[data-acao="recarregar"]');
        var rotulo_do_botao = botao.querySelector('span');
        var icone_do_botao = botao.querySelector('i');
        var texto_do_botao = rotulo_do_botao.textContent;
        var total = cartoes.length;
        var gravados = 0, com_atencao = 0, interrompido = false;

        ocupado = true;
        travar_botoes(true);
        rotulo_do_botao.textContent = 'Sincronizando...';
        icone_do_botao.classList.add('fa-spin');
        recarregar.hidden = true;
        lista.textContent = '';
        var linhas = cartoes.map(function (cartao) {
            var linha = criar_linha_do_codigo(cartao.getAttribute('data-codigo'));
            marcar_linha(linha, 'espera', 'Esperando a vez.');
            lista.appendChild(linha);
            return linha;
        });
        mostrar_andamento(caixa, 'Sincronizando ' + plural(total, 'Código ML', 'Códigos ML') + ' no Mercado Livre...', '');

        var fila = Promise.resolve();
        cartoes.forEach(function (cartao, i) {
            fila = fila.then(function () {
                if (interrompido) {
                    marcar_linha(linhas[i], 'aviso', 'Não consultado: a sincronização foi interrompida.');
                    return null;
                }
                marcar_linha(linhas[i], 'andando', 'Consultando o Mercado Livre...');
                mostrar_andamento(caixa, 'Sincronizando ' + (i + 1) + ' de ' + total + '...', '');
                return consultar_codigo(cartao.getAttribute('data-codigo')).then(function (resultado) {
                    if (resultado.salvou && !resultado.falhas) {
                        gravados += 1;
                        marcar_linha(linhas[i], 'ok', resultado.mensagem);
                        return;
                    }
                    com_atencao += 1;
                    if (resultado.salvou) {
                        gravados += 1;
                        marcar_linha(linhas[i], 'aviso', resultado.mensagem);
                        return;
                    }
                    marcar_linha(linhas[i], 'erro', resultado.mensagem);
                    if (resultado.interromper) interrompido = true;
                });
            });
        });

        fila.then(function () {
            rotulo_do_botao.textContent = texto_do_botao;
            icone_do_botao.classList.remove('fa-spin');

            if (gravados === total && !com_atencao) {
                mostrar_andamento(caixa, 'Pronto: ' + plural(total, 'Código ML consultado', 'Códigos ML consultados') + '. Atualizando a tela...', 'ok');
                window.location.reload();   // tudo foi gravado: a página recarrega lendo só o banco
                return;
            }

            var fim = interrompido ? ' A sincronização foi interrompida no primeiro erro de acesso.' : '';
            if (gravados) {
                mostrar_andamento(caixa, gravados + ' de ' + total + ' consultados e gravados; '
                    + plural(com_atencao, 'precisa de atenção', 'precisam de atenção') + ' (veja abaixo).' + fim, 'aviso');
                recarregar.hidden = false;
            } else {
                mostrar_andamento(caixa, 'Nenhum Código ML foi consultado. O motivo de cada um está abaixo.' + fim, 'erro');
            }
            ocupado = false;
            travar_botoes(false);
        });
    }

    pagina.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-acao="sincronizar"]');
        if (!botao || botao.disabled || ocupado) return;
        sincronizar_produto(botao);
    });

    pagina.addEventListener('click', function (evento) {
        if (evento.target.closest('[data-acao="recarregar"]')) window.location.reload();
    });
})();
