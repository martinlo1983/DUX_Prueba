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

# Valores de prueba recomendados para esta demo DUX.
# Se pueden pisar desde GitHub Actions env/secrets si cambia el ambiente.
DUX_PREFERRED_CODIGO_ITEM = os.getenv("DUX_PREFERRED_CODIGO_ITEM", "00000000000029").strip()
DUX_PREFERRED_ID_DEPOSITO = os.getenv("DUX_PREFERRED_ID_DEPOSITO", "15998").strip()
DUX_REQUIRE_STOCK_FOR_TEST_ITEM = os.getenv("DUX_REQUIRE_STOCK_FOR_TEST_ITEM", "1").strip() == "1"

# Exploración de pedidos existentes para descubrir la estructura real de productos.
# No crea nada: solo lista pedidos y prueba endpoints de detalle.
PROBE_EXISTING_ORDERS = os.getenv("DUX_PROBE_EXISTING_ORDERS", "1").strip() == "1"
DUX_EXISTING_ORDER_ID = os.getenv("DUX_EXISTING_ORDER_ID", "").strip()
EXISTING_ORDERS_LIMIT = int(os.getenv("DUX_EXISTING_ORDERS_LIMIT", "20"))
ORDER_DETAIL_PROBE_LIMIT = int(os.getenv("DUX_ORDER_DETAIL_PROBE_LIMIT", "1"))
ORDER_LOOKBACK_DAYS = int(os.getenv("DUX_ORDER_LOOKBACK_DAYS", "365"))

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

    return {
        "Authorization": DUX_TOKEN,
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
    """
    DUX devuelve el precio dentro de obj["precios"] como una lista:
      "precios": [{"id": ..., "nombre": ..., "precio": "11340.0"}]

    Dejamos también fallback por si algún endpoint devuelve precio plano.
    """
    if not obj:
        return None

    precios = obj.get("precios")
    if isinstance(precios, list) and precios:
        first_price = precios[0]
        if isinstance(first_price, dict):
            value = first_price.get("precio")
            if value not in [None, ""]:
                return value

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


def parse_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def item_price_value(obj: Optional[Dict[str, Any]]) -> Optional[float]:
    if not obj:
        return None
    return parse_float(extract_price(obj))


def item_stock_available_value(obj: Optional[Dict[str, Any]], id_deposito: Optional[Any] = None) -> Optional[float]:
    if not obj:
        return None

    stock = obj.get("stock")
    if isinstance(stock, list):
        candidates = []
        for row in stock:
            if not isinstance(row, dict):
                continue

            if id_deposito is not None:
                row_id = row.get("id") or row.get("id_deposito") or row.get("idDeposito")
                if str(row_id) != str(id_deposito):
                    continue

            for key in ["stock_disponible", "ctd_disponible", "stockDisponible", "disponible", "stock_real"]:
                value = parse_float(row.get(key))
                if value is not None:
                    candidates.append(value)
                    break

        if candidates:
            return max(candidates)

    flat = extract_stock(obj)
    return parse_float(flat)


def is_valid_test_item(obj: Optional[Dict[str, Any]], id_deposito: Optional[Any] = None) -> bool:
    if not obj:
        return False

    price = item_price_value(obj)
    if price is None or price <= 0:
        return False

    if DUX_REQUIRE_STOCK_FOR_TEST_ITEM:
        stock = item_stock_available_value(obj, id_deposito)
        if stock is None or stock <= 0:
            return False

    return True


def choose_deposito(depositos: List[Dict[str, Any]]) -> Tuple[Optional[Any], Optional[Dict[str, Any]], str]:
    if DUX_ID_DEPOSITO:
        wanted = DUX_ID_DEPOSITO
        source = "DUX_ID_DEPOSITO"
    else:
        wanted = DUX_PREFERRED_ID_DEPOSITO
        source = "DUX_PREFERRED_ID_DEPOSITO"

    preferred = None
    if wanted:
        preferred = next(
            (
                d for d in depositos
                if str(extract_id(d, ["idDeposito", "id_deposito", "id"])) == str(wanted)
            ),
            None,
        )

    if preferred:
        return extract_id(preferred, ["idDeposito", "id_deposito", "id"]), preferred, source

    if depositos:
        first = depositos[0]
        return extract_id(first, ["idDeposito", "id_deposito", "id"]), first, "primer_deposito_fallback"

    return None, None, "no_deposito"


def choose_test_item(
    id_lista: Any,
    id_deposito: Any,
    items_result: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
    """
    Selecciona el producto de prueba evitando el falso positivo del primer item con precio 0/stock 0.

    Orden:
    1) DUX_CODIGO_ITEM, si está cargado.
    2) DUX_PREFERRED_CODIGO_ITEM, por defecto 00000000000029.
    3) Primer item de la respuesta inicial que tenga precio > 0 y, si se exige, stock > 0.
    """
    candidates_codes = []
    if DUX_CODIGO_ITEM:
        candidates_codes.append(("DUX_CODIGO_ITEM", DUX_CODIGO_ITEM))
    if DUX_PREFERRED_CODIGO_ITEM and DUX_PREFERRED_CODIGO_ITEM not in [c for _, c in candidates_codes]:
        candidates_codes.append(("DUX_PREFERRED_CODIGO_ITEM", DUX_PREFERRED_CODIGO_ITEM))

    for source, code in candidates_codes:
        res = get_items(id_lista=id_lista, id_deposito=id_deposito, codigo_item=code, limit=5)
        item = first_obj(res)
        if item and is_valid_test_item(item, id_deposito):
            return item, source

        log("ITEM PREFERIDO NO VÁLIDO PARA PEDIDO", {
            "source": source,
            "codigo_item": code,
            "encontrado": bool(item),
            "precio_detectado": extract_price(item) if item else None,
            "stock_detectado": item_stock_available_value(item, id_deposito) if item else None,
            "require_stock": DUX_REQUIRE_STOCK_FOR_TEST_ITEM,
            "nota": "No se usa para pedido porque precio <= 0, no tiene stock o no fue encontrado.",
        })

    initial_items = as_list(items_result.get("response"))
    for item in initial_items:
        if is_valid_test_item(item, id_deposito):
            return item, "primer_item_valido_precio_stock"

    raise RuntimeError(
        "No encontré item válido para pedido. Revisar DUX_PREFERRED_CODIGO_ITEM, "
        "DUX_PREFERRED_ID_DEPOSITO, lista de precios, stock o poner DUX_REQUIRE_STOCK_FOR_TEST_ITEM=0."
    )


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

    depositos = as_list(results.get("depositos", {}).get("response"))
    deposito_id, deposito_obj, deposito_source = choose_deposito(depositos)
    detected["id_deposito"] = deposito_id
    detected["deposito_obj"] = deposito_obj
    detected["deposito_source"] = deposito_source

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
    Pruebas enfocadas en descubrir qué identificador de producto espera DUX
    dentro de productos[] y si acepta precio/descuento enviado por API.

    Hallazgo previo: DUX parece reconocer el campo "precio" porque respondió
    "Debe ingresar un precio mayor a cero" cuando precio=0.
    Por eso ahora probamos precio > 0 y varios nombres posibles para el código.
    """
    variants: List[Tuple[str, Dict[str, Any]]] = []

    try:
        lista_price = float(base_price) if base_price is not None else 11340.0
    except Exception:
        lista_price = 11340.0

    # Si cargás DUX_TEST_FINAL_PRICE como secret, pisa el valor de prueba.
    # Si no, usamos 10000 para detectar si DUX respeta un precio distinto
    # al precio de lista del producto 00000000000029 (11340 en la demo).
    custom_price = float(TEST_FINAL_PRICE) if TEST_FINAL_PRICE else 10000.0
    discount = float(TEST_DISCOUNT)

    variants.extend([
        (
            "cod_item_precio_10000",
            {
                "cod_item": codigo_item,
                "cantidad": 1,
                "precio": custom_price,
            }
        ),
        (
            "codigo_item_precio_10000",
            {
                "codigo_item": codigo_item,
                "cantidad": 1,
                "precio": custom_price,
            }
        ),
        (
            "codigo_precio_10000",
            {
                "codigo": codigo_item,
                "cantidad": 1,
                "precio": custom_price,
            }
        ),
        (
            "id_item_precio_10000",
            {
                "id_item": codigo_item,
                "cantidad": 1,
                "precio": custom_price,
            }
        ),
        (
            "cod_item_precio_lista",
            {
                "cod_item": codigo_item,
                "cantidad": 1,
                "precio": lista_price,
            }
        ),
        (
            "cod_item_precio_10000_descuento",
            {
                "cod_item": codigo_item,
                "cantidad": 1,
                "precio": custom_price,
                "descuento": discount,
            }
        ),
        (
            "cod_item_precio_10000_porcentaje_descuento",
            {
                "cod_item": codigo_item,
                "cantidad": 1,
                "precio": custom_price,
                "porcentaje_descuento": discount,
            }
        ),
        (
            "cod_item_precio_10000_descuentoPorcentaje",
            {
                "cod_item": codigo_item,
                "cantidad": 1,
                "precio": custom_price,
                "descuentoPorcentaje": discount,
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


def consult_existing_orders(id_empresa: Any, id_sucursal: Any) -> Dict[str, Any]:
    """
    Lista pedidos existentes, sin filtrar por CLIENTE DEMO API.
    Esto sirve para usar pedidos reales del sistema como molde y ver cómo DUX
    representa productos, precios, descuentos e ids internos.
    """
    today = datetime.now().date()
    fecha_desde = (today - timedelta(days=ORDER_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    fecha_hasta = today.strftime("%Y-%m-%d")

    params = {
        "offset": 0,
        "limit": EXISTING_ORDERS_LIMIT,
        "idEmpresa": id_empresa,
        "idSucursal": id_sucursal,
        "fechaDesde": fecha_desde,
        "fechaHasta": fecha_hasta,
        "anulados": "false",
    }

    res = request_dux("GET", "/pedidos", params=params)

    rows = as_list(res.get("response"))
    log("PEDIDOS EXISTENTES ENCONTRADOS", {
        "cantidad_parseada": len(rows),
        "lookback_days": ORDER_LOOKBACK_DAYS,
        "nota": "Si cantidad_parseada=0, probar aumentando DUX_ORDER_LOOKBACK_DAYS o quitando fechaDesde/fechaHasta.",
        "primer_pedido": rows[0] if rows else None,
    })

    return res


def extract_order_id(order: Dict[str, Any]) -> Optional[Any]:
    return extract_id(order, [
        "idPedido",
        "id_pedido",
        "id",
        "pedido_id",
        "nroPedido",
        "nro_pedido",
        "numeroPedido",
        "numero_pedido",
    ])


def extract_order_number(order: Dict[str, Any]) -> Optional[Any]:
    return pick_field(order, [
        "nro_pedido",
        "nroPedido",
        "numero_pedido",
        "numeroPedido",
        "pedido",
        "referencia",
    ])


def probe_order_detail(order_id: Any) -> Dict[str, Any]:
    """
    DUX documenta /pedidos para listar, pero no queda claro el endpoint de detalle.
    Esta función prueba variantes típicas y deja todo en el log/artifact.
    Los errores 404/400 no cortan la corrida.
    """
    paths: List[Tuple[str, Optional[Dict[str, Any]]]] = [
        ("/pedido", {"idPedido": order_id}),
        ("/pedido", {"id_pedido": order_id}),
        ("/pedido", {"id": order_id}),
        ("/pedidos", {"idPedido": order_id}),
        ("/pedidos", {"id_pedido": order_id}),
        ("/pedidos", {"id": order_id}),
        ("/pedido/detalle", {"idPedido": order_id}),
        ("/pedido/detalle", {"id_pedido": order_id}),
        ("/pedido/detalle", {"id": order_id}),
        (f"/pedido/{order_id}", None),
        (f"/pedidos/{order_id}", None),
    ]

    results: Dict[str, Any] = {}
    for path, params in paths:
        key = f"GET {path} params={params}"
        try:
            results[key] = request_dux("GET", path, params=params, allow_error=True)
        except Exception as e:
            results[key] = {"exception": str(e)}

    log("PROBE DETALLE PEDIDO EXISTENTE", {
        "order_id": order_id,
        "resultados": results,
    })
    return results


def probe_existing_orders(id_empresa: Any, id_sucursal: Any) -> Dict[str, Any]:
    if not PROBE_EXISTING_ORDERS:
        log("SKIP PEDIDOS EXISTENTES", "DUX_PROBE_EXISTING_ORDERS no está en 1.")
        return {}

    out: Dict[str, Any] = {}
    existing = consult_existing_orders(id_empresa=id_empresa, id_sucursal=id_sucursal)
    out["listado"] = existing

    rows = as_list(existing.get("response"))

    selected_orders: List[Dict[str, Any]] = []
    if DUX_EXISTING_ORDER_ID:
        selected_orders.append({"_forced_order_id": DUX_EXISTING_ORDER_ID})
    else:
        selected_orders = rows[:max(0, ORDER_DETAIL_PROBE_LIMIT)]

    detail_results: Dict[str, Any] = {}
    for idx, order in enumerate(selected_orders, start=1):
        order_id = order.get("_forced_order_id") if isinstance(order, dict) else None
        if not order_id and isinstance(order, dict):
            order_id = extract_order_id(order)

        log("PEDIDO EXISTENTE SELECCIONADO PARA DETALLE", {
            "idx": idx,
            "order_id_detectado": order_id,
            "order_number_detectado": extract_order_number(order) if isinstance(order, dict) else None,
            "pedido_resumen": order,
            "nota": "Si order_id_detectado es None, revisar en este JSON cuál es el campo correcto de identificador.",
        })

        if not order_id:
            detail_results[f"pedido_{idx}_sin_id"] = {"pedido": order, "error": "No pude detectar id del pedido."}
            continue

        detail_results[str(order_id)] = probe_order_detail(order_id)

    out["detalle_probe"] = detail_results
    return out


def main() -> None:
    all_results: Dict[str, Any] = {}

    try:
        log("INICIO DUX DEMO PROBE", {
            "base_url": BASE_URL,
            "create_test_pedidos": CREATE_TEST_PEDIDOS,
            "create_test_factura": CREATE_TEST_FACTURA,
            "nota": "No se recomienda CREATE_TEST_FACTURA salvo demo totalmente descartable.",
            "preferred_codigo_item": DUX_PREFERRED_CODIGO_ITEM,
            "preferred_id_deposito": DUX_PREFERRED_ID_DEPOSITO,
            "require_stock_for_test_item": DUX_REQUIRE_STOCK_FOR_TEST_ITEM,
            "probe_existing_orders": PROBE_EXISTING_ORDERS,
            "existing_order_id_forzado": DUX_EXISTING_ORDER_ID or None,
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

        # Trae items con la lista/deposito elegidos. Se usa limit 50 para tener margen,
        # pero el item de pedido se selecciona con choose_test_item(), no con items[0].
        items_result = get_items(id_lista=id_lista, id_deposito=id_deposito, codigo_item=None, limit=50)
        all_results["items_result"] = items_result

        item, item_source = choose_test_item(
            id_lista=id_lista,
            id_deposito=id_deposito,
            items_result=items_result,
        )

        codigo_item = extract_codigo_item(item)
        if not codigo_item:
            raise RuntimeError(
                "Encontré item pero no pude detectar código de item. Revisar respuesta en artifact."
            )

        base_price_raw = extract_price(item)
        base_price = item_price_value(item)

        log("ITEM BASE PARA PRUEBAS", {
            "source": item_source,
            "codigo_item": codigo_item,
            "precio_detectado": base_price_raw,
            "stock_disponible_detectado": item_stock_available_value(item, id_deposito),
            "id_deposito_usado": id_deposito,
            "require_stock": DUX_REQUIRE_STOCK_FOR_TEST_ITEM,
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

        all_results["existing_orders_probe"] = probe_existing_orders(
            id_empresa=id_empresa,
            id_sucursal=id_sucursal,
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


