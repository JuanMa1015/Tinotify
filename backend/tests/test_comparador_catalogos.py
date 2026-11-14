"""Entradas ficticias para probar el protocolo offline; no simulan ejecucion SQL."""

from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest


comp = SimpleNamespace(**runpy.run_path(str(Path(__file__).resolve().parents[1]/"scripts/comparar_catalogos.py")))


def fila(esquema):
    valores = {str:"sintetico", int:1, bool:True, list:[]}
    return {k: "0"*64 if k.endswith("sha256") else valores[t[0] if type(t) is tuple else t]
            for k,t in esquema.items()}


def snapshot(origen="local"):
    c = {k:[] for k in comp.ESQUEMAS}
    c.update(formato="tinotify_catalogo_v1", contexto=dict(server_version="17.12",server_version_num=170012,
        pg17=True,block_size=8192,encoding="UTF8",quote_all_identifiers="off",search_path_sha256="0"*64),
        extras={"relaciones":0,"rutinas":0},proveedor={"event_triggers":0,"ajustes_supautils":0},
        esquemas=[{"nombre":n,"owner":"postgres"} for n in ("app","app_private")])
    c["roles"]=[{"nombre":n,**{k:None if "fixture" in n else False for k in comp.ESQUEMAS["roles"] if k!="nombre"}} for n in comp.ROLES]
    for (esquema,nombre),cantidad in comp.TABLAS.items():
        c["tablas"].append(dict(esquema=esquema,nombre=nombre,presente=True,owner="postgres",tipo="r",rls=True,force_rls=True))
        for orden in range(1,cantidad+1):
            c["columnas"].append({**fila(comp.ESQUEMAS["columnas"]),"esquema":esquema,"tabla":nombre,"orden":orden})
        for categoria in ("constraints","indices","acl_tablas"):
            c[categoria].append({**fila(comp.ESQUEMAS[categoria]),"esquema":esquema,"tabla":nombre})
    for nombre in ("entorno","ensayos","perfiles"):
        c["tablas"].append(dict(esquema="app_fixture",nombre=nombre,presente=False,owner="<rol_no_previsto>",tipo=None,rls=None,force_rls=None))
    for i in range(22):
        c["funciones"].append({**fila(comp.ESQUEMAS["funciones"]),"esquema":"app_private" if i<10 else "app_fixture","firma":f"sintetica_{i}()","presente":i<10})
    for i in range(25):
        c["politicas"].append({**fila(comp.ESQUEMAS["politicas"]),"nombre_sha256":f"{i:064x}",
            "roles":[{"nombre":"tinotify_state_writer","identidad_sha256":"0"*64}]})
    p = dict(formato="tinotify_precondiciones_4b4b_v1",pg17=True,
             lectura=dict(read_only=True,row_security=True,sin_cambio_identidad=True),
             colisiones=dict.fromkeys("esquema_fixture roles_fixture roles_tinotify_extra politicas_reservadas trigger_reservado rutinas_fixture".split(),0),
             ddl_observable=dict.fromkeys("postgres_existe createrole create_database esquemas_propios tablas_propias".split(),True),
             dependencias=dict(plpgsql=True,uuid_nativo=True,sha256_nativo=True,auth_id_uuid=True,objetos_controlados_extension=0),
             historial=dict.fromkeys("existe sin_rls usage select_version".split(),True),
             no_verificable=dict.fromkeys("identidad_futura_cli restricciones_proveedor_ddl data_api proyecto_endpoint_tls".split(),True))
    h = dict(revision_informe=2,versiones=[dict(version=v,aplicaciones=int(i<3)) for i,v in enumerate(comp.VERSIONES)],
             filas_no_previstas=0,orden_invalido=False,limite="No acredita SQL aplicado")
    return comp.sellar(dict(formato=comp.FORMATO,etapa=3,origen=origen,commit="a"*40,
        archivos_sha256=dict.fromkeys(comp.ARCHIVOS,"0"*64),imagen_digest="sha256:"+"0"*64 if origen=="local" else None,
        preflight=p,catalogo=c,historial=h))


def test_igualdad_nunca_autoriza_despliegue():
    resultado=comp.comparar(snapshot(),snapshot("remoto"))
    assert resultado["veredicto"]=="evidencia_insuficiente" and not resultado["despliegue_autorizado"]
    assert len(resultado["hallazgos"])==4


@pytest.mark.parametrize("seccion,campo,valor",[
    ("tablas","rls",False),("tablas","force_rls",False),("tablas","owner","anon"),
    ("acl_tablas","rol","anon"),("funciones","security_definer",False),
    ("constraints","definicion_sha256","1"*64),("roles","rolcanlogin",True),
    ("politicas","check_sha256","1"*64),("indices","valido",False),
])
def test_diferencias_de_seguridad_bloquean(seccion,campo,valor):
    remoto=snapshot("remoto")
    remoto["catalogo"][seccion][0][campo]=valor
    resultado=comp.comparar(snapshot(),comp.sellar(remoto))
    assert resultado["veredicto"]=="bloqueado"


