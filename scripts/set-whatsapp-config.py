"""Guarda el destinatario de WhatsApp cifrado en MySQL sin usar argumentos CLI."""

import os
import re
import sys
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env", override=False)
sys.path.insert(0, str(BASE_DIR))

from camera_store import save_notification_config  # noqa: E402

phone = re.sub(r"\D", "", getpass("Número WhatsApp con código de país: ").strip())
if not 8 <= len(phone) <= 15:
    raise SystemExit("El número debe contener entre 8 y 15 dígitos.")

save_notification_config(
    phone=phone,
    url=os.getenv("NOTIFY_URL", "https://cenfelec.com/notificarmsg"),
    message=os.getenv("NOTIFY_MESSAGE", "Alguien llegó a la tienda."),
)
print("Configuración de WhatsApp cifrada y guardada en MySQL.")
