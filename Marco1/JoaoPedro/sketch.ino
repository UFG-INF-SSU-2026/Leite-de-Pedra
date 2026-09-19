/*
 * ================================================================
 * Software para Sistemas Ubiquos - Atividade 03 (protótipo individual)
 * Aluno: João Pedro de Brito Tomé - matrícula 202302612
 * Grupo/cenário: o mesmo da Atividade 01/02 - balanceamento de fila em
 *   entrada única de eventos, validação de ingresso feita pela câmera
 *   de um celular/tablet, recomendação de fila calculada na névoa e
 *   exibida em painel de LED.
 *
 * RECORTE INDIVIDUAL: o dispositivo de borda (ponto de validação),
 * do lado da COMUNICAÇÃO E RESILIÊNCIA com a névoa:
 *   - contrato de evento (JSON com identidade/tempo/sequência/valor/unidade)
 *   - sequência monotônica e heartbeat
 *   - fila local (outbox) para quando o enlace cai
 *   - detecção de silêncio (heartbeat sem ACK) e desconexão
 *   - deduplicação de eventos reenviados (idempotência)
 *   - recuperação: flush da fila ao reconectar, sem re-contar duplicatas
 *
 * Teste adversarial exigido pelo final da matrícula (2): "Mudanças
 * rápidas, ruído ou acionamentos repetidos" -> ver debounce + intervalo
 * mínimo entre validações, histerese/debounce do enlace e dedup por
 * sequência (comentados nos pontos correspondentes abaixo).
 *
 * Entradas (todas simuladas - ver relatorio.md, seção "Limitações"):
 *   D4  botão   = ocorrência "ValidacaoRealizada" (pressão curta)
 *                 pressão longa (~1s) = reinjeta manualmente o último
 *                 evento, simulando uma reentrega de rede (QoS>=1)
 *   D18 chave   = estado do enlace dispositivo<->broker/névoa
 *                 (posição para 3V3 = ONLINE; para GND = OFFLINE)
 *   D34 potenciômetro = bateria_pct (grandeza fictícia, ver relatorio.md)
 *
 * Saídas:
 *   D25 LED verde    = painel: recomendação fresca
 *   D26 LED amarelo  = painel: segurando última recomendação (enlace
 *                      caído ou recomendação expirada)
 *   D27 LED vermelho = painel: fila sem dado confiável (offline > limiar)
 *   D14 LED azul     = há eventos pendentes na fila local (outbox)
 *   D13 buzzer       = sinaliza transições de estado do painel (não soa
 *                      em toda leitura, só quando o estado muda)
 * ================================================================
 */

#include <stdarg.h>
#define BTN_VALIDA 4
#define SW_LINK 18
#define POT_BAT 34
#define LED_VERDE 25
#define LED_AMARELO 26
#define LED_VERMELHO 27
#define LED_AZUL 14
#define BUZZER 13
#define DEVICE_ID "esp32-portao2-catraca3"
#define ENTITY_ID "portao-2-catraca-3"
#define BTN_DEBOUNCE_MS 40    // debounce mecânico do botão
#define MIN_INTER_MS 300      // intervalo mínimo entre validações aceitas
#define LONGPRESS_MS 1000     // segurar para reinjetar (simular reentrega)
#define LINK_DEBOUNCE_MS 700  // chave precisa ficar estável antes de mudar de estado
#define LINK_ESTAVEL_MS 2000  // tempo online estável antes de marcar "confiável" (histerese)
#define HB_INTERVAL_MS 4000   // período do heartbeat
#define REC_INTERVAL_MS 5000  // com que frequência a névoa "envia" recomendação
#define REC_STALE_MS 9000     // recomendação é considerada velha após isso
#define DEGRADO_APOS_MS 12000 // ~3 ciclos de heartbeat offline -> fila degradada
#define JANELA_MS 120000      // janela deslizante para fila_atual_estimada (igual Atv02)
#define OUTBOX_CAP 16
#define REC_N 16
#define JANELA_N 64
enum LinkState
{
  LINK_ONLINE,
  LINK_OFFLINE,
  LINK_DEGRADADO
};
enum PanelState
{
  PANEL_BOOT,
  PANEL_FRESCO,
  PANEL_SEGURANDO,
  PANEL_SEM_CONFIANCA
};

