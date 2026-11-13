#include <Arduino.h>
#include <ArduinoJson.h>
#include <MQTT.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>
#include "segredos.h"

#ifdef INTRUSO
// Firmware clonado de teste: conhece a CA (pública), mas não a senha do produtor.
const char *SENHA = "senha-adivinhada";
const char *ID_CLIENTE = "wokwi-intruso";
#else
const char *SENHA = MQTT_SENHA;
const char *ID_CLIENTE = "wokwi-sensores";
#endif

// ESP32 das filas: cada fila tem um sensor na entrada e outro na saída.
// Ele só publica movimentos; quem calcula ocupação e espera é o processador.
// Mensagens no contrato comum (docs/ARQUITETURA.md, "Contrato das mensagens").
const char *BROKER = "host.wokwi.internal";
const char *USUARIO = "produtor";  // também o source: o broker usa o usuário como client id
const char *TOPICO_STATUS = "sistema/produtor/status";
const unsigned long INTERVALO_SENSOR_MS = 200;
const unsigned long INTERVALO_HEARTBEAT_MS = 2000;
const float LIMIAR_PRESENCA_CM = 60.0;
const float LIMIAR_LIBERACAO_CM = 100.0;
const char *FILAS[] = {"fila-a", "fila-b"};

struct Sensor {
  const char *fila;
  const char *tipo;  // "contagem" na entrada, "saida" na saída
  uint8_t trig;
  uint8_t echo;
  bool ocupado;
};

Sensor sensores[4] = {
  {"fila-a", "contagem", 32, 33, false},
  {"fila-a", "saida", 25, 26, false},
  {"fila-b", "contagem", 18, 19, false},
  {"fila-b", "saida", 22, 23, false},
};

WiFiClientSecure tls;
MQTTClient mqtt(768);
String bootId;
uint32_t sequencia = 0;
uint32_t conexoes = 0;
unsigned long ultimaLeitura = 0;
unsigned long ultimoHeartbeat = 0;
unsigned long ultimaTentativa = 0;

struct Pendente { String topico; String payload; };
Pendente pendentes[32];
int inicio = 0;
int quantidadePendente = 0;

