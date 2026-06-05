import os
import shutil
import subprocess
import sys
import time

def launch():
    print("========================================================")
    print("   SISTEMA IOT - MONITOREO ELECTRICO INTELIGENTE")
    print("========================================================")

    # ── 1. Verificar .env ──────────────────────────────────────────────────────
    if not os.path.exists(".env"):
        if os.path.exists(".env.example"):
            shutil.copy(".env.example", ".env")
            print("⚠️  Archivo .env creado desde .env.example.")
            print("👉  Editalo y pone tu DATABASE_URL de Neon antes de continuar.")
            sys.exit(0)
        else:
            print("❌  No se encontro ni .env ni .env.example en la raiz del proyecto.")
            sys.exit(1)

    # ── 2. Instalar dependencias ───────────────────────────────────────────────
    print("\n[1/2] Instalando dependencias...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
    except subprocess.CalledProcessError:
        print("❌  Error instalando dependencias. Revisa requirements.txt.")
        sys.exit(1)

    # ── 3. Iniciar Backend ─────────────────────────────────────────────────────
    print("\n[2/2] Iniciando Backend (FastAPI)...")
    backend_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
    )

    print("⏳  Esperando 6 segundos para que el backend se conecte a Neon...")
    time.sleep(6)

    # ── 4. Iniciar Dashboard ───────────────────────────────────────────────────
    print("\nIniciando Dashboard (Streamlit)...")
    dashboard_process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "dashboard.py"],
    )

    print("\n========================================================")
    print("   SISTEMA INICIADO")
    print("   - Backend:   http://localhost:8000")
    print("   - Dashboard: http://localhost:8501")
    print("   - Docs API:  http://localhost:8000/docs")
    print("========================================================")
    print("   Primero registrate en el Dashboard (login/register)")
    print("   Luego corre el simulador aparte si queres datos:")
    print("   > python scripts/simulador_realista.py --interval 3")
    print("========================================================")
    print("   Ctrl + C para apagar todo.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nApagando servicios...")
        backend_process.terminate()
        dashboard_process.terminate()
        print("Todo apagado correctamente.")

if __name__ == "__main__":
    launch()