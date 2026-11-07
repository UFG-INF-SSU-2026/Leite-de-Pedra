"""python3 -m observabilidade: assina o broker e serve a API interna (app.py)."""

import os

import uvicorn

from mqtt_config import conectar, desconectar

from .app import app, cliente_mqtt

# ponytail: HTTP sem TLS, aceitável só porque não sai da máquina nem da rede do compose.
conectar(cliente_mqtt, "observador", assincrono=True)
cliente_mqtt.loop_start()
try:
    uvicorn.run(app, host=os.getenv("OBSERVABILIDADE_HOST", "127.0.0.1"),
                port=int(os.getenv("OBSERVABILIDADE_PORTA", "8090")),
                access_log=False, server_header=False)  # o painel consulta a cada 2 s
finally:
    desconectar(cliente_mqtt, "observador")
    cliente_mqtt.loop_stop()
