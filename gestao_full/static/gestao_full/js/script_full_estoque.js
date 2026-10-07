// gestao_full/static/gestao_full/js/script_full_estoque.js
//
// Tela "Full — Estoque no Full". Faz só quatro coisas, e nenhuma delas chama o servidor sozinha:
//   1) abrir/fechar as linhas de Código ML de um produto (a seta da primeira coluna) e "Abrir todos / Fechar todos";
//   2) abrir/fechar a linha dos ANÚNCIOS de um Código ML (o botão "N anúncios");
//   3) copiar o título ou o MLB de um anúncio (o ícone ao lado);
//   4) trocar a ordenação assim que a pessoa escolhe outra no seletor (vai para o endereço que a view já montou).
// Buscar, filtrar e paginar são links e um formulário normais: funcionam sem este arquivo.

(function () {
    'use strict';

    const pagina = document.querySelector('.est-pagina');
    if (!pagina) {
        return;
    }

    // Função Objetivo: Abre ou fecha as linhas de Código ML de UM produto (o <tbody> dele) e acerta o aria-expanded da seta.
    function definirAberto(grupo, aberto) {
        const botao = grupo.querySelector('.est-toggle');
        if (botao) {
            botao.setAttribute('aria-expanded', aberto ? 'true' : 'false');
        }
        grupo.querySelectorAll('.est-linha-codigo').forEach(function (linha) {
            linha.hidden = !aberto;
        });
        // Fechou o produto: os anúncios dos Códigos também se escondem. Ao reabrir, eles voltam fechados.
        if (!aberto) {
            grupo.querySelectorAll('.est-linha-anuncios').forEach(function (linha) {
                linha.hidden = true;
            });
            grupo.querySelectorAll('.est-anuncios-toggle').forEach(function (botao) {
                botao.setAttribute('aria-expanded', 'false');
            });
        }
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
            const linha = document.getElementById(anuncios.getAttribute('aria-controls'));
            if (linha) {
                const abrir = anuncios.getAttribute('aria-expanded') !== 'true';
                anuncios.setAttribute('aria-expanded', abrir ? 'true' : 'false');
                linha.hidden = !abrir;
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
})();
