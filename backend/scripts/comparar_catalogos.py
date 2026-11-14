"""Herramienta offline 4B.4-B. No importa drivers ni abre conexiones."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


RAIZ = Path(__file__).resolve().parents[2]
FORMATO = "tinotify_snapshot_4b4b_v1"
VERSIONES = ("20261112050000", "20261112160000", "20261114010000", "20261114020000")
ARCHIVOS = tuple(str(p.relative_to(RAIZ)).replace("\\", "/") for p in sorted(
    (RAIZ/"supabase/migrations").glob("*.sql"))) + (
    "supabase/checks/4b4b_preflight.sql", "supabase/checks/4b4a_inventario.sql",
    "supabase/checks/4b3_historial.sql", "backend/scripts/comparar_catalogos.py")
ARCHIVOS += ("backend/tests/integration/conftest.py", "backend/tests/integration/test_preflight_4b4b.py",
             ".github/workflows/backend-tests.yml")
TABLAS = {("app", "estudiantes"): 4, ("app", "estados_reconciliacion"): 11,
          ("app", "expedientes"): 7, ("app", "actuaciones"): 13, ("app", "eventos"): 12,
          ("app_private", "accesos_sigac"): 11, ("app_private", "sincronizaciones"): 17,
          ("app_private", "importaciones"): 10}
ROLES = ("anon", "authenticated", "postgres", "service_role", "tinotify_api",
         "tinotify_fixture_control", "tinotify_fixture_owner", "tinotify_fixture_recovery",
         "tinotify_guard_reader", "tinotify_notifications", "tinotify_state_writer", "tinotify_sync")
HASH = re.compile(r"[0-9a-f]{64}")


def canonico(valor):
    return json.dumps(valor, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def digest(valor):
    return hashlib.sha256(canonico(valor).encode("utf-8")).hexdigest()


def exigir(condicion):
    if not condicion:
        raise ValueError("Snapshot o evidencia incompletos, corruptos o incompatibles")


def registro(valor, campos):
    exigir(type(valor) is dict and set(valor) == set(campos))


def _sin_duplicados(pares):
    datos = {}
    for clave, valor in pares:
        exigir(clave not in datos)
        datos[clave] = valor
    return datos


def cargar(ruta):
    exigir(ruta.stat().st_size <= 16*1024*1024)
    return json.loads(ruta.read_text(encoding="utf-8-sig"), object_pairs_hook=_sin_duplicados,
                      parse_constant=lambda _: exigir(False))


def tipos(campos, tipo):
    return dict.fromkeys(campos.split(), tipo)


# Esquema cerrado de la salida v1; una evolucion del extractor exige revision.
S = tipos("esquema tabla", str)
ACL = {**S, **tipos("rol rol_sha256 otorgante_sha256 permiso", str), "delegable": bool}
ESQUEMAS = {
    "contexto": {**tipos("server_version encoding quote_all_identifiers search_path_sha256", str),
                 **tipos("server_version_num block_size", int), "pg17": bool},
    "esquemas": {"nombre": str, "owner": str},
    "roles": {"nombre": str, **tipos("rolcanlogin rolinherit rolsuper rolcreatedb rolcreaterole rolreplication rolbypassrls", (bool, type(None)))},
    "tablas": {"esquema": str, "nombre": str, "presente": bool, "owner": str,
               "tipo": (str, type(None)), **tipos("rls force_rls", (bool, type(None)))},
    "columnas": {**S, "orden": int, **tipos("nombre nombre_sha256 tipo identity generated", str),
                 "typmod": int, **tipos("not_null dropped has_missing", bool),
                 **tipos("collation default_sha256", (str, type(None)))},
    "constraints": {**S, "nombre": (str, type(None)), **tipos("nombre_sha256 tipo definicion_sha256", str),
                    **tipos("validado diferible inicialmente_diferido", bool)},
    "indices": {**S, **tipos("nombre_sha256 definicion_sha256", str),
                **tipos("valido listo unico primario nulls_not_distinct", bool)},
    "politicas": {**S, **tipos("nombre_sha256 comando", str), "permisiva": bool, "roles": list,
                  **tipos("using_sha256 check_sha256", (str, type(None)))},
    "funciones": {**tipos("esquema firma owner", str), "presente": bool,
                  **tipos("tipo volatility parallel definicion_sha256", (str, type(None))),
                  **tipos("security_definer strict", (bool, type(None)))},
    "acl_tablas": ACL,
    "acl_columnas": {**ACL, "orden": int},
    "acl_funciones": {**{k:v for k,v in ACL.items() if k != "tabla"}, "firma": str},
    "acl_esquemas": {k:v for k,v in ACL.items() if k != "tabla"},
    "permisos_tabla_efectivos": {**S, **tipos("rol permiso", str)},
    "permisos_columna_efectivos": {**S, "orden": int, **tipos("rol permiso", str)},
    "execute_efectivo": tipos("esquema firma rol", str),
    "permisos_esquema": {**tipos("esquema rol", str), **tipos("usage create", bool)},
    "membresias": {**tipos("rol miembro rol_sha256 miembro_sha256 otorgante_sha256", str),
                   **tipos("admin inherit set", bool)},
    "defaults": {**tipos("creador esquema tipo destinatario destinatario_sha256 otorgante_sha256 permiso", str), "delegable": bool},
    "triggers": {**S, **tipos("nombre_sha256 habilitado definicion_sha256", str)},
    "extras": tipos("relaciones rutinas", int),
    "proveedor": tipos("event_triggers ajustes_supautils", int),
}


def validar_fila(fila, esquema):
    registro(fila, esquema)
    for campo, tipo in esquema.items():
        exigir(type(fila[campo]) in (tipo if type(tipo) is tuple else (tipo,)))
        if campo.endswith("sha256") and fila[campo] is not None:
            exigir(HASH.fullmatch(fila[campo]) is not None)


def validar_catalogo(datos):
    registro(datos, {"formato", *ESQUEMAS})
    exigir(datos["formato"] == "tinotify_catalogo_v1")
    for nombre, esquema in ESQUEMAS.items():
        filas = [datos[nombre]] if nombre in ("contexto", "extras", "proveedor") else datos[nombre]
        exigir(type(filas) is list)
        for fila in filas:
            validar_fila(fila, esquema)
            if nombre == "politicas":
                exigir(len(fila["roles"]) > 0)
                for rol in fila["roles"]:
                    validar_fila(rol, tipos("nombre identidad_sha256", str))
        exigir(len({canonico(f) for f in filas}) == len(filas))
    contexto = datos["contexto"]
    exigir(contexto["pg17"] and contexto["server_version_num"]//10000 == 17)
    exigir(contexto["encoding"] == "UTF8" and contexto["block_size"] > 0)
    exigir(tuple(r["nombre"] for r in datos["roles"]) == ROLES)
    exigir(len(datos["tablas"]) == 11 and len(datos["funciones"]) == 22)
    presentes = {(t["esquema"], t["nombre"]) for t in datos["tablas"] if t["presente"]}
    exigir(presentes == set(TABLAS))
    exigir(all(t["esquema"] == "app_fixture" for t in datos["tablas"] if not t["presente"]))
    exigir(sum(f["presente"] for f in datos["funciones"]) == 10)
    exigir(all(f["presente"] == (f["esquema"] == "app_private") for f in datos["funciones"]))
    for tabla, cantidad in TABLAS.items():
        columnas = [c for c in datos["columnas"] if (c["esquema"], c["tabla"]) == tabla]
        exigir([c["orden"] for c in columnas] == list(range(1, cantidad+1)))
        exigir(all(any((r["esquema"], r["tabla"]) == tabla for r in datos[s]) for s in ("constraints", "indices", "acl_tablas")))
    exigir(len(datos["columnas"]) == sum(TABLAS.values()))
    exigir(len(datos["politicas"]) >= 25)


def validar_preflight(p):
    registro(p, ("formato", "lectura", "pg17", "colisiones", "ddl_observable", "dependencias", "historial", "no_verificable"))
    exigir(p["formato"] == "tinotify_precondiciones_4b4b_v1" and type(p["pg17"]) is bool)
    secciones = {
        "lectura": tipos("read_only row_security sin_cambio_identidad", bool),
        "colisiones": tipos("esquema_fixture roles_fixture roles_tinotify_extra politicas_reservadas trigger_reservado rutinas_fixture", int),
        "ddl_observable": tipos("postgres_existe createrole create_database esquemas_propios tablas_propias", bool),
        "dependencias": {**tipos("plpgsql uuid_nativo sha256_nativo auth_id_uuid", bool), "objetos_controlados_extension": int},
        "historial": tipos("existe sin_rls usage select_version", bool),
        "no_verificable": tipos("identidad_futura_cli restricciones_proveedor_ddl data_api proyecto_endpoint_tls", bool),
    }
    for nombre, esquema in secciones.items():
        validar_fila(p[nombre], esquema)
    exigir(all(p["no_verificable"].values()))


def validar_snapshot(datos):
    registro(datos, ("formato", "etapa", "origen", "commit", "archivos_sha256", "imagen_digest", "preflight", "catalogo", "historial", "integridad"))
    exigir(datos["formato"] == FORMATO and datos["etapa"] == 3 and type(datos["etapa"]) is int)
    exigir(datos["origen"] in ("local", "remoto"))
    exigir(type(datos["commit"]) is str and re.fullmatch(r"[0-9a-f]{40}", datos["commit"]) is not None)
    registro(datos["archivos_sha256"], ARCHIVOS)
    exigir(all(type(h) is str and HASH.fullmatch(h) for h in datos["archivos_sha256"].values()))
    exigir(datos["imagen_digest"] is None if datos["origen"] == "remoto" else
           type(datos["imagen_digest"]) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", datos["imagen_digest"]) is not None)
    exigir(datos["integridad"] == digest({k:v for k,v in datos.items() if k != "integridad"}))
    validar_preflight(datos["preflight"])
    validar_catalogo(datos["catalogo"])
    h = datos["historial"]
    registro(h, ("revision_informe", "versiones", "filas_no_previstas", "orden_invalido", "limite"))
    exigir(h["revision_informe"] == 2 and type(h["filas_no_previstas"]) is int and type(h["orden_invalido"]) is bool)
    exigir(type(h["limite"]) is str and type(h["versiones"]) is list and len(h["versiones"]) == 4)
    for fila in h["versiones"]:
        validar_fila(fila, {"version": str, "aplicaciones": int})
        exigir(fila["aplicaciones"] >= 0)
    exigir(tuple(f["version"] for f in h["versiones"]) == VERSIONES)


def sellar(datos):
    datos = {k:v for k,v in datos.items() if k != "integridad"}
    return {**datos, "integridad": digest(datos)}


def empaquetar(preflight, catalogo, historial, origen, imagen_digest):
    # No usa remotos Git ni lee configuracion/credenciales. Rechaza codigo relevante sucio.
    subprocess.run(["git", "ls-files", "--error-unmatch", "--", *ARCHIVOS], cwd=RAIZ,
                   check=True, capture_output=True)
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", *ARCHIVOS], cwd=RAIZ,
                   check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RAIZ, check=True,
                            capture_output=True, text=True).stdout.strip()
    datos = sellar(dict(formato=FORMATO, etapa=3, origen=origen, commit=commit,
                       archivos_sha256={p:hashlib.sha256((RAIZ/p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in ARCHIVOS},
                       imagen_digest=imagen_digest, preflight=preflight, catalogo=catalogo, historial=historial))
    validar_snapshot(datos)
    return datos


def diferencias(a, b, ruta=""):
    if type(a) is dict and type(b) is dict:
        for clave in sorted(set(a) | set(b)):
            if clave not in a or clave not in b:
                yield ruta+"/"+clave, a.get(clave), b.get(clave)
            else:
                yield from diferencias(a[clave], b[clave], ruta+"/"+clave)
    elif type(a) is list and type(b) is list:
        if len(a) != len(b):
            yield ruta, a, b
        else:
            for indice, (izq, der) in enumerate(zip(a, b)):
                yield from diferencias(izq, der, ruta+"/"+str(indice))
    elif type(a) is not type(b) or a != b:
        yield ruta, a, b


def comparar(referencia, remoto, justificaciones=()):
    validar_snapshot(referencia)
    validar_snapshot(remoto)
    exigir(referencia["origen"] == "local" and remoto["origen"] == "remoto")
    exigir(referencia["commit"] == remoto["commit"] and referencia["archivos_sha256"] == remoto["archivos_sha256"])
    exigir(type(justificaciones) in (list, tuple))
    permisos = {}
    for j in justificaciones:
        validar_fila(j, tipos("campo referencia_sha256 remoto_sha256 causa evidencia", str))
        exigir(j["campo"] not in permisos and len(j["causa"].strip()) >= 10 and len(j["evidencia"].strip()) >= 10)
        # Lista FINITA de campos de contexto, nunca secciones de seguridad o comodines.
        exigir(j["campo"] in ("/catalogo/contexto/server_version", "/catalogo/proveedor/event_triggers", "/catalogo/proveedor/ajustes_supautils", "/catalogo/roles/2/rolsuper"))
        permisos[j["campo"]] = j
    hallazgos = []

    def agregar(clase, campo, causa):
        hallazgos.append(dict(clase=clase, campo=campo, causa=causa))

    for etiqueta, datos in (("referencia", referencia), ("remoto", remoto)):
        p = datos["preflight"]
        if not p["pg17"] or not all(p["lectura"].values()):
            agregar("bloqueante", etiqueta+"/lectura", "Se requiere PG17 y captura READ ONLY sin cambio de identidad")
        if any(p["colisiones"].values()):
            agregar("bloqueante", etiqueta+"/colisiones", "Colision con objetos o roles pendientes")
        if not all(p["ddl_observable"].values()) or not all(v for k,v in p["dependencias"].items() if k != "objetos_controlados_extension") or p["dependencias"]["objetos_controlados_extension"]:
            agregar("bloqueante", etiqueta+"/dependencias", "Propiedad, dependencias o privilegios observables incompatibles")
        if not all(p["historial"].values()):
            agregar("no_verificable", etiqueta+"/historial", "Historial no accesible o potencialmente filtrado por RLS")
        h = datos["historial"]
        if [f["aplicaciones"] for f in h["versiones"]] != [1,1,1,0] or h["filas_no_previstas"] or h["orden_invalido"]:
            agregar("bloqueante", etiqueta+"/historial", "Se exige historial [1,1,1,0] sin versiones ajenas")
        c = datos["catalogo"]
        if c["extras"] != {"relaciones":0,"rutinas":0} or any(not t["rls"] or not t["force_rls"] or t["owner"] != "postgres" for t in c["tablas"] if t["presente"]):
            agregar("bloqueante", etiqueta+"/catalogo", "Objetos extra, propiedad o RLS incompatible incluso si ambos snapshots coinciden")
        if c["esquemas"] != [{"nombre":"app","owner":"postgres"},{"nombre":"app_private","owner":"postgres"}]:
            agregar("bloqueante", etiqueta+"/esquemas", "Esquemas de la etapa previa incompatibles")
        for rol in c["roles"]:
            if rol["nombre"].startswith("tinotify_") and "fixture" not in rol["nombre"] and any(v is not False for k,v in rol.items() if k != "nombre"):
                agregar("bloqueante", etiqueta+"/roles", "Rol interno con atributos incompatibles")
        if any(not k["validado"] for k in c["constraints"]) or any(not i["valido"] or not i["listo"] for i in c["indices"]):
            agregar("bloqueante", etiqueta+"/integridad", "Constraint o indice no valido")
    for campo, izq, der in diferencias(referencia["catalogo"], remoto["catalogo"], "/catalogo"):
        j = permisos.pop(campo, None)
        seguro = campo != "/catalogo/roles/2/rolsuper" or (izq is True and der is False)
        if campo == "/catalogo/contexto/server_version":
            seguro = referencia["catalogo"]["contexto"]["server_version_num"] == remoto["catalogo"]["contexto"]["server_version_num"]
        if j:
            exigir(seguro and j["referencia_sha256"] == digest(izq) and j["remoto_sha256"] == digest(der))
            agregar("esperada_justificada", campo, "Coincidencia exacta de campo y hashes con evidencia externa aportada; requiere revision humana")
        else:
            agregar("bloqueante", campo, "Diferencia de catalogo sin justificacion admisible exacta")
    exigir(not permisos)  # Evita reutilizar evidencia vieja o sobre campos sin diferencias.
    for campo in remoto["preflight"]["no_verificable"]:
        agregar("no_verificable", campo, "El catalogo no demuestra esta propiedad; requiere evidencia independiente")
    return dict(formato="tinotify_comparacion_4b4b_v1", commit=referencia["commit"],
                despliegue_autorizado=False, veredicto="bloqueado" if any(h["clase"] == "bloqueante" for h in hallazgos) else "evidencia_insuficiente",
                hallazgos=hallazgos)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    comandos = parser.add_subparsers(dest="comando", required=True)
    empaqueta = comandos.add_parser("empaquetar")
    for nombre in ("preflight", "catalogo", "historial", "salida"):
        empaqueta.add_argument("--"+nombre, type=Path, required=True)
    empaqueta.add_argument("--origen", choices=("local", "remoto"), required=True)
    empaqueta.add_argument("--imagen-digest")
    compara = comandos.add_parser("comparar")
    compara.add_argument("--referencia", type=Path, required=True)
    compara.add_argument("--remoto", type=Path, required=True)
    compara.add_argument("--justificaciones", type=Path)
    args = parser.parse_args()
    try:
        if args.comando == "empaquetar":
            datos = empaquetar(cargar(args.preflight), cargar(args.catalogo), cargar(args.historial), args.origen, args.imagen_digest)
            with args.salida.open("x", encoding="utf-8") as archivo:
                archivo.write(canonico(datos)+"\n")
            return 0
        resultado = comparar(cargar(args.referencia), cargar(args.remoto), cargar(args.justificaciones) if args.justificaciones else ())
        print(canonico(resultado))
        return 2  # Incluso igualdad completa necesita comprobaciones independientes.
    except (ValueError, OSError, RecursionError, subprocess.CalledProcessError):
        print(canonico({"veredicto":"evidencia_insuficiente", "despliegue_autorizado":False,
                        "error":"Entrada o procedencia invalida; detener sin reparar"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
