"""
seed_usuario.py — Crea un usuario en Neon y le asigna un dispositivo.

Uso:
    python scripts/seed_usuario.py --username juan --password segura123 --device-id 1
    python scripts/seed_usuario.py --username maria --password casa456 --device-id 2 --nombre "Maria Lopez" --email maria@casa.local
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.usuario import Usuario
from app.models.dispositivo import Dispositivo


def main():
    parser = argparse.ArgumentParser(description="Crear usuario y asignarle un dispositivo en Neon")
    parser.add_argument("--username", required=True, help="Nombre de usuario (único)")
    parser.add_argument("--password", required=True, help="Contraseña en texto plano")
    parser.add_argument("--device-id", type=int, required=True, help="ID del dispositivo a asignar")
    parser.add_argument("--nombre", default=None, help="Nombre real del usuario (opcional)")
    parser.add_argument("--email", default=None, help="Email del usuario (opcional, default: {username}@casa.local)")

    args = parser.parse_args()
    email = args.email or f"{args.username}@casa.local"

    db = SessionLocal()
    try:
        if db.query(Usuario).filter(Usuario.username == args.username).first():
            print(f"❌ El username '{args.username}' ya existe en la BD.")
            sys.exit(1)

        dispositivo = db.query(Dispositivo).filter(Dispositivo.id == args.device_id).first()
        if not dispositivo:
            print(f"❌ El dispositivo ID {args.device_id} no existe. Créalo primero o usa otro ID.")
            sys.exit(1)

        if dispositivo.usuario_id is not None:
            print(f"⚠️  El dispositivo ID {args.device_id} ya está asignado al usuario ID {dispositivo.usuario_id}.")
            resp = input("  ¿Re-asignar de todas formas? (s/N): ")
            if resp.lower() != "s":
                print("❌ Operación cancelada.")
                sys.exit(1)

        user = Usuario(
            username=args.username,
            email=email,
            nombre=args.nombre,
            password_hash=hash_password(args.password),
            is_active=True,
        )
        db.add(user)
        db.flush()

        dispositivo.usuario_id = user.id
        db.commit()
        db.refresh(user)

        print(f"✅ Usuario creado:  ID {user.id} — {user.username} ({user.email})")
        print(f"📟 Dispositivo asignado: ID {dispositivo.id} — {dispositivo.nombre or 'sin nombre'}")
        print(f"🔐 Inicia sesión en el dashboard con usuario: {args.username}")

    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
