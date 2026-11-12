# ==========================================================
# DÓNDE VA: MOVIL CHECK (movilcheck.spynetpy.com) -> carpeta principal de Movil Check. Renombrar a: app.py
# ==========================================================
import os
import json
import time
import hmac
import base64
import hashlib
import secrets
import sqlite3
from io import BytesIO
from datetime import datetime, timedelta
from xml.sax.saxutils import escape as esc

from flask import Flask, request, redirect, url_for, render_template, send_file, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

# Variables de entorno desde un archivo .env junto a este app.py (pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave_secreta_movil_check_spycomers_2026")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Clave compartida con SPYnet para el ingreso directo.
# Tiene que ser EXACTAMENTE la misma que SSO_SECRET en el app.py de SPYnet.
# (Si algún día se define SSO_SECRET en un .env, se usa esa en lugar de esta.)
SSO_SECRET = os.environ.get("SSO_SECRET") or "4526185811c46a455c4e91710a766fa1242943a7ac0cf535bc070f292da3d292"

# ==========================================
# CONFIGURACIÓN DE BASE DE DATOS
# ==========================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'moviles.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DB_PATH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ==========================================
# MODELOS DE BASE DE DATOS
# ==========================================
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), unique=True, nullable=False)
    contrasena = db.Column(db.String(120), nullable=False)
    rol = db.Column(db.String(30), default="Chofer")
    activo = db.Column(db.Boolean, default=True, nullable=False)
    # Nombre de usuario con el que esta persona entra a SPYnet (para el ingreso directo)
    usuario_spynet = db.Column(db.String(80), nullable=True)
    checklists = db.relationship('Checklist', backref='usuario', lazy=True)

class Vehiculo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nro_movil = db.Column(db.Integer, nullable=False)
    marca = db.Column(db.String(50), nullable=False)
    modelo = db.Column(db.String(50), nullable=False)
    ano = db.Column(db.Integer, nullable=False)
    chofer_asignado_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    chofer_asignado = db.relationship('Usuario', foreign_keys=[chofer_asignado_id])
    fecha_registro = db.Column(db.String(20), nullable=True)
    checklists = db.relationship('Checklist', backref='vehiculo', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('nro_movil', 'chofer_asignado_id', name='uq_movil_chofer'),
    )

class Checklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculo.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    fecha_control = db.Column(db.String(20), nullable=False)
    aceite = db.Column(db.String(20), nullable=False, default="Optimo")
    agua = db.Column(db.String(20), nullable=False, default="Optimo")
    fluido = db.Column(db.String(20), nullable=False, default="Optimo")
    otros_fluidos = db.Column(db.String(20), nullable=False, default="Optimo")
    luces_freno = db.Column(db.Boolean, default=False)
    luz_baja = db.Column(db.Boolean, default=False)
    luz_alta = db.Column(db.Boolean, default=False)
    senaleros = db.Column(db.Boolean, default=False)
    luz_otro = db.Column(db.Boolean, default=False)
    luz_otro_detalle = db.Column(db.String(250), nullable=True)
    estado_cubiertas = db.Column(db.String(50), default="Bueno")
    kilometraje_actual = db.Column(db.Integer, nullable=False)
    combustible_nivel = db.Column(db.String(20), nullable=False)
    fecha_abastecimiento = db.Column(db.String(20), nullable=True)
    litros_cargados = db.Column(db.Float, nullable=True, default=0.0)
    monto_gastado = db.Column(db.Integer, nullable=True, default=0)
    observaciones_mecanica = db.Column(db.String(250), nullable=True)

class Auditoria(db.Model):
    """Registro de todo lo que pasa en el sistema. No tiene clave foránea a Usuario
    a propósito: el registro se conserva aunque el usuario se elimine después."""
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    usuario_id = db.Column(db.Integer, nullable=True)
    usuario_nombre = db.Column(db.String(80), nullable=False, default="Anónimo")
    accion = db.Column(db.String(60), nullable=False)
    detalle = db.Column(db.String(500), nullable=True)
    ip = db.Column(db.String(60), nullable=True)

# ==========================================
# ARREGLO AUTOMÁTICO DE LA BASE DE DATOS
# (se corre solo, sin perder ningún dato existente)
# ==========================================
def _columnas(cur, tabla):
    cur.execute(f"PRAGMA table_info({tabla})")
    return [c[1] for c in cur.fetchall()]

