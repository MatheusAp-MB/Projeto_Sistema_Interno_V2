// * [EXPLICAÇÃO] → Fecha o modal de confirmação do roadmap ao clicar em "Cancelar"
//                  ou no fundo escurecido — nunca ao clicar dentro da caixa do modal
//                  em si (o atributo data-fechar-modal-roadmap só existe nesses 2
//                  lugares, não na caixa interna).
document.body.addEventListener('click', function (evento) {
    if (evento.target.matches('[data-fechar-modal-roadmap]')) {
        document.getElementById('modal-roadmap-slot').innerHTML = '';
    }
});