"""
crear_dispositivo.py
Script rápido para registrar el Dispositivo ID 1 en Neon.
"""
from app.core.database import SessionLocal
from app.models.dispositivo import Dispositivo

def registrar_base():
    db = SessionLocal()
    try:
        # Verificar si el ID 1 ya existe para no duplicarlo
        existe = db.query(Dispositivo).filter(Dispositivo.id == 1).first()
        
        if not existe:
            print("⏳ Registrando el Dispositivo ID 1 en Neon...")
            # Usamos los campos 'nombre' y 'ubicacion' que lee tu endpoint
            primer_dispositivo = Dispositivo(
                id=1, 
                nombre="Medidor Principal IoT", 
                ubicacion="Tablero Central de Cargas"
            )
            db.add(primer_dispositivo)
            db.commit()
            print("✅ ¡Dispositivo ID 1 creado con éxito en la nube de Neon!")
        else:
            print("💡 El Dispositivo ID 1 ya existe en la base de datos. No hace falta crearlo de nuevo.")
            
    except Exception as e:
        print(f"❌ Error al conectar o insertar en Neon: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    registrar_base()