def arreglar_base_datos_si_hace_falta():
    if not os.path.exists(DB_PATH):
        return  # base nueva, no hay nada que arreglar

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    columnas = _columnas(cur, "vehiculo")
    if columnas and "chofer_asignado_id" not in columnas:
        print("🔧 Actualizando estructura de la base de datos (no se pierde ningún dato)...")
        cur.execute("ALTER TABLE vehiculo RENAME TO vehiculo_old")
        cur.execute("""
            CREATE TABLE vehiculo (
                id INTEGER NOT NULL PRIMARY KEY,
                nro_movil INTEGER NOT NULL,
                marca VARCHAR(50) NOT NULL,
                modelo VARCHAR(50) NOT NULL,
                ano INTEGER NOT NULL,
                chofer_asignado_id INTEGER,
                fecha_registro VARCHAR(20),
                FOREIGN KEY(chofer_asignado_id) REFERENCES usuario (id),
                CONSTRAINT uq_movil_chofer UNIQUE (nro_movil, chofer_asignado_id)
            )
        """)
        fecha_hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
        cur.execute("""
            INSERT INTO vehiculo (id, nro_movil, marca, modelo, ano, chofer_asignado_id, fecha_registro)
            SELECT id, nro_movil, marca, modelo, ano, NULL, ? FROM vehiculo_old
        """, (fecha_hoy,))
        cur.execute("DROP TABLE vehiculo_old")
        print("✅ Tabla de vehículos actualizada.")
    elif columnas and "fecha_registro" not in columnas:
        cur.execute("ALTER TABLE vehiculo ADD COLUMN fecha_registro VARCHAR(20)")
        fecha_hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
        cur.execute("UPDATE vehiculo SET fecha_registro = ? WHERE fecha_registro IS NULL", (fecha_hoy,))
        print("✅ Columna 'fecha_registro' agregada.")

    col_usuario = _columnas(cur, "usuario")
    if col_usuario and "usuario_spynet" not in col_usuario:
        cur.execute("ALTER TABLE usuario ADD COLUMN usuario_spynet VARCHAR(80)")
        print("✅ Columna 'usuario_spynet' agregada.")

    col_check = _columnas(cur, "checklist")
    if col_check and "luz_otro" not in col_check:
        cur.execute("ALTER TABLE checklist ADD COLUMN luz_otro BOOLEAN DEFAULT 0")
        print("✅ Columna 'luz_otro' agregada.")
    if col_check and "luz_otro_detalle" not in col_check:
        cur.execute("ALTER TABLE checklist ADD COLUMN luz_otro_detalle VARCHAR(250)")
        print("✅ Columna 'luz_otro_detalle' agregada.")

    conn.commit()
    conn.close()

