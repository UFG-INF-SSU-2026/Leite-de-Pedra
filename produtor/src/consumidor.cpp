#include <Arduino.h>
#include <ArduinoJson.h>
#include <LiquidCrystal_I2C.h>
#include <MQTT.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <time.h>
#include "segredos_consumidor.h"

// ESP32 de saída: só executa o que o processador decidiu, no contrato comum
// (docs/ARQUITETURA.md, "Contrato das mensagens"). O estado vira semáforo e
// LCD; o resultado de uma leitura vira a reação da catraca, confirmada em
// fila/{id}/reacao para a observabilidade.
const char *BROKER = "host.wokwi.internal";
const char *USUARIO = "consumidor";  // também o source: o broker usa o usuário como client id
const char *TOPICO_STATUS = "sistema/consumidor/status";
const unsigned long DURACAO_REACAO_MS = 4000;
const unsigned long PISCA_REACAO_MS = 250;

struct FilaSinalizada {
  const char *id;
  char letra;
  uint8_t leds[3]; // verde, amarelo, vermelho
  int ocupacao;
  int estado; // -1 sem dados; 0 livre, 1 atenção, 2 bloqueada
  String destino;
  int reacao;  // -1 nenhuma; LED que pisca: 0 liberar (verde), 1 decidir manualmente (amarelo), 2 barrar (vermelho)
  unsigned long reacaoDesde;
  String ultimoResultado;  // event_id: o outbox pode reenviar o mesmo resultado
  String reacaoPendente;   // confirmação a publicar no loop (a biblioteca não publica no callback)
};

FilaSinalizada filas[2] = {
  {"fila-a", 'A', {26, 27, 14}, 0, -1, "fila-a", -1},
  {"fila-b", 'B', {23, 5, 4}, 0, -1, "fila-b", -1},
};
const char *ACOES[] = {"liberar", "decidir-manual", "barrar"};
const char *TEXTOS_REACAO[] = {"LIBERADO", "DECIDIR MANUALMENTE", "BARRADO"};

LiquidCrystal_I2C lcd(0x27, 20, 4);
WiFiClientSecure tls;
MQTTClient mqtt(768);
unsigned long ultimaTentativa = 0;
bool estavaConectado = false;
String bootId;
uint32_t conexoes = 0;

String status(bool online) {
  StaticJsonDocument<384> doc;
  String id = bootId + "-status-" + String(conexoes) + (online ? "-online" : "-offline");
  doc["event_id"] = id;
  doc["correlation_id"] = id;
  doc["event_type"] = "status";
  doc["source"] = USUARIO;
  doc["timestamp"] = static_cast<uint64_t>(time(nullptr)) * 1000;
  doc["payload"]["online"] = online;
  String json;
  serializeJson(doc, json);
  return json;
}

void linhaLcd(uint8_t linha, const String &texto) {
  String ajustado = texto.substring(0, 20);
  while (ajustado.length() < 20) ajustado += ' ';
  lcd.setCursor(0, linha);
  lcd.print(ajustado);
}

void atualizarDisplay() {
  const char *rotulos[] = {"LIV", "ATN", "BLQ"};
  bool conectado = mqtt.connected();
  bool aceso = (millis() / PISCA_REACAO_MS) % 2 == 0;
  FilaSinalizada *ultimaReacao = nullptr;
  for (FilaSinalizada &fila : filas) {
    String texto = String(fila.letra) + " " +
      (fila.estado < 0 ? "---" : rotulos[fila.estado]) + "  " +
      String(fila.ocupacao) + " pessoa(s)";
    linhaLcd(fila.letra == 'A' ? 0 : 1, texto);
    for (int cor = 0; cor < 3; cor++) {
      // Durante a reação, o LED da decisão pisca no lugar do semáforo.
      bool ligado = fila.reacao >= 0 ? fila.reacao == cor && aceso : conectado && fila.estado == cor;
      digitalWrite(fila.leds[cor], ligado ? HIGH : LOW);
    }
    if (fila.reacao >= 0 && (!ultimaReacao || fila.reacaoDesde > ultimaReacao->reacaoDesde)) {
      ultimaReacao = &fila;
    }
  }
  linhaLcd(2, conectado ? "MQTT/TLS conectado" : "MQTT desconectado");
  if (ultimaReacao) {
    linhaLcd(3, String(ultimaReacao->letra) + ": " + TEXTOS_REACAO[ultimaReacao->reacao]);
    return;
  }
  String destino = filas[0].destino == "fila-b" ? "Ir para fila B" :
                   filas[1].destino == "fila-a" ? "Ir para fila A" :
                   "Escolha fila verde";
  linhaLcd(3, destino);
}

