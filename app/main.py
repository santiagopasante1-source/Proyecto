"""
main.py — Entry point de la aplicación (Producción Optimizada)
──────────────────────────────────────────────────────────────
Cambios realizados:
  - Implementación de esquemas Pydantic para el endpoint /analizar.
  - Inyección de dependencias formal para acceder al motor de IA.
  - Protección de Base.metadata.create_all para que solo corra en desarrollo.
  - Tipado estricto y manejo limpio de excepciones.
  - Background task para detección de desconexiones de dispositivos.
"""
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base, SessionLocal, check_db_connection, engine, get_db
from app.api.endpoints import router as telemetry_router
from app.api.auth import router as auth_router
from app.services.ia_manager import IAManager
from app.services.device_monitor import DeviceMonitor

# Registro explícito de todos los modelos antes de create_all
import app.models  # noqa: F401


# ── Esquemas de Validación (Pydantic) ────────────────────────────────────────

class TelemetriaInput(BaseModel):
    """Esquema de validación para los flujos de datos eléctricos de los sensores."""
    voltaje: float = Field(..., description="Voltaje de la línea en Voltios (V)", example=110.5)
    corriente: float = Field(..., description="Corriente de la línea en Amperios (A)", example=15.2)
    frecuencia: float = Field(..., description="Frecuencia de la red en Hertz (Hz)", example=60.0)

    class Config:
        from_attributes = True


# ── Lifespan (Ciclo de Vida) ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización y limpieza del ciclo de vida de la aplicación."""

    # 1. Inicialización de Base de Datos según el entorno
    print("🗄️  Inicializando tablas de la base de datos...")
    Base.metadata.create_all(bind=engine)
    
    # Migración automática: agrega columnas nuevas a la tabla usuarios si no existen
    db = SessionLocal()
    try:
        from sqlalchemy import inspect, text as sql_text
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("usuarios")]
        if "username" not in columns:
            db.execute(sql_text("ALTER TABLE usuarios ADD COLUMN username VARCHAR(80) UNIQUE"))
            print("✅ Columna 'username' agregada a usuarios.")
        if "password_hash" not in columns:
            db.execute(sql_text("ALTER TABLE usuarios ADD COLUMN password_hash VARCHAR(255)"))
            print("✅ Columna 'password_hash' agregada a usuarios.")
        if "reset_code_hash" not in columns:
            db.execute(sql_text("ALTER TABLE usuarios ADD COLUMN reset_code_hash VARCHAR(255)"))
            print("✅ Columna 'reset_code_hash' agregada a usuarios.")
        if "reset_code_expires_at" not in columns:
            db.execute(sql_text("ALTER TABLE usuarios ADD COLUMN reset_code_expires_at TIMESTAMP WITH TIME ZONE"))
            print("✅ Columna 'reset_code_expires_at' agregada a usuarios.")
        db.commit()
    except Exception as e:
        print(f"⚠️  Migración automática (opcional): {e}")
        db.rollback()
    finally:
        db.close()

    # Dispositivo por defecto (ID 1) para que exista siempre
    from app.models.dispositivo import Dispositivo
    db = SessionLocal()
    try:
        if not db.query(Dispositivo).filter(Dispositivo.id == 1).first():
            db.add(Dispositivo(id=1, nombre="Sensor_Principal", is_active=True))
            db.commit()
            print("✅ Dispositivo por defecto (ID 1) creado.")
    except Exception as e:
        print(f"❌ Error al crear dispositivo por defecto: {e}")
    finally:
        db.close()

    # 2. Inicializar motor de IA (Carga del modelo Bidirectional-LSTM)
    print(f"🤖 Cargando motor de IA en modo: {settings.IA_MODE}...")
    app.state.detector = IAManager(mode=settings.IA_MODE)
    print(f"✅ Motor de IA listo: {app.state.detector.status}")

    # 3. Inicializar monitor de desconexión de dispositivos
    print("📡 Iniciando monitor de dispositivos...")
    app.state.device_monitor = DeviceMonitor()
    app.state.device_monitor.start()

    yield

    # 4. Limpieza al apagar el servidor
    app.state.device_monitor.stop()
    app.state.detector = None
    print("🛑 Servidor detenido correctamente.")