# ==========================================
# UTILIDADES GENERALES
# ==========================================
def a_entero(valor, defecto=0):
    try:
        return int(str(valor).replace(".", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return defecto

def a_decimal(valor, defecto=0.0):
    try:
        return float(str(valor).replace(",", ".").strip())
    except (TypeError, ValueError):
        return defecto

def miles(n):
    return f"{int(n or 0):,}".replace(",", ".")

def mensaje(texto, volver_url, volver_texto="Volver"):
    return f"<h3>{esc(texto)}</h3><a href='{volver_url}'>{esc(volver_texto)}</a>"

# ==========================================
# SESIÓN Y REGISTRO DE ACTIVIDAD
# ==========================================
def usuario_actual():
    uid = session.get("user_id")
    if not uid:
        return None
    u = db.session.get(Usuario, uid)
    return u if u and u.activo else None

def iniciar_sesion(u):
    session.clear()
    session["user_id"] = u.id
    session.permanent = True

def url_config():
    return url_for('sistema_pestañas', user_id=usuario_actual().id, pestana='configuracion')

def registrar(accion, detalle="", usuario=None):
    """Anota una acción en la tabla de auditoría. Nunca rompe la acción principal."""
    try:
        u = usuario or usuario_actual()
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
        db.session.add(Auditoria(
            usuario_id=u.id if u else None,
            usuario_nombre=u.nombre if u else "Anónimo",
            accion=accion,
            detalle=(detalle or "")[:500],
            ip=ip[:60],
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ No se pudo registrar la auditoría: {e}")

RUTAS_PUBLICAS = {"login_web", "autenticar", "sso_spynet", "salir", "static"}

@app.before_request
def exigir_sesion():
    if request.endpoint is None or request.endpoint in RUTAS_PUBLICAS:
        return
    if not usuario_actual():
        session.clear()
        return redirect(url_for("login_web"))

def usuario_spynet_en_uso(valor, excluir_id=None):
    q = Usuario.query.filter(db.func.lower(Usuario.usuario_spynet) == valor.lower())
    if excluir_id:
        q = q.filter(Usuario.id != excluir_id)
    return q.first() is not None

# ==========================================
# INGRESO DIRECTO DESDE SPYNET (SSO)
# Token = base64url(JSON) + "." + HMAC-SHA256(base64url(JSON), SSO_SECRET) en hexadecimal
# JSON = {"usuario": "...", "exp": <unix timestamp>, "nonce": "..."}
# ==========================================
def verificar_token_sso(token):
    if not SSO_SECRET or not token or "." not in token:
        return None
    try:
        datos_b64, firma = token.rsplit(".", 1)
        esperada = hmac.new(SSO_SECRET.encode(), datos_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(esperada, firma.lower()):
            return None
        relleno = "=" * (-len(datos_b64) % 4)
        datos = json.loads(base64.urlsafe_b64decode(datos_b64 + relleno))
        if int(datos.get("exp", 0)) < time.time():
            return None
        return datos
    except Exception:
        return None

ROLES_SPYNET = {"admin": "Admin", "administrador": "Admin", "mecánico": "Mecánico", "mecanico": "Mecánico"}

def _rol_desde_spynet(rol):
    """Traduce el rol que manda SPYnet a los roles de Movil Check. Todo lo demás queda como Chofer."""
    return ROLES_SPYNET.get((rol or "").strip().lower(), "Chofer")

def _nombre_disponible(base, usuario_spynet):
    """El nombre es único en Movil Check: si ya está ocupado, se le agrega el usuario de SPYnet."""
    candidatos = [base, f"{base} ({usuario_spynet})"]
    candidatos += [f"{base} ({usuario_spynet} {i})" for i in range(2, 50)]
    for nombre in candidatos:
        nombre = nombre[:80]
        if not Usuario.query.filter_by(nombre=nombre).first():
            return nombre
    return f"{usuario_spynet}-{secrets.token_hex(3)}"[:80]

@app.route("/sso")
def sso_spynet():
    datos = verificar_token_sso(request.args.get("token", ""))
    if not datos:
        session.clear()   # un pase inválido no deja ninguna sesión abierta (y se registra como anónimo)
        registrar("Ingreso SPYnet rechazado", "Token inválido, vencido o SSO desactivado")
        return redirect(url_for("login_web"))

    usuario_spynet = (datos.get("usuario") or "").strip()[:80]
    nombre_spynet = (datos.get("nombre") or usuario_spynet).strip()[:80]
    if not usuario_spynet:
        registrar("Ingreso SPYnet rechazado", "El token no trae usuario")
        return redirect(url_for("login_web"))

    # 1) ¿Ya entró antes desde SPYnet?
    u = Usuario.query.filter(db.func.lower(Usuario.usuario_spynet) == usuario_spynet.lower()).first()
    novedad = None

    if not u:
        # 2) ¿Existe en Movil Check alguien con el mismo nombre y sin vincular? Se lo vincula.
        u = (Usuario.query
             .filter(db.func.lower(Usuario.nombre) == nombre_spynet.lower(), Usuario.usuario_spynet.is_(None))
             .first())
        if u:
            u.usuario_spynet = usuario_spynet
            novedad = ("Usuario vinculado a SPYnet", f"{u.nombre} <- SPYnet '{usuario_spynet}'")
        else:
            # 3) Es la primera vez: se crea el usuario automáticamente.
            #    Contraseña aleatoria: solo puede entrar desde SPYnet, salvo que un admin le asigne una.
            u = Usuario(
                nombre=_nombre_disponible(nombre_spynet, usuario_spynet),
                contrasena=secrets.token_urlsafe(24),
                rol=_rol_desde_spynet(datos.get("rol")),
                activo=True,
                usuario_spynet=usuario_spynet,
            )
            db.session.add(u)
            novedad = ("Usuario creado desde SPYnet", f"{nombre_spynet} · SPYnet '{usuario_spynet}'")
        db.session.commit()

    if not u.activo:
        registrar("Ingreso SPYnet de usuario inactivo", f"{u.nombre} · SPYnet '{usuario_spynet}'", usuario=u)
        return mensaje("❌ Tu usuario está desactivado en Movil Check. Consultá con un administrador.",
                       url_for("login_web"), "Volver")

    iniciar_sesion(u)
    if novedad:
        registrar(novedad[0], novedad[1] + f" · Rol: {u.rol}", usuario=u)
    registrar("Inicio de sesión (SPYnet)", f"Ingreso directo desde SPYnet como '{usuario_spynet}'", usuario=u)
    return redirect(url_for('sistema_pestañas', user_id=u.id, pestana='check'))

# ==========================================
# FUNCIÓN COMPARTIDA: último chofer / última fecha por móvil
# ==========================================
def calcular_ultimo_uso(vehiculos):
    for v in vehiculos:
        ultimo_checklist = (
            Checklist.query
            .filter_by(vehiculo_id=v.id)
            .order_by(Checklist.id.desc())
            .first()
        )
        if ultimo_checklist:
            v.ultimo_chofer = ultimo_checklist.usuario.nombre
            v.ultima_fecha = ultimo_checklist.fecha_control
            v.uso_confirmado = True
        else:
            v.ultimo_chofer = v.chofer_asignado.nombre if v.chofer_asignado else "Sin asignar"
            v.ultima_fecha = v.fecha_registro or "-"
            v.uso_confirmado = False
    return vehiculos

# ==========================================
# INGRESO / SALIDA
# ==========================================
@app.route("/")
def login_web():
    u = usuario_actual()
    if u:
        return redirect(url_for('sistema_pestañas', user_id=u.id, pestana='check'))
    return render_template("login.html")

@app.route("/autenticar", methods=["POST"])
def autenticar():
    nombre_ingresado = (request.form.get("nombre_usuario") or "").strip()
    clave_ingresada = request.form.get("contrasena") or ""
    u = Usuario.query.filter_by(nombre=nombre_ingresado, activo=True).first()

    if u and u.contrasena == clave_ingresada:
        iniciar_sesion(u)
        registrar("Inicio de sesión", "Ingreso con usuario y contraseña", usuario=u)
        return redirect(url_for('sistema_pestañas', user_id=u.id, pestana='check'))

    registrar("Ingreso fallido", f"Nombre ingresado: {nombre_ingresado}")
    return mensaje("❌ Usuario no encontrado, inactivo o clave incorrecta.", url_for("login_web"), "Intentar de nuevo")

@app.route("/salir")
def salir():
    u = usuario_actual()
    if u:
        registrar("Cierre de sesión", "", usuario=u)
    session.clear()
    return redirect(url_for("login_web"))

# ==========================================
# PESTAÑAS
# ==========================================
PESTANAS_VALIDAS = {"check", "registros", "configuracion"}

@app.route("/sistema/<int:user_id>/<pestana>")
def sistema_pestañas(user_id, pestana):
    usuario_activo = usuario_actual()
    if pestana not in PESTANAS_VALIDAS:
        pestana = "check"
    # La URL ya no decide quién es el usuario: manda la sesión
    if user_id != usuario_activo.id or pestana not in request.path:
        return redirect(url_for('sistema_pestañas', user_id=usuario_activo.id, pestana=pestana,
                                page=request.args.get('page')))

    vehiculos = Vehiculo.query.order_by(Vehiculo.nro_movil).all()
    calcular_ultimo_uso(vehiculos)

    pagina_actual = request.args.get('page', 1, type=int)
    paginacion = Checklist.query.order_by(Checklist.id.desc()).paginate(
        page=pagina_actual, per_page=2, error_out=False
    )

    return render_template(
        f"{pestana}.html",
        usuario=usuario_activo,
        vehiculos=vehiculos,
        controles=paginacion.items,
        paginacion=paginacion,
        usuarios=Usuario.query.all(),
        pestana_activa=pestana,
        fecha_hoy=datetime.now().strftime("%d/%m/%Y")
    )

# ==========================================
# CHECKLIST
# ==========================================
@app.route("/guardar-checklist-web", methods=["POST"])
def guardar_checklist_web():
    u = usuario_actual()
    f = request.form
    vehiculo = db.session.get(Vehiculo, a_entero(f.get("vehiculo_id")))
    if not vehiculo:
        return mensaje("❌ Elegí un móvil válido.", url_for('sistema_pestañas', user_id=u.id, pestana='check'))

    c = Checklist(
        vehiculo_id=vehiculo.id,
        usuario_id=u.id,  # siempre el usuario de la sesión, no lo que venga en el formulario
        fecha_control=datetime.now().strftime("%d/%m/%Y %H:%M"),
        aceite=f.get("aceite") or "Optimo",
        agua=f.get("agua") or "Optimo",
        fluido=f.get("fluido") or "Optimo",
        otros_fluidos=f.get("otros_fluidos") or "Optimo",
        luces_freno=bool(f.get("luces_freno")),
        luz_baja=bool(f.get("luz_baja")),
        luz_alta=bool(f.get("luz_alta")),
        senaleros=bool(f.get("senaleros")),
        luz_otro=bool(f.get("luz_otro")),
        luz_otro_detalle=(f.get("luz_otro_detalle") or "").strip() or None,
        estado_cubiertas=f.get("estado_cubiertas") or "Bueno",
        kilometraje_actual=a_entero(f.get("kilometraje_actual")),
        combustible_nivel=f.get("combustible_nivel") or "-",
        fecha_abastecimiento=f.get("fecha_abastecimiento") or None,
        litros_cargados=a_decimal(f.get("litros_cargados")),
        monto_gastado=a_entero(f.get("monto_gastado")),
        observaciones_mecanica=(f.get("observaciones_mecanica") or "").strip() or None,
    )
    db.session.add(c)
    db.session.commit()

    detalle = f"Móvil {vehiculo.nro_movil} · {miles(c.kilometraje_actual)} KM · Tanque {c.combustible_nivel}"
    bajos = [n for n, v in (("Aceite", c.aceite), ("Agua", c.agua), ("Frenos", c.fluido), ("Otros", c.otros_fluidos)) if v == "Bajo"]
    fallas = [n for n, v in (("Freno", c.luces_freno), ("Baja", c.luz_baja), ("Alta", c.luz_alta), ("Giro", c.senaleros)) if not v]
    if bajos:
        detalle += " · Fluidos bajos: " + ", ".join(bajos)
    if fallas:
        detalle += " · Luces con falla: " + ", ".join(fallas)
    if c.luz_otro:
        detalle += f" · Otra luz: {c.luz_otro_detalle or 'sin detalle'}"
    if c.fecha_abastecimiento:
        detalle += f" · Carga: {c.litros_cargados:.1f} Lts / Gs. {miles(c.monto_gastado)}"
    registrar("Checklist cargado", detalle)

    return redirect(url_for('sistema_pestañas', user_id=u.id, pestana='registros'))

# ==========================================
# USUARIOS
# ==========================================
@app.route("/registrar-usuario-nuevo", methods=["POST"])
def registrar_usuario_nuevo():
    f = request.form
    nombre = (f.get("nombre_nuevo") or "").strip()
    rol = f.get("rol_nuevo") or "Chofer"
    spy = (f.get("usuario_spynet_nuevo") or "").strip() or None

    if nombre:
        if Usuario.query.filter_by(nombre=nombre).first():
            return mensaje(f"❌ Ya existe un usuario llamado {nombre}.", url_config())
        if spy and usuario_spynet_en_uso(spy):
            return mensaje(f"❌ El usuario de SPYnet '{spy}' ya está vinculado a otra persona.", url_config())
        db.session.add(Usuario(nombre=nombre, contrasena=f.get("clave_nueva") or "", rol=rol,
                               activo=True, usuario_spynet=spy))
        db.session.commit()
        registrar("Alta de usuario", f"{nombre} · Rol: {rol}" + (f" · SPYnet: {spy}" if spy else ""))
    return redirect(url_config())

@app.route("/editar-usuario", methods=["POST"])
def editar_usuario():
    f = request.form
    u = db.session.get(Usuario, a_entero(f.get("usuario_id_editar")))
    if not u:
        return redirect(url_config())

    nuevo_nombre = (f.get("nombre_editado") or "").strip() or u.nombre
    nueva_clave = f.get("clave_editada") or ""
    nuevo_rol = f.get("rol_editado") or u.rol
    nuevo_activo = f.get("activo_editado") == "True"
    nuevo_spy = (f.get("usuario_spynet_editado") or "").strip() or None if "usuario_spynet_editado" in f else u.usuario_spynet

    if nuevo_nombre != u.nombre and Usuario.query.filter(Usuario.nombre == nuevo_nombre, Usuario.id != u.id).first():
        return mensaje(f"❌ Ya existe otro usuario llamado {nuevo_nombre}.", url_config())
    if nuevo_spy and usuario_spynet_en_uso(nuevo_spy, excluir_id=u.id):
        return mensaje(f"❌ El usuario de SPYnet '{nuevo_spy}' ya está vinculado a otra persona.", url_config())

    cambios = []
    if nuevo_nombre != u.nombre:
        cambios.append(f"nombre: {u.nombre} -> {nuevo_nombre}")
    if nueva_clave != u.contrasena:
        cambios.append("contraseña modificada")
    if nuevo_rol != u.rol:
        cambios.append(f"rol: {u.rol} -> {nuevo_rol}")
    if nuevo_activo != u.activo:
        cambios.append("activado" if nuevo_activo else "desactivado")
    if nuevo_spy != u.usuario_spynet:
        cambios.append(f"SPYnet: {u.usuario_spynet or '-'} -> {nuevo_spy or '-'}")

    u.nombre, u.contrasena, u.rol, u.activo, u.usuario_spynet = nuevo_nombre, nueva_clave, nuevo_rol, nuevo_activo, nuevo_spy
    db.session.commit()
    if cambios:
        registrar("Edición de usuario", f"{u.nombre}: " + "; ".join(cambios))
    return redirect(url_config())

@app.route("/eliminar-usuario/<int:uid>", methods=["POST"])
def eliminar_usuario(uid):
    actual = usuario_actual()
    u = db.session.get(Usuario, uid)
    if not u:
        return redirect(url_config())
    if u.id == actual.id:
        return mensaje("❌ No podés eliminar tu propio usuario.", url_config())

    cantidad = Checklist.query.filter_by(usuario_id=uid).count()
    if cantidad:
        # Se conserva el historial: en lugar de borrar, se desactiva
        u.activo = False
        db.session.commit()
        registrar("Usuario desactivado",
                  f"{u.nombre} tiene {cantidad} inspecciones; se desactivó en lugar de borrarlo para conservar el historial")
    else:
        nombre = u.nombre
        Vehiculo.query.filter_by(chofer_asignado_id=uid).update({"chofer_asignado_id": None})
        db.session.delete(u)
        db.session.commit()
        registrar("Baja de usuario", nombre)
    return redirect(url_config())

# ==========================================
# VEHÍCULOS
# ==========================================
@app.route("/registrar-vehiculo-nuevo", methods=["POST"])
def registrar_vehiculo_nuevo():
    f = request.form
    nro = a_entero(f.get("nro_movil"), None)
    chofer_id = a_entero(f.get("chofer_asignado_id"), None)

    if nro is not None:
        ya_existe = Vehiculo.query.filter_by(nro_movil=nro, chofer_asignado_id=chofer_id).first()
        if ya_existe:
            chofer_nombre = ya_existe.chofer_asignado.nombre if ya_existe.chofer_asignado else "sin chofer asignado"
            return mensaje(f"❌ Ya existe un registro del móvil {nro} asignado a {chofer_nombre}.", url_config())
        v = Vehiculo(
            nro_movil=nro, marca=f.get("marca") or "", modelo=f.get("modelo") or "",
            ano=a_entero(f.get("ano")), chofer_asignado_id=chofer_id,
            fecha_registro=datetime.now().strftime("%d/%m/%Y %H:%M")
        )
        db.session.add(v)
        db.session.commit()
        chofer = v.chofer_asignado.nombre if v.chofer_asignado else "Sin asignar"
        registrar("Alta de vehículo", f"Móvil {v.nro_movil} · {v.marca} {v.modelo} {v.ano} · Chofer: {chofer}")
    return redirect(url_config())

@app.route("/editar-vehiculo", methods=["POST"])
def editar_vehiculo():
    actual = usuario_actual()
    f = request.form
    v = db.session.get(Vehiculo, a_entero(f.get("vehiculo_id_editar")))

    if (f.get("clave_confirmacion") or "") != (actual.contrasena or ""):
        registrar("Edición de vehículo rechazada",
                  f"Contraseña incorrecta · Móvil {v.nro_movil if v else '?'}")
        return mensaje("❌ Contraseña incorrecta. No se guardaron los cambios.", url_config())
    if not v:
        return redirect(url_config())

    antes = {
        "nro": v.nro_movil, "marca": v.marca, "modelo": v.modelo, "año": v.ano,
        "chofer": v.chofer_asignado.nombre if v.chofer_asignado else "Sin asignar",
    }
    v.nro_movil = a_entero(f.get("nro_editado"), v.nro_movil)
    v.marca = f.get("marca_editada") or v.marca
    v.modelo = f.get("modelo_editado") or v.modelo
    v.ano = a_entero(f.get("ano_editado"), v.ano)
    v.chofer_asignado_id = a_entero(f.get("chofer_asignado_editado"), None)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return mensaje("❌ Ya existe ese número de móvil con el mismo chofer asignado.", url_config())

    despues = {
        "nro": v.nro_movil, "marca": v.marca, "modelo": v.modelo, "año": v.ano,
        "chofer": v.chofer_asignado.nombre if v.chofer_asignado else "Sin asignar",
    }
    cambios = [f"{k}: {antes[k]} -> {despues[k]}" for k in antes if antes[k] != despues[k]]
    if cambios:
        registrar("Edición de vehículo", f"Móvil {v.nro_movil}: " + "; ".join(cambios))
    return redirect(url_config())

@app.route("/eliminar-vehiculo/<int:vid>", methods=["POST"])
def eliminar_vehiculo(vid):
    actual = usuario_actual()
    v = db.session.get(Vehiculo, vid)

    if (request.form.get("clave_confirmacion") or "") != (actual.contrasena or ""):
        registrar("Eliminación de vehículo rechazada", f"Contraseña incorrecta · Móvil {v.nro_movil if v else '?'}")
        return mensaje("❌ Contraseña incorrecta. No se eliminó el vehículo.", url_config())
    if not v:
        return redirect(url_config())

    cantidad = Checklist.query.filter_by(vehiculo_id=vid).count()
    if cantidad:
        registrar("Eliminación de vehículo bloqueada", f"Móvil {v.nro_movil} tiene {cantidad} inspecciones registradas")
        return mensaje(
            f"❌ El Móvil {v.nro_movil} tiene {cantidad} inspecciones registradas. "
            "No se puede eliminar para no perder el historial.", url_config()
        )

    descripcion = f"Móvil {v.nro_movil} · {v.marca} {v.modelo} {v.ano}"
    db.session.delete(v)
    db.session.commit()
    registrar("Baja de vehículo", descripcion)
    return redirect(url_config())

# ==========================================
# PDF: PIEZAS COMPARTIDAS
# ==========================================
VERDE, AMBAR, ROJO, AZUL, GRIS = '#1e7e34', '#856404', '#d93025', '#1a73e8', '#8891A0'

def _estilos():
    e = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle('Tit', parent=e['Title'], fontSize=18, textColor=colors.HexColor(AZUL), spaceAfter=2),
        "subtitulo": ParagraphStyle('Sub', parent=e['Heading2'], fontSize=13, textColor=colors.HexColor('#0f172a'),
                                    spaceBefore=16, spaceAfter=8),
        "normal": e['Normal'],
        "celda": ParagraphStyle('Celda', parent=e['Normal'], fontSize=7.5, leading=10),
        "enc": ParagraphStyle('Enc', parent=e['Normal'], fontSize=7.5, leading=10,
                              fontName='Helvetica-Bold', textColor=colors.white),
    }

def _encabezado(titulo, usuario, est, extra=""):
    generado = datetime.now().strftime('%d/%m/%Y %H:%M')
    return [
        Paragraph(titulo, est["titulo"]),
        Paragraph(f"SPYComers &middot; Generado el {generado} por {esc(usuario.nombre)}{extra}", est["normal"]),
        Spacer(1, 10),
    ]

def _tabla(encabezados, filas, anchos_cm, est, vacio="Sin registros todavía."):
    """filas: listas de textos YA escapados (pueden tener marcado de ReportLab)."""
    datos = [[Paragraph(h, est["enc"]) for h in encabezados]]
    for fila in filas:
        datos.append([Paragraph(str(celda), est["celda"]) for celda in fila])
    if not filas:
        datos.append([Paragraph(f'<font color="{GRIS}"><i>{vacio}</i></font>', est["celda"])] + [""] * (len(encabezados) - 1))

    tabla = Table(datos, colWidths=[a * cm for a in anchos_cm], repeatRows=1, hAlign='LEFT')
    estilo = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(AZUL)),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, colors.HexColor('#e3e5e8')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ])
    if not filas:
        estilo.add('SPAN', (0, 1), (-1, 1))
    tabla.setStyle(estilo)
    return tabla

def _generar_pdf(elementos, nombre_base, titulo_doc):
    generado = datetime.now().strftime('%d/%m/%Y %H:%M')
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=1.2 * cm, bottomMargin=1.5 * cm, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
        title=titulo_doc
    )

    def pie(canvas, d):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(colors.HexColor(GRIS))
        canvas.drawString(1.2 * cm, 0.7 * cm, f"Movil Check · SPYComers · Generado el {generado}")
        canvas.drawRightString(landscape(A4)[0] - 1.2 * cm, 0.7 * cm, f"Página {d.page}")
        canvas.restoreState()

    doc.build(elementos, onFirstPage=pie, onLaterPages=pie)
    buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                     download_name=f"{nombre_base}_{datetime.now():%Y%m%d_%H%M}.pdf")

