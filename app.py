import os
import sqlite3
from io import BytesIO
from flask import Flask, request, redirect, url_for, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

app = Flask(__name__)
app.secret_key = "clave_secreta_movil_check_spycomers_2026"

# ==========================================
# CONFIGURACIÓN DE BASE DE DATOS
# ==========================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'moviles.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DB_PATH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ==========================================
# MODELOS DE BASE DE 
# DATOS
# ==========================================
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), unique=True, nullable=False)
    contrasena = db.Column(db.String(120), nullable=False)
    rol = db.Column(db.String(30), default="Chofer")
    activo = db.Column(db.Boolean, default=True, nullable=False)
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
    estado_cubiertas = db.Column(db.String(50), default="Bueno")
    kilometraje_actual = db.Column(db.Integer, nullable=False)
    combustible_nivel = db.Column(db.String(20), nullable=False)
    fecha_abastecimiento = db.Column(db.String(20), nullable=True)
    litros_cargados = db.Column(db.Float, nullable=True, default=0.0)
    monto_gastado = db.Column(db.Integer, nullable=True, default=0)
    observaciones_mecanica = db.Column(db.String(250), nullable=True)

# ==========================================
# ARREGLO AUTOMÁTICO DE LA BASE DE DATOS
# (se corre solo, una vez, sin perder ningún dato existente)
# ==========================================
def arreglar_base_datos_si_hace_falta():
    if not os.path.exists(DB_PATH):
        return  # base nueva, no hay nada que arreglar

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(vehiculo)")
    columnas = [c[1] for c in cur.fetchall()]

    if "chofer_asignado_id" not in columnas:
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
        conn.commit()
        print("✅ Base de datos actualizada. Todos los vehículos existentes se conservaron.")
    elif "fecha_registro" not in columnas:
        print("🔧 Agregando columna 'fecha_registro' (no se pierde ningún dato)...")
        cur.execute("ALTER TABLE vehiculo ADD COLUMN fecha_registro VARCHAR(20)")
        fecha_hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
        cur.execute("UPDATE vehiculo SET fecha_registro = ? WHERE fecha_registro IS NULL", (fecha_hoy,))
        conn.commit()
        print("✅ Base de datos actualizada.")

    conn.close()

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
# RUTAS DEL ENRUTADOR WEB
# ==========================================
@app.route("/")
def login_web():
    return render_template("login.html")

@app.route("/autenticar", methods=["POST"])
def autenticar():
    nombre_ingresado = request.form.get("nombre_usuario")
    clave_ingresada = request.form.get("contrasena") or ""
    usuario_encontrado = Usuario.query.filter_by(nombre=nombre_ingresado, activo=True).first()
    
    if usuario_encontrado and usuario_encontrado.contrasena == clave_ingresada:
        return redirect(url_for('sistema_pestañas', user_id=usuario_encontrado.id, pestana='check'))
    else:
        return "<h3>❌ Usuario no encontrado, inactivo o clave incorrecta.</h3><a href='/'>Intentar de nuevo</a>"

@app.route("/sistema/<int:user_id>/<pestana>")
def sistema_pestañas(user_id, pestana):
    usuario_activo = Usuario.query.get(user_id)
    if not usuario_activo or not usuario_activo.activo:
        return redirect(url_for('login_web'))

    vehiculos = Vehiculo.query.order_by(Vehiculo.nro_movil).all()
    calcular_ultimo_uso(vehiculos)

    pagina_actual = request.args.get('page', 1, type=int)
    paginacion = Checklist.query.order_by(Checklist.id.desc()).paginate(
        page=pagina_actual, per_page=2, error_out=False
    )
    controles = paginacion.items

    todos_usuarios = Usuario.query.all()
    fecha_hoy = datetime.now().strftime("%d/%m/%Y")
    
    archivo_html = f"{pestana}.html"
    return render_template(
        archivo_html, 
        usuario=usuario_activo, 
        vehiculos=vehiculos, 
        controles=controles,
        paginacion=paginacion,
        usuarios=todos_usuarios,
        pestana_activa=pestana,
        fecha_hoy=fecha_hoy
    )

@app.route("/guardar-checklist-web", methods=["POST"])
def guardar_checklist_web():
    u_id = request.form.get("usuario_id")
    v_id = request.form.get("vehiculo_id")
    fecha_hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
    litros = request.form.get("litros_cargados")
    monto = request.form.get("monto_gastado")
    
    nuevo_registro = Checklist(
        vehiculo_id=v_id, usuario_id=u_id, fecha_control=fecha_hoy,
        aceite=request.form.get("aceite") or "Optimo", agua=request.form.get("agua") or "Optimo", fluido=request.form.get("fluido") or "Optimo", otros_fluidos=request.form.get("otros_fluidos") or "Optimo",
        luces_freno=True if request.form.get("luces_freno") else False, luz_baja=True if request.form.get("luz_baja") else False, luz_alta=True if request.form.get("luz_alta") else False, senaleros=True if request.form.get("senaleros") else False,
        estado_cubiertas=request.form.get("estado_cubiertas"), kilometraje_actual=request.form.get("kilometraje_actual") or 0, combustible_nivel=request.form.get("combustible_nivel"),
        fecha_abastecimiento=request.form.get("fecha_abastecimiento"), litros_cargados=float(litros) if litros else 0.0, monto_gastado=int(monto) if monto else 0,
        observaciones_mecanica=request.form.get("observaciones_mecanica")
    )
    db.session.add(nuevo_registro)
    db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id, pestana='registros'))

