# dux_api_demo_probe.py
import os
import json
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests


BASE_URL = os.getenv(
    "DUX_BASE_URL",
    "https://erp.duxsoftware.com.ar/WSERP/rest/services"
).rstrip("/")

DUX_TOKEN = os.getenv("DUX_TOKEN", "").strip()

REQUEST_DELAY_SECONDS = float(os.getenv("DUX_REQUEST_DELAY_SECONDS", "5.2"))
TIMEOUT_SECONDS = int(os.getenv("DUX_TIMEOUT_SECONDS", "40"))

# Datos opcionales. El script intenta autodetectar si faltan.
DUX_ID_EMPRESA = os.getenv("DUX_ID_EMPRESA", "").strip()
DUX_ID_SUCURSAL_EMPRESA = os.getenv("DUX_ID_SUCURSAL_EMPRESA", "").strip()
DUX_ID_DEPOSITO = os.getenv("DUX_ID_DEPOSITO", "").strip()
DUX_CODIGO_ITEM = os.getenv("DUX_CODIGO_ITEM", "").strip()
DUX_ID_LISTA_PRECIO = os.getenv("DUX_ID_LISTA_PRECIO", "").strip()

# En demo lo podés poner en 1 para crear pedidos.
CREATE_TEST_PEDIDOS = os.getenv("DUX_CREATE_TEST_PEDIDOS", "0").strip() == "1"

# Seguridad: no incluyo facturación por defecto.
CREATE_TEST_FACTURA = os.getenv("DUX_CREATE_TEST_FACTURA", "0").strip() == "1"

# Para probar precio/descuento
TEST_FINAL_PRICE = os.getenv("DUX_TEST_FINAL_PRICE", "").strip()
TEST_DISCOUNT = os.getenv("DUX_TEST_DISCOUNT", "10").strip()

ARTIFACT_JSON = "dux_demo_probe_results.json"


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def log(title: str, data: Any = None) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    if data is not None:
        if isinstance(data, str):
            print(data)
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            if k.lower() in ["authorization", "token", "x-api-key", "apikey", "api-key"]:
                redacted[k] = "***REDACTED***"
            else:
                redacted[k] = redact(v)
        return redacted
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def make_headers() -> Dict[str, str]:
    if not DUX_TOKEN:
        raise RuntimeError("Falta DUX_TOKEN en secrets/env.")

    # Si devuelve 401/403, probar cambiar por:
    # {"token": DUX_TOKEN, ...}
    # o {"X-API-Key": DUX_TOKEN, ...}
    return {
        "token": "asd09",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def request_dux(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    allow_error: bool = True,
) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    headers = make_headers()

    payload = {
        "method": method,
        "url": url,
        "params": params,
        "body": body,
        "headers": redact(headers),
    }
    log("REQUEST", payload)

    try:
        res = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=body,
            timeout=TIMEOUT_SECONDS,
        )

        try:
            parsed = res.json()
        except Exception:
            parsed = res.text[:5000]

        out = {
            "ok": res.ok,
            "status_code": res.status_code,
            "content_type": res.headers.get("content-type"),
            "response": parsed,
        }

        log("RESPONSE", out)

        if not allow_error and not res.ok:
            raise RuntimeError(f"Error HTTP {res.status_code}: {parsed}")

        return out

    finally:
        time.sleep(REQUEST_DELAY_SECONDS)