def _nivel(etiqueta, valor):
    if valor == 'Bajo':
        return f'<font color="{ROJO}"><b>{etiqueta}: Bajo</b></font>'
    if valor == 'Medio':
        return f'<font color="{AMBAR}">{etiqueta}: Medio</font>'
    return f'<font color="{VERDE}">{etiqueta}: Óptimo</font>'

def _luz(etiqueta, ok):
    if ok:
        return f'<font color="{VERDE}">{etiqueta}: OK</font>'
    return f'<font color="{ROJO}"><b>{etiqueta}: Falla</b></font>'

def _cubiertas(estado):
    if estado == "Critico":
        return f'<font color="{ROJO}"><b>Crítico</b></font>'
    if estado == "Regular":
        return f'<font color="{AMBAR}">Regular</font>'
    return f'<font color="{VERDE}">{esc(estado or "Bueno")}</font>'

COLUMNAS_CHECK = ["Fecha / Hora", "Móvil", "Inspector", "Niveles de Fluidos", "Luces",
                  "Kilometraje", "Abastecimiento", "Novedades"]
ANCHOS_CHECK = [2.4, 1.7, 2.8, 3.2, 2.6, 2.9, 3.9, 7.8]  # suma 27.3 cm = ancho útil A4 horizontal

def _filas_checklists(checklists):
    filas = []
    for c in checklists:
        luces = "<br/>".join([_luz("Freno", c.luces_freno), _luz("Baja", c.luz_baja),
                              _luz("Alta", c.luz_alta), _luz("Giro", c.senaleros)])
        if c.luz_otro:
            luces += f'<br/><font color="{ROJO}"><b>Otro:</b> {esc(c.luz_otro_detalle or "sin detalle")}</font>'

        if c.fecha_abastecimiento:
            abastecimiento = (
                f"<b>{esc(c.fecha_abastecimiento)}</b><br/>"
                f'Litros: <font color="{AZUL}"><b>{(c.litros_cargados or 0):.1f} Lts</b></font><br/>'
                f'Gasto: <font color="{VERDE}"><b>Gs. {miles(c.monto_gastado)}</b></font>'
            )
        else:
            abastecimiento = f'<font color="{GRIS}"><i>Sin cargas</i></font>'

        novedades = (f'<font color="#c92a2a">{esc(c.observaciones_mecanica)}</font>'
                     if c.observaciones_mecanica else f'<font color="{GRIS}"><i>Sin novedades</i></font>')

        filas.append([
            f"<b>{esc(c.fecha_control)}</b>",
            f'<font color="{AZUL}"><b>Móvil {c.vehiculo.nro_movil}</b></font>',
            f'{esc(c.usuario.nombre)}<br/><font color="{GRIS}">({esc(c.usuario.rol or "")})</font>',
            "<br/>".join([_nivel("Aceite", c.aceite), _nivel("Agua", c.agua),
                          _nivel("Frenos", c.fluido), _nivel("Otros", c.otros_fluidos)]),
            luces,
            f"<b>{miles(c.kilometraje_actual)} KM</b><br/>Tanque: {esc(c.combustible_nivel or '-')}"
            f"<br/>Cubiertas: {_cubiertas(c.estado_cubiertas)}",
            abastecimiento,
            novedades,
        ])
    return filas