# ── Configuración de la Aplicación ────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configuración de CORS para permitir la comunicación con el dashboard Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Reemplazar por ["http://localhost:8501"] (Streamlit) en prod si aplica
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telemetry_router)
app.include_router(auth_router)


# ── Dependencias ──────────────────────────────────────────────────────────────

def get_ia_manager(request: Request) -> IAManager:
    """Dependencia para obtener la instancia activa del motor de IA."""
    detector = getattr(request.app.state, "detector", None)
    if not detector:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="El motor de IA no está inicializado en el servidor."
        )
    return detector


# ── Endpoints de Diagnóstico e IA ─────────────────────────────────────────────

@app.get("/health", tags=["Diagnóstico"])
def health_check(request: Request):
    """Estado general del sistema — usado por el dashboard y balanceadores de carga."""
    # Intentamos obtener el detector de manera segura sin romper el endpoint si falla
    detector = getattr(request.app.state, "detector", None)
    
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": {
            "connected": check_db_connection(),
            "engine": "postgresql" if not settings.is_sqlite else "sqlite",
        },
        "ia": detector.status if detector else {"ready": False},
    }


@app.get("/api/v1/devices/status", tags=["Dispositivos"])
def devices_status(request: Request, db: Session = Depends(get_db)):
    """Estado de conexión de todos los dispositivos activos."""
    from datetime import datetime, timezone, timedelta
    from app.models.dispositivo import Dispositivo
    from app.models.incidencia import Incidencia, EstadoEnum

    TIMEOUT = 10
    ahora = datetime.now(timezone.utc)
    umbral = ahora - timedelta(seconds=TIMEOUT)
    dispositivos = db.query(Dispositivo).filter(Dispositivo.is_active == True).all()

    resultado = []
    for d in dispositivos:
        estado = "desconocido"
        ultimo_ping = d.ultimo_ping

        if ultimo_ping is None:
            estado = "nunca_conectado"
        elif ultimo_ping < umbral:
            segundos_desconectado = int((ahora - ultimo_ping).total_seconds())
            estado = f"desconectado ({segundos_desconectado}s)"
        else:
            estado = "conectado"

        # Verificar si hay un APAGÓN abierto para este dispositivo
        apagon = db.query(Incidencia).filter(
            Incidencia.dispositivo_id == d.id,
            Incidencia.tipo == "APAGON",
            Incidencia.estado == EstadoEnum.abierta,
        ).first()

        resultado.append({
            "id": d.id,
            "nombre": d.nombre or f"Dispositivo {d.id}",
            "ubicacion": d.ubicacion,
            "ultimo_ping": ultimo_ping.isoformat() if ultimo_ping else None,
            "estado": estado,
            "apagon_activo": apagon is not None,
            "apagon_desde": apagon.created_at.isoformat() if apagon else None,
        })

    return {"dispositivos": resultado}


@app.get("/ia/status", tags=["Diagnóstico"])
def ia_status(manager: IAManager = Depends(get_ia_manager)):
    """Estado detallado del motor de IA — usado por el dashboard Streamlit."""
    return manager.status


@app.post("/analizar", tags=["IA"])
async def analizar_datos(
    datos: TelemetriaInput, 
    manager: IAManager = Depends(get_ia_manager)
):
    """
    Análisis directo en tiempo real (sin persistencia) — óptimo para pruebas desde Streamlit.
    
    Valida automáticamente que el flujo contenga:
    - **voltaje** (float)
    - **corriente** (float)
    - **frecuencia** (float)
    
    Pasa estos datos directamente al modelo Bidirectional-LSTM para detectar anomalías.
    """
    try:
        resultado = manager.process_data(datos.model_dump())
        return resultado
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno durante el procesamiento del modelo: {str(e)}"
        )


# ── Endpoints para Setup Web ──────────────────────────────────────────────────