@pytest.mark.parametrize("seccion,campo",[("dependencias","uuid_nativo"),("ddl_observable","create_database")])
def test_precondiciones_no_se_deducen_del_historial(seccion,campo):
    remoto=snapshot("remoto")
    remoto["preflight"][seccion][campo]=False
    assert comp.comparar(snapshot(),comp.sellar(remoto))["veredicto"]=="bloqueado"


@pytest.mark.parametrize("campo",["roles_fixture","trigger_reservado","esquema_fixture","politicas_reservadas"])
def test_colisiones_antes_de_la_cuarta_bloquean(campo):
    remoto=snapshot("remoto")
    remoto["preflight"]["colisiones"][campo]=1
    assert comp.comparar(snapshot(),comp.sellar(remoto))["veredicto"]=="bloqueado"


@pytest.mark.parametrize("versiones",[[1,1,1,1],[1,0,1,0],[2,1,1,0]])
def test_historial_incompatible(versiones):
    remoto=snapshot("remoto")
    for f,n in zip(remoto["historial"]["versiones"],versiones): f["aplicaciones"]=n
    assert comp.comparar(snapshot(),comp.sellar(remoto))["veredicto"]=="bloqueado"


@pytest.mark.parametrize("modificar",[
    lambda d:d.pop("catalogo"),lambda d:d["catalogo"].pop("acl_columnas"),
    lambda d:d["catalogo"]["columnas"].pop(),lambda d:d["catalogo"].update(formato="desconocido"),
    lambda d:d["catalogo"]["tablas"][0].update(rls="false"),
    lambda d:d.update(etapa=4),lambda d:d.update(commit="otro"),
    lambda d:d["archivos_sha256"].pop(next(iter(d["archivos_sha256"]))),
    lambda d:d["catalogo"]["constraints"][0].update(definicion_sha256="corrupto"),
])
def test_snapshot_incompleto_o_corrupto_se_rechaza(modificar):
    datos=snapshot("remoto")
    modificar(datos)
    with pytest.raises(ValueError): comp.validar_snapshot(comp.sellar(datos))


def test_checksum_y_claves_json_duplicadas(tmp_path):
    datos=snapshot()
    datos["commit"]="b"*40
    with pytest.raises(ValueError): comp.validar_snapshot(datos)
    entrada=tmp_path/"duplicado.json"
    entrada.write_text('{"x":1,"x":2}',encoding="utf-8")
    with pytest.raises(ValueError): comp.cargar(entrada)


def test_roles_rls_exactos_y_objetos_extra():
    for seccion in ("politicas","extras"):
        datos=snapshot("remoto")
        if seccion=="politicas": datos["catalogo"][seccion][0]["roles"][0]["nombre"]="PUBLIC"
        else: datos["catalogo"][seccion]["relaciones"]=1
        assert comp.comparar(snapshot(),comp.sellar(datos))["veredicto"]=="bloqueado"


def test_justificacion_exacta_no_excluye_seguridad():
    local,remoto=snapshot(),snapshot("remoto")
    remoto["catalogo"]["proveedor"]["event_triggers"]=6
    j=dict(campo="/catalogo/proveedor/event_triggers",referencia_sha256=comp.digest(0),remoto_sha256=comp.digest(6),
           causa="Hooks del proveedor, pendientes de revision",evidencia="Documento del operador con revision individual")
    resultado=comp.comparar(local,comp.sellar(remoto),[j])
    assert resultado["hallazgos"][0]["clase"]=="esperada_justificada"
    assert not resultado["despliegue_autorizado"]
    for campo in ("/catalogo/acl_tablas","/catalogo/politicas/*","/catalogo/roles"):
        with pytest.raises(ValueError): comp.comparar(local,comp.sellar(remoto),[{**j,"campo":campo}])
    with pytest.raises(ValueError): comp.comparar(local,comp.sellar(remoto),[{**j,"remoto_sha256":"f"*64}])


def test_evidencia_obsoleta_y_contexto_distinto():
    local,remoto=snapshot(),snapshot("remoto")
    remoto["catalogo"]["contexto"]["server_version_num"]=170011
    assert comp.comparar(local,comp.sellar(remoto))["veredicto"]=="bloqueado"
    j=dict(campo="/catalogo/proveedor/event_triggers",referencia_sha256=comp.digest(0),remoto_sha256=comp.digest(0),
           causa="Evidencia obsoleta sin diferencias",evidencia="Documento anterior, no reutilizable")
    with pytest.raises(ValueError): comp.comparar(local,snapshot("remoto"),[j])


def test_historial_no_visible_y_procedencia_distinta():
    remoto=snapshot("remoto")
    remoto["preflight"]["historial"]["select_version"]=False
    assert any(h["campo"]=="remoto/historial" for h in comp.comparar(snapshot(),comp.sellar(remoto))["hallazgos"])
    remoto["commit"]="b"*40
    with pytest.raises(ValueError): comp.comparar(snapshot(),comp.sellar(remoto))


def test_ambos_snapshots_inseguros_no_se_validan_por_igualdad():
    local,remoto=snapshot(),snapshot("remoto")
    for d in (local,remoto): d["catalogo"]["tablas"][0]["force_rls"]=False
    assert comp.comparar(comp.sellar(local),comp.sellar(remoto))["veredicto"]=="bloqueado"
