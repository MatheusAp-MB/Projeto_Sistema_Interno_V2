# core/management/commands/popular_banco_suporte/importar_qualidade_anuncio.py

# Função Objetivo: Importa dados de qualidade/performance e critérios do JSON.
# Explicação em detalhe: pra cada MLB, cria/atualiza QualidadeAnuncio (resumo,
# por VARIAÇÃO — a fonte da verdade é a folha, mesmo resultado replicado pra
# todas as variações daquele MLB) e QualidadeAnuncioCriterio (os critérios).
# Critérios não catalogados são criados automaticamente (catalogado=False),
# nunca perdendo dado da API. 2 fases: Qualidade precisa ter ID salvo antes
# de Critério poder referenciar ela.
#
# Reescrito em POO (16/07) — 2 classes:
#   LinhaQualidadeMLB   → 1 bloco de performance de 1 MLB
#   ImportadorQualidade → o processo inteiro, do arquivo ao banco

import json
from mercado_livre.models import AnuncioMercadoLivre, CriterioQualidade, QualidadeAnuncio, QualidadeAnuncioCriterio
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.management.commands.popular_banco_suporte.parser_data import ParserData


# Função Objetivo: Representa o bloco de performance de 1 MLB do JSON.
class LinhaQualidadeMLB:

    CAMPOS_QUALIDADE = ['score', 'nivel', 'calculado_em', 'http_status', 'erro']

    # Função Objetivo: Recebe o bloco bruto do MLB e o parser de data a usar.
    def __init__(self, mlb_dados, parser_data):
        self.mlb_dados = mlb_dados
        self.parser_data = parser_data
        self.mlb = None
        self.performance = None
        self.perf_dados = None
        self.regras = {}

    # Função Objetivo: Extrai o identificador do MLB.
    def extrair_mlb(self):
        self.mlb = self.mlb_dados.get('mlb')

    # Função Objetivo: Extrai o bloco de performance, só se a chamada teve sucesso.
    def extrair_performance(self):
        self.performance = self.mlb_dados.get('performance', {})
        self.perf_dados = self.performance.get('dados') if self.performance.get('chamado') else None

    # Função Objetivo: Extrai as regras (critérios) de dentro dos buckets.
    def extrair_regras(self):
        buckets = self.perf_dados.get('buckets') if self.perf_dados else None
        resultado = {}
        if not buckets:
            self.regras = resultado
            return resultado

        for bucket in buckets:
            for variable in bucket.get('variables', []):
                var_score = variable.get('score')
                var_calculated = variable.get('calculated_at')
                for rule in variable.get('rules', []):
                    key = rule.get('key')
                    if not key:
                        continue
                    wordings = rule.get('wordings', {})
                    resultado[key] = {
                        'status': rule.get('status'),
                        'score': var_score,
                        'calculated_at': var_calculated,
                        'link': wordings.get('link'),
                        'api_title': wordings.get('title'),
                    }
        self.regras = resultado
        return resultado

    # Função Objetivo: Devolve os campos prontos pro QualidadeAnuncio(**isso).
    def para_dict_qualidade(self):
        return dict(
            score=self.perf_dados.get('score') if self.perf_dados else None,
            nivel=self.perf_dados.get('level_wording') if self.perf_dados else None,
            calculado_em=self.parser_data.parsear(self.perf_dados.get('calculated_at')) if self.perf_dados else None,
            http_status=self.performance.get('http'),
            erro=self.performance.get('erro'),
        )

    # Função Objetivo: Roda os passos acima, na ordem certa.
    def processar(self):
        self.extrair_mlb()
        self.extrair_performance()
        self.extrair_regras()
        return self