COLUMNAS_AUDIT = ["Fecha", "Usuario", "Acción", "Detalle", "IP"]
ANCHOS_AUDIT = [3.2, 4.0, 4.6, 12.5, 3.0]

def _filas_auditoria(registros):
    return [[
        a.fecha.strftime('%d/%m/%Y %H:%M:%S'),
        esc(a.usuario_nombre),
        f"<b>{esc(a.accion)}</b>",
        esc(a.detalle or "-"),
        esc(a.ip or "-"),
    ] for a in registros]

def _resumen_cargas(checklists):
    con_carga = [c for c in checklists if c.fecha_abastecimiento]
    litros = sum(c.litros_cargados or 0 for c in con_carga)
    gasto = sum(c.monto_gastado or 0 for c in con_carga)
    return (f"<br/><b>{len(checklists)}</b> inspecciones &middot; Total cargado: <b>{litros:.1f} Lts</b> "
            f"&middot; Gasto total: <b>Gs. {miles(gasto)}</b>")

# ==========================================
# PDF: RUTAS
# ==========================================
@app.route("/informe-pdf/<int:user_id>")
def informe_pdf(user_id):
    u = usuario_actual()
    registrar("Descarga de PDF", "Informe completo")
    est = _estilos()

    vehiculos = Vehiculo.query.order_by(Vehiculo.nro_movil).all()
    calcular_ultimo_uso(vehiculos)
    usuarios = Usuario.query.order_by(Usuario.nombre).all()
    checklists = Checklist.query.order_by(Checklist.id.desc()).all()
    auditoria = Auditoria.query.order_by(Auditoria.id.desc()).all()

    elementos = _encabezado("Informe General — Movil Check", u, est, _resumen_cargas(checklists))

    elementos.append(Paragraph(f"Vehículos Registrados en la Flota ({len(vehiculos)})", est["subtitulo"]))
    elementos.append(_tabla(
        ["Nro. Móvil", "Marca", "Modelo", "Año", "Chofer Asignado", "Último Chofer", "Última Fecha"],
        [[f"<b>{v.nro_movil}</b>", esc(v.marca), esc(v.modelo), str(v.ano),
          esc(v.chofer_asignado.nombre if v.chofer_asignado else "Sin asignar"),
          esc(v.ultimo_chofer), esc(v.ultima_fecha)] for v in vehiculos],
        [2.0, 3.5, 3.5, 1.8, 5.0, 5.0, 6.5], est
    ))

    elementos.append(Paragraph(f"Usuarios Registrados ({len(usuarios)})", est["subtitulo"]))
    elementos.append(_tabla(
        ["Nombre", "Rol", "Usuario SPYnet", "Activo"],
        [[esc(x.nombre), esc(x.rol or ""), esc(x.usuario_spynet or "-"),
          f'<font color="{VERDE}">Sí</font>' if x.activo else f'<font color="{ROJO}">No</font>'] for x in usuarios],
        [7.0, 4.0, 6.0, 3.0], est
    ))

    elementos.append(PageBreak())
    elementos.append(Paragraph(f"Historial de Inspecciones ({len(checklists)})", est["subtitulo"]))
    elementos.append(_tabla(COLUMNAS_CHECK, _filas_checklists(checklists), ANCHOS_CHECK, est))

    elementos.append(PageBreak())
    elementos.append(Paragraph(f"Registro de Actividad ({len(auditoria)})", est["subtitulo"]))
    elementos.append(_tabla(COLUMNAS_AUDIT, _filas_auditoria(auditoria), ANCHOS_AUDIT, est))

    return _generar_pdf(elementos, "informe_movilcheck", "Informe General — Movil Check")

