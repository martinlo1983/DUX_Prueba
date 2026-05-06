import os
import requests

TOKEN = os.getenv("DUX_TOKEN", "").strip()

BASE_URLS = [
    "https://erp.duxsoftware.com.ar/WSERP/rest/services",
    "https://erp.duxsoftware.com.ar/WSERP/rest",
]

HEADERS = [
    {"Authorization": f"Bearer {TOKEN}"},
    {"Authorization": TOKEN},
    {"token": TOKEN},
    {"Token": TOKEN},
    {"x-api-key": TOKEN},
    {"X-API-Key": TOKEN},
    {"apikey": TOKEN},
]

for base in BASE_URLS:
    for headers in HEADERS:
        url = base + "/listaprecioventa"

        final_headers = {
            **headers,
            "Accept": "application/json",
        }

        print("\n" + "=" * 80)
        print("URL:", url)
        print("HEADERS:", list(final_headers.keys()))
        print("=" * 80)

        try:
            r = requests.get(
                url,
                headers=final_headers,
                timeout=30,
            )

            print("STATUS:", r.status_code)
            print("CONTENT-TYPE:", r.headers.get("content-type"))
            print("BODY:")
            print(r.text[:1000])

            if r.ok:
                print("\n>>> FUNCIONÓ <<<")
                raise SystemExit(0)

        except Exception as e:
            print("ERROR:", repr(e))

print("\nNO FUNCIONÓ NINGUNA VARIANTE")
