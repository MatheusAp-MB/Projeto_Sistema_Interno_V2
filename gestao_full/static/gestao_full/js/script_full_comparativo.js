// gestao_full/static/gestao_full/js/script_full_comparativo.js
//
// Tela "Full — Comparativo de estoque (debug)". Duas partes:
//
// PARTE 1 — só tela (não chama o servidor da Sysemp nem o Mercado Livre):
//   1) abrir/fechar a parte de baixo de cada SKU (a seta da linha) e "Abrir todos / Fechar todos";
//   2) trocar a quantidade por página assim que a pessoa escolhe (vai para o endereço que a view já montou);
//   3) a foto do produto que não carrega (URL fora do ar, ou "http" bloqueada pelo navegador) vira um ícone que ainda abre o endereço;
//   4) as MEDIDAS da tabela que rola sozinha: a altura real das linhas do cabeçalho (para a 2ª e a 3ª "grudarem" certo logo abaixo da 1ª) e a largura da caixa
//      (para a parte que abre embaixo de cada SKU ficar à vista quando a tabela rola para o lado), e a REPARTIÇÃO da largura que sobra quando a caixa é mais larga que a tabela;
//   5) ao chegar pela âncora #cmp-rolagem (depois de ordenar, paginar ou trocar o "Mostrar"), o anel de foco da caixa fica escondido até a pessoa usar o teclado.
// Buscar, filtrar, paginar e ORDENAR (clicar no título da coluna) são links e um formulário normais: funcionam sem este arquivo.
//
// PARTE 2 — o botão "Coletar do Sysemp" (REGRA DO MATHEUS: a tela nunca chama a API sozinha; este é o ÚNICO caminho até a Sysemp e começa num CLIQUE):
//   3) o clique pede ao servidor para coletar em segundo plano; a tela só pergunta o andamento a cada 2 s, mostra a barra, deixa Parar e, no fim,
//      mostra o resumo com o botão "Recarregar a lista" (a lista de baixo não se mexe sozinha: a pessoa pode estar lendo).
//      Ao abrir, a tela pergunta UMA vez se já existe uma coleta rodando (ou um resultado que ninguém viu): isso só lê o cache do servidor.

