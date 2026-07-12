// * [RESUMO] → Script da tela de Recomendação de Precificação.
//              Hoje só cuida do seletor de comportamento — ao trocar,
//              reenvia o formulário automaticamente, recarregando a
//              página com o novo comportamento aplicado no cálculo.

document.addEventListener('DOMContentLoaded', function () {
    var seletor = document.getElementById('select-comportamento');
    if (!seletor) return;

    seletor.addEventListener('change', function () {
        document.getElementById('form-comportamento').submit();
    });
});