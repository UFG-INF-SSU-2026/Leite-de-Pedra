import itertools
import json
import os
import threading
from datetime import datetime

class BancoEmMemoria:
    # Guarda cada evento recebido como um documento JSON. A lista em memória é a
    # fonte da verdade; se houver um arquivo, ele é só um espelho dela, regravado
    # a cada evento e recomeçado a cada partida - não há leitura de volta.
    # A trava existe porque o paho entrega as mensagens numa thread própria e o
    # restante do programa lê daqui.
    def __init__(self, arquivo=None):
        self.eventos = []
        self.ids = itertools.count(1)
        self.trava = threading.Lock()
        self.arquivo = arquivo
        with self.trava:
            self.espelhar()

    def inserir(self, topico, payload):
        registro = {
            "id": next(self.ids),
            "recebidoEmMs": int(datetime.now().timestamp() * 1000),
            "topico": topico,
            "evento": payload,
        }
        with self.trava:
            self.eventos.append(registro)
            self.espelhar()
        return registro

    def espelhar(self):
        if self.arquivo is None:
            return
        # Grava num temporário e troca: quem abrir o arquivo no meio de uma
        # gravação vê o estado anterior inteiro, nunca um JSON pela metade.
        temporario = f"{self.arquivo}.tmp"
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump(self.eventos, f, ensure_ascii=False, indent=2)
        os.replace(temporario, self.arquivo)

    def listar(self, fila=None, tipo=None):
        with self.trava:
            return [
                e for e in self.eventos
                if (fila is None or e["evento"].get("filaId") == fila)
                and (tipo is None or e["evento"].get("tipo", e["topico"].rsplit("/", 1)[-1]) == tipo)
            ]

    def exportar(self):
        with self.trava:
            return json.dumps(self.eventos, ensure_ascii=False, indent=2)

    def __len__(self):
        with self.trava:
            return len(self.eventos)