LinkState linkState = LINK_ONLINE;
PanelState panelAnt = PANEL_BOOT;

uint32_t seqValidacao = 0; // sequência local de ValidacaoRealizada
uint32_t seqControle = 0;  // sequência dos eventos de plano de controle
uint32_t hbSeq = 0;        // heartbeat_seq
uint32_t lastAckedSeq = 0; // maior sequência já confirmada pela névoa (dedup)
uint32_t duplicatasDescartadas = 0;
uint32_t ruidoRejeitado = 0;
uint32_t missedHeartbeats = 0;

// último evento aceito (para a reinjeção manual / teste de duplicação)
uint32_t ultSeq = 0, ultEt = 0;
int ultVal = 0;
char ultModo[8] = "qr";

// botão de validação
bool bpRawAnt = false, bpDeb = false, longFired = false;
uint32_t tBpChange = 0, tBpDown = 0, tUltimaValida = 0;

// chave de enlace
bool rawLinkAnt = true, debLink = true, confiavelEmitida = false;
uint32_t tMudRawLink = 0, tOnlineDesde = 0, tOfflineDesde = 0;

// heartbeat / recomendação da névoa (simulada)
uint32_t tUltimoHB = 0, tUltimaRec = 0, tRecRecebida = 0;
int filaRecomendada = 1;

// bateria (potenciômetro)
int batUltEstavel = 50;
bool batInstavel = false;

// outbox (fila local de reenvio) - arrays paralelos
uint32_t obSeq[OUTBOX_CAP];
uint32_t obEt[OUTBOX_CAP];
int obVal[OUTBOX_CAP];
char obModo[OUTBOX_CAP][8];
int obHead = 0, obCount = 0;
uint32_t perdasOutbox = 0;
bool obAnt = false;

// anel de sequências recentemente confirmadas (idempotência)
uint32_t recSeqs[REC_N];
int recIdx = 0;

// janela deslizante (para fila_atual_estimada, só um proxy local)
uint32_t tsJanela[JANELA_N];
int janelaIdx = 0;

// ---------------------------------------------------------------
// Log / emissão de evento (contrato mínimo da atividade)
// ---------------------------------------------------------------
void logf(const char *fmt, ...)
{
  char b[220];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(b, sizeof b, fmt, ap);
  va_end(ap);
  Serial.printf("-- [t=%lums] %s\n", (unsigned long)millis(), b);
}

// eventType/deviceId/entityId/eventTimeMs/sequence/value/unit/state fixos;
// "extra" carrega campos adicionais específicos de cada evento.
void emitEvento(const char *type, uint32_t seq, long value, const char *unit,
                const char *state, const char *extra)
{
  char buf[420];
  snprintf(buf, sizeof buf,
           "{\"eventType\":\"%s\",\"deviceId\":\"%s\",\"entityId\":\"%s\","
           "\"eventTimeMs\":%lu,\"sequence\":%lu,\"value\":%ld,\"unit\":\"%s\",\"state\":\"%s\"%s}",
           type, DEVICE_ID, ENTITY_ID,
           (unsigned long)millis(), (unsigned long)seq, value, unit, state,
           extra ? extra : "");
  Serial.println(buf);
}

const char *nomeLink()
{
  return linkState == LINK_ONLINE    ? "ONLINE"
         : linkState == LINK_OFFLINE ? "OFFLINE"
                                     : "DEGRADADO";
}

bool seqVista(uint32_t s)
{
  if (s == 0)
    return false;
  for (int i = 0; i < REC_N; i++)
    if (recSeqs[i] == s)
      return true;
  return false;
}
void recordSeq(uint32_t s)
{
  recSeqs[recIdx] = s;
  recIdx = (recIdx + 1) % REC_N;
}

