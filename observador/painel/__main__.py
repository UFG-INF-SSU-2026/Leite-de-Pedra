import sys

from .servidor import iniciar
from .usuarios import criar_usuario

if len(sys.argv) == 3 and sys.argv[1] == "--criar-usuario":
    criar_usuario(sys.argv[2])
else:
    iniciar()
