import os
from flask import Flask, request, redirect, url_for, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.secret_key = "clave_secreta_movil_check_spycomers_2026"

# ==========================================
# CONFIGURACIÓN DE BASE DE DATOS
# ==========================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'moviles.db')
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
    nro_movil = db.Column(db.Integer, unique=True, nullable=False)
    marca = db.Column(db.String(50), nullable=False)
    modelo = db.Column(db.String(50), nullable=False)
    ano = db.Column(db.Integer, nullable=False)
    checklists = db.relationship('Checklist', backref='vehiculo', lazy=True)

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

    pagina_actual = request.args.get('page', 1, type=int)
    paginacion = Checklist.query.order_by(Checklist.id.desc()).paginate(
        page=pagina_actual, per_page=2, error_out=False
    )
    controles = paginacion.items

    todos_usuarios = Usuario.query.all()
    
    archivo_html = f"{pestana}.html"
    return render_template(
        archivo_html, 
        usuario=usuario_activo, 
        vehiculos=vehiculos, 
        controles=controles,
        paginacion=paginacion,
        usuarios=todos_usuarios,
        pestana_activa=pestana
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
    if nro:
        db.session.add(Vehiculo(nro_movil=int(nro), marca=marca, modelo=modelo, ano=int(ano)))
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

@app.route("/editar-vehiculo", methods=["POST"])
def editar_vehiculo():
    u_id_admin = request.form.get("admin_id")
    v_id_editar = request.form.get("vehiculo_id_editar")
    vehiculo_modificar = Vehiculo.query.get(v_id_editar)
    if vehiculo_modificar:
        vehiculo_modificar.nro_movil = int(request.form.get("nro_editado"))
        vehiculo_modificar.marca = request.form.get("marca_editada")
        vehiculo_modificar.modelo = request.form.get("modelo_editada")
        vehiculo_modificar.ano = int(request.form.get("ano_editado"))
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

@app.route("/eliminar-vehiculo/<int:vid>", methods=["POST"])
def eliminar_vehiculo(vid):
    u_id_admin = request.form.get("admin_id")
    vehiculo_borrar = Vehiculo.query.get(vid)
    if vehiculo_borrar:
        Checklist.query.filter_by(vehiculo_id=vid).delete()
        db.session.delete(vehiculo_borrar)
        db.session.commit()
    return redirect(url_for('sistema_pestañas', user_id=u_id_admin, pestana='configuracion'))

# ==========================================
# INICIALIZACIÓN LIMPIABLE AUTOMÁTICA
# ==========================================
if __name__ == "__main__":
    with app.app_context():
        try:
            Usuario.query.count()
        except Exception:
            db.drop_all()
        db.create_all()
        
        if Usuario.query.count() == 0:
            db.session.add(Usuario(nombre="Oscar", contrasena="", rol="Admin", activo=True))
            db.session.commit()
            
        app.run(debug=True, host='0.0.0.0', port=8080)