// * [RESUMO] → Script da tela "Full — ficha do código" do ML.
//              REGRA: este script NUNCA chama a API do Mercado Livre por
//              conta própria. Abrir uma ficha, trocar de código, filtrar as
//              linhas, editar nome interno, situação ou observação só falam
//              com o nosso servidor (que lê/grava no banco). O ÚNICO gatilho
//              que faz o servidor consultar o ML é o botão
//              "Consultar no Mercado Livre".

(function () {
    var pagina = document.querySelector('.ful-pagina');
    if (!pagina) return;

    // ================================================
    // UTILITÁRIOS
    // ================================================

    function obter_csrf() {
        var campo = document.querySelector('#ful-csrf input[name="csrfmiddlewaretoken"]');
        return campo ? campo.value : '';
    }

    // Função Objetivo: POST que devolve {ok, status, dados}. Nunca lança para HTTP de
    // erro (409, 502...): a tela precisa ler a mensagem do servidor. O corpo vai como JSON.
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

    // ================================================
    // MENSAGEM DO TOPO
    // ================================================

    var caixa_resultado = document.getElementById('ful-resultado');
    var texto_resultado = document.getElementById('ful-resultado-texto');

    // tipo: 'ok' | 'erro' | '' (informação)
    function mostrar_resultado(texto, tipo) {
        if (!caixa_resultado || !texto_resultado) return;
        texto_resultado.textContent = texto;
        caixa_resultado.classList.remove('ful-resultado--ok', 'ful-resultado--erro');
        if (tipo) caixa_resultado.classList.add('ful-resultado--' + tipo);
        caixa_resultado.hidden = false;
    }

    // ================================================
    // CONSULTAR NO MERCADO LIVRE (o único botão que chama o ML)
    // ================================================

    var botao_consultar = document.getElementById('ful-btn-consultar');
    var campo_codigo = document.getElementById('ful-codigo');

    if (botao_consultar && campo_codigo) {
        botao_consultar.addEventListener('click', function () {
            var codigo = campo_codigo.value.trim();
            if (!codigo) {
                mostrar_resultado('Digite o código antes de consultar.', 'erro');
                campo_codigo.focus();
                return;
            }

            botao_consultar.disabled = true;
            botao_consultar.classList.add('ful-btn--lendo');
            mostrar_resultado('Consultando o Mercado Livre…', '');

            chamar_servidor(pagina.dataset.urlConsultar, { codigo: codigo }).then(function (resposta) {
                if (resposta.ok && resposta.dados.ok) {
                    mostrar_resultado(resposta.dados.mensagem + ' Abrindo a ficha…', 'ok');
                    window.location.href = resposta.dados.url;
                    return;
                }
                mostrar_resultado(resposta.dados.mensagem || 'Não consegui consultar o Mercado Livre. Tente de novo.', 'erro');
                botao_consultar.disabled = false;
                botao_consultar.classList.remove('ful-btn--lendo');
            }).catch(function () {
                mostrar_resultado('Não consegui falar com o servidor. Confira a conexão e tente de novo.', 'erro');
                botao_consultar.disabled = false;
                botao_consultar.classList.remove('ful-btn--lendo');
            });
        });
    }

    // ================================================
    // REGISTRO DE CAMPOS (nome interno, situação, observação) — grava só no banco
    // ================================================

    function ajustar_altura(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
    }

    function chave_da_linha(linha) {
        return linha.dataset.fonte + '|' + linha.dataset.caminho;
    }

    function ler_linha(linha) {
        return {
            fonte: linha.dataset.fonte,
            caminho: linha.dataset.caminho,
            nome_interno: linha.querySelector('[data-campo="nome_interno"]').value,
            situacao: linha.querySelector('[data-campo="situacao"]').value,
            observacao: linha.querySelector('[data-campo="observacao"]').value
        };
    }

    function pintar_situacao(linha, situacao) {
        linha.dataset.situacao = situacao;
        linha.querySelector('[data-campo="situacao"]').dataset.situacao = situacao;
    }

    // Função Objetivo: O mesmo campo aparece em vários blocos (1 por anúncio, 1 por produto, 1 por ficha):
    // quando um é salvo, os outros recebem os mesmos valores para não ficarem desatualizados. O que a
    // equipe registra descreve o CAMPO, não o anúncio — o VALOR de cada anúncio continua só dele.
    function copiar_para_iguais(linha_origem, dados) {
        var chave = chave_da_linha(linha_origem);
        pagina.querySelectorAll('.ful-linha').forEach(function (linha) {
            if (linha === linha_origem || chave_da_linha(linha) !== chave) return;
            linha.querySelector('[data-campo="nome_interno"]').value = dados.nome_interno;
            linha.querySelector('[data-campo="situacao"]').value = dados.situacao;
            var observacao = linha.querySelector('[data-campo="observacao"]');
            observacao.value = dados.observacao;
            ajustar_altura(observacao);
            pintar_situacao(linha, dados.situacao);
        });
    }

    // * [EXPLICAÇÃO] → O placar do topo conta o catálogo inteiro (vem do servidor), e a mesma informação
    //                  (fonte + caminho) aparece em vários blocos — 1 por anúncio. Por isso o placar não é
    //                  recontado pelas linhas da tela: quando uma situação é salva, move-se 1 unidade da
    //                  situação antiga para a nova, uma vez só por campo. 'situacaoSalva' guarda a última
    //                  situação gravada no banco de cada linha.
    pagina.querySelectorAll('.ful-linha').forEach(function (linha) {
        linha.dataset.situacaoSalva = linha.dataset.situacao;
    });

    function numero_do_placar(situacao) {
        return pagina.querySelector('[data-placar="' + situacao + '"]');
    }

    // Função Objetivo: Atualiza o placar do topo e marca o novo valor como o salvo nas linhas do mesmo campo.
    function atualizar_placar(linha_origem, nova_situacao) {
        var antiga = linha_origem.dataset.situacaoSalva;
        if (antiga !== nova_situacao) {
            var de = numero_do_placar(antiga);
            var para = numero_do_placar(nova_situacao);
            if (de) de.textContent = Math.max(0, (parseInt(de.textContent, 10) || 0) - 1);
            if (para) para.textContent = (parseInt(para.textContent, 10) || 0) + 1;
        }
        var chave = chave_da_linha(linha_origem);
        pagina.querySelectorAll('.ful-linha').forEach(function (linha) {
            if (chave_da_linha(linha) === chave) linha.dataset.situacaoSalva = nova_situacao;
        });
    }

    function salvar_linha(linha) {
        var dados = ler_linha(linha);
        var aviso = linha.querySelector('.ful-salvo');
        aviso.classList.remove('ful-salvo--erro');
        aviso.textContent = 'Salvando…';

        chamar_servidor(pagina.dataset.urlSalvarCampo, dados).then(function (resposta) {
            if (resposta.ok && resposta.dados.ok) {
                aviso.textContent = 'Salvo ' + resposta.dados.atualizado_em;
                copiar_para_iguais(linha, dados);
                atualizar_placar(linha, dados.situacao);
                return;
            }
            aviso.classList.add('ful-salvo--erro');
            aviso.textContent = resposta.dados.mensagem || 'Não salvou. Tente de novo.';
        }).catch(function () {
            aviso.classList.add('ful-salvo--erro');
            aviso.textContent = 'Sem conexão com o servidor. Não salvou.';
        });
    }

    // O "change" dispara ao sair do campo (texto) ou ao escolher (situação).
    pagina.addEventListener('change', function (evento) {
        var campo = evento.target.closest('[data-campo]');
        var linha = evento.target.closest('.ful-linha');
        if (!campo || !linha) return;
        if (campo.dataset.campo === 'situacao') pintar_situacao(linha, campo.value);
        salvar_linha(linha);
    });

    pagina.addEventListener('input', function (evento) {
        if (evento.target.matches('.ful-campo--obs')) ajustar_altura(evento.target);
    });

    pagina.querySelectorAll('.ful-campo--obs').forEach(ajustar_altura);

    // ================================================
    // "COMO VEIO DA API" (só mostra/esconde dado que já está na página)
    // ================================================

    // Função Objetivo: Abre/fecha a 2ª linha da tabela (o dado cru) que vem logo abaixo da linha do
    // botão. abrir = true/false força o estado; sem ele, inverte.
    function alternar_bruto_da_linha(botao, abrir) {
        var linha = botao.closest('.ful-linha');
        var bruto = linha ? linha.nextElementSibling : null;
        if (!bruto || !bruto.classList.contains('ful-linha-bruto')) return;
        if (typeof abrir !== 'boolean') abrir = bruto.hidden;
        bruto.hidden = !abrir;
        botao.setAttribute('aria-expanded', abrir ? 'true' : 'false');
    }

    pagina.addEventListener('click', function (evento) {
        var botao = evento.target.closest('.ful-bruto-botao');
        if (botao) alternar_bruto_da_linha(botao);
    });

    // Função Objetivo: "Abrir todos / Fechar todos" — linhas da tabela, cartões das fontes e tabelas.
    pagina.querySelectorAll('[data-bruto-todos]').forEach(function (botao) {
        botao.addEventListener('click', function () {
            var abrir = botao.dataset.brutoTodos === 'abrir';
            pagina.querySelectorAll('.ful-bruto-botao').forEach(function (b) { alternar_bruto_da_linha(b, abrir); });
            pagina.querySelectorAll('.ful-bruto-detalhes').forEach(function (d) { d.open = abrir; });
        });
    });

    // ================================================
    // ÍNDICE DOS ANÚNCIOS (só leva até um bloco que já está na página)
    // ================================================

    // Função Objetivo: Clicar no MLB do índice abre o bloco do anúncio, mesmo que ele esteja recolhido.
    pagina.addEventListener('click', function (evento) {
        var link = evento.target.closest('a[href^="#ful-anuncio-"]');
        if (!link) return;
        var alvo = document.getElementById(link.getAttribute('href').slice(1));
        if (alvo && alvo.tagName === 'DETAILS') alvo.open = true;
    });

    // ================================================
    // FILTRO POR SITUAÇÃO (só esconde/mostra linhas já na tela)
    // ================================================

    function aplicar_filtro(situacao) {
        pagina.querySelectorAll('.ful-linha').forEach(function (linha) {
            linha.hidden = !!situacao && linha.dataset.situacao !== situacao;
        });
        pagina.querySelectorAll('.ful-bloco[data-bloco]').forEach(function (bloco) {
            bloco.hidden = !bloco.querySelector('.ful-linha:not([hidden])');
        });
        pagina.querySelectorAll('.ful-agrupador').forEach(function (agrupador) {
            agrupador.hidden = !agrupador.querySelector('.ful-linha:not([hidden])');
        });
    }

    pagina.querySelectorAll('.ful-placar-item').forEach(function (botao) {
        botao.addEventListener('click', function () {
            pagina.querySelectorAll('.ful-placar-item').forEach(function (outro) {
                var ativo = outro === botao;
                outro.classList.toggle('ful-placar-item--ativo', ativo);
                outro.setAttribute('aria-pressed', ativo ? 'true' : 'false');
            });
            aplicar_filtro(botao.dataset.filtro);
        });
    });
})();