void janelaRegistra(uint32_t t)
{
  tsJanela[janelaIdx] = t;
  janelaIdx = (janelaIdx + 1) % JANELA_N;
}
int janelaConta()
{
  uint32_t now = millis();
  int n = 0;
  for (int i = 0; i < JANELA_N; i++)
    if (tsJanela[i] != 0 && (now - tsJanela[i]) <= (uint32_t)JANELA_MS)
      n++;
  return n;
}

const char *extraValidacao(uint32_t seq, const char *modo)
{
  static char x[140];
  snprintf(x, sizeof x,
           ",\"resultado\":\"validado\",\"modo\":\"%s\",\"linkState\":\"%s\",\"outboxDepth\":%d,\"seqLocal\":%lu",
           modo, nomeLink(), obCount, (unsigned long)seq);
  return x;
}

void outboxEnfileira(uint32_t seq, uint32_t et, int val, const char *modo)
{
  if (obCount == OUTBOX_CAP)
  {
    // outbox cheia: descarta o mais antigo, mas TORNA A PERDA VISÍVEL
    // (nunca descarta silenciosamente)
    obHead = (obHead + 1) % OUTBOX_CAP;
    obCount--;
    perdasOutbox++;
    logf("outbox CHEIA (%d): evento mais antigo DESCARTADO -> PERDA #%lu",
         OUTBOX_CAP, (unsigned long)perdasOutbox);
  }
  int i = (obHead + obCount) % OUTBOX_CAP;
  obSeq[i] = seq;
  obEt[i] = et;
  obVal[i] = val;
  strncpy(obModo[i], modo, 7);
  obModo[i][7] = 0;
  obCount++;
}

void processarSaida(uint32_t seq, uint32_t et, int val, const char *modo, bool reenvio)
{
  (void)et;
  if (linkState == LINK_ONLINE)
  {
    if (seq != 0 && (seq <= lastAckedSeq || seqVista(seq)))
    {
      duplicatasDescartadas++;
      emitEvento("validacao.realizada", seq, val, "bool", "DUPLICATA_DESCARTADA", extraValidacao(seq, modo));
      logf("dedup: seq=%lu ja confirmada (lastAcked=%lu) -> DESCARTADA (idempotencia p/ reentrega QoS>=1)",
           (unsigned long)seq, (unsigned long)lastAckedSeq);
    }
    else
    {
      if (seq > lastAckedSeq)
        lastAckedSeq = seq;
      recordSeq(seq);
      emitEvento("validacao.realizada", seq, val, "bool", reenvio ? "REENVIADO" : "ENVIADO", extraValidacao(seq, modo));
    }
  }
  else
  {
    outboxEnfileira(seq, et, val, modo);
    emitEvento("validacao.realizada", seq, val, "bool", "ENFILEIRADO", extraValidacao(seq, modo));
    logf("enlace %s: evento seq=%lu enfileirado (outbox=%d/%d)",
         nomeLink(), (unsigned long)seq, obCount, OUTBOX_CAP);
  }
}

// Aceita uma validação genuína (após debounce + filtro de ruído do botão)
void registrarValidacao()
{
  seqValidacao++;
  uint32_t et = millis();
  const char *modo = (seqValidacao % 2) ? "qr" : "facial";
  ultSeq = seqValidacao;
  ultEt = et;
  ultVal = 1;
  strncpy(ultModo, modo, 7);
  ultModo[7] = 0;
  janelaRegistra(et);
  logf("validacao ACEITA: seq=%lu modo=%s (%d na janela de %ds)",
       (unsigned long)seqValidacao, modo, janelaConta(), JANELA_MS / 1000);
  processarSaida(seqValidacao, et, 1, modo, false);
}

