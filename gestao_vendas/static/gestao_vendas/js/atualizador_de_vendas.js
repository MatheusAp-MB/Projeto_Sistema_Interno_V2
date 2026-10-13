// gestao_vendas/static/gestao_vendas/js/atualizador_de_vendas.js
//
// O ORQUESTRADOR ÚNICO do "Atualizar" de vendas do Mercado Livre (decisão do Matheus, 13/10/2026: "um botão que para 1 item atualize TUDO que envolve o cálculo dele").
// Mora aqui uma vez só, e quem precisa atualizar vendas USA este arquivo, em vez de ter a sua própria cópia:
//   - a tela "Vendas — Histórico de vendas" (script_vendas.js: "Atualizar" de um MLB e "Atualizar produto");
//   - a tela "Previsão de Ruptura de estoque" (script_ruptura.js: o botão "Atualizar este item", que depois das vendas ainda consulta o estoque).
//
// O que ele faz num clique: 1) pergunta ao servidor o PLANO (só lê o banco: o que falta coletar dos MLBs pedidos; dia já coletado completo é pulado, os últimos 30 dias são sempre relidos);
// 2) lê os trechos do plano em fila curta, vários ao mesmo tempo (CONCORRENCIA); trecho com pedidos demais volta partido do servidor e os pedaços entram na frente da fila; um trecho que falha
// não impede os outros; acesso recusado (ou coleta de período rodando) para tudo; 3) soma o total EXATO de chamadas ao Mercado Livre que o clique gastou; 4) monta o resumo em texto;
// 5) GUARDA o clique no banco (ExecucaoColetaVendasMercadoLivre, via execucao/registrar/: essa view não chama o Mercado Livre).
//
// * [EXPLICAÇÃO] → NADA aqui fala com o Mercado Livre sozinho e nenhum caminho novo foi criado: os endereços (planejar, atualizar/mlb/, execucao/registrar/) são os mesmos que a tela de Vendas já usava,
//                  com as mesmas travas e contadores do servidor. Este arquivo só decide a ORDEM e soma o que o servidor respondeu. Mexer na tela (botão, texto do botão, recarregar) é de quem chama.
// * [EXPLICAÇÃO] → Nunca rejeita: toda falha (rede, servidor, plano) volta como resultado {ok: false, mensagem}.