@app.route("/registrar-usuario-nuevo", methods=["POST"])
def registrar_usuario_nuevo():
    u_id_admin = request.form.get("admin_id")
    nombre_nuevo = request.form.get("nombre_nuevo")
    clave_nueva = request.form.get("clave_nueva") or ""
    rol_nuevo = request.form.get("rol_nuevo")
    if nombre_nuevo:
        db.session.add(Usuario(nombre=nombre_nuevo, contrasena=clave_nueva, rol=rol_nuevo, activo=True))
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

@app.route("/editar-usuario", methods=["POST"])
def editar_usuario():
    u_id_admin = request.form.get("admin_id")
    u_id_editar = request.form.get("usuario_id_editar")
    user_modificar = Usuario.query.get(u_id_editar)
    if user_modificar:
        user_modificar.nombre = request.form.get("nombre_editado")
        user_modificar.contrasena = request.form.get("clave_editada") or ""
        user_modificar.rol = request.form.get("rol_editado")
        estado_activo = request.form.get("activo_editado")
        user_modificar.activo = True if estado_activo == "True" else False
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

@app.route("/eliminar-usuario/<int:uid>", methods=["POST"])
def eliminar_usuario(uid):
    u_id_admin = request.form.get("admin_id")
    user_borrar = Usuario.query.get(uid)
    if user_borrar:
        Checklist.query.filter_by(usuario_id=uid).delete()
        db.session.delete(user_borrar)
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

@app.route("/registrar-vehiculo-nuevo", methods=["POST"])
def registrar_vehiculo_nuevo():
    u_id_admin = request.form.get("admin_id")
    nro = request.form.get("nro_movil")
    marca = request.form.get("marca")
    modelo = request.form.get("modelo")
    ano = request.form.get("ano")
    chofer_id_raw = request.form.get("chofer_asignado_id")
    chofer_id = int(chofer_id_raw) if chofer_id_raw else None

    if nro:
        ya_existe = Vehiculo.query.filter_by(nro_movil=int(nro), chofer_asignado_id=chofer_id).first()
        if ya_existe:
            chofer_nombre = ya_existe.chofer_asignado.nombre if ya_existe.chofer_asignado else "sin chofer asignado"
            return (
                f"<h3>❌ Ya existe un registro del móvil {nro} asignado a {chofer_nombre}.</h3>"
                f"<a href='{url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion')}'>Volver</a>"
            )
        db.session.add(Vehiculo(
            nro_movil=int(nro), marca=marca, modelo=modelo, ano=int(ano),
            chofer_asignado_id=chofer_id,
            fecha_registro=datetime.now().strftime("%d/%m/%Y %H:%M")
        ))
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

@app.route("/editar-vehiculo", methods=["POST"])
def editar_vehiculo():
    u_id_admin = request.form.get("admin_id")
    clave_confirmacion = request.form.get("clave_confirmacion") or ""
    admin = Usuario.query.get(u_id_admin)

    if not admin or clave_confirmacion != (admin.contrasena or ""):
        return (
            "<h3>❌ Contraseña incorrecta. No se guardaron los cambios.</h3>"
            f"<a href='{url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion')}'>Volver</a>"
        )

    v_id_editar = request.form.get("vehiculo_id_editar")
    vehiculo_modificar = Vehiculo.query.get(v_id_editar)
    if vehiculo_modificar:
        vehiculo_modificar.nro_movil = int(request.form.get("nro_editado"))
        vehiculo_modificar.marca = request.form.get("marca_editada")
        vehiculo_modificar.modelo = request.form.get("modelo_editado")
        vehiculo_modificar.ano = int(request.form.get("ano_editado"))
        chofer_id_raw = request.form.get("chofer_asignado_editado")
        vehiculo_modificar.chofer_asignado_id = int(chofer_id_raw) if chofer_id_raw else None
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

@app.route("/eliminar-vehiculo/<int:vid>", methods=["POST"])
def eliminar_vehiculo(vid):
    u_id_admin = request.form.get("admin_id")
    clave_confirmacion = request.form.get("clave_confirmacion") or ""
    admin = Usuario.query.get(u_id_admin)

    if not admin or clave_confirmacion != (admin.contrasena or ""):
        return (
            "<h3>❌ Contraseña incorrecta. No se eliminó el vehículo.</h3>"
            f"<a href='{url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion')}'>Volver</a>"
        )

    vehiculo_borrar = Vehiculo.query.get(vid)
    if vehiculo_borrar:
        Checklist.query.filter_by(vehiculo_id=vid).delete()
        db.session.delete(vehiculo_borrar)
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

