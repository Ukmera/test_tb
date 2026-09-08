import sys
import socket
import uvicorn
from config.settings import DASHBOARD_HOST, DASHBOARD_PORT

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def find_free_port(host: str, starting_port: int, max_attempts: int = 50) -> int:
    """Vérifie si le port est disponible et trouve le premier port libre si nécessaire."""
    for p in range(starting_port, starting_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return starting_port


def main():
    actual_port = find_free_port(DASHBOARD_HOST, DASHBOARD_PORT)

    print("=" * 60)
    print("🚀 DÉMARRAGE DU DASHBOARD VISUEL INSTITUTIONNEL SMC")
    print(f"🌐 URL d'accès vérifiée et disponible : http://{DASHBOARD_HOST}:{actual_port}")
    print("=" * 60)
    uvicorn.run("dashboard.app:app", host=DASHBOARD_HOST, port=actual_port, reload=False)


if __name__ == "__main__":
    main()
