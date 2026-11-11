"""python3 -m backend: serve a API do app por HTTPS (TLS 1.2 ou superior)."""

import os
import sys
from pathlib import Path

import uvicorn

PASTA_SEGREDOS = Path(__file__).resolve().parent.parent / ".local" / "backend"

# ponytail: só para desenvolvimento, quando o celular não confia na CA. Senhas e
# tokens passam em texto puro pela rede: contraria a regra 1 (só TLS) da arquitetura.
SEM_TLS = os.getenv("BACKEND_SEM_TLS") == "1"
if SEM_TLS:
    print("ATENÇÃO: backend em HTTP, sem TLS (BACKEND_SEM_TLS=1). Só para desenvolvimento.")
elif not (PASTA_SEGREDOS / "servidor.crt").exists():
    sys.exit("Backend não configurado. Execute backend/configurar-backend.sh.")

# 127.0.0.1 por padrão. Para o celular na mesma rede, BACKEND_HOST=0.0.0.0 e
# um certificado com o IP da máquina (configurar-backend.sh <ip>).
uvicorn.run(
    "backend.app:app",
    host=os.getenv("BACKEND_HOST", "127.0.0.1"),
    port=int(os.getenv("BACKEND_PORTA", "8444")),
    ssl_certfile=None if SEM_TLS else str(PASTA_SEGREDOS / "servidor.crt"),
    ssl_keyfile=None if SEM_TLS else str(PASTA_SEGREDOS / "servidor.key"),
    proxy_headers=False,
    server_header=False,
)
