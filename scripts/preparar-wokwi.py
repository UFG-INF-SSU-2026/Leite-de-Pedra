"""Gera o cabeçalho local do ESP32 com a CA pública e a senha do produtor."""

import json
from pathlib import Path


raiz = Path(__file__).resolve().parent.parent
segredos = raiz / ".local" / "mqtt"
destino = raiz / "wokwi" / "include" / "segredos.h"

ca = (segredos / "ca.crt").read_text(encoding="ascii")
senha = (segredos / "produtor.password").read_text(encoding="ascii").strip()
if not senha:
    raise RuntimeError("Senha do produtor vazia")

destino.parent.mkdir(parents=True, exist_ok=True)
destino.write_text(
    "#pragma once\n"
    "// Arquivo local gerado; não versionar.\n"
    f"static const char MQTT_SENHA[] = {json.dumps(senha)};\n"
    f"static const char MQTT_CA[] = R\"CERT({ca})CERT\";\n",
    encoding="utf-8",
)
destino.chmod(0o600)
print(f"Credenciais de desenvolvimento preparadas em {destino}")
