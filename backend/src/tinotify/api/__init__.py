"""API minima de disponibilidad; sin integracion con PostgreSQL ni SIGAC."""

from fastapi import FastAPI


app = FastAPI(
    title="Tinotify API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Indica que el proceso HTTP responde, sin comprobar sistemas externos."""
    return {"status": "ok"}
