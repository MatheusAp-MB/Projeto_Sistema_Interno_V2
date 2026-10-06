# api_mercado_livre/atributos_ml.py

# Função Objetivo: Contexto "Características (atributos)" — sabe tudo que o
# ClienteApiMercadoLivre (transporte puro) não deve saber sobre este
# domínio: quais endpoints chamar e como montar a resposta.
#   1) O que a CATEGORIA pede no card "Características principais":
#      grupo MAIN de GET /categories/{id}/technical_specs/input, menos os
#      atributos com a etiqueta allow_variations; mais a definição de cada
#      um (tipo, limite, opções, unidades) em GET /categories/{id}/attributes.
#   2) Os valores que o ANÚNCIO tem hoje: GET /items/{mlb} com
#      include_internal_attributes=true (o multiget /items?ids= NÃO foi
#      testado com esse parâmetro — por isso a leitura é 1 chamada por MLB).
#   3) O ENVIO dos valores novos: PUT /items/{mlb} só com os atributos que o
#      usuário mandou mudar. É o ÚNICO método desta classe que ESCREVE no ML —
#      e só roda depois do "Confirmar envio" da tela.
# Compõe um ClienteApiMercadoLivre (nunca herda dele) e devolve o dado como
# a API mandou — quem chama decide como e quando gravar; esta classe não
# sabe de banco nem de disco. IMPORTANTE: nada aqui roda sozinho — só quem
# é disparado por um botão da tela de Características dos anúncios chama
# estes métodos (regra do Matheus: nunca requisição automática à API).
# Lógica de leitura portada de scripts_exploracao_ML/
# gerar_planilha_llm_inventario.py (buscar_categoria / buscar_item), já
# validada com dado real.

import json
import logging
import re
from pathlib import Path

from api_mercado_livre.core.estrutura_api.excecoes import ErroAPI, ErroAutenticacaoAPI

NOME_LOG = "sincronizar_caracteristicas_ml"

# * [EXPLICAÇÃO] → Os envios têm log próprio, separado das leituras. O
#                  transporte (chamar_api) registra cada chamada mas NÃO o
#                  corpo enviado; por isso o "..._corpos.log" guarda, por
#                  envio, o que foi mandado e o que o ML respondeu.
NOME_LOG_ENVIO = "enviar_caracteristicas_ml"
NOME_LOG_CORPOS_ENVIO = "enviar_caracteristicas_ml_corpos"

# Formato do erro que o transporte levanta: "Erro 400 em /items/MLB123: {corpo}".
_PADRAO_ERRO_HTTP = re.compile(r"^Erro (\d{3}) em [^:]*: (.*)$", re.DOTALL)