// Pressão longa no botão: reinjeta manualmente o último evento aceito,
// simulando uma reentrega de rede (ex.: MQTT QoS>=1) para demonstrar
// que a duplicação é detectada e descartada, e não contada duas vezes.
void reinjetarUltimo()
{
  if (seqValidacao == 0)
  {
    logf("reinjecao ignorada: nenhuma validacao produzida ainda");
    return;
  }
  logf("REINJECAO manual (simula reentrega de rede/QoS>=1) do evento seq=%lu", (unsigned long)ultSeq);
  emitEvento("enlace.reinjecao", ++seqControle, ultSeq, "seq", "REINJETADO", "");
  processarSaida(ultSeq, ultEt, ultVal, ultModo, true);
}

void reconectarEFlush(uint32_t offms)
{
  logf("reconexao confirmada: iniciando flush de %d evento(s) pendente(s)", obCount);
  int reenv = 0, dup = 0;
  while (obCount > 0)
  {
    int i = obHead;
    obHead = (obHead + 1) % OUTBOX_CAP;
    obCount--;
    uint32_t s = obSeq[i];

    digitalWrite(LED_AZUL, HIGH);
    delay(25);
    digitalWrite(LED_AZUL, obCount > 0 ? HIGH : LOW);

    if (s != 0 && (s <= lastAckedSeq || seqVista(s)))
    {
      dup++;
      duplicatasDescartadas++;
      emitEvento("validacao.realizada", s, obVal[i], "bool", "DUPLICATA_DESCARTADA", extraValidacao(s, obModo[i]));
    }
    else
    {
      if (s > lastAckedSeq)
        lastAckedSeq = s;
      recordSeq(s);
      reenv++;
      emitEvento("validacao.realizada", s, obVal[i], "bool", "REENVIADO", extraValidacao(s, obModo[i]));
    }
  }
  digitalWrite(LED_AZUL, LOW);
  obAnt = false;
  logf("flush concluido: %d reenviado(s), %d duplicata(s) descartada(s)", reenv, dup);

  char x[220];
  snprintf(x, sizeof x,
           ",\"reenviados\":%d,\"duplicatas_descartadas\":%d,\"perdas_outbox\":%lu,\"offline_ms\":%lu,"
           "\"ruido_rejeitado\":%lu,\"heartbeats_perdidos\":%lu",
           reenv, dup, (unsigned long)perdasOutbox, (unsigned long)offms,
           (unsigned long)ruidoRejeitado, (unsigned long)missedHeartbeats);
  emitEvento("enlace.recuperado", ++seqControle, reenv, "evt", "RECUPERADO", x);
  missedHeartbeats = 0;
}

void lerBotao()
{
  bool pressed = (digitalRead(BTN_VALIDA) == LOW);
  if (pressed != bpRawAnt)
  {
    bpRawAnt = pressed;
    tBpChange = millis();
  }

  if (millis() - tBpChange >= BTN_DEBOUNCE_MS && bpDeb != pressed)
  {
    bpDeb = pressed;
    if (bpDeb)
    {
      tBpDown = millis();
      longFired = false;
      if (millis() - tUltimaValida >= MIN_INTER_MS)
      {
        tUltimaValida = millis();
        registrarValidacao();
      }
      else
      {
        ruidoRejeitado++;
        logf("RUIDO rejeitado: toque a %lums da ultima validacao (< %dms) -> NAO vira evento (total ruido=%lu)",
             (unsigned long)(millis() - tUltimaValida), MIN_INTER_MS, (unsigned long)ruidoRejeitado);
      }
    }
  }
  if (bpDeb && !longFired && (millis() - tBpDown >= LONGPRESS_MS))
  {
    longFired = true;
    reinjetarUltimo();
  }
}