(function () {
    'use strict';

    const pagina = document.querySelector('.cmp-pagina');
    if (!pagina) {
        return;
    }

    function porId(id) {
        return document.getElementById(id);
    }

    // ---------- PARTE 1: linhas e seletores ----------

    // Função Objetivo: Abre ou fecha a parte de baixo de UM SKU (a linha escondida logo depois da linha principal) e acerta o aria-expanded da seta.
    function definirAberto(botao, aberto) {
        const detalhe = porId(botao.getAttribute('aria-controls'));
        if (!detalhe) {
            return;
        }
        botao.setAttribute('aria-expanded', aberto ? 'true' : 'false');
        detalhe.hidden = !aberto;
    }

    pagina.addEventListener('click', function (evento) {
        const botao = evento.target.closest('.cmp-toggle');
        if (botao) {
            definirAberto(botao, botao.getAttribute('aria-expanded') !== 'true');
            return;
        }
        const acao = evento.target.closest('[data-acao]');
        if (!acao) {
            return;
        }
        const abrir = acao.getAttribute('data-acao') === 'abrir-todos';
        if (abrir || acao.getAttribute('data-acao') === 'fechar-todos') {
            pagina.querySelectorAll('.cmp-toggle').forEach(function (seta) {
                definirAberto(seta, abrir);
            });
        }
    });

    // Função Objetivo: Mede a tabela que rola sozinha e passa as medidas ao CSS (variáveis na própria tabela): onde a 2ª e a 3ª linha do cabeçalho grudam (a soma das alturas
    // das linhas de cima, que pode mudar com a fonte do navegador ou com um texto que quebra) e a largura visível da caixa (para a parte que abre não rolar para o lado).
    // Mesma ideia do script do Resumo por Marketplace, que mede a 1ª linha do cabeçalho em vez de chutar um valor fixo.
    const caixaDaTabela = porId('cmp-rolagem');
    const tabela = caixaDaTabela ? caixaDaTabela.querySelector('.cmp-tabela') : null;

    // Função Objetivo: Reparte a largura que SOBRA quando a caixa é mais larga que a tabela (tela grande, ou a Magazine, que tem menos colunas): sem isso a tabela termina no meio
    // da tela e o resto fica em branco. A sobra vai primeiro para o título (45%, no máximo +260 px: é o que mais aparece cortado com "…") e para a marca (10%, no máximo +60 px);
    // o que restar vai para as colunas que rolam, proporcional à largura de cada uma. Seta, foto e SKU não mudam; título e marca mudam pelas variáveis do CSS (o "left" das colunas
    // fixas é calculado com elas, então continua exato). Em tela estreita não sobra nada: vale o CSS como está e a tabela rola para o lado.
    function repartirSobraDeLargura() {
        const colunas = Array.from(tabela.querySelectorAll('colgroup .cmp-col'));
        // Volta ao tamanho do CSS antes de medir (senão a repartição anterior entraria na conta).
        tabela.style.removeProperty('--cmp-w-titulo');
        tabela.style.removeProperty('--cmp-w-marca');
        colunas.forEach(function (coluna) {
            coluna.style.width = '';
        });
        const sobra = Math.floor(caixaDaTabela.clientWidth - tabela.offsetWidth);
        const colunaTitulo = tabela.querySelector('.cmp-col--titulo');
        const colunaMarca = tabela.querySelector('.cmp-col--marca');
        const rolam = colunas.filter(function (coluna) {
            return /cmp-col--(num|sozinha|conta|achados)/.test(coluna.className);
        });
        if (sobra < 2 || !colunaTitulo || !colunaMarca || !rolam.length) {
            return;
        }
        // Mede tudo ANTES de mexer em qualquer coluna.
        const larguraTitulo = colunaTitulo.getBoundingClientRect().width;
        const larguraMarca = colunaMarca.getBoundingClientRect().width;
        const largurasQueRolam = rolam.map(function (coluna) {
            return coluna.getBoundingClientRect().width;
        });
        const somaQueRola = largurasQueRolam.reduce(function (soma, largura) {
            return soma + largura;
        }, 0);

        const aoTitulo = Math.floor(Math.min(sobra * 0.45, 260));
        const aMarca = Math.floor(Math.min(sobra * 0.10, 60));
        const resto = sobra - aoTitulo - aMarca;
        tabela.style.setProperty('--cmp-w-titulo', (larguraTitulo + aoTitulo) + 'px');
        tabela.style.setProperty('--cmp-w-marca', (larguraMarca + aMarca) + 'px');
        let repartido = 0;
        rolam.forEach(function (coluna, i) {
            // A última leva o que sobrou do arredondamento: a soma fecha exatamente na largura da caixa.
            const parte = (i === rolam.length - 1) ? resto - repartido : Math.floor(resto * largurasQueRolam[i] / somaQueRola);
            repartido += parte;
            coluna.style.width = (largurasQueRolam[i] + parte) + 'px';
        });
    }

    // A repartição só é refeita quando a LARGURA da caixa muda (a altura do cabeçalho muda junto com ela e é medida logo depois, sempre).
    let larguraNaUltimaReparticao = -1;

    function medirTabela() {
        if (!caixaDaTabela || !tabela) {
            return;
        }
        if (caixaDaTabela.clientWidth !== larguraNaUltimaReparticao) {
            larguraNaUltimaReparticao = caixaDaTabela.clientWidth;
            repartirSobraDeLargura();
        }
        const linhaBlocos = tabela.querySelector('.cmp-blocos');
        const linhaFontes = tabela.querySelector('.cmp-fontes-linha');
        if (linhaBlocos && linhaFontes) {
            const alturaBlocos = linhaBlocos.getBoundingClientRect().height;
            tabela.style.setProperty('--cmp-topo-fontes', alturaBlocos + 'px');
            tabela.style.setProperty('--cmp-topo-colunas', (alturaBlocos + linhaFontes.getBoundingClientRect().height) + 'px');
        }
        tabela.style.setProperty('--cmp-largura-caixa', caixaDaTabela.clientWidth + 'px');
    }

    if (tabela) {
        medirTabela();
        window.addEventListener('load', medirTabela);
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(medirTabela);
        }
        // A caixa muda de largura sem a janela mudar (esconder ou mostrar o menu lateral): quem avisa é o ResizeObserver.
        if (typeof ResizeObserver === 'function') {
            new ResizeObserver(medirTabela).observe(caixaDaTabela);
        } else {
            window.addEventListener('resize', medirTabela);
        }
    }

    // Função Objetivo: Esconde o anel de foco da caixa quando a página chega pela âncora #cmp-rolagem: o navegador dá o foco à caixa sozinho e o anel azul apareceria sem
    // ninguém ter usado o teclado. O anel volta na primeira tecla apertada ou quando o foco sai da caixa (quem navega com Tab continua vendo onde está).
    if (caixaDaTabela && window.location.hash === '#cmp-rolagem') {
        caixaDaTabela.classList.add('cmp-rolagem--sem-anel');
        const mostrarAnel = function () {
            caixaDaTabela.classList.remove('cmp-rolagem--sem-anel');
        };
        document.addEventListener('keydown', mostrarAnel, { once: true });
        caixaDaTabela.addEventListener('blur', mostrarAnel, { once: true });
    }

    pagina.querySelectorAll('select[data-navegar]').forEach(function (seletor) {
        seletor.addEventListener('change', function () {
            // O #cmp-rolagem leva a pessoa de volta à tabela (a página recarrega no topo).
            window.location.href = seletor.value + '#cmp-rolagem';
        });
    });

    // Função Objetivo: Troca uma foto que não carregou por um ícone (o link em volta continua abrindo o endereço da foto em outra aba).
    function trocarFotoQuebrada(imagem) {
        if (!imagem.classList.contains('cmp-foto') || imagem.dataset.falhou) {
            return;
        }
        imagem.dataset.falhou = '1';
        const aviso = document.createElement('span');
        aviso.className = 'cmp-foto-falha';
        aviso.title = 'A foto não carregou (o endereço pode estar fora do ar ou ser "http", que o navegador pode bloquear). Clique para abrir o endereço.';
        const icone = document.createElement('i');
        icone.className = 'fas fa-image';
        icone.setAttribute('aria-hidden', 'true');
        aviso.appendChild(icone);
        imagem.replaceWith(aviso);
    }

    // O evento "error" de imagem não sobe pela página: por isso o ouvido é na fase de captura.
    pagina.addEventListener('error', function (evento) {
        if (evento.target && evento.target.tagName === 'IMG') {
            trocarFotoQuebrada(evento.target);
        }
    }, true);

    // Foto que já falhou antes deste arquivo carregar (o evento já passou): confere as que terminaram de carregar sem imagem.
    pagina.querySelectorAll('img.cmp-foto').forEach(function (imagem) {
        if (imagem.complete && imagem.naturalWidth === 0) {
            trocarFotoQuebrada(imagem);
        }
    });

    // ---------- PARTE 2: a coleta da Sysemp ----------

    const INTERVALO_STATUS_MS = 2000;
    const urlColetar = pagina.getAttribute('data-url-coletar');
    const urlStatus = pagina.getAttribute('data-url-status');
    const urlParar = pagina.getAttribute('data-url-parar');
    const botaoColetar = porId('cmp-coletar');
    const botaoParar = porId('cmp-parar');
    let temporizador = null;

    function csrf() {
        const campo = document.querySelector('#cmp-csrf input[name="csrfmiddlewaretoken"]');
        return campo ? campo.value : '';
    }

    // Função Objetivo: Chama o servidor e devolve {ok, status, dados}. dados é {} se a resposta não for JSON (ex.: página de erro do servidor).
    function chamar(url, metodo) {
        const opcoes = { method: metodo, credentials: 'same-origin', headers: { 'Accept': 'application/json' } };
        if (metodo !== 'GET') {
            opcoes.headers['X-CSRFToken'] = csrf();
        }
        return fetch(url, opcoes).then(function (resposta) {
            return resposta.json().catch(function () { return {}; }).then(function (dados) {
                return { ok: resposta.ok, status: resposta.status, dados: dados };
            });
        });
    }

    // Função Objetivo: "75" -> "1 min 15 s"; "42" -> "42 s".
    function textoDoTempo(segundos) {
        const total = Math.max(parseInt(segundos, 10) || 0, 0);
        return total >= 60 ? Math.floor(total / 60) + ' min ' + String(total % 60).padStart(2, '0') + ' s' : total + ' s';
    }

    // Função Objetivo: Mostra o resultado (ou o erro) da coleta na caixa de resultado. "tom" = ok | atencao | erro.
    function mostrarResultado(mensagem, tom) {
        const caixa = porId('cmp-resultado');
        caixa.classList.remove('cmp-resultado--ok', 'cmp-resultado--atencao', 'cmp-resultado--erro');
        caixa.classList.add('cmp-resultado--' + tom);
        porId('cmp-resultado-icone').className = 'fas cmp-resultado-icone ' + (tom === 'ok' ? 'fa-circle-check' : 'fa-triangle-exclamation');
        porId('cmp-resultado-texto').textContent = mensagem;
        caixa.hidden = false;
    }

    function esconderAndamento() {
        porId('cmp-andamento').hidden = true;
        if (botaoColetar) {
            botaoColetar.disabled = false;
        }
    }

    function pararDePerguntar() {
        if (temporizador !== null) {
            window.clearInterval(temporizador);
            temporizador = null;
        }
    }

    // Função Objetivo: Desenha o andamento ("página 3 · 280 linhas · 12 s") e trava o botão Coletar enquanto roda.
    function mostrarAndamento(estado) {
        porId('cmp-andamento').hidden = false;
        porId('cmp-andamento-rotulo').textContent = estado.rotulo || 'Chamando a API Sysemp';
        const partes = [];
        if (estado.paginas) {
            partes.push('página ' + estado.paginas);
            partes.push(estado.linhas + ' linhas');
        }
        partes.push(textoDoTempo(estado.decorrido));
        porId('cmp-andamento-numeros').textContent = partes.join(' · ');
        if (botaoColetar) {
            botaoColetar.disabled = true;
        }
        if (botaoParar) {
            botaoParar.disabled = !!estado.parando;
        }
    }

    // Função Objetivo: Acerta a tela conforme o estado do servidor: rodando = barra; concluído/erro = resumo; ocioso = nada.
    function aplicarEstado(estado) {
        if (estado.status === 'rodando') {
            mostrarAndamento(estado);
            return true;
        }
        esconderAndamento();
        pararDePerguntar();
        if (estado.status === 'concluido') {
            mostrarResultado(estado.mensagem || 'Coleta concluída.', estado.completa ? 'ok' : 'atencao');
        } else if (estado.status === 'erro') {
            mostrarResultado(estado.mensagem || 'A coleta falhou.', 'erro');
        }
        return false;
    }

    function perguntarAndamento() {
        chamar(urlStatus, 'GET').then(function (resposta) {
            if (!resposta.ok) {
                porId('cmp-andamento-numeros').textContent = 'Perdi a conexão com o servidor; tentando de novo… (a coleta continua rodando lá).';
                return;
            }
            aplicarEstado(resposta.dados);
        }).catch(function () {
            // Sem conexão: a coleta continua lá; a tela tenta de novo em vez de dar a coleta por perdida.
            porId('cmp-andamento-numeros').textContent = 'Perdi a conexão com o servidor; tentando de novo… (a coleta continua rodando lá).';
        });
    }

    function comecarAPerguntar() {
        if (temporizador === null) {
            temporizador = window.setInterval(perguntarAndamento, INTERVALO_STATUS_MS);
        }
    }

    if (botaoColetar) {
        botaoColetar.addEventListener('click', function () {
            botaoColetar.disabled = true;
            porId('cmp-resultado').hidden = true;
            chamar(urlColetar, 'POST').then(function (resposta) {
                if (resposta.dados.status === 'rodando') {
                    mostrarAndamento(resposta.dados);
                    comecarAPerguntar();
                    return;
                }
                botaoColetar.disabled = false;
                mostrarResultado(resposta.dados.mensagem || 'Não consegui começar a coleta. Tente de novo.', 'erro');
            }).catch(function () {
                botaoColetar.disabled = false;
                mostrarResultado('Não consegui falar com o servidor para começar a coleta. Tente de novo.', 'erro');
            });
        });
    }

    if (botaoParar) {
        botaoParar.addEventListener('click', function () {
            botaoParar.disabled = true;
            chamar(urlParar, 'POST').then(function (resposta) {
                if (resposta.dados.status === 'rodando') {
                    mostrarAndamento(resposta.dados);
                }
            }).catch(function () {
                botaoParar.disabled = false;
                mostrarResultado('Não consegui falar com o servidor para parar a coleta. Tente de novo.', 'erro');
            });
        });
    }

    porId('cmp-recarregar').addEventListener('click', function () {
        window.location.reload();
    });

    porId('cmp-resultado-fechar').addEventListener('click', function () {
        porId('cmp-resultado').hidden = true;
    });

    // Ao abrir a tela: já existe uma coleta rodando (começada antes, em outra aba, ou antes de recarregar) ou um resultado que ninguém viu?
    // Só pergunta ao servidor (cache): nada é chamado na Sysemp.
    if (urlStatus) {
        chamar(urlStatus, 'GET').then(function (resposta) {
            if (resposta.ok && aplicarEstado(resposta.dados)) {
                comecarAPerguntar();
            }
        }).catch(function () { /* sem conexão ao abrir: a tela continua utilizável; o botão Coletar funciona quando voltar */ });
    }
})();