class AtributosML:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: Tags da API (dict {tag: true} em /attributes, lista
    # em technical_specs) -> lista ordenada só com as ativas.
    @staticmethod
    def _tags_ativas(attr: dict) -> list[str]:
        tags = attr.get("tags")
        if isinstance(tags, dict):
            return sorted(str(k) for k, v in tags.items() if v)
        if isinstance(tags, list):
            return sorted(str(t) for t in tags)
        return []

    # Função Objetivo: Lê o que a categoria pede no card "Características
    # principais" (2 chamadas: technical_specs/input + attributes). Devolve
    # {"card": {atributo_id: {...}}, "defs": {atributo_id: {...}}} na ordem
    # em que o ML mostra os campos. "card" vem do componente de tela
    # (nome, tags, allow_custom_value, tipo de componente); "defs" vem da
    # definição do atributo (value_type, tamanho máximo, opções, unidades,
    # tags) — só dos atributos que estão no card.
    def buscar_card_categoria(self, category_id: str, pasta_logs) -> dict:
        resposta_specs = self._cliente.chamar(
            "GET", f"/categories/{category_id}/technical_specs/input",
            pasta_logs=pasta_logs, nome_log=NOME_LOG,
        )
        card = {}
        for grupo in resposta_specs.json().get("groups", []):
            if grupo.get("id") != "MAIN":
                continue
            for componente in grupo.get("components", []):
                ui_config = componente.get("ui_config") or {}
                for attr in componente.get("attributes", []):
                    atributo_id = attr.get("id")
                    tags = self._tags_ativas(attr)
                    if not atributo_id or "allow_variations" in tags:
                        continue
                    card[atributo_id] = {
                        "label": attr.get("label") or attr.get("name") or atributo_id,
                        "tags": tags,
                        "allow_custom_value": ui_config.get("allow_custom_value"),  # True / False / None (não informado)
                        "componente": componente.get("component"),
                    }

        resposta_attrs = self._cliente.chamar(
            "GET", f"/categories/{category_id}/attributes",
            pasta_logs=pasta_logs, nome_log=NOME_LOG,
        )
        defs = {}
        for attr in resposta_attrs.json():
            atributo_id = attr.get("id")
            if not atributo_id or atributo_id not in card:
                continue
            defs[atributo_id] = {
                "value_type": attr.get("value_type"),
                "value_max_length": attr.get("value_max_length"),
                "values": [{"id": o.get("id"), "name": o.get("name")} for o in attr.get("values") or []],
                "allowed_units": [{"id": u.get("id"), "name": u.get("name")} for u in attr.get("allowed_units") or []],
                "tags": self._tags_ativas(attr),
            }

        return {"card": card, "defs": defs}

    # Função Objetivo: Lê os valores que o anúncio tem HOJE no ML. Devolve a
    # categoria e o status que o ML informou agora e o array "attributes"
    # CRU (inclusive os "N/A", que chegam com value_id "-1" e value_name
    # nulo) — sem nenhuma normalização, é o espelho que a tela mostra em
    # "Hoje no Mercado Livre".
    def buscar_atributos_item(self, mlb: str, pasta_logs) -> dict:
        resposta = self._cliente.chamar(
            "GET", f"/items/{mlb}",
            pasta_logs=pasta_logs, nome_log=NOME_LOG,
            params={"include_internal_attributes": "true"},
        )
        corpo = resposta.json()
        return {
            "category_id": corpo.get("category_id"),
            "status": corpo.get("status"),
            "attributes": corpo.get("attributes") or [],
        }

    # Função Objetivo: ESCREVE no ML — PUT /items/{mlb} só com os atributos
    # que o usuário mandou mudar. O PUT é PARCIAL (confirmado com dado real em
    # 05/10/2026: o que não vai no corpo fica como está). 1 única tentativa,
    # sem retentativa: escrita não se repete sozinha. Nunca levanta erro de
    # resposta do ML — devolve um dicionário que conta o que aconteceu:
    #   ok           True se o ML respondeu 200;
    #   status_http  código HTTP (None quando não houve resposta);
    #   avisos       textos do campo "warnings" do ML (ele pode aceitar com aviso);
    #   mensagem     texto pronto para mostrar ao usuário;
    #   incerto      True quando NÃO dá para saber se o ML aplicou (tempo
    #                esgotado, erro 5xx, queda de conexão) — só a leitura de
    #                volta responde isso.
    # Só o 401 (token recusado) sobe como ErroAutenticacaoAPI: sem token
    # válido, todos os próximos envios falhariam do mesmo jeito.
    # IMPORTANTE: só o botão "Confirmar envio" da tela de Características dos
    # anúncios chama este método (regra do Matheus: nada automático).
    def enviar_atributos_item(self, mlb: str, atributos: list[dict], pasta_logs) -> dict:
        corpo = {"attributes": atributos}
        try:
            resposta = self._cliente.chamar(
                "PUT", f"/items/{mlb}",
                pasta_logs=pasta_logs, nome_log=NOME_LOG_ENVIO,
                json_body=corpo, max_tentativas=1,
            )
        except ErroAutenticacaoAPI as erro:
            self._registrar_envio(pasta_logs, mlb, corpo, {"ok": False, "status_http": 401, "detalhe_cru": str(erro)[:500]})
            raise
        except ErroAPI as erro:
            resultado = self._interpretar_erro(str(erro))
        else:
            resultado = self._interpretar_resposta(resposta)
        self._registrar_envio(pasta_logs, mlb, corpo, resultado)
        return resultado

    # Função Objetivo: Transforma os "warnings" do ML (lista de dicts ou de
    # textos) numa lista de textos.
    @staticmethod
    def _textos_dos_avisos(avisos) -> list[str]:
        textos = []
        for aviso in avisos or []:
            if isinstance(aviso, dict):
                texto = aviso.get("message") or aviso.get("code") or json.dumps(aviso, ensure_ascii=False)
            else:
                texto = str(aviso)
            if texto and texto not in textos:
                textos.append(texto)
        return textos

    @staticmethod
    def _interpretar_resposta(resposta) -> dict:
        try:
            corpo = resposta.json()
        except ValueError:
            corpo = {}
        avisos = AtributosML._textos_dos_avisos(corpo.get("warnings") if isinstance(corpo, dict) else None)
        if resposta.status_code != 200:
            return {
                "ok": False, "status_http": resposta.status_code, "avisos": avisos, "incerto": True,
                "mensagem": f"O ML respondeu {resposta.status_code} em vez de 200; não dá para ter certeza de que aplicou.",
            }
        return {
            "ok": True, "status_http": 200, "avisos": avisos, "incerto": False,
            "mensagem": "Aceito pelo Mercado Livre.",
        }

    # Função Objetivo: Pega o texto de erro que o ML mandou (JSON com
    # "message" e "cause") e junta as mensagens numa frase só.
    @staticmethod
    def _detalhe_do_erro(corpo: str) -> str:
        try:
            dados = json.loads(corpo)
        except ValueError:
            return corpo[:300]
        if not isinstance(dados, dict):
            return corpo[:300]
        textos = []
        mensagem = dados.get("message")
        if isinstance(mensagem, str) and mensagem:
            textos.append(mensagem)
        causas = dados.get("cause")
        for causa in causas if isinstance(causas, list) else [causas]:
            if isinstance(causa, dict):
                texto = causa.get("message") or causa.get("description") or causa.get("code")
            else:
                texto = causa
            if isinstance(texto, str) and texto and texto not in textos:
                textos.append(texto)
        if not textos:
            erro = dados.get("error")
            textos.append(erro if isinstance(erro, str) and erro else corpo[:300])
        return "; ".join(textos)[:500]

    # Função Objetivo: Traduz o erro que o transporte levantou para o
    # dicionário de resultado. Só o que PODE ter alterado o anúncio (tempo
    # esgotado, 5xx, queda de conexão) fica como "incerto".
    @staticmethod
    def _interpretar_erro(texto: str) -> dict:
        achou = _PADRAO_ERRO_HTTP.match(texto)
        if not achou:
            if texto.startswith("Timeout esgotado"):
                return {
                    "ok": False, "status_http": None, "avisos": [], "incerto": True, "detalhe_cru": texto[:500],
                    "mensagem": "O ML não respondeu a tempo. Não sei se aplicou o envio; a leitura de volta confere.",
                }
            if "Número máximo de tentativas" in texto:
                return {
                    "ok": False, "status_http": 429, "avisos": [], "incerto": False, "detalhe_cru": texto[:500],
                    "mensagem": "O ML pediu para esperar (limite de chamadas). Este anúncio não foi alterado; tente de novo em instantes.",
                }
            return {
                "ok": False, "status_http": None, "avisos": [], "incerto": True, "detalhe_cru": texto[:500],
                "mensagem": "Falha ao falar com o ML. Não sei se aplicou o envio; a leitura de volta confere.",
            }

        status = int(achou.group(1))
        detalhe = AtributosML._detalhe_do_erro(achou.group(2).strip())
        sufixo = f": {detalhe}" if detalhe else "."
        incerto = False
        if status >= 500:
            incerto = True
            mensagem = f"O ML teve um erro interno (HTTP {status}). Não sei se aplicou o envio; a leitura de volta confere."
        elif status == 409:
            mensagem = "O anúncio estava sendo alterado no ML. Espere alguns segundos e envie de novo" + sufixo
        elif status == 403:
            mensagem = "O ML não permitiu alterar este anúncio" + sufixo
        elif status == 404:
            mensagem = "O ML não encontrou este anúncio" + sufixo
        else:
            mensagem = "O ML recusou o envio" + sufixo
        return {
            "ok": False, "status_http": status, "avisos": [], "incerto": incerto,
            "detalhe_cru": achou.group(2).strip()[:500], "mensagem": mensagem,
        }

    # Função Objetivo: 1 linha de log por envio: o que foi mandado e o que o
    # ML respondeu. Falha de gravação do log nunca derruba o envio.
    @staticmethod
    def _registrar_envio(pasta_logs, mlb: str, corpo: dict, resultado: dict) -> None:
        try:
            pasta = Path(pasta_logs)
            logger = logging.getLogger(f"envios_caracteristicas.{pasta}")
            if not logger.handlers:
                pasta.mkdir(parents=True, exist_ok=True)
                manipulador = logging.FileHandler(pasta / f"{NOME_LOG_CORPOS_ENVIO}.log", encoding="utf-8")
                manipulador.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
                logger.addHandler(manipulador)
                logger.setLevel(logging.INFO)
                logger.propagate = False
            logger.info(json.dumps({"mlb": mlb, "enviado": corpo, "resultado": resultado}, ensure_ascii=False))
        except OSError:
            pass