void lerEnlace()
{
  bool raw = (digitalRead(SW_LINK) == HIGH);
  if (raw != rawLinkAnt)
  {
    rawLinkAnt = raw;
    tMudRawLink = millis();
    // torna a oscilacao VISIVEL no log mesmo quando ela nao chega a virar
    // estado (evidencia positiva do debounce, em vez de so a ausencia de
    // enlace.perdido/recuperado - mais facil de provar no teste adversarial)
    if (raw != debLink)
    {
      logf("enlace: oscilacao detectada na chave (foi p/ %s) -> aguardando %dms estavel antes de mudar de estado",
           raw ? "ONLINE" : "OFFLINE", LINK_DEBOUNCE_MS);
    }
  }

  if (millis() - tMudRawLink >= LINK_DEBOUNCE_MS && debLink != raw)
  {
    debLink = raw;
    if (debLink)
    {
      uint32_t offms = millis() - tOfflineDesde;
      linkState = LINK_ONLINE;
      tOnlineDesde = millis();
      confiavelEmitida = false;
      logf("enlace: estavel em ONLINE ha %dms -> reconectado (ficou offline %lums)",
           LINK_DEBOUNCE_MS, (unsigned long)offms);
      reconectarEFlush(offms);
    }
    else
    {
      linkState = LINK_OFFLINE;
      tOfflineDesde = millis();
      logf("enlace: estavel em OFFLINE -> broker/nevoa inalcancavel; eventos passam a ser enfileirados");
      char ex[100];
      snprintf(ex, sizeof ex, ",\"motivo\":\"chave de enlace\",\"outboxDepth\":%d", obCount);
      emitEvento("enlace.perdido", ++seqControle, (long)obCount, "evt", "OFFLINE", ex);
    }
  }

  if (linkState == LINK_OFFLINE && millis() - tOfflineDesde > (uint32_t)DEGRADO_APOS_MS)
  {
    linkState = LINK_DEGRADADO;
    logf("enlace: offline ha %lums (> %dms, ~3 heartbeats) -> fila DEGRADADA, excluida do argmax da nevoa",
         (unsigned long)(millis() - tOfflineDesde), DEGRADO_APOS_MS);
    char ex[120];
    snprintf(ex, sizeof ex,
             ",\"motivo\":\"sem ACK por ~3 heartbeats\",\"offline_ms\":%lu",
             (unsigned long)(millis() - tOfflineDesde));
    emitEvento("fila.degradada", ++seqControle, (long)missedHeartbeats, "hb", "DEGRADADO", ex);
  }

  // histerese: só volta a considerar a fila "confiável" após um tempo
  // mínimo estável online, para não reagir a uma reconexão passageira
  if (linkState == LINK_ONLINE && !confiavelEmitida && millis() - tOnlineDesde >= (uint32_t)LINK_ESTAVEL_MS)
  {
    confiavelEmitida = true;
    logf("enlace: estavel ONLINE ha %dms -> fila volta a ser CONFIAVEL (histerese)", LINK_ESTAVEL_MS);
    emitEvento("fila.confiavel", ++seqControle, 1, "bool", "OK", "");
  }
}

void tarefaHeartbeat()
{
  if (millis() - tUltimoHB < (uint32_t)HB_INTERVAL_MS)
    return;
  tUltimoHB = millis();
  hbSeq++;

  int bat = lerBateria();
  int fila = janelaConta();

  if (linkState == LINK_ONLINE)
  {
    missedHeartbeats = 0;
    const char *st = (bat < 10) ? "OK_BATERIA_BAIXA" : "OK";
    char x[180];
    snprintf(x, sizeof x,
             ",\"bateria_pct\":%d,\"fila_atual_estimada\":%d,\"missedHeartbeats\":0,"
             "\"bateria_instavel\":%s,\"outboxDepth\":%d",
             bat, fila, batInstavel ? "true" : "false", obCount);
    emitEvento("dispositivo.heartbeat", hbSeq, bat, "%", st, x);
  }
  else
  {
    missedHeartbeats++;
    logf("heartbeat #%lu NAO enviado (enlace %s); perdidos consecutivos=%lu [descartado, nao enfileirado]",
         (unsigned long)hbSeq, nomeLink(), (unsigned long)missedHeartbeats);
  }
}

