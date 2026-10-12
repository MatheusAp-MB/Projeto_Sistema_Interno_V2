/*
 * [RESUMO] → Os pequenos extras da LISTA de vendas (a tela "Vendas — Histórico de vendas" quando nenhum produto está aberto). Quase tudo na lista é link ou
 *            formulário normal (filtro, ordem, período, página, busca); sem este arquivo a lista continua aparecendo e filtrando, só não abre as linhas por dentro.
 * * [EXPLICAÇÃO] → 1) Selects (Marca, Ordenar por, Por página): cada opção guarda o ENDEREÇO da tela já pronto; ao escolher uma, o navegador vai para ele.
 *                  2) Seta de cada linha: abre/fecha os anúncios (MLBs) de dentro do SKU ou do Código ML.
 *                  3) "Abrir todos" / "Fechar todos": fazem o mesmo para todas as linhas da página que está na tela.
 *                  4) Foto que não carrega: troca o ícone de imagem quebrada do navegador por um ícone (caixa na linha do produto, imagem no cartão do anúncio).
 *                  5) Botões de copiar do cartão do anúncio (título, MLB e SKU).
 *                  Este arquivo NUNCA chama o Mercado Livre nem o servidor: só mostra e esconde o que a página já trouxe.
 */
(function () {
    'use strict';

    const pagina = document.querySelector('.vnd-pagina');
    if (!pagina || !pagina.querySelector('.vnd-l-caixa')) {
        return;   // a tela do produto (calendário) não tem lista
    }

    // Função Objetivo: Só vai para endereços do próprio site (as opções vêm do Python, mas a conferência é barata).
    function irPara(endereco) {
        if (!endereco) {
            return;
        }
        try {
            const destino = new URL(endereco, window.location.href);
            if (destino.origin === window.location.origin) {
                window.location.href = destino.href;
            }
        } catch (erro) {
            // endereço inválido: não faz nada
        }
    }

    // Função Objetivo: Foto que não carregou (endereço quebrado, servidor fora do ar): tira a <img> e põe o ícone no lugar. No cartão do anúncio vira o mesmo quadrado cinza de
    // "anúncio sem foto" que o Python já desenha quando não há endereço; na linha do produto vira o ícone de caixa.
    function trocarFotoQuebrada(imagem) {
        if (imagem.classList.contains('cartao-anuncio-imagem')) {
            const vazia = document.createElement('div');
            vazia.className = 'cartao-anuncio-imagem cartao-anuncio-imagem--vazia';
            vazia.setAttribute('role', 'img');
            vazia.setAttribute('aria-label', 'Anúncio sem foto');
            const iconeVazio = document.createElement('i');
            iconeVazio.className = 'fas fa-image';
            iconeVazio.setAttribute('aria-hidden', 'true');
            vazia.appendChild(iconeVazio);
            imagem.replaceWith(vazia);
            return;
        }
        if (!imagem.closest('.vnd-l-foto')) {
            return;
        }
        const icone = document.createElement('i');
        icone.className = 'fas fa-box';
        icone.setAttribute('aria-hidden', 'true');
        imagem.replaceWith(icone);
    }

    // * [EXPLICAÇÃO] → O evento "error" de imagem não sobe pela página: por isso escuto na fase de captura. As fotos que já falharam antes deste arquivo
    //                  carregar são pegas pela conferência logo abaixo (complete + largura 0).
    pagina.addEventListener('error', function (evento) {
        if (evento.target && evento.target.tagName === 'IMG') {
            trocarFotoQuebrada(evento.target);
        }
    }, true);
    pagina.querySelectorAll('.vnd-l-foto img, .vnd-l-id--anuncio img.cartao-anuncio-imagem').forEach(function (imagem) {
        if (imagem.complete && imagem.naturalWidth === 0) {
            trocarFotoQuebrada(imagem);
        }
    });

    // Função Objetivo: Copia um texto. O jeito moderno (navigator.clipboard) só existe em contexto seguro (https ou localhost); no http puro cai no jeito antigo.
    function copiarTexto(texto) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(texto);
        }
        return new Promise(function (resolve, reject) {
            const anterior = document.activeElement;
            const campo = document.createElement('textarea');
            campo.value = texto;
            campo.style.position = 'fixed';
            campo.style.opacity = '0';
            document.body.appendChild(campo);
            campo.focus();
            campo.select();
            try {
                if (document.execCommand('copy')) {
                    resolve();
                } else {
                    reject(new Error('cópia recusada'));
                }
            } catch (erro) {
                reject(erro);
            } finally {
                document.body.removeChild(campo);
                if (anterior && anterior.focus) {
                    anterior.focus();
                }
            }
        });
    }

    // * [EXPLICAÇÃO] → Um único ouvinte na página atende todos os botões de copiar do cartão do anúncio (título, MLB e SKU; a lista tem centenas). Mesmo jeito da tela
    //                  "Estoque no Full": botão .cartao-anuncio-copiar com o texto em data-copiar; o ícone vira um "certo" verde (.copiado) por 1,2 s.
    pagina.addEventListener('click', function (evento) {
        const botao = evento.target.closest('button.cartao-anuncio-copiar[data-copiar]');
        if (!botao || !pagina.contains(botao)) {
            return;
        }
        evento.preventDefault();
        const valor = botao.getAttribute('data-copiar');
        if (!valor) {
            return;
        }
        copiarTexto(valor).then(function () {
            const icone = botao.querySelector('i');
            botao.classList.add('copiado');
            if (icone) {
                icone.className = 'fas fa-check';
            }
            window.setTimeout(function () {
                botao.classList.remove('copiado');
                if (icone) {
                    icone.className = 'fas fa-copy';
                }
            }, 1200);
        }).catch(function () {
            botao.title = 'Não foi possível copiar: selecione o texto e use Ctrl+C';
        });
    });

    pagina.querySelectorAll('select[data-vnd-l-ir]').forEach(function (campo) {
        campo.addEventListener('change', function () {
            irPara(campo.value);
        });
    });

    // Função Objetivo: Abre ou fecha os anúncios de dentro de uma linha e deixa o leitor de tela saber (aria-expanded).
    function definirAberto(bloco, aberto) {
        const filhos = bloco.querySelector('.vnd-l-filhos');
        const botao = bloco.querySelector('[data-vnd-l-alternar]');
        if (!filhos || !botao) {
            return;
        }
        filhos.hidden = !aberto;
        botao.setAttribute('aria-expanded', aberto ? 'true' : 'false');
        bloco.classList.toggle('vnd-l-bloco--aberto', aberto);
    }

    pagina.addEventListener('click', function (evento) {
        const botao = evento.target.closest('[data-vnd-l-alternar]');
        if (!botao) {
            return;
        }
        const bloco = botao.closest('[data-vnd-l-bloco]');
        if (bloco) {
            definirAberto(bloco, botao.getAttribute('aria-expanded') !== 'true');
        }
    });

    function todos(aberto) {
        pagina.querySelectorAll('[data-vnd-l-bloco]').forEach(function (bloco) {
            definirAberto(bloco, aberto);
        });
    }

    const abrirTodos = pagina.querySelector('[data-vnd-l-abrir-todos]');
    const fecharTodos = pagina.querySelector('[data-vnd-l-fechar-todos]');
    if (abrirTodos) {
        abrirTodos.addEventListener('click', function () {
            todos(true);
        });
    }
    if (fecharTodos) {
        fecharTodos.addEventListener('click', function () {
            todos(false);
        });
    }
})();
