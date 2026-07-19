function destacar_linha_tiktok(peso_min) {
    document.querySelectorAll('.destaque-linha').forEach(el => el.classList.remove('destaque-linha'));

    const linha = document.querySelector(`tr[data-peso-min="${peso_min}"]`);
    if (!linha) return;

    linha.scrollIntoView({ behavior: 'smooth', block: 'center' });
    linha.querySelectorAll('td').forEach(td => td.classList.add('destaque-linha'));
}