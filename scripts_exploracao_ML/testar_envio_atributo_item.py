# scripts_exploracao_ML/testar_envio_atributo_item.py
#
# PRIMEIRO script desta pasta que ESCREVE no Mercado Livre (todos os outros
# só leem). Serve pra testar, num anúncio real e escolhido por você, o que a
# documentação oficial não deixa claro sobre PUT /items/{id} com o array
# "attributes":
#
#   1) O PUT é PARCIAL (só muda o que foi enviado) ou SUBSTITUTIVO (o que não
#      foi enviado some)? A doc de Atributos se contradiz: a seção "Modificar"
#      manda reenviar os atributos já preenchidos "a fim de não perder as
#      informações", e a seção "Remover" diz que enviar só o que muda não
#      apaga os demais. A página "Sincronização e modificação de publicações"
#      não fala de atributos. Só um teste real resolve.
#   2) O que a resposta do PUT traz (status HTTP, corpo, avisos "warnings").
#   3) Quanto tempo o GET leva pra refletir a mudança. Se o anúncio for um
#      User Product (family_name preenchido), a doc diz que a alteração é
#      replicada de forma ASSÍNCRONA pros outros itens do mesmo User Product.
#   4) Se o "desfazer" a partir da leitura de antes devolve o anúncio ao que
#      era.
#
# 3 modos (constante MODO, logo abaixo):
#
#   "simular"  -> só LÊ (GET) e mostra o corpo que SERIA enviado. Não escreve
#                 nada no Mercado Livre. Use sempre primeiro.
#   "enviar"   -> lê, confere, mostra o corpo, pede confirmação DIGITADA
#                 (você digita o MLB), faz 1 único PUT, relê o item e compara
#                 a lista inteira de atributos antes x depois. Opcionalmente
#                 relê de novo depois de N segundos.
#   "desfazer" -> relê o item e devolve ao que estava no arquivo "antes"
#                 salvo por uma execução anterior (mesma confirmação digitada).
#
# Regras de segurança deste script:
#   - 1 MLB e 1 atributo por execução (o "desfazer" pode reenviar mais de um
#     atributo, mas só os que estiverem diferentes do "antes", e mostra tudo
#     antes de pedir a confirmação).
#   - No máximo 1 PUT por execução, SEM retentativa automática (max_tentativas=1).
#     Em caso de erro, o script mostra o erro cru e para; quem decide rodar de
#     novo é você.
#   - Recusa atributo com tag read_only / fixed / inferred, dimensões de pacote
#     (SELLER_PACKAGE_*, que exigem os 4 juntos) e anúncio de catálogo
#     (catalog_listing=True: os atributos são herdados do catálogo).
#   - Não toca no banco do sistema nem em nenhuma tela.
#   - Tudo que é lido ou enviado fica salvo em scripts_exploracao_ML/saidas_teste_envio/
#     (leitura completa antes e depois, corpo enviado, resposta crua e relatório).
#
# Ao terminar, suba na conversa os arquivos *_relatorio.json, *_antes.json e
# *_depois.json (e o *_depois_tardio.json, se houver) pra eu analisar.

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Permite rodar este script direto (python scripts_exploracao_ML/testar_envio_atributo_item.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
MODO = "simular"          # "simular" | "enviar" | "desfazer"
MLB = "MLB2696429175"     # SKU F7891988006671.001 (Guarany PCP-1,25) — 1 dos 4 MLBs desse SKU na conta MB
CONTA = "MB"              # "MB" (Magazine) ou "SV" (Samvale) — CONFIRME de qual empresa é esse MLB antes de rodar

# Atributo a enviar (usado em "simular" e "enviar"; em "desfazer" só se DESFAZER_SOMENTE_ATRIBUTO=True).
ATRIBUTO_ID = "LINE"      # "Linha" — o "ID na API" que aparece no card da tela
# Valor a enviar, conforme o tipo do atributo (o script confere e avisa se não combinar):
#   lista / Sim-Não  -> VALOR_ID (o id do valor na lista do ML). VALOR_NOME pode ser o nome do valor da lista
#                       no lugar do id; se ele for diferente do nome oficial, o ML trata como valor personalizado.
#   texto / número   -> VALOR_NOME (ex.: "Modelo X1")
#   número + unidade -> VALOR_NOME como um texto só (ex.: "6 cm")
VALOR_ID = None
VALOR_NOME = "Pulverizadores"

RELER_APOS_SEGUNDOS = 60  # só em "enviar" e "desfazer": relê o item de novo depois de N segundos (0 = não relê)
ARQUIVO_ANTES = None      # só em "desfazer": caminho (ou nome dentro de saidas_teste_envio) do *_antes.json. None = o mais recente deste MLB
DESFAZER_SOMENTE_ATRIBUTO = False  # só em "desfazer": True = só o ATRIBUTO_ID acima; False = tudo que estiver diferente do "antes"
# ========================================

NOME_LOG = "testar_envio_atributo_item"
PASTA_LOGS = Path(__file__).resolve().parent / "logs"
PASTA_SAIDA = Path(__file__).resolve().parent / "saidas_teste_envio"

MLB_LIMPO = MLB.strip().upper()
ATRIBUTO = ATRIBUTO_ID.strip()
CARIMBO = datetime.now().strftime("%Y%m%d_%H%M%S")

TAGS_INALTERAVEIS = ("read_only", "fixed", "inferred")
HIERARQUIAS_DE_IDENTIDADE = ("PARENT_PK", "CHILD_PK", "PRODUCT_IDENTIFIER")


class Abortar(Exception):
    """Interrompe o script com uma mensagem clara. Nada foi enviado ao ML."""


# ─── UTILITÁRIOS ──────────────────────────────────────────

def titulo(texto):
    print()
    print("=" * 78)
    print(texto)
    print("=" * 78)


def salvar_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    return caminho


def caminho_saida(sufixo):
    return PASTA_SAIDA / f"{MLB_LIMPO}_{CARIMBO}_{sufixo}.json"


def chamar(metodo, endpoint, **kwargs):
    return chamar_api(metodo, endpoint, pasta_logs=PASTA_LOGS, conta=CONTA, nome_log=NOME_LOG, **kwargs)


def tem_tag(tags, nome):
    # /categories/{id}/attributes devolve tags como dict ({"required": true});
    # outros recursos devolvem como lista (["required"]). Aceita os dois.
    if isinstance(tags, dict):
        return bool(tags.get(nome))
    if isinstance(tags, (list, tuple)):
        return nome in tags
    return False


def validar_configuracao():
    if MODO not in ("simular", "enviar", "desfazer"):
        raise Abortar('MODO deve ser "simular", "enviar" ou "desfazer".')
    if not MLB_LIMPO.startswith("MLB") or len(MLB_LIMPO) < 8:
        raise Abortar("Configure o MLB no topo do script (ex.: MLB1234567890).")
    if CONTA not in ("MB", "SV"):
        raise Abortar('CONTA deve ser "MB" ou "SV".')
    if MODO in ("simular", "enviar"):
        if not ATRIBUTO:
            raise Abortar("Configure o ATRIBUTO_ID no topo do script (o \"ID na API\" do card).")
        if VALOR_ID is None and VALOR_NOME is None:
            raise Abortar("Configure VALOR_ID e/ou VALOR_NOME no topo do script.")
    if MODO == "desfazer" and DESFAZER_SOMENTE_ATRIBUTO and not ATRIBUTO:
        raise Abortar("DESFAZER_SOMENTE_ATRIBUTO=True exige ATRIBUTO_ID configurado.")


def confirmar(aviso):
    print()
    print(aviso)
    try:
        digitado = input(f"Para CONFIRMAR, digite o MLB ({MLB_LIMPO}) e aperte Enter (qualquer outra coisa cancela): ")
    except EOFError:
        digitado = ""
    if digitado.strip().upper() != MLB_LIMPO:
        raise Abortar("Envio cancelado: nada foi enviado ao Mercado Livre.")


def aguardar_com_contagem(segundos):
    print(f"Aguardando {segundos}s antes de reler o item...")
    restante = segundos
    while restante > 0:
        passo = min(10, restante)
        time.sleep(passo)
        restante -= passo
        print(f"  ... faltam {restante}s")


# ─── LEITURAS (GET) ───────────────────────────────────────

def ler_item(rotulo):
    print(f"Lendo o item {MLB_LIMPO} ({rotulo})...")
    resposta = chamar("GET", f"/items/{MLB_LIMPO}", params={"include_internal_attributes": "true"})
    return resposta.json()


def ler_atributos_da_categoria(category_id):
    print(f"Lendo os atributos da categoria {category_id}...")
    resposta = chamar("GET", f"/categories/{category_id}/attributes")
    return {a["id"]: a for a in resposta.json() if a.get("id")}


def ler_hierarquias(category_id):
    # Informativo: technical_specs/input traz "hierarchy" (PARENT_PK, CHILD_PK,
    # PRODUCT_IDENTIFIER...) por atributo. Se falhar, só avisa e segue.
    try:
        resposta = chamar("GET", f"/categories/{category_id}/technical_specs/input", max_tentativas=1)
    except ErroAPI as erro:
        print(f"  (não consegui consultar a hierarquia dos atributos: {erro})")
        return {}
    hierarquias = {}
    for grupo in resposta.json().get("groups", []):
        for componente in grupo.get("components", []):
            for atributo in componente.get("attributes", []):
                if atributo.get("id") and atributo.get("hierarchy"):
                    hierarquias[atributo["id"]] = atributo["hierarchy"]
    return hierarquias


# ─── VALORES E COMPARAÇÃO ─────────────────────────────────

def indexar(item):
    return {a["id"]: a for a in item.get("attributes", []) if a.get("id")}


def valor_efetivo(atributo):
    # Atributo ausente e atributo presente com value_id e value_name nulos
    # são a mesma coisa pra comparação: "sem valor".
    if atributo is None:
        return None
    valor_id, valor_nome = atributo.get("value_id"), atributo.get("value_name")
    if valor_id is None and valor_nome is None:
        return None
    return (valor_id, valor_nome)


def formatar_valor(atributo):
    efetivo = valor_efetivo(atributo)
    if efetivo is None:
        return "(sem valor)"
    valor_id, valor_nome = efetivo
    if valor_id == "-1":
        return "N/A (não se aplica)"
    if valor_id is None:
        return repr(valor_nome)
    return f"{valor_nome!r} (value_id {valor_id})"


def comparar(antes, depois):
    ind_antes, ind_depois = indexar(antes), indexar(depois)
    resultado = {"mudaram": [], "sumiram": [], "apareceram": []}
    for attr_id in sorted(set(ind_antes) | set(ind_depois)):
        v_antes, v_depois = valor_efetivo(ind_antes.get(attr_id)), valor_efetivo(ind_depois.get(attr_id))
        if v_antes == v_depois:
            continue
        registro = {
            "id": attr_id,
            "antes": formatar_valor(ind_antes.get(attr_id)),
            "depois": formatar_valor(ind_depois.get(attr_id)),
        }
        if v_antes is not None and v_depois is None:
            resultado["sumiram"].append(registro)
        elif v_antes is None and v_depois is not None:
            resultado["apareceram"].append(registro)
        else:
            resultado["mudaram"].append(registro)
    return resultado


def imprimir_comparacao(comparacao):
    if not any(comparacao.values()):
        print("  Nenhuma diferença entre as duas leituras.")
        return
    rotulos = (
        ("mudaram", "MUDARAM"),
        ("sumiram", "SUMIRAM (tinham valor antes e não têm mais)"),
        ("apareceram", "APARECERAM (não tinham valor antes)"),
    )
    for chave, rotulo in rotulos:
        for e in comparacao[chave]:
            print(f"  {rotulo}: {e['id']}: {e['antes']}  ->  {e['depois']}")


def atributo_para_reenvio(atributo):
    # Reenvia o valor exatamente como o GET devolveu (id e nome quando os dois
    # existiam, pra não perder um nome personalizado nem depender do ML
    # resolver o nome a partir do id). N/A mantém o formato oficial
    # (value_id "-1" + value_name nulo).
    valor_id, valor_nome = atributo.get("value_id"), atributo.get("value_name")
    if valor_id == "-1":
        return {"id": atributo["id"], "value_id": "-1", "value_name": None}
    if valor_id is not None and valor_nome is not None:
        return {"id": atributo["id"], "value_id": valor_id, "value_name": valor_nome}
    if valor_id is not None:
        return {"id": atributo["id"], "value_id": valor_id}
    return {"id": atributo["id"], "value_name": valor_nome}


def atributo_para_remocao(attr_id):
    # Forma oficial de remover: value_id e value_name nulos (não vale pra obrigatório).
    return {"id": attr_id, "value_id": None, "value_name": None}


# ─── CONFERÊNCIA DO ATRIBUTO ──────────────────────────────

def listar_valores(valores, limite=15):
    itens = [f"{v.get('id')} = {v.get('name')}" for v in valores[:limite]]
    sufixo = f" ... (+{len(valores) - limite})" if len(valores) > limite else ""
    return "; ".join(itens) + sufixo


def validar_atributo(meta, hierarquias):
    """Confere o ATRIBUTO/VALOR configurados contra a definição da categoria.
    Devolve (atributo_para_enviar, erros, avisos)."""
    erros, avisos = [], []
    if meta is None:
        return None, [f"O atributo {ATRIBUTO} não existe na categoria deste anúncio."], avisos

    tags = meta.get("tags")
    for tag in TAGS_INALTERAVEIS:
        if tem_tag(tags, tag):
            erros.append(f"O atributo tem a tag '{tag}': o Mercado Livre não deixa o vendedor alterar.")
    if ATRIBUTO.upper().startswith("SELLER_PACKAGE_"):
        erros.append("Dimensões do pacote precisam ir as 4 juntas (altura, comprimento, largura e peso, "
                     "só inteiros, em cm e g). Este script não envia esse grupo.")
    if tem_tag(tags, "required"):
        avisos.append("Atributo OBRIGATÓRIO (tag required): pode ser alterado, mas nunca removido, e não aceita N/A.")
    if tem_tag(tags, "conditional_required"):
        avisos.append("Atributo obrigatório sob condição (conditional_required).")
    for tag in ("allow_variations", "variation_attribute", "defines_picture"):
        if tem_tag(tags, tag):
            avisos.append(f"Atributo com tag '{tag}': ligado a variações do anúncio.")
    hierarquia = hierarquias.get(ATRIBUTO)
    if hierarquia in HIERARQUIAS_DE_IDENTIDADE:
        avisos.append(f"Hierarquia {hierarquia}: ajuda a identificar o produto/família (User Product). "
                      "Evite no primeiro teste.")

    tipo = meta.get("value_type")
    atributo = {"id": ATRIBUTO}

    if tipo in ("list", "boolean"):
        valores = meta.get("values") or []
        nomes_por_id = {str(v.get("id")): v.get("name") for v in valores}
        valor_id = None if VALOR_ID is None else str(VALOR_ID)
        if valor_id is None and VALOR_NOME is not None:
            achados = [vid for vid, nome in nomes_por_id.items()
                       if nome and nome.strip().lower() == str(VALOR_NOME).strip().lower()]
            if len(achados) == 1:
                valor_id = achados[0]
                avisos.append(f"VALOR_ID resolvido pelo nome: {valor_id}.")
        if valor_id is None:
            erros.append(f"Atributo do tipo '{tipo}': informe VALOR_ID (ou um VALOR_NOME igual ao nome de um valor "
                         f"da lista). Valores aceitos: {listar_valores(valores)}")
        elif valor_id not in nomes_por_id:
            erros.append(f"VALOR_ID {valor_id} não está na lista do ML. Valores aceitos: {listar_valores(valores)}")
        else:
            atributo["value_id"] = valor_id
            nome_oficial = nomes_por_id[valor_id]
            if (tipo == "list" and VALOR_NOME is not None and nome_oficial
                    and str(VALOR_NOME).strip().lower() != nome_oficial.strip().lower()):
                atributo["value_name"] = str(VALOR_NOME).strip()
                avisos.append(f"VALOR_NOME difere do nome da lista ({nome_oficial!r}): o ML tratará como "
                              "valor PERSONALIZADO.")
    elif tipo in ("string", "number", "number_unit"):
        if VALOR_NOME is None:
            erros.append(f"Atributo do tipo '{tipo}': informe VALOR_NOME.")
        else:
            texto = str(VALOR_NOME).strip()
            limite = meta.get("value_max_length")
            if limite and len(texto) > int(limite):
                erros.append(f"VALOR_NOME tem {len(texto)} caracteres; o máximo é {limite}.")
            if tipo == "number" and not re.fullmatch(r"-?\d+(?:[.,]\d+)?", texto):
                erros.append("Atributo numérico: VALOR_NOME deve ser só número (ex.: 4 ou 4.5).")
            if tipo == "number_unit":
                casou = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*([^\d\s.,-].*)", texto)
                if not casou:
                    erros.append("Número com unidade: VALOR_NOME deve ser número + unidade num texto só (ex.: \"6 cm\").")
                else:
                    unidade = casou.group(2).strip().lower()
                    unidades = meta.get("allowed_units") or []
                    aceitas = {str(u.get("id")).lower() for u in unidades} | {str(u.get("name")).lower() for u in unidades}
                    if unidades and unidade not in aceitas:
                        erros.append(f"Unidade '{casou.group(2).strip()}' não permitida. Aceitas: "
                                     f"{', '.join(str(u.get('id')) for u in unidades)}")
            atributo["value_name"] = texto
            if VALOR_ID is not None:
                atributo["value_id"] = str(VALOR_ID)
                avisos.append("VALOR_ID enviado junto com o texto (só faz sentido se for um valor sugerido pelo ML).")
    else:
        avisos.append(f"Tipo '{tipo}' não previsto neste script: o corpo vai como você informou.")
        if VALOR_ID is not None:
            atributo["value_id"] = str(VALOR_ID)
        if VALOR_NOME is not None:
            atributo["value_name"] = str(VALOR_NOME)

    if erros:
        return None, erros, avisos
    return atributo, erros, avisos


def problemas_do_item(item):
    """Problemas de nível de anúncio. Devolve (erros, avisos)."""
    erros, avisos = [], []
    if item.get("catalog_listing"):
        erros.append("Anúncio de catálogo (catalog_listing=True): os atributos são herdados do produto de "
                     "catálogo. Escolha outro MLB.")
    if item.get("status") not in ("active", "paused"):
        avisos.append(f"Status do item: {item.get('status')} (o sistema só trabalha com ativos e pausados).")
    if item.get("family_name") or item.get("user_product_id") or item.get("family_id"):
        avisos.append("Item no modelo User Products (family_name/user_product_id/family_id preenchidos): a doc diz que o PUT "
                      "em /items que muda atributos é REPLICADO de forma assíncrona para todos os itens do mesmo "
                      "User Product. Outros MLBs do mesmo produto podem mudar também.")
    if item.get("variations"):
        avisos.append(f"O item tem {len(item['variations'])} variação(ões).")
    return erros, avisos


def mostrar_resumo_item(item):
    print(f"  Título:           {item.get('title')}")
    print(f"  Status:           {item.get('status')} {item.get('sub_status') or ''}")
    print(f"  Categoria:        {item.get('category_id')}")
    print(f"  seller_id:        {item.get('seller_id')}")
    print(f"  Vendas:           {item.get('sold_quantity')}")
    print(f"  catalog_listing:  {item.get('catalog_listing')} (catalog_product_id: {item.get('catalog_product_id')})")
    print(f"  user_product_id:  {item.get('user_product_id')}")
    print(f"  family_name:      {item.get('family_name')}")
    print(f"  family_id:        {item.get('family_id')}")
    print(f"  Variações:        {len(item.get('variations') or [])}")
    print(f"  Atributos lidos:  {len(item.get('attributes') or [])}")
    print(f"  Tags do item:     {', '.join(item.get('tags') or [])}")


def resumo_item_para_relatorio(item):
    return {
        "id": item.get("id"), "title": item.get("title"), "status": item.get("status"),
        "sub_status": item.get("sub_status"), "category_id": item.get("category_id"),
        "seller_id": item.get("seller_id"), "sold_quantity": item.get("sold_quantity"),
        "catalog_listing": item.get("catalog_listing"), "catalog_product_id": item.get("catalog_product_id"),
        "user_product_id": item.get("user_product_id"), "family_name": item.get("family_name"),
        "family_id": item.get("family_id"),
        "total_variacoes": len(item.get("variations") or []),
        "total_atributos": len(item.get("attributes") or []),
        "last_updated": item.get("last_updated"), "tags": item.get("tags"),
    }


# ─── ENVIO (PUT) ──────────────────────────────────────────

def executar_put(atributos_envio):
    """Faz 1 único PUT, sem retentativa. Nunca levanta erro da API: devolve o
    registro cru (status e corpo, ou o texto do erro) pra ir pro relatório."""
    corpo = {"attributes": atributos_envio}
    registro = {"momento": datetime.now().isoformat(timespec="seconds"), "corpo_enviado": corpo}
    try:
        resposta = chamar("PUT", f"/items/{MLB_LIMPO}", json_body=corpo, max_tentativas=1)
    except ErroAutenticacaoAPI as erro:
        registro["erro"] = f"ErroAutenticacaoAPI: {erro}"
    except ErroAPI as erro:
        registro["erro"] = f"ErroAPI: {erro}"
    else:
        registro["status_http"] = resposta.status_code
        try:
            registro["resposta"] = resposta.json()
        except ValueError:
            registro["resposta"] = resposta.text
    return registro


def mostrar_resultado_put(registro):
    if "erro" in registro:
        print("  O PUT FALHOU. Resposta crua do Mercado Livre (como o transporte devolveu):")
        print(f"  {registro['erro']}")
        return
    print(f"  Status HTTP do PUT: {registro.get('status_http')}")
    resposta = registro.get("resposta")
    if not isinstance(resposta, dict):
        print(f"  Corpo da resposta (não é JSON): {resposta!r}")
        return
    print(f"  Chaves da resposta: {', '.join(sorted(resposta.keys()))}")
    print(f"  Atributos na resposta: {len(resposta.get('attributes') or [])}")
    print(f"  last_updated: {resposta.get('last_updated')}")
    for chave in ("warnings", "cause"):
        if resposta.get(chave):
            print(f"  {chave.upper()} devolvidos pelo ML:")
            print(json.dumps(resposta[chave], ensure_ascii=False, indent=2))


def interpretar_envio(comparacao, atributo_id, put_falhou=False):
    alvo = [e for chave in comparacao for e in comparacao[chave] if e["id"] == atributo_id]
    sumiram_outros = [e for e in comparacao["sumiram"] if e["id"] != atributo_id]
    mudaram_outros = [e for e in comparacao["mudaram"] + comparacao["apareceram"] if e["id"] != atributo_id]
    print()
    if put_falhou and not any(comparacao.values()):
        print("  >>> O PUT foi recusado e o anúncio não mudou (esperado). Veja o erro cru do ML acima.")
        return
    if put_falhou:
        print("  >>> ATENÇÃO: o PUT deu erro, mas o anúncio mudou entre as leituras (confira a lista acima).")
        return
    if sumiram_outros:
        print("  >>> ATENÇÃO: atributos que você NÃO enviou perderam o valor. Isso indica PUT SUBSTITUTIVO "
              "(ou o ML limpou algo). Use MODO = \"desfazer\" pra restaurar.")
    elif not alvo:
        print("  >>> O campo enviado NÃO mudou na releitura. Pode ser atraso do ML (veja a releitura tardia) "
              "ou o envio ter sido ignorado (veja warnings/cause da resposta).")
    else:
        print("  >>> O campo enviado mudou e nenhum outro atributo perdeu o valor: o PUT parece PARCIAL.")
    if mudaram_outros:
        print("  >>> Outros atributos também mudaram sem você enviar (confira a lista acima).")


def reler_e_comparar(rotulo, item_referencia, sufixo_arquivo):
    item = ler_item(rotulo)
    caminho = salvar_json(caminho_saida(sufixo_arquivo), item)
    print(f"  Leitura completa salva em: {caminho}")
    comparacao = comparar(item_referencia, item)
    imprimir_comparacao(comparacao)
    return item, comparacao


# ─── FLUXO: SIMULAR / ENVIAR ──────────────────────────────

def fluxo_simular_ou_enviar():
    relatorio = {
        "modo": MODO, "mlb": MLB_LIMPO, "conta": CONTA, "atributo_id": ATRIBUTO,
        "valor_id": VALOR_ID, "valor_nome": VALOR_NOME, "carimbo": CARIMBO,
    }
    caminho_relatorio = caminho_saida("relatorio")

    titulo(f"1) Leitura do item {MLB_LIMPO} (o \"antes\")")
    antes = ler_item("antes")
    caminho_antes = salvar_json(caminho_saida("antes"), antes)
    mostrar_resumo_item(antes)
    print(f"  Valor atual de {ATRIBUTO}: {formatar_valor(indexar(antes).get(ATRIBUTO))}")
    print(f"  Leitura completa salva em: {caminho_antes}")
    relatorio["item_antes"] = resumo_item_para_relatorio(antes)
    relatorio["arquivo_antes"] = str(caminho_antes)

    titulo("2) Conferência do atributo na categoria")
    categoria_id = antes.get("category_id")
    meta_categoria = ler_atributos_da_categoria(categoria_id)
    hierarquias = ler_hierarquias(categoria_id)
    atributo_envio, erros, avisos = validar_atributo(meta_categoria.get(ATRIBUTO), hierarquias)
    erros_item, avisos_item = problemas_do_item(antes)
    erros, avisos = erros + erros_item, avisos + avisos_item
    for aviso in avisos:
        print(f"  AVISO: {aviso}")
    for erro in erros:
        print(f"  ERRO:  {erro}")
    relatorio["avisos"], relatorio["erros_de_conferencia"] = avisos, erros
    if erros:
        salvar_json(caminho_relatorio, relatorio)
        raise Abortar("O envio foi recusado na conferência (veja os ERROS acima). Nada foi enviado.")
    print("  Conferência OK.")

    titulo("3) Corpo que seria enviado (PUT /items/" + MLB_LIMPO + ")")
    corpo = {"attributes": [atributo_envio]}
    print(json.dumps(corpo, ensure_ascii=False, indent=2))
    relatorio["corpo_a_enviar"] = corpo
    if MODO == "simular":
        salvar_json(caminho_relatorio, relatorio)
        print()
        print('MODO "simular": nada foi enviado ao Mercado Livre.')
        print(f"Relatório salvo em: {caminho_relatorio}")
        print('Pra enviar de verdade, troque MODO para "enviar" e rode de novo.')
        return

    titulo("4) Envio")
    aviso_confirmacao = (f"ATENÇÃO: isto vai ALTERAR o anúncio real {MLB_LIMPO} na conta {CONTA} "
                         f"(atributo {ATRIBUTO}: {formatar_valor(indexar(antes).get(ATRIBUTO))} -> o corpo acima).")
    if antes.get("family_name") or antes.get("user_product_id") or antes.get("family_id"):
        aviso_confirmacao += " Item de User Product: a mudança pode ser replicada para outros itens do mesmo produto."
    confirmar(aviso_confirmacao)
    registro_put = executar_put([atributo_envio])
    relatorio["put"] = registro_put
    salvar_json(caminho_relatorio, relatorio)  # salva já, antes de reler: se a releitura falhar, o PUT não se perde
    mostrar_resultado_put(registro_put)

    titulo("5) Releitura imediata e comparação (antes x depois)")
    depois, comparacao = reler_e_comparar("depois", antes, "depois")
    relatorio["comparacao_imediata"] = comparacao
    put_falhou = "erro" in registro_put
    interpretar_envio(comparacao, ATRIBUTO, put_falhou)

    if RELER_APOS_SEGUNDOS and RELER_APOS_SEGUNDOS > 0 and not put_falhou:
        titulo(f"6) Releitura tardia ({RELER_APOS_SEGUNDOS}s depois) e comparação (antes x tardia)")
        aguardar_com_contagem(RELER_APOS_SEGUNDOS)
        _, comparacao_tardia = reler_e_comparar("tardia", antes, "depois_tardio")
        relatorio["comparacao_tardia"] = comparacao_tardia
        interpretar_envio(comparacao_tardia, ATRIBUTO)

    salvar_json(caminho_relatorio, relatorio)
    titulo("Fim")
    print(f"Relatório salvo em: {caminho_relatorio}")
    print("Suba na conversa: o *_relatorio.json, o *_antes.json e o *_depois.json "
          "(e o *_depois_tardio.json, se existir).")
    print('Pra devolver o anúncio ao que era: MODO = "desfazer" (ele usa o *_antes.json mais recente deste MLB).')


# ─── FLUXO: DESFAZER ──────────────────────────────────────

def localizar_arquivo_antes():
    if ARQUIVO_ANTES:
        candidato = Path(ARQUIVO_ANTES)
        if not candidato.exists():
            candidato = PASTA_SAIDA / ARQUIVO_ANTES
        if not candidato.exists():
            raise Abortar(f"Arquivo ARQUIVO_ANTES não encontrado: {ARQUIVO_ANTES}")
        return candidato
    candidatos = sorted(PASTA_SAIDA.glob(f"{MLB_LIMPO}_*_antes.json"))
    if not candidatos:
        raise Abortar(f"Nenhum arquivo {MLB_LIMPO}_*_antes.json encontrado em {PASTA_SAIDA}. "
                      "Sem o \"antes\" não há o que desfazer.")
    return candidatos[-1]


def montar_envios_de_desfazer(antes, comparacao, meta_categoria):
    ind_antes = indexar(antes)
    envios, ignorados = [], []

    def inalteravel(attr_id):
        meta = meta_categoria.get(attr_id)
        if meta is None:
            return "não existe mais na categoria"
        for tag in TAGS_INALTERAVEIS:
            if tem_tag(meta.get("tags"), tag):
                return f"tag {tag}"
        return None

    for e in comparacao["mudaram"] + comparacao["sumiram"]:
        attr_id = e["id"]
        if DESFAZER_SOMENTE_ATRIBUTO and attr_id != ATRIBUTO:
            continue
        motivo = inalteravel(attr_id)
        if motivo:
            ignorados.append({"id": attr_id, "motivo": motivo})
            continue
        envios.append(atributo_para_reenvio(ind_antes[attr_id]))

    for e in comparacao["apareceram"]:
        attr_id = e["id"]
        if DESFAZER_SOMENTE_ATRIBUTO and attr_id != ATRIBUTO:
            continue
        motivo = inalteravel(attr_id)
        if motivo:
            ignorados.append({"id": attr_id, "motivo": motivo})
            continue
        if tem_tag((meta_categoria.get(attr_id) or {}).get("tags"), "required"):
            ignorados.append({"id": attr_id, "motivo": "obrigatório: o ML não deixa remover"})
            continue
        envios.append(atributo_para_remocao(attr_id))
    return envios, ignorados


def fluxo_desfazer():
    relatorio = {"modo": MODO, "mlb": MLB_LIMPO, "conta": CONTA, "carimbo": CARIMBO,
                 "somente_atributo": ATRIBUTO if DESFAZER_SOMENTE_ATRIBUTO else None}
    caminho_relatorio = caminho_saida("relatorio_desfazer")

    titulo("1) Arquivo de referência (o \"antes\")")
    caminho_antes = localizar_arquivo_antes()
    print(f"  Usando: {caminho_antes}")
    with open(caminho_antes, "r", encoding="utf-8") as f:
        antes = json.load(f)
    if str(antes.get("id", "")).upper() != MLB_LIMPO:
        raise Abortar(f"O arquivo é do item {antes.get('id')}, não de {MLB_LIMPO}.")
    relatorio["arquivo_antes"] = str(caminho_antes)

    titulo(f"2) Leitura do estado atual de {MLB_LIMPO}")
    atual = ler_item("atual")
    caminho_atual = salvar_json(caminho_saida("antes_do_desfazer"), atual)
    print(f"  Leitura completa salva em: {caminho_atual}")
    comparacao = comparar(antes, atual)
    print("  Diferenças entre o \"antes\" salvo e o estado atual:")
    imprimir_comparacao(comparacao)
    relatorio["diferencas_antes_x_atual"] = comparacao

    titulo("3) O que seria reenviado para voltar ao \"antes\"")
    meta_categoria = ler_atributos_da_categoria(atual.get("category_id"))
    envios, ignorados = montar_envios_de_desfazer(antes, comparacao, meta_categoria)
    for item_ignorado in ignorados:
        print(f"  IGNORADO: {item_ignorado['id']} ({item_ignorado['motivo']}) - não dá pra reenviar.")
    relatorio["ignorados"] = ignorados
    if not envios:
        salvar_json(caminho_relatorio, relatorio)
        print("  Nada a desfazer: o item já está igual ao \"antes\" (ou só há itens ignorados).")
        return
    corpo = {"attributes": envios}
    print(json.dumps(corpo, ensure_ascii=False, indent=2))
    relatorio["corpo_a_enviar"] = corpo

    titulo("4) Envio do desfazer")
    confirmar(f"ATENÇÃO: isto vai ALTERAR o anúncio real {MLB_LIMPO} na conta {CONTA}, "
              f"reenviando {len(envios)} atributo(s) para voltar ao \"antes\".")
    registro_put = executar_put(envios)
    relatorio["put"] = registro_put
    salvar_json(caminho_relatorio, relatorio)
    mostrar_resultado_put(registro_put)

    titulo("5) Releitura imediata (o \"antes\" salvo x agora)")
    _, comparacao_pos = reler_e_comparar("depois do desfazer", antes, "depois_do_desfazer")
    relatorio["comparacao_imediata"] = comparacao_pos

    if RELER_APOS_SEGUNDOS and RELER_APOS_SEGUNDOS > 0:
        titulo(f"6) Releitura tardia ({RELER_APOS_SEGUNDOS}s depois)")
        aguardar_com_contagem(RELER_APOS_SEGUNDOS)
        _, comparacao_tardia = reler_e_comparar("tardia", antes, "depois_do_desfazer_tardio")
        relatorio["comparacao_tardia"] = comparacao_tardia

    salvar_json(caminho_relatorio, relatorio)
    titulo("Fim")
    print(f"Relatório salvo em: {caminho_relatorio}")


def main():
    try:
        validar_configuracao()
        print(f"MODO: {MODO} | MLB: {MLB_LIMPO} | CONTA: {CONTA}")
        if MODO == "desfazer":
            fluxo_desfazer()
        else:
            fluxo_simular_ou_enviar()
    except Abortar as motivo:
        print(f"\nINTERROMPIDO: {motivo}")
    except ErroAutenticacaoAPI as erro:
        print(f"\nERRO DE AUTENTICAÇÃO (401): {erro}")
    except ErroAPI as erro:
        print(f"\nERRO DA API: {erro}")


if __name__ == "__main__":
    main()
