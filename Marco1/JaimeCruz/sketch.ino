#include <Arduino.h>

// --- Pinagem simulada no Wokwi ---
const int POT_A_PIN = 34;  // ocupacao fila A
const int POT_B_PIN = 35;  // ocupacao fila B
const int BTN_A_PIN  = 32;  // validacao fila A
const int BTN_B_PIN  = 33;  // validacao fila B
const int LED_A_PIN  = 25;  // recomendacao fila A
const int LED_B_PIN  = 26;  // recomendacao fila B

// --- Parametros de contexto ---
const unsigned long WINDOW_MS = 20000; // janela temporal recente de 20 s
const float HISTERESIS_MIN = 0.5f;
const unsigned long CANDIDATE_MS = 3000;
const unsigned long DEBOUNCE_MS = 50;
const unsigned long REPORT_INTERVAL_MS = 1000;
const int MAX_EVENTS = 100;

// --- Estados da maquina ---
enum State {
  RECOMENDA_A,
  CANDIDATA_B,
  RECOMENDA_B,
  CANDIDATA_A,
  DADOS_INSUFICIENTES
};

State currentState = RECOMENDA_A;
State lastRecommendation = RECOMENDA_A;
unsigned long candidateStartMs = 0;
unsigned long sequence = 0;
unsigned long lastReportMs = 0;

struct ButtonState {
  int pin;
  bool wasPressed;
  unsigned long lastAcceptedMs;
};

ButtonState buttonA = {BTN_A_PIN, false, 0};
ButtonState buttonB = {BTN_B_PIN, false, 0};

// Eventos recentes de validacoes por fila.
unsigned long timesA[MAX_EVENTS];
unsigned long timesB[MAX_EVENTS];
int countA = 0;
int countB = 0;

// Computed metrics
float flowA = 0;
float flowB = 0;
float waitA = 0;
float waitB = 0;

// --- util: limpar eventos fora da janela ---
void cleanOldEvents(unsigned long now, unsigned long* times, int* count) {
  int valid = 0;
  for (int i = 0; i < *count; i++) {
    if ((now - times[i]) < WINDOW_MS) {
      times[valid++] = times[i];
    }
  }
  *count = valid;
}

// --- util: registrar validacao de uma fila ---
void registerValidation(int fila, unsigned long now) {
  if (fila == 0) {
    if (countA < MAX_EVENTS) {
      timesA[countA++] = now;
    } else {
      for (int i = 1; i < MAX_EVENTS; i++) {
        timesA[i - 1] = timesA[i];
      }
      timesA[MAX_EVENTS - 1] = now;
    }
  } else {
    if (countB < MAX_EVENTS) {
      timesB[countB++] = now;
    } else {
      for (int i = 1; i < MAX_EVENTS; i++) {
        timesB[i - 1] = timesB[i];
      }
      timesB[MAX_EVENTS - 1] = now;
    }
  }
}

// --- leitura de ocupacao em 0..50 pessoas ---
int readOccupationFromAnalog(int pin) {
  int raw = analogRead(pin);
  return map(raw, 0, 4095, 0, 50);
}

// Retorna true uma unica vez por pressionamento confirmado.
bool validationPressed(ButtonState& button, unsigned long now) {
  bool pressed = digitalRead(button.pin) == LOW;
  bool fallingEdge = pressed && !button.wasPressed;
  button.wasPressed = pressed;

  if (fallingEdge &&
      (button.lastAcceptedMs == 0 || now - button.lastAcceptedMs >= DEBOUNCE_MS)) {
    button.lastAcceptedMs = now;
    return true;
  }
  return false;
}

// --- emit event JSON para serial monitor ---
void emitJson(const char* eventType, const char* entityId, unsigned long eventTimeMs, float value, const char* unit, const char* state) {
  Serial.print("{\"eventType\":\"");
  Serial.print(eventType);
  Serial.print("\",\"deviceId\":\"esp32-portao-01\",\"entityId\":\"");
  Serial.print(entityId);
  Serial.print("\",\"eventTimeMs\":");
  Serial.print(eventTimeMs);
  Serial.print(",\"sequence\":");
  Serial.print(sequence++);
  Serial.print(",\"value\":");
  Serial.print(value, 2);
  Serial.print(",\"unit\":\"");
  Serial.print(unit);
  Serial.print("\",\"state\":\"");
  Serial.print(state);
  Serial.println("\"}");
}

// --- restricao de transicao de fluxo para recomendacao ---
void applyRecommendationLighting(State st) {
  State shown = st;
  if (st == CANDIDATA_A || st == CANDIDATA_B) {
    shown = lastRecommendation;
  }
  digitalWrite(LED_A_PIN, shown == RECOMENDA_A ? HIGH : LOW);
  digitalWrite(LED_B_PIN, shown == RECOMENDA_B ? HIGH : LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_A_PIN, INPUT_PULLUP);
  pinMode(BTN_B_PIN, INPUT_PULLUP);
  pinMode(LED_A_PIN, OUTPUT);
  pinMode(LED_B_PIN, OUTPUT);

  digitalWrite(LED_A_PIN, LOW);
  digitalWrite(LED_B_PIN, LOW);

  // estado inicial da recomendacao
  currentState = RECOMENDA_A;
  applyRecommendationLighting(currentState);

  Serial.println("Iniciando prototipo FILA_A / FILA_B");
  Serial.println("Simplificacao: potenciometro simula ocupacao, botao simula validacao.");
}

