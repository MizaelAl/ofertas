#!/usr/bin/env python3
"""Busca os mais vendidos da Shopee e do Mercado Livre e grava docs/offers.json.

Uso:
  python scripts/fetch_offers.py              -> busca diária
  python scripts/fetch_offers.py --ml-setup CODIGO
                                              -> troca o código de autorização do
                                                 Mercado Livre pelo primeiro token

Variáveis de ambiente (vêm dos Secrets do GitHub):
  SHOPEE_APP_ID, SHOPEE_SECRET
  ML_CLIENT_ID, ML_CLIENT_SECRET, ML_REFRESH_TOKEN, ML_REDIRECT_URI
  GH_PAT, GITHUB_REPOSITORY  (para salvar o novo token do ML a cada execução)
"""
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "offers.json")
CONFIG = os.path.join(ROOT, "config.json")

SHOPEE_URL = "https://open-api.affiliate.shopee.com.br/graphql"
ML_API = "https://api.mercadolibre.com"
BRT = timezone(timedelta(hours=-3))


# ----------------------------------------------------------------- utilidades
def http(method, url, headers=None, body=None, timeout=30):
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else body.encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    req.add_header("User-Agent", "ofertas-afiliado/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:500]}


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pct(v):
    """Shopee devolve taxa como '0.12' (12%). Normaliza para porcentagem."""
    f = to_float(v)
    if f is None:
        return None
    return round(f * 100, 1) if f <= 1 else round(f, 1)


# --------------------------------------------------------------------- Shopee
SHOPEE_QUERY = """query Ofertas($keyword: String, $sortType: Int, $page: Int, $limit: Int) {
  productOfferV2(keyword: $keyword, sortType: $sortType, page: $page, limit: $limit) {
    nodes {
      itemId productName imageUrl shopName
      priceMin priceMax priceDiscountRate
      commissionRate commission sales ratingStar
      productLink offerLink
    }
    pageInfo { page limit hasNextPage }
  }
}"""


def shopee_signature(app_id, secret, timestamp, payload):
    raw = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def shopee_request(app_id, secret, variables):
    payload = json.dumps({"query": SHOPEE_QUERY, "variables": variables},
                         separators=(",", ":"), ensure_ascii=False)
    ts = int(time.time())
    sig = shopee_signature(app_id, secret, ts, payload)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={sig}",
    }
    status, data = http("POST", SHOPEE_URL, headers, payload)
    if status != 200 or data.get("errors"):
        raise RuntimeError(f"Shopee HTTP {status}: {json.dumps(data.get('errors', data))[:400]}")
    return data["data"]["productOfferV2"]["nodes"] or []


def normalize_shopee(n, keyword):
    price = to_float(n.get("priceMin"))
    discount = n.get("priceDiscountRate") or 0
    old = round(price / (1 - discount / 100), 2) if price and 0 < discount < 95 else None
    return {
        "id": f"shopee-{n.get('itemId')}",
        "source": "shopee",
        "title": (n.get("productName") or "").strip(),
        "price": price,
        "old_price": old,
        "discount": discount or None,
        "commission_rate": pct(n.get("commissionRate")),
        "commission_value": to_float(n.get("commission")),
        "sales": n.get("sales"),
        "rating": to_float(n.get("ratingStar")),
        "image": n.get("imageUrl"),
        "link": n.get("offerLink"),          # link de afiliado, já rastreado
        "product_url": n.get("productLink"),
        "category": keyword or "Mais vendidos",
        "shop": n.get("shopName"),
    }


def fetch_shopee(cfg):
    app_id, secret = os.environ.get("SHOPEE_APP_ID"), os.environ.get("SHOPEE_SECRET")
    if not app_id or not secret:
        raise RuntimeError("Faltam os secrets SHOPEE_APP_ID / SHOPEE_SECRET")
    seen, out = set(), []
    for kw in cfg.get("palavras_chave", [""]):
        variables = {"sortType": cfg.get("sortType", 2), "page": 1,
                     "limit": cfg.get("por_busca", 30)}
        if kw:
            variables["keyword"] = kw
        for n in shopee_request(app_id, secret, variables):
            o = normalize_shopee(n, kw)
            if o["id"] in seen or not o["link"]:
                continue
            if (o["commission_rate"] or 0) < cfg.get("comissao_minima_pct", 0):
                continue
            seen.add(o["id"])
            out.append(o)
        time.sleep(1)
    return out


# -------------------------------------------------------------- Mercado Livre
def ml_token_request(params):
    body = urllib.parse.urlencode(params)
    status, data = http("POST", f"{ML_API}/oauth/token",
                        {"Content-Type": "application/x-www-form-urlencoded",
                         "Accept": "application/json"}, body)
    if status != 200 or "access_token" not in data:
        raise RuntimeError(f"Token do Mercado Livre falhou (HTTP {status}): {data}")
    return data


def save_github_secret(name, value):
    """Grava um Secret no repositório (o refresh_token do ML muda a cada uso)."""
    pat, repo = os.environ.get("GH_PAT"), os.environ.get("GITHUB_REPOSITORY")
    if not pat or not repo:
        print(f"AVISO: sem GH_PAT; não deu para salvar {name}. Novo valor não persistido.")
        return False
    from nacl import encoding, public  # instalado no workflow

    h = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    status, key = http("GET", f"https://api.github.com/repos/{repo}/actions/secrets/public-key", h)
    if status != 200:
        raise RuntimeError(f"GitHub public-key HTTP {status}: {key}")
    pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(value.encode())
    body = json.dumps({"encrypted_value": base64.b64encode(sealed).decode(),
                       "key_id": key["key_id"]})
    status, resp = http("PUT", f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
                        dict(h, **{"Content-Type": "application/json"}), body)
    if status not in (201, 204):
        raise RuntimeError(f"Salvar secret {name} HTTP {status}: {resp}")
    return True