@app.route("/historial-pdf/<int:user_id>")
def historial_pdf(user_id):
    u = usuario_actual()
    registrar("Descarga de PDF", "Historial de inspecciones")
    est = _estilos()
    checklists = Checklist.query.order_by(Checklist.id.desc()).all()

    elementos = _encabezado("Historial de Inspecciones — Movil Check", u, est, _resumen_cargas(checklists))
    elementos.append(_tabla(COLUMNAS_CHECK, _filas_checklists(checklists), ANCHOS_CHECK, est,
                            vacio="No hay registros cargados todavía."))
    return _generar_pdf(elementos, "historial_inspecciones", "Historial de Inspecciones")

@app.route("/auditoria-pdf")
def auditoria_pdf():
    u = usuario_actual()
    registrar("Descarga de PDF", "Registro de actividad")
    est = _estilos()
    registros = Auditoria.query.order_by(Auditoria.id.desc()).all()

    elementos = _encabezado("Registro de Actividad — Movil Check", u, est,
                            f"<br/><b>{len(registros)}</b> movimientos registrados")
    elementos.append(_tabla(COLUMNAS_AUDIT, _filas_auditoria(registros), ANCHOS_AUDIT, est))
    return _generar_pdf(elementos, "registro_actividad", "Registro de Actividad")

# ==========================================
# ESTO SE EJECUTA SIEMPRE QUE SE CARGA app.py
# (tanto con "python app.py" como con Gunicorn: gunicorn app:app)
# ==========================================
arreglar_base_datos_si_hace_falta()

with app.app_context():
    db.create_all()  # crea sólo lo que falte (por ejemplo, la tabla de auditoría); no toca datos existentes
    if Usuario.query.count() == 0:
        db.session.add(Usuario(nombre="Oscar", contrasena="", rol="Admin", activo=True))
        db.session.commit()

# ==========================================
# ESTO SOLO SE EJECUTA SI CORRÉS "python app.py" DIRECTO
# ==========================================
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8080)