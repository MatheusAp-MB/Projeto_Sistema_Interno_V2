# * [RESUMO] → Constantes compartilhadas de performance — hoje só o
#              batch_size usado em TODO bulk_create/bulk_update do
#              popular_banco. Existe pra testar tamanhos diferentes
#              trocando 1 número aqui, em vez de editar 20 linhas
#              espalhadas em 8 arquivos toda vez que quiser comparar.

BATCH_SIZE_PADRAO = 5000