# Função Objetivo: Orquestra a importação inteira de Qualidade, do arquivo ao banco.
class ImportadorQualidade:

    # Função Objetivo: Recebe o caminho do JSON, o stdout, e zera os contadores.
    def __init__(self, caminho_json, stdout):
        self.caminho_json = caminho_json
        self.stdout = stdout
        self.parser_data = ParserData(origem='iso')

        self.dados = None
        self.blocos_sku = []

        self.criterios_por_key = {}
        self.anuncios_por_mlb = {}
        self.qualidades_existentes = {}
        self.qualidade_id_por_variacao_id = {}

        self.qualidades_para_criar = []
        self.qualidades_para_atualizar = []
        self.ids_ja_atualizados = set()
        self.regras_por_variacao_id = {}

        self.criterios_para_criar = []
        self.criterios_para_atualizar = []

        self.total_mlbs = 0
        self.sem_anuncio_correspondente = 0
        self.criterios_novos = 0
        self.avisos = []

    # Função Objetivo: Lê o JSON de qualidade/performance.
    def ler_json(self):
        with open(self.caminho_json, encoding='utf-8') as f:
            self.dados = json.load(f)
        self.blocos_sku = self.dados.get('skus', [])

    # Função Objetivo: Carrega em memória tudo que já existe no banco.
    def carregar_dados_existentes(self):
        self.criterios_por_key = {c.rule_key: c for c in CriterioQualidade.objects.all()}
        self.anuncios_por_mlb = {
            a.mlb: a for a in AnuncioMercadoLivre.objects.prefetch_related('variacoes').all()
        }
        self.qualidades_existentes = {qa.variacao_id: qa for qa in QualidadeAnuncio.objects.all()}

    # Função Objetivo: Processa cada MLB e replica o resultado pras variações.
    def processar_mlbs_e_variacoes(self):
        total_mlbs_esperado = sum(len(bloco.get('mlbs', [])) for bloco in self.blocos_sku)

        for bloco in self.blocos_sku:
            for mlb_dados in bloco.get('mlbs', []):
                self.total_mlbs += 1
                if self.total_mlbs % 500 == 0 or self.total_mlbs == total_mlbs_esperado:
                    self.stdout.write(f'    ... {self.total_mlbs}/{total_mlbs_esperado} MLBs processados')

                linha = LinhaQualidadeMLB(mlb_dados, self.parser_data).processar()

                anuncio = self.anuncios_por_mlb.get(linha.mlb)
                if not anuncio:
                    self.sem_anuncio_correspondente += 1
                    self.avisos.append(f'[SEM ANÚNCIO] {linha.mlb} não encontrado no banco — pulado')
                    continue

                variacoes_do_mlb = list(anuncio.variacoes.all())
                if not variacoes_do_mlb:
                    self.sem_anuncio_correspondente += 1
                    self.avisos.append(f'[SEM VARIAÇÃO] {linha.mlb} não tem nenhuma variação no banco — pulado')
                    continue

                dados_qualidade = linha.para_dict_qualidade()

                for variacao_alvo in variacoes_do_mlb:
                    existente = self.qualidades_existentes.get(variacao_alvo.id)
                    if existente:
                        for campo, valor in dados_qualidade.items():
                            setattr(existente, campo, valor)
                        # * [EXPLICAÇÃO] → Se ainda não tem PK, é objeto NOVO
                        #                  desta mesma rodada (mesma variação
                        #                  apareceu 2x no arquivo) — já vai
                        #                  ser salvo pelo bulk_create, não
                        #                  pode ir pro bulk_update.
                        if existente.pk and id(existente) not in self.ids_ja_atualizados:
                            self.qualidades_para_atualizar.append(existente)
                            self.ids_ja_atualizados.add(id(existente))
                    else:
                        nova = QualidadeAnuncio(variacao=variacao_alvo, **dados_qualidade)
                        self.qualidades_para_criar.append(nova)
                        self.qualidades_existentes[variacao_alvo.id] = nova

                    if linha.regras:
                        self.regras_por_variacao_id[variacao_alvo.id] = linha.regras

    # Função Objetivo: Salva as qualidades e resolve os IDs pros critérios.
    # Explicação em detalhe: rebusca os IDs direto do banco (1 query), em vez
    # de confiar que bulk_create preencheu .id sozinho — mais simples e
    # 100% seguro, independente de particularidade do MySQL nesse ponto.
    def salvar_qualidades(self):
        if self.qualidades_para_criar:
            QualidadeAnuncio.objects.bulk_create(self.qualidades_para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.qualidades_para_atualizar:
            QualidadeAnuncio.objects.bulk_update(
                self.qualidades_para_atualizar, LinhaQualidadeMLB.CAMPOS_QUALIDADE, batch_size=BATCH_SIZE_PADRAO
            )

        ids_variacao_com_regras = list(self.regras_por_variacao_id.keys())
        self.qualidade_id_por_variacao_id = dict(
            QualidadeAnuncio.objects.filter(variacao_id__in=ids_variacao_com_regras)
            .values_list('variacao_id', 'id')
        )

    # Função Objetivo: Processa os critérios, usando os IDs já resolvidos.
    def processar_criterios(self):
        criterios_existentes = {
            (qac.qualidade_id, qac.criterio_id): qac
            for qac in QualidadeAnuncioCriterio.objects.filter(
                qualidade_id__in=self.qualidade_id_por_variacao_id.values()
            )
        }

        for variacao_id, regras in self.regras_por_variacao_id.items():
            qualidade_id = self.qualidade_id_por_variacao_id.get(variacao_id)
            if not qualidade_id:
                continue

            for rule_key, info in regras.items():
                criterio = self.criterios_por_key.get(rule_key)

                if not criterio:
                    criterio = CriterioQualidade.objects.create(
                        rule_key=rule_key,
                        grupo=CriterioQualidade.Grupo.DESCONHECIDO,
                        nome=info.get('api_title') or rule_key,
                        pergunta=info.get('api_title') or rule_key,
                        catalogado=False,
                    )
                    self.criterios_por_key[rule_key] = criterio
                    self.criterios_novos += 1
                    self.avisos.append(f'[CRITÉRIO NOVO] {rule_key} não catalogado — criado como Desconhecido')

                status_valor = (
                    QualidadeAnuncioCriterio.Status.APROVADO
                    if info['status'] == 'COMPLETED'
                    else QualidadeAnuncioCriterio.Status.NAO_APROVADO
                )
                dados_criterio = dict(
                    status=status_valor,
                    score=info.get('score'),
                    calculado_em=self.parser_data.parsear(info.get('calculated_at')),
                    link_correcao=info.get('link'),
                )

                chave = (qualidade_id, criterio.id)
                existente_crit = criterios_existentes.get(chave)
                if existente_crit:
                    for campo, valor in dados_criterio.items():
                        setattr(existente_crit, campo, valor)
                    self.criterios_para_atualizar.append(existente_crit)
                else:
                    novo = QualidadeAnuncioCriterio(qualidade_id=qualidade_id, criterio=criterio, **dados_criterio)
                    self.criterios_para_criar.append(novo)
                    criterios_existentes[chave] = novo

    # Função Objetivo: Grava os critérios no banco em lote.
    def salvar_criterios(self):
        campos_criterio = ['status', 'score', 'calculado_em', 'link_correcao']
        if self.criterios_para_criar:
            QualidadeAnuncioCriterio.objects.bulk_create(self.criterios_para_criar, batch_size=BATCH_SIZE_PADRAO)
        if self.criterios_para_atualizar:
            QualidadeAnuncioCriterio.objects.bulk_update(
                self.criterios_para_atualizar, campos_criterio, batch_size=BATCH_SIZE_PADRAO
            )

    # Função Objetivo: Roda a importação inteira, do arquivo ao banco.
    def rodar_importacao_completa(self):
        self.ler_json()
        self.carregar_dados_existentes()
        self.processar_mlbs_e_variacoes()
        self.salvar_qualidades()
        self.processar_criterios()
        self.salvar_criterios()
        return self

    # Função Objetivo: Monta o texto de resumo pro terminal.
    def relatorio(self):
        return (
            f'[QUALIDADE] Concluído!\n'
            f'    Total de MLBs processados: {self.total_mlbs}\n'
            f'    QualidadeAnuncio criados: {len(self.qualidades_para_criar)}\n'
            f'    QualidadeAnuncio atualizados: {len(self.qualidades_para_atualizar)}\n'
            f'    Sem anúncio correspondente: {self.sem_anuncio_correspondente}\n'
            f'    Critérios novos (desconhecidos): {self.criterios_novos}'
        )


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def importar_qualidade_anuncio(stdout, style, caminho_json):
    if not caminho_json.exists():
        stdout.write(style.WARNING(
            f'[QUALIDADE] Arquivo {caminho_json} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[QUALIDADE] Lendo {caminho_json}...')

    importador = ImportadorQualidade(caminho_json, stdout)
    importador.rodar_importacao_completa()

    stdout.write(f'    {len(importador.blocos_sku)} SKU(s) no arquivo')
    for aviso in importador.avisos:
        stdout.write(style.WARNING(f'    {aviso}') if 'CRITÉRIO NOVO' in aviso else aviso)

    stdout.write('')
    stdout.write(style.SUCCESS(importador.relatorio()))