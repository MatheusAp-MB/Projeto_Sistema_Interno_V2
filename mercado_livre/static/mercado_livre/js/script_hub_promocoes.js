// * [RESUMO] → JS específico do Hub de Promoções. Hoje só cobre a
//              confirmação obrigatória antes de "Participar"/"Trocar"
//              quando a sugestão é de risco (Catálogo, margem abaixo
//              do mínimo — a única situação em que isso pode
//              acontecer, já que Simples/Base nunca chega a sugerir
//              risco). O href ainda é "#" (aguardando link real da
//              API do ML) — quando existir, este listener já vai
//              funcionar sem precisar de ajuste.

document.addEventListener('click', function (evento) {
    const botao = evento.target.closest('[data-confirmar-risco="true"]');
    if (!botao) return;

    const margem = botao.dataset.margem || '?';
    const confirmado = window.confirm(
        `Atenção: esta é uma sugestão de risco.\n\n` +
        `A margem calculada é de ${margem}%, abaixo do mínimo seguro configurado.\n\n` +
        `Isso só deve ser aceito em casos específicos (queima de estoque, ` +
        `necessidade de ganhar o catálogo a qualquer custo, ou decisão ` +
        `deliberada de um gestor após análise).\n\n` +
        `Deseja continuar mesmo assim?`
    );

    if (!confirmado) {
        evento.preventDefault();
    }
});