#include <Arduino.h>
#include <ArduinoJson.h>
#include <LiquidCrystal_I2C.h>
#include <MQTT.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <time.h>
#include "segredos_consumidor.h"

// ESP32 de saída: apenas recebe o estado publicado pelo processador Python.
const char *BROKER = "host.wokwi.internal";

struct FilaSinalizada {
  const char *id;
  char letra;
  uint8_t leds[3]; // verde, amarelo, vermelho
  int ocupacao;
  int estado; // -1 sem dados; 0 livre, 1 atenção, 2 bloqueada
  String destino;
};

FilaSinalizada filas[2] = {
  {"fila-a", 'A', {26, 27, 14}, 0, -1, "fila-a"},
  {"fila-b", 'B', {23, 5, 4}, 0, -1, "fila-b"},
};

LiquidCrystal_I2C lcd(0x27, 20, 4);
WiFiClientSecure tls;
MQTTClient mqtt(768);
unsigned long ultimaTentativa = 0;
bool estavaConectado = false;

void linhaLcd(uint8_t linha, const String &texto) {
  String ajustado = texto.substring(0, 20);
  while (ajustado.length() < 20) ajustado += ' ';
  lcd.setCursor(0, linha);
  lcd.print(ajustado);
}

void atualizarDisplay() {
  const char *rotulos[] = {"LIV", "ATN", "BLQ"};
  bool conectado = mqtt.connected();
  for (FilaSinalizada &fila : filas) {
    String texto = String(fila.letra) + " " +
      (fila.estado < 0 ? "---" : rotulos[fila.estado]) + "  " +
      String(fila.ocupacao) + " pessoa(s)";
    linhaLcd(fila.letra == 'A' ? 0 : 1, texto);
    for (int cor = 0; cor < 3; cor++) {
      digitalWrite(fila.leds[cor], conectado && fila.estado == cor ? HIGH : LOW);
    }
  }
  linhaLcd(2, conectado ? "MQTT/TLS conectado" : "MQTT desconectado");
  String destino = filas[0].destino == "fila-b" ? "Ir para fila B" :
                   filas[1].destino == "fila-a" ? "Ir para fila A" :
                   "Escolha fila verde";
  linhaLcd(3, destino);
}

void receberEstado(String &topico, String &mensagem) {
  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, mensagem)) return;
  const char *id = doc["filaId"] | "";
  for (FilaSinalizada &fila : filas) {
    if (strcmp(id, fila.id) != 0 || topico != String("fila/") + fila.id + "/estado") continue;
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

void conectarMqtt() {
  if (mqtt.connected() || millis() - ultimaTentativa < 3000) return;
  ultimaTentativa = millis();
  if (mqtt.connect("wokwi-consumidor", "consumidor", MQTT_SENHA)) {
    Serial.println("MQTT/TLS autenticado como consumidor");
    mqtt.subscribe("fila/+/estado", 1);
    estavaConectado = true;
    atualizarDisplay();
  } else {
    Serial.printf("Falha MQTT: %d\n", mqtt.lastError());
  }
}

void setup() {
  Serial.begin(115200);
  for (FilaSinalizada &fila : filas) {
    for (uint8_t led : fila.leds) pinMode(led, OUTPUT);
  }
  lcd.init();
  lcd.backlight();
  linhaLcd(0, "Conectando WiFi...");
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
  if (!mqtt.connected() && estavaConectado) {
    estavaConectado = false;
    for (FilaSinalizada &fila : filas) fila.estado = -1;
    atualizarDisplay();
  }
  conectarMqtt();
}