void loop() {
  unsigned long now = millis();

  // leitura de ocupacao representada por potenciometro
  int occA = readOccupationFromAnalog(POT_A_PIN);
  int occB = readOccupationFromAnalog(POT_B_PIN);

  // leitura de botoes: pressionar -> uma validacao
  // botao em pull-up: LOW == pressionado
  if (validationPressed(buttonA, now)) {
    registerValidation(0, now);
    emitJson("fila.validacao", "fila-A", now, 1, "pessoa", "VALIDADA");
  }

  if (validationPressed(buttonB, now)) {
    registerValidation(1, now);
    emitJson("fila.validacao", "fila-B", now, 1, "pessoa", "VALIDADA");
  }

  // limpar eventos fora de janela e recalcular metricao
  cleanOldEvents(now, timesA, &countA);
  cleanOldEvents(now, timesB, &countB);

  // vazao recente em pessoas/minuto
  flowA = countA * (60.0 / 20.0);
  flowB = countB * (60.0 / 20.0);

  // DADOS_INSUFICIENTES: se a vazao for zero, a fila nao tem dados recentes suficientes
  if (countA == 0 || countB == 0) {
    if (currentState != DADOS_INSUFICIENTES) {
      currentState = DADOS_INSUFICIENTES;
      applyRecommendationLighting(currentState);
      Serial.println("DADOS_INSUFICIENTES: sem validacoes recentes nas duas filas");
    }
    if (now - lastReportMs >= REPORT_INTERVAL_MS) {
      lastReportMs = now;
      emitJson("fila.recomendacao", "nenhuma", now, 0, "min", "DADOS_INSUFICIENTES");
      Serial.print("[entradas] btnA=");
      Serial.print(digitalRead(BTN_A_PIN));
      Serial.print(" btnB=");
      Serial.print(digitalRead(BTN_B_PIN));
      Serial.print(" ocupacaoA=");
      Serial.print(occA);
      Serial.print(" ocupacaoB=");
      Serial.println(occB);
    }
    return;
  }

  // Ao recuperar dados validos, retoma a ultima recomendacao confirmada.
  if (currentState == DADOS_INSUFICIENTES) {
    currentState = lastRecommendation;
    applyRecommendationLighting(currentState);
    Serial.println("Dados recuperados; retomando ultima recomendacao valida");
  }

  // Estimativa de tempo de espera = ocupacao / vazao
  waitA = (flowA > 0) ? occA / flowA : 9999;
  waitB = (flowB > 0) ? occB / flowB : 9999;

  // Regras de decisao baseada na histerese e persistencia temporal
  // estado e transicao deterministica
  float diffB = waitA - waitB; // vantagem de B sobre A
  float diffA = waitB - waitA; // vantagem de A sobre B

  bool canBReplaceA = diffB >= HISTERESIS_MIN;
  bool canAReplaceB = diffA >= HISTERESIS_MIN;

  if (currentState == RECOMENDA_A && canBReplaceA) {
    currentState = CANDIDATA_B;
    candidateStartMs = now;
    Serial.print("CANDIDATA_B diff=");
    Serial.println(diffB, 2);
  }
  else if (currentState == CANDIDATA_B) {
    if (canBReplaceA && (now - candidateStartMs >= CANDIDATE_MS)) {
      currentState = RECOMENDA_B;
      lastRecommendation = RECOMENDA_B;
      Serial.println("RECOMENDA_B");
    }
    else if (!canBReplaceA) {
      currentState = RECOMENDA_A;
      lastRecommendation = RECOMENDA_A;
      Serial.println("RECOMENDA_A");
    }
  }
  else if (currentState == RECOMENDA_B && canAReplaceB) {
    currentState = CANDIDATA_A;
    candidateStartMs = now;
    Serial.print("CANDIDATA_A diff=");
    Serial.println(diffA, 2);
  }
  else if (currentState == CANDIDATA_A) {
    if (canAReplaceB && (now - candidateStartMs >= CANDIDATE_MS)) {
      currentState = RECOMENDA_A;
      lastRecommendation = RECOMENDA_A;
      Serial.println("RECOMENDA_A");
    }
    else if (!canAReplaceB) {
      currentState = RECOMENDA_B;
      lastRecommendation = RECOMENDA_B;
      Serial.println("RECOMENDA_B");
    }
  }

  const char* stateName = "RECOMENDA_A";
  if (currentState == RECOMENDA_A) {
    stateName = "RECOMENDA_A";
  } else if (currentState == RECOMENDA_B) {
    stateName = "RECOMENDA_B";
  } else if (currentState == CANDIDATA_B) {
    stateName = "CANDIDATA_B";
  } else if (currentState == CANDIDATA_A) {
    stateName = "CANDIDATA_A";
  }

  applyRecommendationLighting(currentState);

  if (now - lastReportMs < REPORT_INTERVAL_MS) {
    return;
  }
  lastReportMs = now;

  emitJson("fila.metrica", "fila-A", now, flowA, "pessoas/min", "NORMAL");
  emitJson("fila.metrica", "fila-B", now, flowB, "pessoas/min", "NORMAL");

  const char* recommendedEntity = lastRecommendation == RECOMENDA_A ? "fila-A" : "fila-B";
  float recommendedWait = lastRecommendation == RECOMENDA_A ? waitA : waitB;
  emitJson("fila.recomendacao", recommendedEntity, now, recommendedWait, "min", stateName);

  // logs humanos auxiliares
  Serial.print("[");
  Serial.print(now);
  Serial.print(" ms] A=");
  Serial.print(waitA, 2);
  Serial.print(" B=");
  Serial.print(waitB, 2);
  Serial.print(" diffB=");
  Serial.print(diffB, 2);
  Serial.print(" state=");
  Serial.println(stateName);
}