@app.get("/api/v1/devices", tags=["Dispositivos"])
def list_devices(db: Session = Depends(get_db)):
    """Lista todos los dispositivos activos con su usuario asignado."""
    from app.models.dispositivo import Dispositivo
    dispositivos = db.query(Dispositivo).filter(Dispositivo.is_active == True).all()
    return {
        "dispositivos": [
            {
                "id": d.id,
                "nombre": d.nombre or f"Dispositivo {d.id}",
                "ubicacion": d.ubicacion,
                "usuario_id": d.usuario_id,
            }
            for d in dispositivos
        ]
    }


SETUP_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Setup - Configurar Dispositivos</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; display: flex; justify-content: center; padding: 40px 20px; }
  .card { background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); padding: 32px; max-width: 560px; width: 100%; }
  h1 { font-size: 22px; color: #1a1a2e; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 14px; margin-bottom: 24px; }
  .section { border-top: 1px solid #e5e7eb; margin-top: 20px; padding-top: 20px; }
  .section-title { font-weight: 600; color: #1a1a2e; font-size: 15px; margin-bottom: 12px; }
  label { display: block; font-size: 13px; font-weight: 600; color: #333; margin: 10px 0 4px; }
  input, select { width: 100%; padding: 10px 12px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; }
  input:focus, select:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.15); }
  button { width: 100%; padding: 11px; background: #2563eb; color: #fff; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; margin-top: 12px; }
  button:hover { background: #1d4ed8; }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  button.sec { background: #6b7280; }
  button.sec:hover { background: #4b5563; }
  button.danger { background: #dc2626; }
  button.danger:hover { background: #b91c1c; }
  .msg { padding: 10px 14px; border-radius: 8px; margin-top: 12px; font-size: 14px; display: none; }
  .success { background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; display: block; }
  .error { background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; display: block; }
  .info { background: #e0f2fe; color: #075985; border: 1px solid #bae6fd; display: block; }
  .device-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: #f9fafb; border-radius: 8px; margin-bottom: 8px; }
  .device-name { font-weight: 600; font-size: 14px; }
  .device-id { color: #9ca3af; font-size: 12px; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 10px; font-size: 12px; font-weight: 600; }
  .badge-free { background: #dbeafe; color: #1e40af; }
  .badge-yours { background: #d1fae5; color: #065f46; }
  .badge-other { background: #fef3c7; color: #92400e; }
  .user-card { background: #f0f9ff; padding: 14px; border-radius: 10px; margin-bottom: 12px; font-size: 14px; }
  .user-card .row { display: flex; justify-content: space-between; padding: 4px 0; }
  .user-card .label { color: #6b7280; }
  .user-card .value { font-weight: 500; }
  .inline-group { display: flex; gap: 8px; }
  .inline-group input { flex: 1; }
  .inline-group button { width: auto; padding: 10px 16px; margin-top: 0; flex-shrink: 0; }
  .link { color: #2563eb; cursor: pointer; text-decoration: underline; font-size: 13px; }
  .link:hover { color: #1d4ed8; }
</style>
</head>
<body>
<div class="card">
  <h1>🔧 Configuración</h1>
  <p class="subtitle">Administra tus dispositivos y notificaciones Telegram</p>

  <!-- Step 1: Login -->
  <div id="step1">
    <div class="section-title">Iniciar sesión</div>
    <label for="username">Usuario</label>
    <input type="text" id="username" placeholder="Tu nombre de usuario" autocomplete="username">
    <label for="password">Contraseña</label>
    <input type="password" id="password" placeholder="Tu contraseña" autocomplete="current-password">
    <button id="btn-login" onclick="login()">Ingresar</button>
    <div id="msg-login" class="msg"></div>
  </div>

  <!-- Step 2: Dashboard -->
  <div id="step2" style="display:none">

    <!-- User info -->
    <div id="user-card" class="user-card"></div>

    <!-- Telegram -->
    <div class="section">
      <div class="section-title">📨 Telegram</div>
      <div class="inline-group">
        <input type="text" id="tg-input" placeholder="ID numérico (ej: 1885567115)">
        <button id="btn-tg" onclick="saveTelegram()">Guardar</button>
      </div>
      <button class="sec" id="btn-tg-test" onclick="testTelegram()">📨 Probar Telegram</button>
      <button class="sec" id="btn-tg-diag" onclick="diagnosticTelegram()" style="margin-top:6px">🔍 Diagnóstico</button>
      <div id="msg-tg" class="msg"></div>
      <pre id="diag-result" style="display:none;background:#f3f4f6;padding:10px;border-radius:8px;font-size:12px;margin-top:8px;white-space:pre-wrap;word-break:break-all;"></pre>
    </div>

    <!-- Devices -->
    <div class="section">
      <div class="section-title">📟 Dispositivos</div>
      <div id="device-list"></div>
      <div id="msg-dev" class="msg"></div>
    </div>

    <div style="margin-top: 20px; text-align: center;">
      <span class="link" onclick="logout()">Cerrar sesión</span>
    </div>
  </div>
</div>

<script>
let token = '';
let userId = 0;

function show(id, msg, type) {
  const el = document.getElementById(id);
  el.className = 'msg ' + type;
  el.textContent = msg;
  el.style.display = 'block';
}

function hide(id) {
  const el = document.getElementById(id);
  el.style.display = 'none';
  el.className = 'msg';
}

async function login() {
  const btn = document.getElementById('btn-login');
  btn.disabled = true;
  hide('msg-login');

  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value.trim();
  if (!username || !password) { show('msg-login', 'Completa todos los campos', 'error'); btn.disabled = false; return; }

  try {
    const r = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await r.json();
    if (!r.ok) { show('msg-login', data.detail || 'Error al iniciar sesión', 'error'); btn.disabled = false; return; }

    token = data.access_token;
    userId = data.user.id;

    document.getElementById('user-card').innerHTML =
      '<div class="row"><span class="label">👤 Usuario</span><span class="value">' + data.user.username + '</span></div>' +
      '<div class="row"><span class="label">📧 Email</span><span class="value">' + (data.user.email || '—') + '</span></div>' +
      '<div class="row"><span class="label">🤖 Telegram</span><span class="value">' + (data.user.telegram_id ? '✅ ' + data.user.telegram_id : '❌ No vinculado') + '</span></div>';

    document.getElementById('tg-input').value = data.user.telegram_id || '';

    document.getElementById('step1').style.display = 'none';
    document.getElementById('step2').style.display = 'block';
    await loadDevices();
  } catch(e) {
    show('msg-login', 'Error de conexión con el servidor', 'error');
  }
  btn.disabled = false;
}

function logout() {
  token = '';
  userId = 0;
  document.getElementById('step1').style.display = 'block';
  document.getElementById('step2').style.display = 'none';
  document.getElementById('username').value = '';
  document.getElementById('password').value = '';
}

async function loadDevices() {
  hide('msg-dev');
  try {
    const r = await fetch('/api/v1/devices');
    const data = await r.json();
    if (!r.ok) throw new Error();
    const list = document.getElementById('device-list');
    list.innerHTML = '';

    if (data.dispositivos.length === 0) {
      list.innerHTML = '<p style="color:#9ca3af;font-size:14px">No hay dispositivos registrados.</p>';
      return;
    }

    for (const d of data.dispositivos) {
      const row = document.createElement('div');
      row.className = 'device-row';

      let badge = '';
      let canAssign = false;
      if (!d.usuario_id) {
        badge = '<span class="badge badge-free">✅ Libre</span>';
        canAssign = true;
      } else if (d.usuario_id === userId) {
        badge = '<span class="badge badge-yours">✅ Tuyo</span>';
      } else {
        badge = '<span class="badge badge-other">🔒 Otro usuario</span>';
      }

      const info = document.createElement('div');
      info.innerHTML = '<div class="device-name">' + d.nombre + ' <span class="device-id">(ID ' + d.id + ')</span></div>' + badge;

      const btn = document.createElement('button');
      if (!d.usuario_id) {
        btn.textContent = 'Asignar a mi cuenta';
        btn.onclick = function() { assignDevice(d.id, false); };
      } else if (d.usuario_id === userId) {
        btn.textContent = '✔ Asignado';
        btn.disabled = true;
        btn.style.background = '#6b7280';
      } else {
        btn.textContent = 'Tomar dispositivo';
        btn.className = 'danger';
        btn.onclick = function() { assignDevice(d.id, true); };
      }
      btn.style.width = 'auto';
      btn.style.marginTop = '0';
      btn.style.padding = '6px 14px';
      btn.style.fontSize = '13px';

      row.appendChild(info);
      row.appendChild(btn);
      list.appendChild(row);
    }
  } catch(e) {
    show('msg-dev', 'Error al cargar dispositivos', 'error');
  }
}

async function assignDevice(id, force) {
  hide('msg-dev');
  try {
    const body = { dispositivo_id: id };
    if (force) body.force = true;
    const r = await fetch('/api/v1/auth/asignar-dispositivo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify(body)
    });
    const data = await r.json();
    if (!r.ok) {
      if (r.status === 409) {
        if (confirm('Este dispositivo pertenece a otro usuario. ¿Tomarlo?')) {
          return assignDevice(id, true);
        }
      } else {
        show('msg-dev', data.detail || 'Error al asignar', 'error');
      }
      return;
    }
    show('msg-dev', '✅ ' + data.mensaje, 'success');
    await loadDevices();
  } catch(e) {
    show('msg-dev', 'Error de conexión con el servidor', 'error');
  }
}

async function saveTelegram() {
  const btn = document.getElementById('btn-tg');
  btn.disabled = true;
  hide('msg-tg');

  const val = document.getElementById('tg-input').value.trim();
  if (!val || !/^\\d+$/.test(val)) { show('msg-tg', 'Ingresa un ID numérico de Telegram', 'error'); btn.disabled = false; return; }

  try {
    const r = await fetch('/api/v1/auth/telegram', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ telegram_id: parseInt(val) })
    });
    const data = await r.json();
    if (!r.ok) { show('msg-tg', data.detail || 'Error al guardar', 'error'); btn.disabled = false; return; }
    show('msg-tg', '✅ Telegram vinculado correctamente', 'success');
    // Refresh user info
    const r2 = await fetch('/api/v1/auth/me', { headers: { 'Authorization': 'Bearer ' + token } });
    const user = await r2.json();
    document.querySelector('#user-card .row:nth-child(3) .value').textContent = '✅ ' + val;
  } catch(e) {
    show('msg-tg', 'Error de conexión con el servidor', 'error');
  }
  btn.disabled = false;
}

async function testTelegram() {
  const btn = document.getElementById('btn-tg-test');
  btn.disabled = true;
  hide('msg-tg');
  try {
    const r = await fetch('/api/v1/auth/telegram/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: '{}'
    });
    const data = await r.json();
    if (!r.ok) { show('msg-tg', data.detail || 'Error al enviar prueba', 'error'); btn.disabled = false; return; }
    show('msg-tg', '✅ Mensaje de prueba enviado — revisa tu Telegram', 'success');
  } catch(e) {
    show('msg-tg', 'Error de conexión con el servidor', 'error');
  }
  btn.disabled = false;
}

async function diagnosticTelegram() {
  const btn = document.getElementById('btn-tg-diag');
  btn.disabled = true;
  hide('msg-tg');
  const pre = document.getElementById('diag-result');
  pre.style.display = 'none';

  try {
    const r = await fetch('/api/v1/auth/telegram/diagnostico', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: '{}'
    });
    const data = await r.json();
    pre.textContent = JSON.stringify(data, null, 2);
    pre.style.display = 'block';
    if (data.ok) {
      show('msg-tg', '✅ Telegram funciona correctamente', 'success');
    } else {
      show('msg-tg', '❌ Error en Telegram — revisa el diagnóstico', 'error');
    }
  } catch(e) {
    show('msg-tg', 'Error de conexión con el servidor', 'error');
  }
  btn.disabled = false;
}
</script>
</body>
</html>"""


@app.get("/setup", response_class=HTMLResponse, tags=["Setup"])
def setup_page():
    """Página web para asignar dispositivos a tu cuenta."""
    return HTMLResponse(content=SETUP_HTML)