// Confirmação da reação: mesma operação (correlation_id) e event_id derivado do
// resultado, para quem observa deduplicar um reenvio.
String reacaoJson(JsonObject resultado, const char *resultadoId, const char *correlacao, int reacao) {
  StaticJsonDocument<512> doc;
  doc["event_id"] = String(resultadoId) + "-reacao";
  doc["correlation_id"] = correlacao;
  doc["event_type"] = "reacao";
  doc["source"] = USUARIO;
  doc["timestamp"] = static_cast<uint64_t>(time(nullptr)) * 1000;
  doc["payload"]["filaId"] = resultado["filaId"];
  doc["payload"]["resultadoId"] = resultadoId;
  doc["payload"]["resultado"] = resultado["resultado"];
  doc["payload"]["acao"] = ACOES[reacao];
  String json;
  serializeJson(doc, json);
  return json;
}

void receberResultado(String &topico, JsonDocument &doc) {
  JsonObject resultado = doc["payload"];
  const char *id = resultado["filaId"] | "";
  const char *decisao = resultado["resultado"] | "";
  const char *resultadoId = doc["event_id"] | "";
  int reacao = strcmp(decisao, "aceito") == 0 ? 0 :
               strcmp(decisao, "indeterminado") == 0 ? 1 :
               strcmp(decisao, "recusado") == 0 ? 2 : -1;
  if (reacao < 0 || strlen(resultadoId) == 0) return;
  for (FilaSinalizada &fila : filas) {
    if (strcmp(id, fila.id) != 0 || topico != String("fila/") + fila.id + "/resultado") continue;
    // Reenvio do mesmo resultado: confirma de novo, sem repetir a reação.
    if (fila.ultimoResultado != resultadoId) {
      fila.ultimoResultado = resultadoId;
      fila.reacao = reacao;
      fila.reacaoDesde = millis();
      Serial.printf("Resultado recebido: %s, %s -> %s\n", fila.id, decisao, ACOES[reacao]);
      atualizarDisplay();
    }
    fila.reacaoPendente = reacaoJson(resultado, resultadoId, doc["correlation_id"] | resultadoId, reacao);
    return;
  }
}

void receberEstado(String &topico, JsonDocument &doc) {
  JsonObject estado = doc["payload"];
  const char *id = estado["filaId"] | "";
  for (FilaSinalizada &fila : filas) {
    if (strcmp(id, fila.id) != 0 || topico != String("fila/") + fila.id + "/estado") continue;
    const char *cor = estado["semaforo"] | "";
    fila.estado = strcmp(cor, "livre") == 0 ? 0 :
                  strcmp(cor, "atencao") == 0 ? 1 :
                  strcmp(cor, "bloqueada") == 0 ? 2 : -1;
    fila.ocupacao = estado["ocupacao"] | 0;
    fila.destino = String((const char *)(estado["sentidoRecomendado"] | fila.id));
    Serial.printf("Estado recebido: %s, %d pessoa(s), %s\n",
                  fila.id, fila.ocupacao, cor);
    atualizarDisplay();
    return;
  }
}

void receber(String &topico, String &mensagem) {
  StaticJsonDocument<768> doc;
  if (deserializeJson(doc, mensagem)) return;
  const char *tipo = doc["event_type"] | "";
  if (strcmp(tipo, "estado") == 0 && topico.endsWith("/estado")) receberEstado(topico, doc);
  if (strcmp(tipo, "resultado") == 0 && topico.endsWith("/resultado")) receberResultado(topico, doc);
}

void conectarMqtt() {
  if (mqtt.connected() || millis() - ultimaTentativa < 3000) return;
  ultimaTentativa = millis();
  conexoes++;
  // Last Will: se a conexão cair, o broker publica offline (retido) por nós.
  mqtt.setWill(TOPICO_STATUS, status(false).c_str(), true, 1);
  if (mqtt.connect("wokwi-consumidor", USUARIO, MQTT_SENHA)) {
    Serial.println("MQTT/TLS autenticado como consumidor");
    mqtt.publish(TOPICO_STATUS, status(true), true, 1);
    mqtt.subscribe("fila/+/estado", 1);
    mqtt.subscribe("fila/+/resultado", 1);
    estavaConectado = true;
    atualizarDisplay();
  } else {
    Serial.printf("Falha MQTT: %d\n", mqtt.lastError());
  }
}

void setup() {
  Serial.begin(115200);
  bootId = String(esp_random(), HEX);
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
  mqtt.onMessage(receber);
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
  bool emReacao = false;
  for (FilaSinalizada &fila : filas) {
    if (fila.reacaoPendente.length() && mqtt.connected() &&
        mqtt.publish(String("fila/") + fila.id + "/reacao", fila.reacaoPendente, false, 1)) {
      Serial.printf("Reação confirmada: %s\n", fila.id);
      fila.reacaoPendente = "";
    }
    if (fila.reacao >= 0 && millis() - fila.reacaoDesde >= DURACAO_REACAO_MS) {
      fila.reacao = -1;  // volta ao semáforo
      atualizarDisplay();
    }
    emReacao = emReacao || fila.reacao >= 0;
  }
  static unsigned long ultimoPisca = 0;
  if (emReacao && millis() - ultimoPisca >= PISCA_REACAO_MS) {
    ultimoPisca = millis();
    atualizarDisplay();
  }
}
