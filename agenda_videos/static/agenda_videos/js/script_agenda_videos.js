// agenda_videos/static/agenda_videos/js/script_agenda_videos.js

// Função Objetivo: Garante que "A Fazer Hoje" e "Estágio" sejam mutuamente
// exclusivos no filtro em destaque.
// Explicação em detalhe: marcar um precisa desmarcar o outro automaticamente,
// antes de enviar — senão os 2 vão juntos na URL, e o servidor (de propósito)
// sempre prioriza "A Fazer Hoje" quando ele está presente, fazendo o Estágio
// recém-clicado parecer "não funcionar".

function agendaAlternarAFazerHoje(checkbox) {
    if (checkbox.checked) {
        document.querySelectorAll('input[name="estagio"]').forEach(function (input) {
            input.checked = false;
        });
    }
    checkbox.form.submit();
}

function agendaAlternarEstagio(checkbox) {
    if (checkbox.checked) {
        const aFazerHoje = document.querySelector('input[name="a_fazer_hoje"]');
        if (aFazerHoje) aFazerHoje.checked = false;
    }
    checkbox.form.submit();
}