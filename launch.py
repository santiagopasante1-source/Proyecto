import os
import shutil
import subprocess
import sys
import time

def launch():
    print("========================================================")
    print("     SISTEMA IOT - ORQUESTRADOR DE DESARROLLO")
    print("========================================================")

    # 1. Preparar entorno y dependencias
    print("\n[1/3] Verificando e instalando dependencias...")
    try:
        # Corre la instalación de forma visible para rastrear errores de librerías
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
    except subprocess.CalledProcessError:
        print("❌ Error crítico: No se pudieron instalar las dependencias de requirements.txt")
        sys.exit(1)

    # 2. Copiar .env si no existe
    if not os.path.exists(".env"):
        if os.path.exists(".env.example"):
            shutil.copy(".env.example", ".env")
            print("⚠️ Archivo .env creado automáticamente desde .env.example.")
            print("👉 Corre a poner tu URL de Neon en el archivo .env antes de continuar.")
            sys.exit(0)
        else:
            print("❌ Error: No se encontró ni .env ni .env.example en la raíz.")
            sys.exit(1)

    # 3. Lanzar FastAPI (Backend)
    print("\n[2/3] Iniciando Backend (FastAPI)...")
    # Usamos Popen para que corra en segundo plano pero canalice los logs aquí mismo
    backend_process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"])

    # Espera estratégica para que SQLAlchemy se conecte a Neon y genere las tablas
    print("⏳ Esperando 5 segundos para la sincronización y creación de tablas en Neon...")
    time.sleep(5)

    # 4. Lanzar Dashboard (Streamlit)
    print("\n[3/3] Iniciando Dashboard (Streamlit)...")
    dashboard_process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "dashboard.py"])


    # Arrancar el simulador automáticamente a los 8 segundos
    print("\n[4/4] Levantando el Simulador Eléctrico Realista...")
    time.sleep(3)
    simulador_process = subprocess.Popen([sys.executable, "scripts/simulador_realista.py", "--interval", "3"])

    print("\n========================================================")
    print("🚀 SISTEMA INICIADO Y MONITOREADO EN VIVO")
    print("   - Backend FastAPI:  http://localhost:8000")
    print("   - Dashboard UI:     http://localhost:8501")
    print("========================================================")
    print("💡 Los logs de ambos servicios saldrán abajo en tiempo real.")
    print("🛑 Para apagar TODO el sistema en combo, presiona Ctrl + C.\n")

    # Mantener el script vivo y vigilar el apagado limpio
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Deteniendo servicios en combo de forma segura...")
        backend_process.terminate()
        dashboard_process.terminate()
        print("👋 ¡Todo apagado correctamente! Nos vemos.")

if __name__ == "__main__":
    launch()