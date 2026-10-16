#include <Arduino.h>
#include <ArduinoJson.h>
#include <MQTT.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>
#include "segredos.h"

// ESP32 de entrada: somente detecta chegadas e publica telemetria.
// A passagem validada é publicada pelo aplicativo no navegador.
const char *BROKER = "host.wokwi.internal";
const unsigned long INTERVALO_SENSOR_MS = 200;
const unsigned long INTERVALO_HEARTBEAT_MS = 2000;
const float LIMIAR_CHEGADA_CM = 60.0;
const float LIMIAR_LIBERACAO_CM = 100.0;

struct FilaSensor {
  const char *id;
  uint8_t trig;
  uint8_t echo;
  bool sensorOcupado;
};

FilaSensor filas[2] = {
  {"fila-a", 32, 33, false},
  {"fila-b", 18, 19, false},
};

WiFiClientSecure tls;
MQTTClient mqtt(768);
String bootId;
uint32_t sequencia = 0;
unsigned long ultimaLeitura = 0;
unsigned long ultimoHeartbeat = 0;
unsigned long ultimaTentativa = 0;

struct Pendente { String topico; String payload; };
Pendente pendentes[32];
int inicio = 0;
int quantidadePendente = 0;

float distanciaCm(const FilaSensor &fila) {
  digitalWrite(fila.trig, LOW);
  delayMicroseconds(2);
  digitalWrite(fila.trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(fila.trig, LOW);
  unsigned long pulso = pulseIn(fila.echo, HIGH, 30000);
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

void publicarEvento(FilaSensor &fila, const char *tipo) {
  // Heartbeat é descartável: não ocupa o buffer reservado às chegadas
  // durante uma queda do broker.
  if (strcmp(tipo, "heartbeat") == 0 &&
      (!mqtt.connected() || quantidadePendente > 0)) return;
  StaticJsonDocument<256> doc;
  doc["filaId"] = fila.id;
  doc["tipo"] = tipo;
  doc["sequence"] = ++sequencia;
  doc["eventTimeMs"] = static_cast<uint64_t>(time(nullptr)) * 1000;
  doc["eventId"] = bootId + "-" + String(sequencia);
  String payload;
  serializeJson(doc, payload);
  String topico = String("fila/") + fila.id + "/" + tipo;
  if (strcmp(tipo, "heartbeat") == 0) {
    mqtt.publish(topico, payload, false, 1);
  } else {
    enfileirar(topico, payload);
    publicarPendentes();
  }
}

void verificarSensor(FilaSensor &fila) {
  float cm = distanciaCm(fila);
  if (!fila.sensorOcupado && cm <= LIMIAR_CHEGADA_CM) {
    fila.sensorOcupado = true;
    Serial.printf("Chegada detectada na %s (%.0f cm)\n", fila.id, cm);
    publicarEvento(fila, "contagem");
  } else if (fila.sensorOcupado && cm >= LIMIAR_LIBERACAO_CM) {
    fila.sensorOcupado = false;
  }
}

void conectarMqtt() {
  if (mqtt.connected() || millis() - ultimaTentativa < 3000) return;
  ultimaTentativa = millis();
  if (mqtt.connect("wokwi-sensores", "produtor", MQTT_SENHA)) {
    Serial.println("MQTT/TLS autenticado");
    publicarPendentes();
  } else {
    Serial.printf("Falha MQTT: %d\n", mqtt.lastError());
  }
}

void setup() {
  Serial.begin(115200);
  for (FilaSensor &fila : filas) {
    pinMode(fila.trig, OUTPUT);
    pinMode(fila.echo, INPUT);
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
    for (FilaSensor &fila : filas) verificarSensor(fila);
  }
  if (millis() - ultimoHeartbeat >= INTERVALO_HEARTBEAT_MS) {
    ultimoHeartbeat = millis();
    for (FilaSensor &fila : filas) publicarEvento(fila, "heartbeat");
  }
  publicarPendentes();
}
