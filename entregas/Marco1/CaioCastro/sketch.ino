const int POT_PIN = 34;
const int LED_PIN = 2;

const char* DEVICE_ID = "esp32-catraca-03";
const char* ENTITY_ID = "portao-2-catraca-3";

const int VALOR_MINIMO = 0;
const int VALOR_MAXIMO = 100;

// =========================================================
// HISTERese
// =========================================================

const int LIMIAR_ALERTA = 55;
const int LIMIAR_RETORNO = 45;

// Variação máxima considerada normal entre duas leituras.
// Uma variação maior será considerada uma leitura instável.
const int MAX_VARIACAO = 40;

int sequence = 0;
int valorAnterior = 0;
bool primeiraLeitura = true;

enum State {
  NORMAL,
  ALERTA
};

State currentState = NORMAL;


// =========================================================
// CONVERSÃO DO ESTADO
// =========================================================

const char* stateToString(State state) {
  if (state == NORMAL) {
    return "NORMAL";
  }

  return "ALERTA";
}


// =========================================================
// SETUP
// =========================================================

void setup() {
  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);

  // Estado inicial:
  // NORMAL = lâmpada acesa
  digitalWrite(LED_PIN, HIGH);
}


// =========================================================
// LOOP
// =========================================================

void loop() {

  // =======================================================
  // 1. LEITURA
  // =======================================================

  int valorBruto = analogRead(POT_PIN);

  // O potenciômetro representa uma grandeza fictícia
  // em uma escala de 0 a 100 pontos.
  int valor = map(valorBruto, 0, 4095, 0, 100);

  Serial.print("[READING] value=");
  Serial.println(valor);


  // =======================================================
  // 2. IDENTIDADE DO EVENTO
  // =======================================================

  sequence++;

  String correlationId = "evt-" + String(sequence);

  unsigned long eventTimeMs = millis();


  // =======================================================
  // 3. GUARDA ESTADO ANTERIOR
  // =======================================================

  State previousState = currentState;


  // =======================================================
  // 4. VALIDAÇÃO DA LEITURA
  // =======================================================

  bool leituraValida =
    valor >= VALOR_MINIMO &&
    valor <= VALOR_MAXIMO;

  bool leituraInstavel = false;

  if (!primeiraLeitura) {

    int variacao = abs(valor - valorAnterior);

    if (variacao > MAX_VARIACAO) {

      leituraInstavel = true;
      leituraValida = false;

      Serial.print("[VALIDATION] correlationId=");
      Serial.print(correlationId);

      Serial.print(" status=UNSTABLE_READING variation=");
      Serial.println(variacao);
    }
  }

  if (!leituraValida && !leituraInstavel) {

    Serial.print("[VALIDATION] correlationId=");
    Serial.print(correlationId);

    Serial.println(" status=INVALID_VALUE");
  }


  // =======================================================
  // 5. PROCESSAMENTO E REGRA
  // =======================================================

  if (leituraValida) {

    // Histerese:
    //
    // NORMAL + valor >= 55 -> ALERTA
    //
    // ALERTA + valor <= 45 -> NORMAL
    //
    // Entre 45 e 55:
    // mantém o estado atual.

    if (
      currentState == NORMAL &&
      valor >= LIMIAR_ALERTA
    ) {

      currentState = ALERTA;
    }

    else if (
      currentState == ALERTA &&
      valor <= LIMIAR_RETORNO
    ) {

      currentState = NORMAL;
    }
  }


  // =======================================================
  // 6. EVENTO JSON
  // =======================================================

  Serial.print("{");

  Serial.print("\"eventType\":\"CondicaoFilaAtualizada\",");

  Serial.print("\"deviceId\":\"");
  Serial.print(DEVICE_ID);
  Serial.print("\",");

  Serial.print("\"entityId\":\"");
  Serial.print(ENTITY_ID);
  Serial.print("\",");

  Serial.print("\"eventTimeMs\":");
  Serial.print(eventTimeMs);
  Serial.print(",");

  Serial.print("\"sequence\":");
  Serial.print(sequence);
  Serial.print(",");

  Serial.print("\"correlationId\":\"");
  Serial.print(correlationId);
  Serial.print("\",");

  Serial.print("\"value\":");
  Serial.print(valor);
  Serial.print(",");

  Serial.print("\"unit\":\"pontos\",");

  Serial.print("\"state\":\"");
  Serial.print(stateToString(currentState));
  Serial.println("\"}");
  

  // =======================================================
  // 7. ESTADO
  // =======================================================

  Serial.print("[STATE] correlationId=");
  Serial.print(correlationId);

  Serial.print(" previous=");
  Serial.print(stateToString(previousState));

  Serial.print(" current=");
  Serial.println(stateToString(currentState));


  // =======================================================
  // 8. DECISÃO
  // =======================================================

  if (!leituraValida) {

    Serial.print("[DECISION] correlationId=");
    Serial.print(correlationId);

    Serial.println(
      " action=MAINTAIN reason=INVALID_OR_UNSTABLE_INPUT"
    );
  }

  else if (previousState != currentState) {

    Serial.print("[DECISION] correlationId=");
    Serial.print(correlationId);

    Serial.print(" action=CHANGE_STATE");

    if (currentState == ALERTA) {

      Serial.println(
        " reason=VALUE_REACHED_UPPER_THRESHOLD"
      );
    }

    else {

      Serial.println(
        " reason=VALUE_REACHED_LOWER_THRESHOLD"
      );
    }
  }

  // NORMAL dentro da faixa de histerese
  else if (
    currentState == NORMAL &&
    valor >= LIMIAR_RETORNO &&
    valor < LIMIAR_ALERTA
  ) {

    Serial.print("[DECISION] correlationId=");
    Serial.print(correlationId);

    Serial.println(
      " action=MAINTAIN reason=WITHIN_HYSTERESIS"
    );
  }

  // ALERTA dentro da faixa de histerese
  else if (
    currentState == ALERTA &&
    valor > LIMIAR_RETORNO &&
    valor <= LIMIAR_ALERTA
  ) {

    Serial.print("[DECISION] correlationId=");
    Serial.print(correlationId);

    Serial.println(
      " action=MAINTAIN reason=WITHIN_HYSTERESIS"
    );
  }

  else if (currentState == NORMAL) {

    Serial.print("[DECISION] correlationId=");
    Serial.print(correlationId);

    Serial.println(
      " action=MAINTAIN reason=STATE_ALREADY_NORMAL"
    );
  }

  else {

    Serial.print("[DECISION] correlationId=");
    Serial.print(correlationId);

    Serial.println(
      " action=MAINTAIN reason=STATE_ALREADY_ALERTA"
    );
  }


  // =======================================================
  // 9. ATUADOR
  // =======================================================

  if (previousState != currentState) {

    if (currentState == NORMAL) {

      // NORMAL = lâmpada ACESA
      digitalWrite(LED_PIN, HIGH);

      Serial.print("[ACTUATOR] correlationId=");
      Serial.println(correlationId);

      Serial.println("[ACTUATOR] led=ON");
    }

    else {

      // ALERTA = lâmpada APAGADA
      digitalWrite(LED_PIN, LOW);

      Serial.print("[ACTUATOR] correlationId=");
      Serial.println(correlationId);

      Serial.println("[ACTUATOR] led=OFF");
    }
  }

  else {

    Serial.print("[ACTUATOR] correlationId=");
    Serial.print(correlationId);

    Serial.println(
      " action=NONE reason=STATE_UNCHANGED"
    );
  }


  // =======================================================
  // 10. PREPARAR PRÓXIMA LEITURA
  // =======================================================

  valorAnterior = valor;
  primeiraLeitura = false;

  Serial.println();

  delay(500);
}