def as_list(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if isinstance(data, dict):
        for key in ["data", "result", "results", "items", "content", "rows"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

        # Si vino un objeto único
        return [data]

    return []


def first_obj(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rows = as_list(result.get("response"))
    return rows[0] if rows else None


def pick_field(obj: Dict[str, Any], candidates: List[str]) -> Optional[Any]:
    lower_map = {str(k).lower(): k for k in obj.keys()}
    for c in candidates:
        key = lower_map.get(c.lower())
        if key is not None:
            return obj[key]
    return None


def extract_id(obj: Dict[str, Any], preferred: List[str]) -> Optional[Any]:
    value = pick_field(obj, preferred)
    if value not in [None, ""]:
        return value

    for k, v in obj.items():
        lk = str(k).lower()
        if lk.startswith("id") and v not in [None, ""]:
            return v

    return None


def extract_codigo_item(obj: Dict[str, Any]) -> Optional[str]:
    value = pick_field(obj, [
        "codigoItem",
        "codigo_item",
        "cod_item",
        "codigo",
        "sku",
        "item",
    ])
    return str(value) if value not in [None, ""] else None


def extract_price(obj: Dict[str, Any]) -> Optional[Any]:
    return pick_field(obj, [
        "precio",
        "precioUnitario",
        "precio_unitario",
        "precioVenta",
        "precio_venta",
        "precioFinal",
        "precio_final",
        "precioConIva",
        "precio_con_iva",
    ])


def extract_stock(obj: Dict[str, Any]) -> Optional[Any]:
    return pick_field(obj, [
        "stock",
        "saldoStock",
        "saldo_stock",
        "cantidadStock",
        "cantidad_stock",
        "disponible",
    ])


def get_basic_resources() -> Dict[str, Any]:
    results = {}

    endpoints = {
        "empresas": ("/empresas", None),
        "depositos": ("/deposito", None),
        "listas_precio": ("/listaprecioventa", None),
        "rubros": ("/rubros", {"offset": 0, "limit": 20}),
        "subrubros": ("/subrubros", {"offset": 0, "limit": 20}),
    }

    for name, (path, params) in endpoints.items():
        results[name] = request_dux("GET", path, params=params)

    return results


def autodetect_ids(results: Dict[str, Any]) -> Dict[str, Any]:
    detected = {}

    empresa_id = DUX_ID_EMPRESA
    if not empresa_id:
        empresa = first_obj(results.get("empresas", {}))
        if empresa:
            empresa_id = extract_id(empresa, ["idEmpresa", "id_empresa", "id"])
            detected["empresa_obj"] = empresa

    detected["id_empresa"] = empresa_id

    if empresa_id:
        sucursales = request_dux("GET", "/sucursales", params={"idEmpresa": empresa_id})
        detected["sucursales_result"] = sucursales

        suc = first_obj(sucursales)
        sucursal_id = DUX_ID_SUCURSAL_EMPRESA
        if not sucursal_id and suc:
            sucursal_id = extract_id(suc, ["idSucursal", "id_sucursal", "idSucursalEmpresa", "id_sucursal_empresa", "id"])

        detected["id_sucursal_empresa"] = sucursal_id

    deposito_id = DUX_ID_DEPOSITO
    if not deposito_id:
        dep = first_obj(results.get("depositos", {}))
        if dep:
            deposito_id = extract_id(dep, ["idDeposito", "id_deposito", "id"])
            detected["deposito_obj"] = dep

    detected["id_deposito"] = deposito_id

    lista_id = DUX_ID_LISTA_PRECIO
    listas = as_list(results.get("listas_precio", {}).get("response"))
    if not lista_id and listas:
        lista_id = extract_id(listas[0], ["idListaPrecio", "id_lista_precio", "idListaPrecioVenta", "id"])
        detected["lista_precio_obj"] = listas[0]

    detected["id_lista_precio"] = lista_id

    return detected


def get_items(
    id_lista: Optional[Any] = None,
    id_deposito: Optional[Any] = None,
    codigo_item: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "offset": 0,
        "limit": limit,
        "habilitado": "SI",
    }

    if id_lista:
        params["idListaPrecio"] = id_lista

    if id_deposito:
        params["idDeposito"] = id_deposito

    if codigo_item:
        params["codigoItem"] = codigo_item

    return request_dux("GET", "/items", params=params)


def compare_price_lists(lists: List[Dict[str, Any]], codigo_item: str, id_deposito: Optional[Any]) -> Dict[str, Any]:
    out = {}

    usable_lists = []
    for l in lists:
        lid = extract_id(l, ["idListaPrecio", "id_lista_precio", "idListaPrecioVenta", "id"])
        if lid:
            usable_lists.append((lid, l))

    for lid, lista_obj in usable_lists[:5]:
        res = get_items(id_lista=lid, id_deposito=id_deposito, codigo_item=codigo_item, limit=5)
        item = first_obj(res)
        out[str(lid)] = {
            "lista": lista_obj,
            "item": item,
            "precio_detectado": extract_price(item) if item else None,
            "stock_detectado": extract_stock(item) if item else None,
            "raw": res,
        }

    log("COMPARACIÓN DE PRECIOS POR LISTA", out)
    return out


def compare_stock_deposits(depositos: List[Dict[str, Any]], codigo_item: str, id_lista: Optional[Any]) -> Dict[str, Any]:
    out = {}

    usable_deps = []
    for d in depositos:
        did = extract_id(d, ["idDeposito", "id_deposito", "id"])
        if did:
            usable_deps.append((did, d))

    for did, dep_obj in usable_deps[:5]:
        res = get_items(id_lista=id_lista, id_deposito=did, codigo_item=codigo_item, limit=5)
        item = first_obj(res)
        out[str(did)] = {
            "deposito": dep_obj,
            "item": item,
            "precio_detectado": extract_price(item) if item else None,
            "stock_detectado": extract_stock(item) if item else None,
            "raw": res,
        }

    log("COMPARACIÓN DE STOCK POR DEPÓSITO", out)
    return out


def build_order_product_variants(codigo_item: str, base_price: Optional[float]) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Probamos distintos nombres de campos porque la documentación pública no muestra
    el detalle interno de productos. En demo, esto sirve para aprender qué acepta.
    """
    variants = []

    variants.append((
        "solo_codigo_cantidad",
        {
            "codigoItem": codigo_item,
            "cantidad": 1,
        }
    ))

    if base_price is not None:
        final_price = float(TEST_FINAL_PRICE) if TEST_FINAL_PRICE else round(base_price * 0.95, 2)
    else:
        final_price = float(TEST_FINAL_PRICE) if TEST_FINAL_PRICE else 1.0

    discount = float(TEST_DISCOUNT)

    variants.extend([
        (
            "precio_unitario_snake",
            {
                "codigoItem": codigo_item,
                "cantidad": 1,
                "precio_unitario": final_price,
            }
        ),
        (
            "precioUnitario_camel",
            {
                "codigoItem": codigo_item,
                "cantidad": 1,
                "precioUnitario": final_price,
            }
        ),
        (
            "precio",
            {
                "codigoItem": codigo_item,
                "cantidad": 1,
                "precio": final_price,
            }
        ),
        (
            "descuento",
            {
                "codigoItem": codigo_item,
                "cantidad": 1,
                "descuento": discount,
            }
        ),
        (
            "porcentaje_descuento",
            {
                "codigoItem": codigo_item,
                "cantidad": 1,
                "porcentaje_descuento": discount,
            }
        ),
        (
            "descuentoPorcentaje_camel",
            {
                "codigoItem": codigo_item,
                "cantidad": 1,
                "descuentoPorcentaje": discount,
            }
        ),
        (
            "precio_y_descuento",
            {
                "codigoItem": codigo_item,
                "cantidad": 1,
                "precio_unitario": final_price,
                "descuento": discount,
            }
        ),
    ])

    return variants


def build_base_order(
    id_empresa: Any,
    id_sucursal: Any,
    id_deposito: Any,
    producto: Dict[str, Any],
    referencia_suffix: str,
) -> Dict[str, Any]:
    today = datetime.now().strftime("%d%m%Y")
    ref = f"PRUEBA API {referencia_suffix}"[:100]

    return {
        "fecha": today,
        "id_empresa": safe_int(id_empresa) or id_empresa,
        "id_sucursal_empresa": str(id_sucursal),
        "apellido_razon_social": "CLIENTE DEMO API",
        "nombre": "PRUEBA",
        "categoria_fiscal": "CONSUMIDOR_FINAL",
        "tipo_doc": "DNI",
        "nro_doc": 11111111,
        "telefono": "0000000000",
        "email": "demo.api@example.com",
        "domicilio": "DOMICILIO DEMO API",
        "referencia": ref,
        "id_deposito": safe_int(id_deposito) or id_deposito,
        "productos": [producto],
    }


def create_test_orders(
    id_empresa: Any,
    id_sucursal: Any,
    id_deposito: Any,
    codigo_item: str,
    base_price: Optional[float],
) -> Dict[str, Any]:
    if not CREATE_TEST_PEDIDOS:
        log("SKIP PEDIDOS", "DUX_CREATE_TEST_PEDIDOS no está en 1.")
        return {}

    results = {}
    variants = build_order_product_variants(codigo_item, base_price)

    for name, product_payload in variants:
        order_body = build_base_order(
            id_empresa=id_empresa,
            id_sucursal=id_sucursal,
            id_deposito=id_deposito,
            producto=product_payload,
            referencia_suffix=name,
        )

        res = request_dux("POST", "/pedido/nuevopedido", body=order_body)
        results[name] = {
            "body": order_body,
            "result": res,
        }

    return results


def consult_recent_orders(id_empresa: Any, id_sucursal: Any) -> Dict[str, Any]:
    today = datetime.now().date()
    fecha_desde = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    fecha_hasta = today.strftime("%Y-%m-%d")

    params = {
        "offset": 0,
        "limit": 50,
        "idEmpresa": id_empresa,
        "idSucursal": id_sucursal,
        "fechaDesde": fecha_desde,
        "fechaHasta": fecha_hasta,
        "cliente": "CLIENTE DEMO API",
        "anulados": "false",
    }

    return request_dux("GET", "/pedidos", params=params)


def main() -> None:
    all_results: Dict[str, Any] = {}

    try:
        log("INICIO DUX DEMO PROBE", {
            "base_url": BASE_URL,
            "create_test_pedidos": CREATE_TEST_PEDIDOS,
            "create_test_factura": CREATE_TEST_FACTURA,
            "nota": "No se recomienda CREATE_TEST_FACTURA salvo demo totalmente descartable.",
        })

        if CREATE_TEST_FACTURA:
            raise RuntimeError(
                "CREATE_TEST_FACTURA está en 1. No implementé facturación automática por seguridad. "
                "Primero validemos pedidos y precios."
            )

        basic = get_basic_resources()
        all_results["basic_resources"] = basic

        detected = autodetect_ids(basic)
        all_results["detected"] = detected
        log("IDS DETECTADOS", detected)

        id_empresa = detected.get("id_empresa")
        id_sucursal = detected.get("id_sucursal_empresa")
        id_deposito = detected.get("id_deposito")
        id_lista = detected.get("id_lista_precio")

        if not id_empresa:
            raise RuntimeError("No pude detectar id_empresa. Cargá DUX_ID_EMPRESA.")
        if not id_sucursal:
            raise RuntimeError("No pude detectar id_sucursal_empresa. Cargá DUX_ID_SUCURSAL_EMPRESA.")
        if not id_deposito:
            raise RuntimeError("No pude detectar id_deposito. Cargá DUX_ID_DEPOSITO.")
        if not id_lista:
            raise RuntimeError("No pude detectar id_lista_precio. Cargá DUX_ID_LISTA_PRECIO.")

        codigo_item = DUX_CODIGO_ITEM

        # Trae items con la lista/deposito detectados.
        items_result = get_items(id_lista=id_lista, id_deposito=id_deposito, codigo_item=codigo_item or None, limit=10)
        all_results["items_result"] = items_result

        item = first_obj(items_result)
        if not item:
            raise RuntimeError("No encontré items para probar. Revisar datos demo, lista, depósito o filtros.")

        if not codigo_item:
            codigo_item = extract_codigo_item(item)

        if not codigo_item:
            raise RuntimeError(
                "Encontré item pero no pude detectar código de item. Revisar respuesta en artifact."
            )

        base_price_raw = extract_price(item)
        try:
            base_price = float(base_price_raw) if base_price_raw is not None else None
        except Exception:
            base_price = None

        log("ITEM BASE PARA PRUEBAS", {
            "codigo_item": codigo_item,
            "precio_detectado": base_price_raw,
            "stock_detectado": extract_stock(item),
            "item": item,
        })

        listas = as_list(basic["listas_precio"]["response"])
        depositos = as_list(basic["depositos"]["response"])

        all_results["compare_price_lists"] = compare_price_lists(
            lists=listas,
            codigo_item=codigo_item,
            id_deposito=id_deposito,
        )

        all_results["compare_stock_deposits"] = compare_stock_deposits(
            depositos=depositos,
            codigo_item=codigo_item,
            id_lista=id_lista,
        )

        all_results["create_test_orders"] = create_test_orders(
            id_empresa=id_empresa,
            id_sucursal=id_sucursal,
            id_deposito=id_deposito,
            codigo_item=codigo_item,
            base_price=base_price,
        )

        all_results["recent_orders"] = consult_recent_orders(
            id_empresa=id_empresa,
            id_sucursal=id_sucursal,
        )

        with open(ARTIFACT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

        log("FIN OK", f"Resultados guardados en {ARTIFACT_JSON}")

    except Exception as e:
        all_results["fatal_error"] = {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

        with open(ARTIFACT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

        log("ERROR GENERAL", all_results["fatal_error"])
        raise


if __name__ == "__main__":
    main()