(function (global) {
    'use strict';

    // * [EXPLICAÇÃO] → Trechos lidos AO MESMO TEMPO. Nunca medi o limite do Mercado Livre para este endpoint (as respostas não trazem cabeçalho
    //                  de limite): se o resumo mostrar recusas (429), baixe este número para 2 ou 1.
    const CONCORRENCIA = 3;
    const ESPERA_FILA_MS = 150;

    function plural(n, singular, pluralTexto) {
        return n === 1 ? singular : pluralTexto;
    }

    function formatarNumero(n) {
        return Number(n || 0).toLocaleString('pt-BR');
    }

    function diasEntre(de, ate) {
        return Math.round((Date.parse(ate + 'T00:00:00Z') - Date.parse(de + 'T00:00:00Z')) / 86400000) + 1;
    }

    function dataCurta(iso) {
        return iso.slice(8, 10) + '/' + iso.slice(5, 7);
    }

    // Função Objetivo: A função que chama o servidor desta página: devolve {ok, status, dados} (dados = o JSON, ou {} se a resposta não for JSON). Só rejeita se a rede falhar.
    //                  `csrf` é uma função que devolve o token do formulário da página.
    function chamador(csrf) {
        return function chamar(url, metodo, corpo) {
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
        };
    }

    // Função Objetivo: O pedaço da mensagem final com o total EXATO de requisições que o clique gastou no Mercado Livre (a soma dos trechos, inclusive
    //                  os que voltaram partidos ou falharam). Se algum trecho não informou o número, diz que a contagem está incompleta.
    function textoDeChamadas(balanco) {
        const total = formatarNumero(balanco.chamadas) + ' ' + plural(balanco.chamadas, 'chamada', 'chamadas') + ' ao Mercado Livre';
        const incompleta = balanco.semContagem
            ? ' (contagem incompleta: ' + balanco.semContagem + ' ' + plural(balanco.semContagem, 'trecho', 'trechos') + ' sem informar)' : '';
        return total + incompleta;
    }

    // Função Objetivo: Monta o resumo do clique: {texto, tipo}. tipo = 'ok' | 'aviso' | 'erro' (a tela escolhe a cor). `rotulo` = o MLB, ou "Produto", ou "Item".
    function resumir(rotulo, plano, balanco) {
        const nTrechos = balanco.trechos + ' ' + plural(balanco.trechos, 'trecho', 'trechos');
        const lidos = plural(balanco.trechos, 'lido', 'lidos');
        const pulados = plano.dias_total - plano.dias_a_coletar;
        const pulou = pulados > 0 && plano.dias_total
            ? ' O que já estava coletado foi pulado (' + Math.round(100 * pulados / plano.dias_total) + '%).' : '';
        const recusas = balanco.erros429
            ? ' O Mercado Livre recusou ' + balanco.erros429 + ' ' + plural(balanco.erros429, 'chamada', 'chamadas') +
              ' por excesso (429): se isso se repetir, reduza os trechos simultâneos.' : '';
        let texto;
        let tipo = 'ok';
        if (balanco.parou) {
            const ultima = balanco.falhas[balanco.falhas.length - 1];
            texto = 'Parei no ' + balanco.parou + ' (' + nTrechos + ' ' + lidos + ' antes). ' + ultima.mensagem + ' Ao todo: ' + textoDeChamadas(balanco) + '.';
            tipo = 'erro';
        } else if (balanco.falhas.length) {
            const lista = balanco.falhas.slice(0, 2).map(function (f) {
                return f.mlb + ' (' + dataCurta(f.de) + ' a ' + dataCurta(f.ate) + ') — ' + f.mensagem;
            }).join(' | ');
            texto = rotulo + ' atualizado em parte: ' + nTrechos + ' ' + lidos + ', ' + balanco.falhas.length + ' ' +
                plural(balanco.falhas.length, 'falhou', 'falharam') + '. ' + lista +
                (balanco.falhas.length > 2 ? ' (e mais ' + (balanco.falhas.length - 2) + ')' : '') + recusas +
                ' Ao todo: ' + textoDeChamadas(balanco) + '.';
            tipo = 'aviso';
        } else {
            texto = rotulo + ' atualizado: ' + formatarNumero(balanco.pedidos) + ' ' + plural(balanco.pedidos, 'pedido', 'pedidos') +
                ' em ' + nTrechos + ', com ' + textoDeChamadas(balanco) + '.' + pulou + recusas;
            if (balanco.comAviso || balanco.erros429) {
                tipo = 'aviso';
                if (balanco.comAviso) {
                    texto += ' Em ' + balanco.comAviso + ' ' + plural(balanco.comAviso, 'trecho', 'trechos') + ' o coletor deixou aviso (os textos ficam guardados na coleta, no banco).';
                }
            }
        }
        return { texto: texto, tipo: tipo };
    }

    // Função Objetivo: Cria o atualizador de UMA página. `config` = {enderecos: {planejar, mlb, execucao}, sku, chamar} (`chamar` vem de chamador()).
    //                  Devolve {atualizar}.
    function criar(config) {
        const enderecos = config.enderecos;
        const sku = config.sku || '';
        const chamar = config.chamar;

        // Função Objetivo: Pergunta o PLANO ao servidor (só lê o banco). `mlbs` vazio = todos os MLBs do SKU (o servidor sabe quais); com MLBs, só esses. Devolve (sempre) {ok, plano | mensagem}.
        function pedirPlano(mlbs, dias, tudo) {
            let url = enderecos.planejar + '?sku=' + encodeURIComponent(sku) + '&dias=' + dias;
            mlbs.forEach(function (mlb) {
                url += '&mlb=' + encodeURIComponent(mlb);
            });
            if (tudo) {
                url += '&tudo=1';
            }
            return chamar(url, 'GET').then(function (resposta) {
                const dados = resposta.dados || {};
                if (!resposta.ok || !dados.ok) {
                    return { ok: false, mensagem: dados.mensagem || 'Não consegui montar o plano de atualização. Tente de novo.' };
                }
                return { ok: true, plano: dados };
            }).catch(function () {
                return { ok: false, mensagem: 'Não consegui falar com o servidor. Confira a conexão e tente de novo.' };
            });
        }

        // Função Objetivo: Lê UM trecho de UM MLB. Devolve (sempre, sem rejeitar) {tipo: 'ok' | 'dividir' | 'erro', ...}. `maxPedidos` 0 = sem limite.
        function coletarTrecho(trecho, maxPedidos) {
            const corpo = { mlb: trecho.mlb, sku: sku, de: trecho.de, ate: trecho.ate };
            if (maxPedidos) {
                corpo.max_pedidos = maxPedidos;
            }
            return chamar(enderecos.mlb, 'POST', corpo).then(function (resposta) {
                const dados = resposta.dados || {};
                // [EXPLICAÇÃO] → `chamadas` = requisições reais que o servidor gastou NESTE trecho; null = o servidor não informou (erro inesperado, rede caída).
                const chamadas = typeof dados.chamadas === 'number' ? dados.chamadas : null;
                if (dados.dividir && dados.partes && dados.partes.length > 1) {
                    return { tipo: 'dividir', partes: dados.partes, chamadas: chamadas };
                }
                if (!resposta.ok || !dados.ok) {
                    return {
                        tipo: 'erro', erros429: dados.erros_429 || 0, interromper: Boolean(dados.interromper), chamadas: chamadas,
                        mensagem: dados.mensagem || 'Não consegui consultar o Mercado Livre. Tente de novo.'
                    };
                }
                return { tipo: 'ok', pedidos: dados.pedidos || 0, avisos: dados.avisos || 0, erros429: dados.erros_429 || 0, chamadas: chamadas };
            }).catch(function () {
                return { tipo: 'erro', erros429: 0, chamadas: null, interromper: true, mensagem: 'Não consegui falar com o servidor. Confira a conexão e tente de novo.' };
            });
        }

        // Função Objetivo: Lê os trechos do plano, CONCORRENCIA por vez. Devolve (sem rejeitar) o balanço: {pedidos, trechos, diasFeitos, erros429, chamadas (total exato), semContagem (trechos que não informaram), comAviso,
        //                  falhas: [{mlb, de, ate, mensagem}], parou: o MLB onde o acesso foi recusado ou a rede caiu (''), se tudo andou}.
        //                  `aoAndar(balanco)` é chamada a cada trecho que termina (a tela usa para o percentual no botão).
        function executarFila(trechos, maxPedidos, aoAndar) {
            const fila = trechos.slice();
            const balanco = { pedidos: 0, trechos: 0, diasFeitos: 0, erros429: 0, chamadas: 0, semContagem: 0, comAviso: 0, falhas: [], parou: '' };
            let ativos = 0;
            let interrompido = false;

            function trabalhador() {
                if (interrompido) {
                    return Promise.resolve();
                }
                if (!fila.length) {
                    // Fila vazia mas outro trecho ainda lê: ele pode devolver pedaços novos. Espera em vez de sair.
                    return ativos === 0 ? Promise.resolve() : new Promise(function (r) { setTimeout(r, ESPERA_FILA_MS); }).then(trabalhador);
                }
                const trecho = fila.shift();
                ativos += 1;
                return coletarTrecho(trecho, trecho.dias > 1 ? maxPedidos : 0).then(function (r) {
                    ativos -= 1;
                    balanco.erros429 += r.erros429 || 0;
                    if (r.chamadas === null) {
                        balanco.semContagem += 1;
                    } else {
                        balanco.chamadas += r.chamadas;
                    }
                    if (r.tipo === 'dividir') {
                        const pedacos = r.partes.map(function (p) { return { mlb: trecho.mlb, de: p.de, ate: p.ate, dias: diasEntre(p.de, p.ate) }; });
                        Array.prototype.unshift.apply(fila, pedacos);
                    } else if (r.tipo === 'ok') {
                        balanco.trechos += 1;
                        balanco.pedidos += r.pedidos;
                        balanco.diasFeitos += trecho.dias;
                        balanco.comAviso += r.avisos ? 1 : 0;
                    } else {
                        balanco.falhas.push({ mlb: trecho.mlb, de: trecho.de, ate: trecho.ate, mensagem: r.mensagem });
                        if (r.interromper) {
                            interrompido = true;
                            balanco.parou = trecho.mlb;
                        }
                    }
                    aoAndar(balanco);
                    return trabalhador();
                });
            }

            const trabalhadores = [];
            for (let i = 0; i < CONCORRENCIA; i += 1) {
                trabalhadores.push(trabalhador());
            }
            return Promise.all(trabalhadores).then(function () { return balanco; });
        }

        // Função Objetivo: GUARDA no banco o resultado deste clique (o total EXATO de chamadas ao Mercado Livre, trechos, pedidos, tempo...) para consultas futuras
        //                  (tabela ExecucaoColetaVendasMercadoLivre). Devolve (sempre, sem rejeitar) '' se guardou, ou uma frase de atenção para somar à mensagem
        //                  quando NÃO conseguiu guardar.
        function registrar(opcoes, plano, balanco, segundos, mensagem) {
            const naoGuardou = ' Atenção: não consegui guardar este total de chamadas no banco.';
            const unicoMlb = opcoes.tipo === 'mlb' ? (opcoes.mlbs[0] || '') : '';
            return chamar(enderecos.execucao, 'POST', {
                tipo: opcoes.tipo, sku: sku, mlb: unicoMlb, dias: opcoes.dias, reler_tudo: Boolean(opcoes.tudo),
                mlbs: plano.mlbs || opcoes.mlbs.length, dias_total: plano.dias_total, dias_a_coletar: plano.dias_a_coletar,
                trechos: balanco.trechos, trechos_com_falha: balanco.falhas.length, trechos_sem_contagem: balanco.semContagem, parou: Boolean(balanco.parou),
                pedidos: balanco.pedidos, chamadas: balanco.chamadas, erros_429: balanco.erros429, segundos: segundos,
                mensagem: (opcoes.origem ? '[' + opcoes.origem + '] ' : '') + mensagem
            }).then(function (resposta) {
                return resposta.ok && resposta.dados && resposta.dados.ok ? '' : naoGuardou;
            }).catch(function () {
                return naoGuardou;
            });
        }

        // Função Objetivo: O "Atualizar": plano → fila de trechos → resumo → guarda no banco. Devolve (sempre, sem rejeitar):
        //                    {ok: false, mensagem}                      o plano não saiu (nada foi chamado no Mercado Livre);
        //                    {ok: true, texto, tipo, trechos, chamadas, semContagem, parou, balanco, plano}   o clique terminou (mesmo que em parte). `trechos` = quantos trechos foram lidos
        //                    (0 = nada mudou no banco); `chamadas` = o total EXATO; `parou` = o MLB onde o acesso foi recusado ('' = não parou).
        // `opcoes` = {mlbs: [] (vazio = todos os MLBs do SKU), dias, tudo, tipo: 'mlb' | 'produto' (como o clique é guardado), rotulo (MLB, "Produto" ou "Item": abre o resumo), origem (opcional: de qual tela veio,
        //            vai na frente do texto guardado no banco), aoAndar(pct, balanco) (opcional: a cada trecho, 0 a 100)}.
        function atualizar(opcoes) {
            const inicio = Date.now();
            return pedirPlano(opcoes.mlbs, opcoes.dias, opcoes.tudo).then(function (resposta) {
                if (!resposta.ok) {
                    return { ok: false, mensagem: resposta.mensagem };
                }
                const plano = resposta.plano;
                const trechos = plano.trechos.slice().sort(function (a, b) { return b.dias - a.dias; });
                const percentual = function (balanco) {
                    return plano.dias_a_coletar ? Math.min(100, Math.round(100 * balanco.diasFeitos / plano.dias_a_coletar)) : 100;
                };
                const andar = function (balanco) {
                    if (opcoes.aoAndar) {
                        opcoes.aoAndar(percentual(balanco), balanco);
                    }
                };
                andar({ diasFeitos: 0 });
                return executarFila(trechos, plano.max_pedidos, andar).then(function (balanco) {
                    const segundos = Math.round((Date.now() - inicio) / 1000);
                    const resumo = resumir(opcoes.rotulo, plano, balanco);
                    // [EXPLICAÇÃO] → Plano sem trechos (tudo já coletado) não gastou chamada nenhuma: nada a guardar.
                    const guardar = plano.trechos.length ? registrar(opcoes, plano, balanco, segundos, resumo.texto) : Promise.resolve('');
                    return guardar.then(function (aviso) {
                        let texto = resumo.texto;
                        let tipo = resumo.tipo;
                        if (aviso) {
                            texto += aviso;
                            tipo = tipo === 'ok' ? 'aviso' : tipo;
                        }
                        return {
                            ok: true, texto: texto, tipo: tipo, trechos: balanco.trechos, chamadas: balanco.chamadas, semContagem: balanco.semContagem,
                            parou: balanco.parou, balanco: balanco, plano: plano
                        };
                    });
                });
            });
        }

        return { atualizar: atualizar };
    }

    global.AtualizadorDeVendas = { criar: criar, chamador: chamador, plural: plural, formatarNumero: formatarNumero };
})(window);
