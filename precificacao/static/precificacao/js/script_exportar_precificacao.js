document.addEventListener('change', function (evento) {
    if (evento.target.name === 'canal') {
        document.querySelectorAll('.exportacao-canal-card').forEach(function (card) {
            card.classList.remove('exportacao-canal-card--ativa');
        });
        evento.target.closest('.exportacao-canal-card').classList.add('exportacao-canal-card--ativa');
        return;
    }

    if (evento.target.name === 'margem') {
        document.querySelectorAll('.promocao-margem-card').forEach(function (card) {
            card.classList.remove('grade-margem-card--ativa');
        });
        evento.target.closest('.promocao-margem-card').classList.add('grade-margem-card--ativa');
    }
});