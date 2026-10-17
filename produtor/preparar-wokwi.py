"""Gera o cabeçalho local dos dois ESP32 com a CA e senhas distintas."""

import json
from pathlib import Path


raiz = Path(__file__).resolve().parent.parent
segredos = raiz / ".local" / "mqtt"
ca = (segredos / "ca.crt").read_text(encoding="ascii")
for papel, nome in (("produtor", "segredos.h"),
                    ("sinalizador", "segredos_sinalizador.h")):
    senha = (segredos / f"{papel}.password").read_text(encoding="ascii").strip()
    if not senha:
        raise RuntimeError(f"Senha MQTT vazia para {papel}")
    destino = raiz / "produtor" / "include" / nome
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        "#pragma once\n"
        "// Arquivo local gerado; não versionar.\n"
        f"static const char MQTT_SENHA[] = {json.dumps(senha)};\n"
        f"static const char MQTT_CA[] = R\"CERT({ca})CERT\";\n",
        encoding="utf-8",
    )
    destino.chmod(0o600)
    print(f"Credencial de {papel} preparada em {destino}")
