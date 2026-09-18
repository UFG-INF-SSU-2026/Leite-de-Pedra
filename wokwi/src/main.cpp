#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// Protótipo de hardware de duas filas. Não fala com o broker nem com o
// consumidor.py: existe para mostrar o que o hardware do ponto de entrada faz.
//
// Cada fila tem um botão de chegada, que faz o papel do infravermelho da
// entrada contando uma pessoa, e um semáforo de três LEDs. O validador facial
// não tem botão: aprova uma pessoa a cada INTERVALO_APROVACAO_MS enquanto houver
// alguém na fila. O display mostra o estado das duas filas e qual delas o
// próximo a chegar deve procurar.

enum Estado { LIVRE, ATENCAO, BLOQUEADA };
const char *ROTULOS[] = {"LIV", "ATN", "BLQ"};

// O validador do protótipo é mais rápido que o do produtor.py (7 s por pessoa)
// para que a fila se esvazie a tempo de acompanhar a simulação. Como a espera
// estimada parte desse tempo, os limiares do consumidor passam a valer com mais
// gente na fila: amarelo a partir de 8 pessoas, vermelho a partir de 16.
const unsigned long INTERVALO_APROVACAO_MS = 2000;
const int TEMPO_MEDIO_PASSAGEM = INTERVALO_APROVACAO_MS / 1000;   // segundos por pessoa

// Mesmos limiares do consumidor.py.
const int LIMITE_ATENCAO = 15;        // segundos de espera estimada
const int LIMITE_BLOQUEIO = 30;
const int MARGEM_HISTERESE = 7;

const unsigned long DEBOUNCE_MS = 40;

struct Botao {
  uint8_t pino;
  int ultimaLeitura;
  int estavel;
  unsigned long mudouEm;
};

struct Fila {
  char nome;
  Botao chegada;
  uint8_t leds[3];   // indexado por Estado: verde, amarelo, vermelho
  int entradas;
  int saidas;
  Estado estado;
  unsigned long ultimaAprovacao;
};

const int QUANTIDADE = 2;
Fila filas[QUANTIDADE] = {
  {'A', {32, HIGH, HIGH, 0}, {26, 27, 14}, 0, 0, LIVRE, 0},
  {'B', {18, HIGH, HIGH, 0}, {23, 5, 4},   0, 0, LIVRE, 0},
};

LiquidCrystal_I2C lcd(0x27, 20, 4);

// Ocupação é diferença de contadores acumulados, como no consumidor.
int ocupacao(const Fila &f) {
  return max(0, f.entradas - f.saidas);
}

// Neste protótipo não há vazão medida: a espera usa o tempo médio nominal.
int espera(const Fila &f) {
  return ocupacao(f) * TEMPO_MEDIO_PASSAGEM;
}

// Mesma histerese do consumidor: sobe pelo limite, desce só com margem.
// Sem ela o semáforo piscaria com a espera oscilando em torno do limite.
Estado classificar(Estado atual, int tempo) {
  int desceParaLivre = LIMITE_ATENCAO - MARGEM_HISTERESE;
  int desceParaAtencao = LIMITE_BLOQUEIO - MARGEM_HISTERESE;

  if (atual == BLOQUEADA) {
    if (tempo <= desceParaLivre) return LIVRE;
    if (tempo <= desceParaAtencao) return ATENCAO;
    return BLOQUEADA;
  }
  if (atual == ATENCAO) {
    if (tempo > LIMITE_BLOQUEIO) return BLOQUEADA;
    if (tempo <= desceParaLivre) return LIVRE;
    return ATENCAO;
  }
  if (tempo > LIMITE_BLOQUEIO) return BLOQUEADA;
  if (tempo > LIMITE_ATENCAO) return ATENCAO;
  return LIVRE;
}

// Fila que o próximo a chegar deve procurar: a de menor espera estimada.
// Devolve -1 quando todas esperam o mesmo, porque então não há o que indicar
// e apontar sempre a primeira faria as pessoas se empilharem nela.
int melhorFila() {
  int melhor = 0;
  bool todasIguais = true;
  for (int i = 1; i < QUANTIDADE; i++) {
    if (espera(filas[i]) != espera(filas[0])) todasIguais = false;
    if (espera(filas[i]) < espera(filas[melhor])) melhor = i;
  }
  return todasIguais ? -1 : melhor;
}

bool acionado(Botao &b) {
  int leitura = digitalRead(b.pino);
  if (leitura != b.ultimaLeitura) {
    b.mudouEm = millis();
    b.ultimaLeitura = leitura;
  }
  if (millis() - b.mudouEm >= DEBOUNCE_MS && leitura != b.estavel) {
    b.estavel = leitura;
    return leitura == LOW;
  }
  return false;
}

void atualizar() {
  for (int i = 0; i < QUANTIDADE; i++) {
    Estado anterior = filas[i].estado;
    filas[i].estado = classificar(anterior, espera(filas[i]));
    if (filas[i].estado != anterior) {
      Serial.printf(">>> fila-%c: %s -> %s  (%ds de espera, %d na fila)\n",
                    filas[i].nome, ROTULOS[anterior], ROTULOS[filas[i].estado],
                    espera(filas[i]), ocupacao(filas[i]));
    }
  }

  for (int i = 0; i < QUANTIDADE; i++) {
    for (int e = LIVRE; e <= BLOQUEADA; e++) {
      digitalWrite(filas[i].leds[e], e == filas[i].estado ? HIGH : LOW);
    }

    char linha[21];
    snprintf(linha, sizeof(linha), "%c %s %2dp %3ds", filas[i].nome,
             ROTULOS[filas[i].estado], ocupacao(filas[i]), espera(filas[i]));
    lcd.setCursor(0, i);
    lcd.print(linha);
  }

  int melhor = melhorFila();
  char indicacao[21];
  if (melhor < 0) {
    snprintf(indicacao, sizeof(indicacao), "%-20s", "  Qualquer fila");
  } else {
    char texto[21];
    snprintf(texto, sizeof(texto), ">> Ir para fila %c <<", filas[melhor].nome);
    snprintf(indicacao, sizeof(indicacao), "%-20s", texto);
  }
  lcd.setCursor(0, 3);
  lcd.print(indicacao);
}

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < QUANTIDADE; i++) {
    pinMode(filas[i].chegada.pino, INPUT_PULLUP);
    for (int e = LIVRE; e <= BLOQUEADA; e++) pinMode(filas[i].leds[e], OUTPUT);
  }

  lcd.init();
  lcd.backlight();

  Serial.println("Protótipo de hardware: 2 filas");
  atualizar();
}

void loop() {
  bool mudou = false;

  for (int i = 0; i < QUANTIDADE; i++) {
    if (acionado(filas[i].chegada)) {
      filas[i].entradas++;
      Serial.printf("infravermelho fila-%c: %d na fila\n", filas[i].nome, ocupacao(filas[i]));
      mudou = true;
    }
    // O validador só tem o que aprovar se houver alguém na fila; com a fila
    // vazia o ciclo apenas passa.
    if (millis() - filas[i].ultimaAprovacao >= INTERVALO_APROVACAO_MS) {
      filas[i].ultimaAprovacao = millis();
      if (ocupacao(filas[i]) > 0) {
        filas[i].saidas++;
        Serial.printf("validador fila-%c: aprovado, %d na fila\n", filas[i].nome, ocupacao(filas[i]));
        mudou = true;
      }
    }
  }

  if (mudou) atualizar();
}