float distanciaCm(const Sensor &sensor) {
  digitalWrite(sensor.trig, LOW);
  delayMicroseconds(2);
  digitalWrite(sensor.trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(sensor.trig, LOW);
  unsigned long pulso = pulseIn(sensor.echo, HIGH, 30000);
  return pulso == 0 ? 400.0 : pulso / 58.0;
}

void enfileirar(const String &topico, const String &payload) {
  if (quantidadePendente == 32) {
    Serial.println("Fila local cheia: aproxime novamente após reconexão");
    return;
  }
  int posicao = (inicio + quantidadePendente) % 32;
  pendentes[posicao] = {topico, payload};
  quantidadePendente++;
}

void publicarPendentes() {
  while (mqtt.connected() && quantidadePendente > 0) {
    Pendente &evento = pendentes[inicio];
    if (!mqtt.publish(evento.topico, evento.payload, false, 1)) return;
    Serial.printf("Publicado: %s = %s\n", evento.topico.c_str(), evento.payload.c_str());
    evento = {"", ""};
    inicio = (inicio + 1) % 32;
    quantidadePendente--;
  }
}

// Envelope do contrato. Um movimento abre a própria operação: correlation_id = event_id.
String envelope(const String &id, const char *tipo, JsonDocument &doc) {
  doc["event_id"] = id;
  doc["correlation_id"] = id;
  doc["event_type"] = tipo;
  doc["source"] = USUARIO;
  doc["timestamp"] = static_cast<uint64_t>(time(nullptr)) * 1000;
  String json;
  serializeJson(doc, json);
  return json;
}

String status(bool online) {
  StaticJsonDocument<384> doc;
  doc["payload"]["online"] = online;
  return envelope(bootId + "-status-" + String(conexoes) + (online ? "-online" : "-offline"),
                  "status", doc);
}

void publicarEvento(const char *fila, const char *tipo) {
  // Heartbeat é descartável: não ocupa o buffer reservado aos movimentos
  // durante uma queda do broker.
  if (strcmp(tipo, "heartbeat") == 0 &&
      (!mqtt.connected() || quantidadePendente > 0)) return;
  StaticJsonDocument<384> doc;
  doc["payload"]["filaId"] = fila;
  doc["payload"]["sequence"] = ++sequencia;
  String payload = envelope(bootId + "-" + String(sequencia), tipo, doc);
  String topico = String("fila/") + fila + "/" + tipo;
  if (strcmp(tipo, "heartbeat") == 0) {
    mqtt.publish(topico, payload, false, 1);
  } else {
    enfileirar(topico, payload);
    publicarPendentes();
  }
}

void verificarSensor(Sensor &sensor) {
  float cm = distanciaCm(sensor);
  if (!sensor.ocupado && cm <= LIMIAR_PRESENCA_CM) {
    sensor.ocupado = true;
    Serial.printf("%s detectada na %s (%.0f cm)\n",
                  strcmp(sensor.tipo, "saida") == 0 ? "Saída" : "Chegada", sensor.fila, cm);
    publicarEvento(sensor.fila, sensor.tipo);
  } else if (sensor.ocupado && cm >= LIMIAR_LIBERACAO_CM) {
    sensor.ocupado = false;
  }
}

// Simulação: "chegada fila-a" ou "saida fila-b" na serial vale como uma pessoa
// passando pelo sensor. É por aqui que o teste e2e (tests/e2e_completo.py) lota
// as filas pela porta RFC 2217 do Wokwi, já que o slider do HC-SR04 não aceita automação.
void lerComandoSerial() {
  if (!Serial.available()) return;
  String linha = Serial.readStringUntil('\n');
  linha.trim();
  int espaco = linha.indexOf(' ');
  String acao = linha.substring(0, espaco);
  String fila = linha.substring(espaco + 1);
  for (Sensor &sensor : sensores) {
    bool saida = strcmp(sensor.tipo, "saida") == 0;
    if (espaco > 0 && fila == sensor.fila && acao == (saida ? "saida" : "chegada")) {
      Serial.printf("%s simulada na %s\n", saida ? "Saída" : "Chegada", sensor.fila);
      publicarEvento(sensor.fila, sensor.tipo);
      return;
    }
  }
  if (linha.length()) Serial.printf("Comando desconhecido: %s\n", linha.c_str());
}

void conectarMqtt() {
  if (mqtt.connected() || millis() - ultimaTentativa < 3000) return;
  ultimaTentativa = millis();
  conexoes++;
  // Last Will: se a conexão cair, o broker publica offline (retido) por nós.
  mqtt.setWill(TOPICO_STATUS, status(false).c_str(), true, 1);
  if (mqtt.connect(ID_CLIENTE, USUARIO, SENHA)) {
    Serial.println("MQTT/TLS autenticado");
    mqtt.publish(TOPICO_STATUS, status(true), true, 1);
    publicarPendentes();
  } else {
    // Retorno 5 do CONNACK = não autorizado pelo broker.
    Serial.printf("Falha MQTT: %d (retorno %d)\n", mqtt.lastError(), mqtt.returnCode());
  }
}

void setup() {
  Serial.begin(115200);
  for (Sensor &sensor : sensores) {
    pinMode(sensor.trig, OUTPUT);
    pinMode(sensor.echo, INPUT);
  }
  bootId = String(esp_random(), HEX);
  WiFi.begin("Wokwi-GUEST", "", 6);
  while (WiFi.status() != WL_CONNECTED) delay(100);
  Serial.println("WiFi conectado");
  configTime(0, 0, "pool.ntp.org");
  while (time(nullptr) < 1700000000) delay(100);
  tls.setCACert(MQTT_CA);
  mqtt.begin(BROKER, 8883, tls);
  conectarMqtt();
}

void loop() {
  mqtt.loop();
  conectarMqtt();
  if (millis() - ultimaLeitura >= INTERVALO_SENSOR_MS) {
    ultimaLeitura = millis();
    for (Sensor &sensor : sensores) verificarSensor(sensor);
  }
  lerComandoSerial();
  if (millis() - ultimoHeartbeat >= INTERVALO_HEARTBEAT_MS) {
    ultimoHeartbeat = millis();
    for (const char *fila : FILAS) publicarEvento(fila, "heartbeat");
  }
  publicarPendentes();
}