@app.route("/informe-pdf/<int:user_id>")
def informe_pdf(user_id):
    usuario_activo = Usuario.query.get(user_id)
    if not usuario_activo or not usuario_activo.activo:
        return redirect(url_for('login_web'))

    vehiculos = Vehiculo.query.order_by(Vehiculo.nro_movil).all()
    calcular_ultimo_uso(vehiculos)
    usuarios = Usuario.query.all()
    checklists = Checklist.query.order_by(Checklist.id.desc()).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
        leftMargin=1.2 * cm, rightMargin=1.2 * cm
    )
    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle(
        'TituloInforme', parent=estilos['Title'],
        fontSize=18, textColor=colors.HexColor('#1a73e8'), spaceAfter=2
    )
    estilo_subtitulo = ParagraphStyle(
        'Subtitulo', parent=estilos['Heading2'],
        fontSize=13, textColor=colors.HexColor('#0f172a'),
        spaceBefore=16, spaceAfter=8
    )

    def estilo_tabla():
        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ])

    elementos = []
    elementos.append(Paragraph("Informe General — Movil Check", estilo_titulo))
    elementos.append(Paragraph(
        f"SPYComers &middot; Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} "
        f"por {usuario_activo.nombre}",
        estilos['Normal']
    ))

    # --- VEHÍCULOS ---
    elementos.append(Paragraph(f"Vehículos Registrados en la Flota ({len(vehiculos)})", estilo_subtitulo))
    datos_vehiculos = [["Nro. Móvil", "Marca", "Modelo", "Año", "Chofer Asignado", "Último Chofer", "Última Fecha"]]
    for v in vehiculos:
        datos_vehiculos.append([
            str(v.nro_movil), v.marca, v.modelo, str(v.ano),
            v.chofer_asignado.nombre if v.chofer_asignado else "Sin asignar",
            v.ultimo_chofer, v.ultima_fecha
        ])
    tabla_vehiculos = Table(datos_vehiculos, repeatRows=1, hAlign='LEFT')
    tabla_vehiculos.setStyle(estilo_tabla())
    elementos.append(tabla_vehiculos)

    # --- USUARIOS ---
    elementos.append(Paragraph(f"Usuarios Registrados ({len(usuarios)})", estilo_subtitulo))
    datos_usuarios = [["Nombre", "Rol", "Activo"]]
    for u in usuarios:
        datos_usuarios.append([u.nombre, u.rol, "Sí" if u.activo else "No"])
    tabla_usuarios = Table(datos_usuarios, repeatRows=1, hAlign='LEFT', colWidths=[6 * cm, 4 * cm, 3 * cm])
    tabla_usuarios.setStyle(estilo_tabla())
    elementos.append(tabla_usuarios)

    # --- HISTORIAL DE INSPECCIONES ---
    elementos.append(PageBreak())
    elementos.append(Paragraph(f"Historial de Inspecciones ({len(checklists)})", estilo_subtitulo))
    datos_checklists = [[
        "Fecha", "Móvil", "Inspector", "Aceite", "Agua", "Frenos",
        "Otros Fl.", "Luces OK", "KM", "Combustible", "Observaciones"
    ]]
    if checklists:
        for c in checklists:
            luces_ok = sum([c.luces_freno, c.luz_baja, c.luz_alta, c.senaleros])
            datos_checklists.append([
                c.fecha_control, f"Móvil {c.vehiculo.nro_movil}", c.usuario.nombre,
                c.aceite, c.agua, c.fluido, c.otros_fluidos,
                f"{luces_ok}/4", str(c.kilometraje_actual), c.combustible_nivel,
                (c.observaciones_mecanica or "-")[:45]
            ])
    else:
        datos_checklists.append(["—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "Sin registros todavía"])

    tabla_checklists = Table(datos_checklists, repeatRows=1, hAlign='LEFT')
    tabla_checklists.setStyle(estilo_tabla())
    elementos.append(tabla_checklists)

    doc.build(elementos)
    buffer.seek(0)

    nombre_archivo = f"informe_movilcheck_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return send_file(
        buffer, mimetype='application/pdf',
        as_attachment=True, download_name=nombre_archivo
    )

# ==========================================
# ESTO SE EJECUTA SIEMPRE QUE SE CARGA app.py
# (tanto con "python app.py" como con Gunicorn: gunicorn app:app)
# ==========================================
arreglar_base_datos_si_hace_falta()

with app.app_context():
    db.create_all()  # crea sólo lo que falte; no toca tablas ni datos existentes
    if Usuario.query.count() == 0:
        db.session.add(Usuario(nombre="Oscar", contrasena="", rol="Admin", activo=True))
        db.session.commit()

# ==========================================
# ESTO SOLO SE EJECUTA SI CORRÉS "python app.py" DIRECTO
# (en producción con Gunicorn, esta parte no se usa)
# ==========================================
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8080)