// Simula a recomendação periódica que a névoa publicaria de volta ao
// painel; só chega enquanto o enlace está ONLINE.
void tarefaRecomendacao()
{
  if (linkState != LINK_ONLINE)
    return;
  if (millis() - tUltimaRec < (uint32_t)REC_INTERVAL_MS)
    return;
  tUltimaRec = millis();
  filaRecomendada = (filaRecomendada % 3) + 1;
  tRecRecebida = millis();
  logf("recomendacao da nevoa recebida: seguir fila #%d (valida por %dms)", filaRecomendada, REC_STALE_MS);
}

int lerBateria()
{
  int a = analogRead(POT_BAT), b = analogRead(POT_BAT), c = analogRead(POT_BAT);
  int mn = min(a, min(b, c));
  int mx = max(a, max(b, c));
  batInstavel = (mx - mn) > 600;
  int med = a + b + c - mn - mx; // mediana de 3
  int pct = (int)map(med, 0, 4095, 0, 100);

  if (pct < 0 || pct > 100)
  { // fora da faixa valida -> clamp defensivo
    logf("BATERIA: valor fora da faixa (%d%%) -> clamp para [0,100]", pct);
    pct = constrain(pct, 0, 100);
  }
  if (batInstavel)
  {
    logf("BATERIA: leitura instavel (spread ADC=%d) -> mantendo ultimo valor estavel=%d%%", mx - mn, batUltEstavel);
    return batUltEstavel;
  }
  batUltEstavel = pct;
  return pct;
}

void beep(unsigned int freq, unsigned long ms)
{
  tone(BUZZER, freq);
  delay(ms);
  noTone(BUZZER);
}

// Recebe os estados como "int" (e não como o enum PanelState) de propósito:
// o gerador automático de protótipos do Arduino insere os protótipos logo
// após os #include/#define do topo do arquivo, ou seja, ANTES da definição
// do enum — usar o enum como tipo de parâmetro quebraria a compilação.
void aplicarPainel(int p, int prev)
{
  digitalWrite(LED_VERDE, p == PANEL_FRESCO ? HIGH : LOW);
  digitalWrite(LED_AMARELO, p == PANEL_SEGURANDO ? HIGH : LOW);
  digitalWrite(LED_VERMELHO, p == PANEL_SEM_CONFIANCA ? HIGH : LOW);

  const char *nome = p == PANEL_FRESCO      ? "FRESCO (verde)"
                     : p == PANEL_SEGURANDO ? "SEGURANDO ULTIMA RECOMENDACAO (amarelo)"
                                            : "SEM DADO CONFIAVEL (vermelho)";
  logf("PAINEL -> %s | fila recomendada exibida=#%d | ultima recomendacao ha %lums",
       nome, filaRecomendada, (unsigned long)(millis() - tRecRecebida));

  if (prev == PANEL_BOOT)
    return; // não soa alarme na inicialização
  if (p == PANEL_SEM_CONFIANCA)
  {
    beep(300, 130);
    delay(30);
    beep(300, 130);
  }
  else if (p == PANEL_SEGURANDO && prev == PANEL_FRESCO)
  {
    beep(1200, 90);
  }
  else if (p == PANEL_FRESCO)
  {
    beep(1800, 80);
    delay(20);
    beep(2400, 80);
  }
}

void atualizarPainel()
{
  PanelState p;
  if (linkState == LINK_DEGRADADO)
  {
    p = PANEL_SEM_CONFIANCA;
  }
  else if (millis() - tRecRecebida > (uint32_t)REC_STALE_MS)
  {
    p = PANEL_SEGURANDO;
  }
  else
  {
    p = PANEL_FRESCO;
  }
  if (p != panelAnt)
  {
    aplicarPainel(p, panelAnt);
    panelAnt = p;
  }
}

