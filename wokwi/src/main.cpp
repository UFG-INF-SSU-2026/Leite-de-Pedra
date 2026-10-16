#include <Arduino.h>
#include <ArduinoJson.h>
#include <LiquidCrystal_I2C.h>
#include <MQTT.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <time.h>
#include "segredos.h"

// Cada aproximação seguida de afastamento representa uma nova chegada.
// A passagem validada é publicada pelo aplicativo no navegador.
const char *BROKER = "host.wokwi.internal";
const unsigned long INTERVALO_SENSOR_MS = 200;
const unsigned long INTERVALO_HEARTBEAT_MS = 2000;
const float LIMIAR_CHEGADA_CM = 60.0;
const float LIMIAR_LIBERACAO_CM = 100.0;

struct Fila {
  const char *id;
  char letra;
  uint8_t trig;
  uint8_t echo;
  uint8_t leds[3]; // verde, amarelo, vermelho
  bool sensorOcupado;
  int ocupacao;
  int estado; // -1 sem recomendação; 0 livre, 1 atenção, 2 bloqueada
  String destino;
};

Fila filas[2] = {
  {"fila-a", 'A', 32, 33, {26, 27, 14}, false, 0, -1, "fila-a"},
  {"fila-b", 'B', 18, 19, {23, 5, 4}, false, 0, -1, "fila-b"},
};

LiquidCrystal_I2C lcd(0x27, 20, 4);
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

void linhaLcd(uint8_t linha, const String &texto) {
  String ajustado = texto.substring(0, 20);
  while (ajustado.length() < 20) ajustado += ' ';
  lcd.setCursor(0, linha);
  lcd.print(ajustado);
}

void atualizarDisplay() {
  const char *rotulos[] = {"LIV", "ATN", "BLQ"};
  for (Fila &fila : filas) {
    String texto = String(fila.letra) + " " +
      (fila.estado < 0 ? "---" : rotulos[fila.estado]) + "  " +
      String(fila.ocupacao) + " pessoa(s)";
    linhaLcd(fila.letra == 'A' ? 0 : 1, texto);
    for (int cor = 0; cor < 3; cor++) {
      digitalWrite(fila.leds[cor], fila.estado == cor ? HIGH : LOW);
    }
  }
  linhaLcd(2, mqtt.connected() ? "MQTT/TLS conectado" : "MQTT desconectado");
  String destino = filas[0].destino == "fila-b" ? "Ir para fila B" :
                   filas[1].destino == "fila-a" ? "Ir para fila A" :
                   "Escolha fila verde";
  linhaLcd(3, destino);
}

void receberEstado(String &topico, String &mensagem) {
  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, mensagem)) return;
  const char *id = doc["filaId"] | "";
  for (Fila &fila : filas) {
    if (strcmp(id, fila.id) != 0) continue;
    const char *cor = doc["semaforo"] | "";
    fila.estado = strcmp(cor, "livre") == 0 ? 0 :
                  strcmp(cor, "atencao") == 0 ? 1 :
                  strcmp(cor, "bloqueada") == 0 ? 2 : -1;
    fila.ocupacao = doc["ocupacao"] | 0;
    fila.destino = String((const char *)(doc["sentidoRecomendado"] | fila.id));
    Serial.printf("Estado recebido: %s, %d pessoa(s), %s\n",
                  fila.id, fila.ocupacao, cor);
    atualizarDisplay();
    return;
  }
}

float distanciaCm(const Fila &fila) {
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

void publicarEvento(Fila &fila, const char *tipo) {
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

void verificarSensor(Fila &fila) {
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
  if (mqtt.connect("wokwi-filas", "produtor", MQTT_SENHA)) {
    Serial.println("MQTT/TLS autenticado");
    mqtt.subscribe("fila/+/estado", 1);
    publicarPendentes();
    atualizarDisplay();
  } else {
    Serial.printf("Falha MQTT: %d\n", mqtt.lastError());
  }
}

void setup() {
  Serial.begin(115200);
  for (Fila &fila : filas) {
    pinMode(fila.trig, OUTPUT);
    pinMode(fila.echo, INPUT);
    for (uint8_t led : fila.leds) pinMode(led, OUTPUT);
  }
  lcd.init();
  lcd.backlight();
  linhaLcd(0, "Conectando WiFi...");
  bootId = String(esp_random(), HEX);
  WiFi.begin("Wokwi-GUEST", "", 6);
  while (WiFi.status() != WL_CONNECTED) delay(100);
  Serial.println("WiFi conectado");
  configTime(0, 0, "pool.ntp.org");
  while (time(nullptr) < 1700000000) delay(100);
  tls.setCACert(MQTT_CA);
  mqtt.begin(BROKER, 8883, tls);
  mqtt.onMessage(receberEstado);
  conectarMqtt();
  atualizarDisplay();
}

void loop() {
  mqtt.loop();
  conectarMqtt();
  if (millis() - ultimaLeitura >= INTERVALO_SENSOR_MS) {
    ultimaLeitura = millis();
    for (Fila &fila : filas) verificarSensor(fila);
  }
  if (millis() - ultimoHeartbeat >= INTERVALO_HEARTBEAT_MS) {
    ultimoHeartbeat = millis();
    for (Fila &fila : filas) publicarEvento(fila, "heartbeat");
  }
  publicarPendentes();
}
