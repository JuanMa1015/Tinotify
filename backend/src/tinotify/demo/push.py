"""Solo Expo HTTPS. Los errores nunca incorporan tokens o respuestas crudas."""

import httpx


class ExpoPush:
    def __init__(self, access_token=None, transport=None):
        self._client = httpx.AsyncClient(
            base_url="https://exp.host/--/api/v2/push/", timeout=10, trust_env=False,
            follow_redirects=False, transport=transport,
            headers={"Authorization": "Bearer " + access_token} if access_token else {},
        )

    async def cerrar(self):
        await self._client.aclose()

    async def enviar(self, token, evento):
        try:
            r = await self._client.post("send", json={
                "to": token, "title": "Tinotify Demo", "body": evento["mensaje"],
                "sound": "default", "channelId": "tinotify-demo", "priority": "high",
                "data": {"caseId": evento["caso"], "eventId": evento["id"], "demo": True},
            })
            if r.status_code == 429:
                return "reintentable", None
            if r.status_code >= 500:
                return "incierto", None
            if r.status_code != 200:
                return "rechazado", None
            datos = r.json().get("data", {})
            if datos.get("status") == "ok" and isinstance(datos.get("id"), str):
                return "aceptado_expo", datos["id"]
            return ("dispositivo_invalido" if datos.get("details", {}).get("error") == "DeviceNotRegistered"
                    else "rechazado"), None
        except httpx.ConnectError:
            return "reintentable", None
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            return "incierto", None

    async def recibos(self, tickets):
        try:
            r = await self._client.post("getReceipts", json={"ids": tickets})
            datos = r.json().get("data", {}) if r.status_code == 200 else {}
            return datos if isinstance(datos, dict) else {}
        except (httpx.HTTPError, ValueError, AttributeError):
            return {}