def ml_access_token():
    cid, csec = os.environ.get("ML_CLIENT_ID"), os.environ.get("ML_CLIENT_SECRET")
    refresh = os.environ.get("ML_REFRESH_TOKEN")
    if not (cid and csec and refresh):
        raise RuntimeError("Faltam ML_CLIENT_ID / ML_CLIENT_SECRET / ML_REFRESH_TOKEN "
                           "(rode o workflow 'Configurar Mercado Livre')")
    data = ml_token_request({"grant_type": "refresh_token", "client_id": cid,
                             "client_secret": csec, "refresh_token": refresh})
    if data.get("refresh_token") and data["refresh_token"] != refresh:
        save_github_secret("ML_REFRESH_TOKEN", data["refresh_token"])
    return data["access_token"]


def ml_get(path, token):
    status, data = http("GET", f"{ML_API}{path}", {"Authorization": f"Bearer {token}"})
    time.sleep(0.15)
    return status, data


def first_picture(d):
    pics = d.get("pictures") or []
    if pics:
        p = pics[0]
        return p.get("secure_url") or p.get("url")
    return d.get("secure_thumbnail") or d.get("thumbnail")


def ml_offer_from_item(d, category):
    price, old = to_float(d.get("price")), to_float(d.get("original_price"))
    return {
        "id": f"ml-{d.get('id')}", "source": "ml",
        "title": d.get("title", "").strip(), "price": price,
        "old_price": old if old and price and old > price else None,
        "discount": round((1 - price / old) * 100) if old and price and old > price else None,
        "commission_rate": None, "commission_value": None, "sales": None, "rating": None,
        "image": first_picture(d), "link": None, "product_url": d.get("permalink"),
        "category": category, "shop": None,
    }


def ml_offer_from_product(d, category):
    bb = d.get("buy_box_winner") or {}
    price, old = to_float(bb.get("price")), to_float(bb.get("original_price"))
    url = d.get("permalink") or f"https://www.mercadolivre.com.br/p/{d.get('id')}"
    return {
        "id": f"ml-{d.get('id')}", "source": "ml",
        "title": (d.get("name") or "").strip(), "price": price,
        "old_price": old if old and price and old > price else None,
        "discount": round((1 - price / old) * 100) if old and price and old > price else None,
        "commission_rate": None, "commission_value": None, "sales": None, "rating": None,
        "image": first_picture(d), "link": None, "product_url": url,
        "category": category, "shop": None,
    }


def fetch_ml(cfg):
    token = ml_access_token()
    out, seen, warnings = [], set(), []
    for cat_id, cat_name in cfg.get("categorias", {}).items():
        status, data = ml_get(f"/highlights/MLB/category/{cat_id}", token)
        if status != 200:
            warnings.append(f"ML {cat_name}: HTTP {status}")
            continue
        content = sorted(data.get("content", []), key=lambda c: c.get("position", 99))
        count = 0
        for c in content:
            if count >= cfg.get("por_categoria", 10):
                break
            kind, eid = c.get("type"), c.get("id")
            if kind == "PRODUCT":
                s, d = ml_get(f"/products/{eid}", token)
                o = ml_offer_from_product(d, cat_name) if s == 200 else None
            elif kind == "ITEM":
                s, d = ml_get(f"/items/{eid}", token)
                o = ml_offer_from_item(d, cat_name) if s == 200 else None
            else:
                o = None  # USER_PRODUCT: sem página pública estável, ignorado
            if o and o["title"] and o["id"] not in seen:
                o["rank"] = c.get("position")
                seen.add(o["id"])
                out.append(o)
                count += 1
    return out, warnings


# ------------------------------------------------------------------ principal
def load_previous():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--ml-setup":
        data = ml_token_request({
            "grant_type": "authorization_code",
            "client_id": os.environ["ML_CLIENT_ID"],
            "client_secret": os.environ["ML_CLIENT_SECRET"],
            "code": sys.argv[2].strip(),
            "redirect_uri": os.environ.get("ML_REDIRECT_URI", "https://www.google.com"),
        })
        save_github_secret("ML_REFRESH_TOKEN", data["refresh_token"])
        print("Mercado Livre configurado com sucesso.")
        return

    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    prev = load_previous()
    result = {"updated_at": datetime.now(BRT).isoformat(timespec="minutes"),
              "shopee": prev.get("shopee", []), "ml": prev.get("ml", []), "errors": []}

    if cfg.get("shopee", {}).get("ativo"):
        try:
            result["shopee"] = fetch_shopee(cfg["shopee"])
            print(f"Shopee: {len(result['shopee'])} ofertas")
        except Exception as e:  # mantém a lista anterior se a busca falhar
            result["errors"].append(f"Shopee: {e}")
    if cfg.get("mercadolivre", {}).get("ativo"):
        try:
            result["ml"], warns = fetch_ml(cfg["mercadolivre"])
            result["errors"] += warns
            print(f"Mercado Livre: {len(result['ml'])} ofertas")
        except Exception as e:
            result["errors"].append(f"Mercado Livre: {e}")

    for err in result["errors"]:
        print("ERRO:", err)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    if not result["shopee"] and not result["ml"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
