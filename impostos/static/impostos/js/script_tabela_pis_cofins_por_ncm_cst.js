// impostos/static/impostos/js/script_tabela_pis_cofins_por_ncm_cst.js
//
// * [RESUMO] → Script da tela de PIS/COFINS por NCM + CST.
//              Destaca a linha correspondente na tabela depois de uma
//              consulta bem-sucedida — mesmo padrão do destacar_celula()
//              da tela de ICMS por NCM, simplificado porque aqui a linha
//              inteira é o alvo (não há coluna fixa lateral pra descontar).

function limpar_destaque_pis_cofins() {
    document.querySelectorAll('.tabela-pc tr.destaque').forEach(function(tr) {
        tr.classList.remove('destaque');
    });
}

function destacar_grupo(ncm, cst) {
    limpar_destaque_pis_cofins();

    var linha = document.querySelector(
        `.tabela-pc tr[data-ncm="${ncm}"][data-cst="${cst}"]`
    );
    if (!linha) return;

    linha.classList.add('destaque');
    linha.scrollIntoView({ behavior: 'smooth', block: 'center' });
}