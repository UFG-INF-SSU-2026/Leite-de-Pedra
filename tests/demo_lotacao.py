"""Demonstração ao vivo: as filas lotam pelo Wokwi enquanto você usa o app de verdade.

    .venv/bin/python tests/demo_lotacao.py

Antes: o mesmo do e2e (Docker, AWS, as duas simulações do Wokwi). Então:
- No celular, com a sua conta de cliente (rosto cadastrado pelo app): compre um
  ingresso e abra-o. A tela mostra em qual fila entrar e se atualiza sozinha.
- No computador: http://localhost:8444/painel/ como e2e-validador (senha
  e2e-senha-de-teste). A catraca abre com a webcam: mostre o QR do celular e o rosto.

Fase 1, lotado: a catraca da fila-a está travada (ninguém sai) e chega gente até
ela fechar; a fila-b anda devagar e fica sendo a recomendada.
Fase 2, depois que a sua leitura for aceita: você passa pela saída da sua fila,
as duas catracas voltam a andar e quem chega segue a recomendação. Ctrl+C encerra.
"""

import time

from e2e_completo import SerialProdutor, api, conta, fila, ocupacao, semaforo

LOTACAO_FILA_A = 7
FILA_B = (2, 4)  # a fila-b oscila entre 2 e 4 pessoas enquanto a fila-a está travada
CHEGADA_SEGUNDOS = 4
ANDAR_FILA_B_SEGUNDOS = 6
CATRACA_LIBERADA_SEGUNDOS = 3
ROTULOS = {"livre": "VERDE", "atencao": "AMARELO", "bloqueada": "VERMELHO", None: "--"}


def aceitas(estado):
    """Leituras aceitas que o ao vivo mostra agora, por fila: {leituraId: filaId}."""
    return {f["ultimoResultado"]["leituraId"]: f["filaId"] for f in estado["filas"]
            if (f.get("ultimoResultado") or {}).get("resultado") == "aceito"}


def main():
    admin = conta("e2e-admin", "Admin E2E", "admin")
    conta("e2e-validador", "Validador E2E", "validador")
    serial = SerialProdutor()
    _, estado = api("GET", "/admin/ao-vivo", token=admin)
    ja_vistas = set(aceitas(estado))
    liberado = False
    proximo = {"chegada": 0, "fila-b": 0, "catraca": 0}
    painel_anterior = None
    print("Fase 1: lotando a fila-a. Abra o ingresso no celular e vá para a fila que ele indicar.")
    print("A fila-a fica vermelha quando a catraca dela passa a contar como parada (até ~90 s).\n")

    while True:
        _, estado = api("GET", "/admin/ao-vivo", token=admin)
        agora = time.monotonic()
        a, b = ocupacao(estado, "fila-a") or 0, ocupacao(estado, "fila-b") or 0

        for leitura, fila_id in aceitas(estado).items():
            if leitura not in ja_vistas:
                ja_vistas.add(leitura)
                serial.pessoa("saida", fila_id)
                if not liberado:
                    liberado = True
                    print(f"\n>>> Você passou na {fila_id}. Fase 2: catracas liberadas e mais gente chegando.\n")

        if not liberado:
            if agora >= proximo["chegada"] and a < LOTACAO_FILA_A:
                serial.pessoa("chegada", "fila-a")
                proximo["chegada"] = agora + CHEGADA_SEGUNDOS
            if agora >= proximo["fila-b"]:
                serial.pessoa("chegada" if b < FILA_B[1] else "saida", "fila-b")
                if b > FILA_B[0]:
                    serial.pessoa("saida", "fila-b")
                proximo["fila-b"] = agora + ANDAR_FILA_B_SEGUNDOS
        else:
            if agora >= proximo["catraca"]:
                for fila_id, pessoas in (("fila-a", a), ("fila-b", b)):
                    if pessoas:
                        serial.pessoa("saida", fila_id)
                proximo["catraca"] = agora + CATRACA_LIBERADA_SEGUNDOS
            if agora >= proximo["chegada"]:
                _, filas = api("GET", "/filas", token=admin)
                serial.pessoa("chegada", filas["recomendada"] or "fila-a")
                proximo["chegada"] = agora + CHEGADA_SEGUNDOS

        _, filas = api("GET", "/filas", token=admin)
        painel = (f"fila-a {ROTULOS[semaforo(estado, 'fila-a')]:>8} {a:>2} pessoas | "
                  f"fila-b {ROTULOS[semaforo(estado, 'fila-b')]:>8} {b:>2} pessoas | "
                  f"quem chega vai para: {filas.get('recomendada')}")
        if painel != painel_anterior:
            print(time.strftime("%H:%M:%S"), painel)
            painel_anterior = painel
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDemonstração encerrada.")