void atualizarLedOutbox()
{
  bool now = (obCount > 0);
  if (now != obAnt)
  {
    obAnt = now;
    digitalWrite(LED_AZUL, now ? HIGH : LOW);
    logf("OUTBOX %s (%d evento(s) pendente(s) de reenvio)", now ? "COM PENDENCIAS" : "vazia", obCount);
  }
}

// ---------------------------------------------------------------
void setup()
{
  Serial.begin(115200);
  delay(300);

  pinMode(BTN_VALIDA, INPUT_PULLUP);
  pinMode(SW_LINK, INPUT);
  pinMode(LED_VERDE, OUTPUT);
  pinMode(LED_AMARELO, OUTPUT);
  pinMode(LED_VERMELHO, OUTPUT);
  pinMode(LED_AZUL, OUTPUT);
  pinMode(BUZZER, OUTPUT);
  analogReadResolution(12);

  // "Aquece" o canal LEDC do buzzer aqui, no boot: a primeira chamada a
  // tone()/noTone() na sessao dispara um aviso interno inofensivo do
  // driver do ESP32 ("ledc_get_duty: LEDC is not initialized"), nao
  // importa a variante usada. Disparando esse primeiro uso aqui, o aviso
  // acontece antes de qualquer evento interessante, em vez de aparecer
  // no meio de um teste.
  tone(BUZZER, 1000);
  delay(1);
  noTone(BUZZER);

  bool raw = (digitalRead(SW_LINK) == HIGH);
  rawLinkAnt = raw;
  debLink = raw;
  tMudRawLink = millis();
  linkState = raw ? LINK_ONLINE : LINK_OFFLINE;

  uint32_t t = millis();
  tOnlineDesde = t;
  tOfflineDesde = t;
  tUltimaRec = t;
  tUltimoHB = t;
  // tRecRecebida comeca ja "velha" (nao em t): nenhuma recomendacao real
  // foi recebida ainda, entao o painel nao deve nascer verde/"fresco" so
  // porque acabou de ligar - ele so fica verde quando a primeira
  // recomendacao de fato chegar (tarefaRecomendacao(), com o enlace
  // online). Sem isso, um boot com o enlace ja offline mostraria verde
  // por REC_STALE_MS antes de virar amarelo, o que nao reflete a
  // realidade (achado ao testar de verdade no Wokwi).
  tRecRecebida = t - (uint32_t)REC_STALE_MS - 1;

  Serial.println();
  Serial.println(F("=================================================================="));
  Serial.println(F(" Atividade 03 - Software para Sistemas Ubiquos"));
  Serial.println(F(" Recorte: ponto de validacao (borda) - COMUNICACAO E RESILIENCIA"));
  Serial.println(F(" Matricula 202302612 | adversarial: mudancas rapidas/ruido/acionamentos repetidos"));
  Serial.println(F(" D4  botao  = ValidacaoRealizada (toque) | segure ~1s = reinjeta ultimo evento"));
  Serial.println(F(" D18 chave  = enlace com o broker/nevoa (para 3V3 = ONLINE, para GND = OFFLINE)"));
  Serial.println(F(" D34 potenc.= bateria_pct (grandeza ficticia)"));
  Serial.println(F(" LEDs: verde/amarelo/vermelho = painel | azul = outbox com pendencias"));
  Serial.println(F("=================================================================="));

  logf("boot: %s responsabilidade=Comunicacao e resiliencia", DEVICE_ID);
  emitEvento("dispositivo.online", ++seqControle, 1, "bool", raw ? "ONLINE" : "OFFLINE",
             ",\"fw\":\"atv03-com-resil-v1\",\"nota\":\"eventTimeMs = ms desde o boot (sem RTC/NTP no Wokwi)\"");
}

void loop()
{
  lerBotao();
  lerEnlace();
  tarefaHeartbeat();
  tarefaRecomendacao();
  atualizarPainel();
  atualizarLedOutbox();
  delay(5);
}
