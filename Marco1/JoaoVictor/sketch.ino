/**
 * =============================================================================
 *  CATRACA COM VALIDACAO FACIAL PELO CELULAR — PROTOTIPO DE BORDA (ESP32)
 * =============================================================================
 *  Atividade 03 — Software para Sistemas Ubiquos — UFG / INF
 *  Responsabilidade individual assumida: SENSORIAMENTO E QUALIDADE
 *      (leitura, faixa valida, calibracao, filtragem, debounce,
 *       qualidade do sinal e deteccao de falha)
 *
 *  Recorte do projeto do grupo:
 *      A validacao facial e feita pelo APP no celular do usuario, que calcula
 *      um score de qualidade da captura e o envia ao controlador da catraca.
 *      Este prototipo implementa o lado do CONTROLADOR: como ele consome esse
 *      score, decide se libera a passagem, e — principalmente — como ele evita
 *      decidir com base em informacao velha.
 *
 *  -------------------------------------------------------------------------
 *  AVISO DE FIDELIDADE (obrigatorio, secao 4 da atividade):
 *  NAO ha aquisicao nem validacao de grandeza fisica real. NAO ha camera, nao
 *  ha reconhecimento facial e nao ha biometria neste prototipo. O potenciometro
 *  e uma ENTRADA SUBSTITUTA que representa um valor FICTICIO de "score de
 *  qualidade da captura facial" (0-100%), e a chave deslizante representa,
 *  tambem de forma ficticia, o enlace de rede com o aplicativo do celular.
 *  Renomear a entrada no codigo nao a transforma em sensor real.
 *  -------------------------------------------------------------------------
 *
 *  TESTE ADVERSARIAL OBRIGATORIO — final de matricula 4
 *      "Informacao que permanece armazenada depois de perder a validade."
 *
 *  Problema que ele expoe: uma implementacao ingenua guarda o ultimo score numa
 *  variavel global e decide com base nela sempre que alguem encosta na catraca.
 *  Se o app parar de enviar (tela bloqueada, camera coberta, Wi-Fi caindo), essa
 *  variavel continua valendo 92% indefinidamente e a catraca libera o acesso com
 *  base numa medicao que ja nao descreve mais a cena na frente da catraca.
 *
 *  Mecanismo implementado: toda amostra aceita recebe um CARIMBO DE TEMPO. Toda
 *  decisao consulta a IDADE do dado antes de usa-lo. Passado o TTL, o dado e
 *  marcado como expirado, vira estado observavel (LED amarelo + evento JSON) e
 *  o comportamento seguro e NEGAR. A autorizacao concedida tambem tem prazo.
 *
 *  REGRAS DE FIRMWARE
 *   1. ZERO delay() — todo o controle temporal usa millis().
 *   2. A decisao NAO e uma comparacao instantanea: exige persistencia por
 *      janela continua, debounce, histerese, filtragem e dado dentro do prazo.
 *
 *  HARDWARE (Wokwi)
 *   - Push button ......... GPIO 4  INPUT_PULLUP   presenca na catraca
 *   - Potenciometro ....... GPIO 34 ADC1_CH6       score ficticio 0-100 %
 *   - Chave deslizante .... GPIO 5                 enlace com o app do celular
 *   - LED verde ........... GPIO 18                acesso liberado
 *   - LED vermelho ........ GPIO 19                acesso negado
 *   - LED amarelo ......... GPIO 21                dado expirado / falha
 * =============================================================================
 */

// ----------------------------------------------------------------------------
// MAPEAMENTO DE HARDWARE
// ----------------------------------------------------------------------------
const uint8_t PINO_BOTAO       = 4;
const uint8_t PINO_POT         = 34;
const uint8_t PINO_CHAVE       = 5;
const uint8_t PINO_LED_VERDE   = 18;
const uint8_t PINO_LED_VERM    = 19;
const uint8_t PINO_LED_AMARELO = 21;

// ----------------------------------------------------------------------------
// IDENTIDADE (contrato de evento)
// ----------------------------------------------------------------------------
const char* DEVICE_ID = "esp32-catraca-03";
const char* ENTITY_ID = "portao-2-catraca-3";
const char* UNIDADE   = "%";
const char* MODO      = "facial";   // Atividade 02: modo = qr | facial

// ----------------------------------------------------------------------------
// FAIXA VALIDA E CALIBRACAO DA ENTRADA
// ----------------------------------------------------------------------------
const uint16_t ADC_RESOLUCAO_MAX = 4095;   // ADC de 12 bits do ESP32

// Faixa considerada plausivel para um score vindo do app. O app nunca reporta
// zero absoluto nem saturacao total: valores fora disso sao tratados como
// leitura implausivel (falha do enlace ou do sensor), e nao como score baixo.
const uint16_t ADC_MIN_VALIDO = 40;        // ~1 %
const uint16_t ADC_MAX_VALIDO = 4080;      // ~99 %

// ----------------------------------------------------------------------------
// PARAMETROS DA REGRA DE DECISAO
// ----------------------------------------------------------------------------
const uint8_t  LIMIAR_QUALIDADE        = 85;    // % — superado de forma ESTRITA
const uint8_t  HISTERESE_PCT           = 2;     // banda morta na borda do limiar
const uint32_t JANELA_ESTABILIDADE_MS  = 1500;  // persistencia continua exigida

// ----------------------------------------------------------------------------
// PRAZOS DE VALIDADE — nucleo do teste adversarial
// ----------------------------------------------------------------------------
const uint32_t VALIDADE_AMOSTRA_MS     = 800;   // TTL do score recebido do app
const uint32_t VALIDADE_AUTORIZACAO_MS = 3000;  // TTL da liberacao concedida

// ----------------------------------------------------------------------------
// TEMPORIZACAO OPERACIONAL
// ----------------------------------------------------------------------------
const uint32_t INTERVALO_AMOSTRAGEM_MS = 10;    // 100 Hz
const uint32_t DEBOUNCE_MS             = 50;    // botao e chave
const uint32_t DURACAO_FEEDBACK_MS     = 1200;
const uint32_t DURACAO_REJEICAO_MS     = 800;
const uint32_t INTERVALO_TELEMETRIA_MS = 250;
const uint32_t INTERVALO_HEARTBEAT_MS  = 5000;
const uint32_t PISCA_MS                = 150;
const uint8_t  N_AMOSTRAS_MEDIA        = 8;     // filtro de ruido

// ----------------------------------------------------------------------------
// MAQUINA DE ESTADOS
// ----------------------------------------------------------------------------
enum Estado {
  AGUARDANDO,
  ANALISANDO,
  VALIDADO,
  REJEITADO,
  DADO_EXPIRADO
};

// Prototipos explicitos (o gerador automatico do Arduino nao conhece o enum).
void        lerEntradasDigitais(uint32_t agora);
void        amostrarQualidade(uint32_t agora);
void        executarMaquinaEstados(uint32_t agora);
void        verificarAutorizacao(uint32_t agora);
void        atualizarAtuadores(uint32_t agora);
void        emitirTelemetria(uint32_t agora);
void        emitirHeartbeat(uint32_t agora);
void        trocarEstado(Estado novo, uint32_t agora);
void        publicarEvento(const char* eventType, const char* state,
                           uint8_t valor, const char* reason, uint32_t agora);
const char* nomeEstado(Estado e);
bool        dadoFresco(uint32_t agora);
uint32_t    idadeDado(uint32_t agora);

Estado estadoAtual = AGUARDANDO;
uint32_t tsEntradaEstado = 0;

// ----------------------------------------------------------------------------
// SENSORIAMENTO — filtro de media movel circular
// ----------------------------------------------------------------------------
uint16_t bufferAmostras[N_AMOSTRAS_MEDIA];
uint8_t  idxBuffer    = 0;
uint32_t somaAmostras = 0;

uint8_t  scoreQualidade   = 0;      // ultimo score filtrado (PODE ESTAR VELHO)
uint32_t tsAmostraValida  = 0;      // carimbo de frescor do score acima
// Sinalizador explicito de "ja houve ao menos uma amostra aceita". NAO use
// tsAmostraValida == 0 como sentinela: millis() vale 0 durante o setup(), entao
// um carimbo legitimo tirado no boot seria indistinguivel de "nunca amostrei".
bool     amostraJaValida  = false;
bool     leituraInvalida  = false;  // leitura fora da faixa plausivel
bool     falhaJaReportada = false;  // evita repetir o evento de falha
bool     acimaDoLimiar    = false;  // com histerese

// ----------------------------------------------------------------------------
// ENTRADAS DIGITAIS COM DEBOUNCE
// ----------------------------------------------------------------------------
bool     botaoEstavel      = false;   // true = pressionado
bool     botaoUltimaLeitura = false;
uint32_t tsMudancaBotao    = 0;

bool     enlaceEstavel      = true;   // true = app enviando amostras
bool     enlaceUltimaLeitura = true;
uint32_t tsMudancaChave     = 0;

// ----------------------------------------------------------------------------
// CONTROLE DA JANELA E DA AUTORIZACAO
// ----------------------------------------------------------------------------
uint32_t tsInicioJanela    = 0;   // 0 = nenhuma janela continua em andamento
bool     autorizacaoAtiva  = false;
uint32_t tsAutorizacao     = 0;

// ----------------------------------------------------------------------------
// TEMPORIZADORES E CONTADORES
// ----------------------------------------------------------------------------
uint32_t tsUltimaAmostra    = 0;
uint32_t tsUltimaTelemetria = 0;
uint32_t tsUltimoHeartbeat  = 0;
uint32_t tsUltimoBlink      = 0;
bool     estadoBlink        = false;

uint32_t sequencia          = 0;   // numero de sequencia do contrato de evento
uint32_t contadorExpiracoes = 0;
uint32_t contadorQuedas     = 0;

// ============================================================================
// SETUP
// ============================================================================
void setup() {
  Serial.begin(115200);

  pinMode(PINO_BOTAO, INPUT_PULLUP);
  pinMode(PINO_CHAVE, INPUT_PULLUP);
  pinMode(PINO_LED_VERDE, OUTPUT);
  pinMode(PINO_LED_VERM, OUTPUT);
  pinMode(PINO_LED_AMARELO, OUTPUT);
  // GPIO 34 e entrada analogica pura (input-only), nao aceita pinMode.

  digitalWrite(PINO_LED_VERDE, LOW);
  digitalWrite(PINO_LED_VERM, LOW);
  digitalWrite(PINO_LED_AMARELO, LOW);

  analogReadResolution(12);
  analogSetPinAttenuation(PINO_POT, ADC_11db);   // faixa 0 a 3,3 V

  // Sincroniza o debounce com a posicao real das entradas no instante do boot,
  // evitando uma transicao falsa no primeiro ciclo.
  botaoUltimaLeitura  = (digitalRead(PINO_BOTAO) == LOW);
  botaoEstavel        = botaoUltimaLeitura;
  enlaceUltimaLeitura = (digitalRead(PINO_CHAVE) == HIGH);
  enlaceEstavel       = enlaceUltimaLeitura;

  // Pre-carrega o filtro com a leitura atual, evitando um transitorio artificial
  // de subida nos primeiros ciclos apos o boot.
  uint16_t inicial = analogRead(PINO_POT);
  for (uint8_t i = 0; i < N_AMOSTRAS_MEDIA; i++) {
    bufferAmostras[i] = inicial;
    somaAmostras += inicial;
  }

  // Se a leitura de boot for plausivel e o enlace estiver ativo, ela ja conta
  // como a primeira amostra valida e recebe carimbo de frescor. Caso contrario
  // o carimbo fica zerado e o sistema parte de SEM DADO CONFIAVEL — nunca de um
  // score herdado sem procedencia.
  if (inicial >= ADC_MIN_VALIDO && inicial <= ADC_MAX_VALIDO && enlaceEstavel) {
    scoreQualidade  = (uint8_t)((uint32_t)inicial * 100UL / ADC_RESOLUCAO_MAX);
    tsAmostraValida = millis();
    amostraJaValida = true;
  } else {
    scoreQualidade  = 0;
    tsAmostraValida = 0;
    amostraJaValida = false;
  }
  tsEntradaEstado = millis();

  Serial.println();
  Serial.println(F("============================================================"));
  Serial.println(F(" CATRACA — VALIDACAO FACIAL PELO CELULAR (borda ESP32)"));
  Serial.println(F("------------------------------------------------------------"));
  Serial.print  (F(" deviceId ................. ")); Serial.println(DEVICE_ID);
  Serial.print  (F(" entityId ................. ")); Serial.println(ENTITY_ID);
  Serial.println(F(" Responsabilidade ......... Sensoriamento e qualidade"));
  Serial.print  (F(" Limiar de qualidade ...... > ")); Serial.print(LIMIAR_QUALIDADE); Serial.println(F(" %"));
  Serial.print  (F(" Janela continua .......... ")); Serial.print(JANELA_ESTABILIDADE_MS); Serial.println(F(" ms"));
  Serial.print  (F(" TTL da amostra ........... ")); Serial.print(VALIDADE_AMOSTRA_MS); Serial.println(F(" ms"));
  Serial.print  (F(" TTL da autorizacao ....... ")); Serial.print(VALIDADE_AUTORIZACAO_MS); Serial.println(F(" ms"));
  Serial.print  (F(" Faixa valida do ADC ...... ")); Serial.print(ADC_MIN_VALIDO);
  Serial.print  (F(" a ")); Serial.println(ADC_MAX_VALIDO);
  Serial.println(F(" Adversarial (final 4) .... Dado que sobrevive a validade"));
  Serial.println(F(" AVISO: entrada substituta; nao ha camera nem biometria."));
  Serial.println(F("============================================================"));
}

// ============================================================================
// LOOP — 100 % NAO BLOQUEANTE
// ============================================================================
void loop() {
  uint32_t agora = millis();

  lerEntradasDigitais(agora);
  amostrarQualidade(agora);
  executarMaquinaEstados(agora);
  verificarAutorizacao(agora);
  atualizarAtuadores(agora);
  emitirTelemetria(agora);
  emitirHeartbeat(agora);
}

// ============================================================================
// CAMADA DE SENSORIAMENTO
// ============================================================================

/** Debounce nao-bloqueante do botao de presenca e da chave de enlace. */
void lerEntradasDigitais(uint32_t agora) {
  // Botao: INPUT_PULLUP, LOW = pressionado.
  bool bruto = (digitalRead(PINO_BOTAO) == LOW);
  if (bruto != botaoUltimaLeitura) {
    tsMudancaBotao = agora;
    botaoUltimaLeitura = bruto;
  }
  if ((agora - tsMudancaBotao) >= DEBOUNCE_MS) botaoEstavel = bruto;

  // Chave de enlace: HIGH = app enviando amostras, LOW = enlace caido.
  bool chave = (digitalRead(PINO_CHAVE) == HIGH);
  if (chave != enlaceUltimaLeitura) {
    tsMudancaChave = agora;
    enlaceUltimaLeitura = chave;
  }
  if ((agora - tsMudancaChave) >= DEBOUNCE_MS) enlaceEstavel = chave;
}

/**
 * Le o potenciometro a 100 Hz e aplica, nesta ordem:
 *   1. validacao de faixa  — descarta leitura implausivel (deteccao de falha)
 *   2. verificacao de enlace — sem enlace, nenhuma amostra nova e aceita
 *   3. filtragem por media movel — atenua o ruido do ADC
 *   4. carimbo de frescor — registra QUANDO este score passou a valer
 *
 * O passo 4 e o que torna o teste adversarial possivel: o score continua na
 * memoria, mas o firmware sabe de quando ele e.
 */
void amostrarQualidade(uint32_t agora) {
  if ((agora - tsUltimaAmostra) < INTERVALO_AMOSTRAGEM_MS) return;
  tsUltimaAmostra = agora;

  uint16_t bruto = analogRead(PINO_POT);

  // --- 1. faixa valida / deteccao de falha ---------------------------------
  if (bruto < ADC_MIN_VALIDO || bruto > ADC_MAX_VALIDO) {
    leituraInvalida = true;
    if (!falhaJaReportada) {
      falhaJaReportada = true;
      Serial.print(F("[FALHA]  Leitura fora da faixa plausivel: adc="));
      Serial.print(bruto);
      Serial.println(F(" — amostra descartada, score NAO atualizado"));
      publicarEvento("sensor.leitura_invalida", "FALHA_LEITURA",
                     scoreQualidade, "adc_fora_da_faixa", agora);
    }
    return;   // nao atualiza o filtro nem renova o carimbo de validade
  }
  leituraInvalida = false;
  falhaJaReportada = false;

  // --- 2. enlace com o app --------------------------------------------------
  if (!enlaceEstavel) {
    // O app parou de enviar. O ultimo score CONTINUA em memoria — e exatamente
    // essa a informacao que uma implementacao ingenua usaria para decidir.
    // Aqui o carimbo NAO e renovado, entao o dado envelhece ate expirar.
    return;
  }

  // --- 3. filtragem ---------------------------------------------------------
  somaAmostras -= bufferAmostras[idxBuffer];
  bufferAmostras[idxBuffer] = bruto;
  somaAmostras += bruto;
  idxBuffer = (idxBuffer + 1) % N_AMOSTRAS_MEDIA;

  uint16_t filtrado = (uint16_t)(somaAmostras / N_AMOSTRAS_MEDIA);
  scoreQualidade = (uint8_t)((uint32_t)filtrado * 100UL / ADC_RESOLUCAO_MAX);
  if (scoreQualidade > 100) scoreQualidade = 100;

  // --- 4. carimbo de frescor ------------------------------------------------
  tsAmostraValida = agora;
  amostraJaValida = true;

  // Histerese: entra acima de 85 %, so sai abaixo de 83 %. Protege a sinalizacao
  // contra jitter sem afrouxar a regra de decisao, que continua estrita.
  if (!acimaDoLimiar && scoreQualidade > LIMIAR_QUALIDADE) {
    acimaDoLimiar = true;
  } else if (acimaDoLimiar && scoreQualidade <= (LIMIAR_QUALIDADE - HISTERESE_PCT)) {
    acimaDoLimiar = false;
  }
}

/** Idade do score em memoria. Sem nenhuma amostra aceita ainda, retorna o maximo. */
uint32_t idadeDado(uint32_t agora) {
  if (!amostraJaValida) return 0xFFFFFFFFUL;
  return agora - tsAmostraValida;
}

/** O score em memoria ainda esta dentro do prazo de validade? */
bool dadoFresco(uint32_t agora) {
  return idadeDado(agora) <= VALIDADE_AMOSTRA_MS;
}

// ============================================================================
// MAQUINA DE ESTADOS
// ============================================================================
void executarMaquinaEstados(uint32_t agora) {
  bool fresco = dadoFresco(agora);
  bool qualidadeOk = (scoreQualidade > LIMIAR_QUALIDADE);   // comparacao ESTRITA

  switch (estadoAtual) {

    // ------------------------------------------------------------------
    case AGUARDANDO:
      // Dado vencido enquanto ninguem tenta passar: sinaliza, mas nao rejeita.
      if (!fresco || leituraInvalida) {
        contadorExpiracoes++;
        Serial.print(F("[EXPIRA] Score de "));
        Serial.print(scoreQualidade);
        Serial.print(F("% perdeu a validade (idade "));
        Serial.print(idadeDado(agora));
        Serial.print(F(" ms > "));
        Serial.print(VALIDADE_AMOSTRA_MS);
        Serial.println(F(" ms) — dado marcado como NAO CONFIAVEL"));
        trocarEstado(DADO_EXPIRADO, agora);
        publicarEvento("sensor.dado_expirado", "DADO_EXPIRADO", scoreQualidade,
                       (!amostraJaValida) ? "sem_amostra_valida"
                                          : "ttl_amostra_excedido", agora);
        break;
      }
      if (botaoEstavel) {
        trocarEstado(ANALISANDO, agora);
        tsInicioJanela = 0;
      }
      break;

    // ------------------------------------------------------------------
    case ANALISANDO: {
      // --- TESTE ADVERSARIAL: o dado venceu no meio da analise -------------
      // Uma implementacao ingenua continuaria contando com o score antigo.
      if (!fresco || leituraInvalida) {
        uint32_t descartado = (tsInicioJanela == 0) ? 0 : (agora - tsInicioJanela);
        contadorExpiracoes++;
        tsInicioJanela = 0;
        Serial.print(F("[EXPIRA] Dado venceu durante a analise (idade "));
        Serial.print(idadeDado(agora));
        Serial.print(F(" ms) — janela ZERADA, descartados "));
        Serial.print(descartado);
        Serial.println(F(" ms. Decisao segura: NEGAR."));
        trocarEstado(DADO_EXPIRADO, agora);
        publicarEvento("ValidacaoRealizada", "DADO_EXPIRADO",
                       scoreQualidade, "dado_expirado", agora);
        break;
      }

      // --- presenca do usuario ---------------------------------------------
      if (!botaoEstavel) {
        uint32_t descartado = (tsInicioJanela == 0) ? 0 : (agora - tsInicioJanela);
        contadorQuedas++;
        tsInicioJanela = 0;
        Serial.print(F("[QUEDA]  Presenca perdida — janela ZERADA, descartados "));
        Serial.print(descartado);
        Serial.println(F(" ms"));
        trocarEstado(REJEITADO, agora);
        publicarEvento("ValidacaoRealizada", "REJEITADO",
                       scoreQualidade, "perda_de_presenca", agora);
        break;
      }

      // --- qualidade do sinal ----------------------------------------------
      if (!qualidadeOk) {
        if (tsInicioJanela != 0) {
          uint32_t descartado = agora - tsInicioJanela;
          contadorQuedas++;
          tsInicioJanela = 0;
          Serial.print(F("[QUEDA]  Score caiu para "));
          Serial.print(scoreQualidade);
          Serial.print(F("% — janela ZERADA, descartados "));
          Serial.print(descartado);
          Serial.println(F(" ms (intervalos picotados nao sao somados)"));
          trocarEstado(REJEITADO, agora);
          publicarEvento("ValidacaoRealizada", "REJEITADO",
                         scoreQualidade, "qualidade_insuficiente", agora);
        }
        break;
      }

      // --- persistencia por janela continua ---------------------------------
      if (tsInicioJanela == 0) {
        tsInicioJanela = agora;
        Serial.print(F("[JANELA] Score "));
        Serial.print(scoreQualidade);
        Serial.print(F("% acima do limiar — contando "));
        Serial.print(JANELA_ESTABILIDADE_MS);
        Serial.println(F(" ms continuos"));
      }
      if ((agora - tsInicioJanela) >= JANELA_ESTABILIDADE_MS) {
        autorizacaoAtiva = true;
        tsAutorizacao = agora;
        trocarEstado(VALIDADO, agora);
        publicarEvento("ValidacaoRealizada", "VALIDADO",
                       scoreQualidade, "janela_continua_atingida", agora);
      }
      break;
    }

    // ------------------------------------------------------------------
    case VALIDADO:
      if ((agora - tsEntradaEstado) >= DURACAO_FEEDBACK_MS) {
        trocarEstado(AGUARDANDO, agora);
        tsInicioJanela = 0;
      }
      break;

    // ------------------------------------------------------------------
    case REJEITADO:
      if ((agora - tsEntradaEstado) >= DURACAO_REJEICAO_MS) {
        trocarEstado(AGUARDANDO, agora);
        tsInicioJanela = 0;
      }
      break;

    // ------------------------------------------------------------------
    case DADO_EXPIRADO:
      // Sai daqui somente quando voltar a existir dado fresco e valido:
      // o sistema nao "se recupera sozinho" apenas pela passagem do tempo.
      if (fresco && !leituraInvalida) {
        Serial.print(F("[REARME] Dado fresco novamente (score "));
        Serial.print(scoreQualidade);
        Serial.println(F("%) — sensoriamento reabilitado"));
        trocarEstado(AGUARDANDO, agora);
        tsInicioJanela = 0;
      }
      break;
  }
}

/**
 * A autorizacao concedida tambem e informacao com prazo. Sem isto, uma
 * validacao feita ha dez minutos ainda abriria a catraca.
 */
void verificarAutorizacao(uint32_t agora) {
  if (!autorizacaoAtiva) return;
  if ((agora - tsAutorizacao) < VALIDADE_AUTORIZACAO_MS) return;

  autorizacaoAtiva = false;
  Serial.print(F("[EXPIRA] Autorizacao concedida ha "));
  Serial.print(agora - tsAutorizacao);
  Serial.println(F(" ms perdeu a validade — nova validacao completa e exigida"));
  publicarEvento("credencial.expirada", "EXPIRADO",
                 scoreQualidade, "ttl_autorizacao_excedido", agora);
}

void trocarEstado(Estado novo, uint32_t agora) {
  if (novo == estadoAtual) return;
  Serial.print(F("[ESTADO] "));
  Serial.print(nomeEstado(estadoAtual));
  Serial.print(F(" -> "));
  Serial.println(nomeEstado(novo));
  estadoAtual = novo;
  tsEntradaEstado = agora;
}

const char* nomeEstado(Estado e) {
  switch (e) {
    case AGUARDANDO:    return "AGUARDANDO";
    case ANALISANDO:    return "ANALISANDO";
    case VALIDADO:      return "VALIDADO";
    case REJEITADO:     return "REJEITADO";
    case DADO_EXPIRADO: return "DADO_EXPIRADO";
  }
  return "DESCONHECIDO";
}

// ============================================================================
// ATUACAO — sem delay, apenas comparacao de millis()
// ============================================================================
void atualizarAtuadores(uint32_t agora) {
  bool verde = false, vermelho = false, amarelo = false;

  switch (estadoAtual) {
    case AGUARDANDO:
      break;

    case ANALISANDO:
      if (tsInicioJanela != 0) {
        if ((agora - tsUltimoBlink) >= PISCA_MS) {
          tsUltimoBlink = agora;
          estadoBlink = !estadoBlink;
        }
        verde = estadoBlink;
      } else {
        vermelho = true;      // presente, porem qualidade insuficiente
      }
      break;

    case VALIDADO:
      verde = true;
      break;

    case REJEITADO:
      vermelho = true;
      break;

    case DADO_EXPIRADO:
      // Amarelo piscando: o sistema nao sabe o estado atual da cena.
      if ((agora - tsUltimoBlink) >= PISCA_MS) {
        tsUltimoBlink = agora;
        estadoBlink = !estadoBlink;
      }
      amarelo = estadoBlink;
      break;
  }

  digitalWrite(PINO_LED_VERDE,   verde    ? HIGH : LOW);
  digitalWrite(PINO_LED_VERM,    vermelho ? HIGH : LOW);
  digitalWrite(PINO_LED_AMARELO, amarelo  ? HIGH : LOW);
}

// ============================================================================
// CONTRATO DE EVENTO
// ============================================================================

/**
 * Emite no monitor serial um evento JSON com o contrato minimo exigido pela
 * atividade (eventType, deviceId, entityId, eventTimeMs, sequence, value,
 * unit, state) acrescido dos campos de diagnostico do perfil de sensoriamento.
 *
 * RASTREABILIDADE COM A ATIVIDADE 02 (contrato do grupo):
 *   ValidacaoRealizada   -> mesmo nome de evento; `modo` e `sequence` mapeiam
 *                           os campos `modo` e `seq`; `entityId` mapeia `fila_id`;
 *                           `state` mapeia `resultado`.
 *   DispositivoHeartbeat -> mesmo nome de evento, mesma finalidade (tornar
 *                           visivel que o dispositivo ficou silencioso).
 *   sensor.dado_expirado, sensor.leitura_invalida e credencial.expirada sao
 *   eventos NOVOS, introduzidos por este prototipo para o perfil de
 *   sensoriamento e qualidade.
 *
 * LIMITACAO DOCUMENTADA: nao ha relogio de parede sincronizado no prototipo.
 * eventTimeMs e o tempo decorrido desde o boot (millis()), e sofre overflow
 * apos aproximadamente 49 dias de operacao continua.
 */
void publicarEvento(const char* eventType, const char* state,
                    uint8_t valor, const char* reason, uint32_t agora) {
  sequencia++;

  char payload[480];
  snprintf(payload, sizeof(payload),
    "{\"eventType\":\"%s\",\"deviceId\":\"%s\",\"entityId\":\"%s\","
    "\"eventTimeMs\":%lu,\"sequence\":%lu,\"value\":%u,\"unit\":\"%s\","
    "\"state\":\"%s\",\"modo\":\"%s\",\"reason\":\"%s\",\"dataAgeMs\":%lu,"
    "\"dataValid\":%s,\"linkUp\":%s,\"windowMs\":%lu,"
    "\"expirations\":%lu,\"dropouts\":%lu}",
    eventType, DEVICE_ID, ENTITY_ID,
    (unsigned long)agora,
    (unsigned long)sequencia,
    (unsigned int)valor,
    UNIDADE,
    state, MODO, reason,
    (unsigned long)(idadeDado(agora) == 0xFFFFFFFFUL ? 0UL : idadeDado(agora)),
    dadoFresco(agora) ? "true" : "false",
    enlaceEstavel ? "true" : "false",
    (unsigned long)(tsInicioJanela == 0 ? 0UL : agora - tsInicioJanela),
    (unsigned long)contadorExpiracoes,
    (unsigned long)contadorQuedas
  );

  Serial.println(payload);
}

/** Heartbeat: torna visivel que o dispositivo esta vivo e qual o estado dele. */
void emitirHeartbeat(uint32_t agora) {
  if ((agora - tsUltimoHeartbeat) < INTERVALO_HEARTBEAT_MS) return;
  tsUltimoHeartbeat = agora;
  publicarEvento("DispositivoHeartbeat", nomeEstado(estadoAtual),
                 scoreQualidade, "periodico", agora);
}

/** Telemetria de diagnostico — mostra o score E a idade dele lado a lado. */
void emitirTelemetria(uint32_t agora) {
  if ((agora - tsUltimaTelemetria) < INTERVALO_TELEMETRIA_MS) return;
  tsUltimaTelemetria = agora;

  uint32_t idade = idadeDado(agora);

  Serial.print(F("[SINAL]  estado="));
  Serial.print(nomeEstado(estadoAtual));
  Serial.print(F(" score="));
  Serial.print(scoreQualidade);
  Serial.print(F("% idade="));
  if (idade == 0xFFFFFFFFUL) Serial.print(F("sem_amostra"));
  else                     { Serial.print(idade); Serial.print(F("ms")); }
  Serial.print(F(" valido="));
  Serial.print(dadoFresco(agora) ? F("SIM") : F("NAO"));
  Serial.print(F(" enlace="));
  Serial.print(enlaceEstavel ? F("ATIVO") : F("CAIDO"));
  Serial.print(F(" botao="));
  Serial.print(botaoEstavel ? F("PRESSIONADO") : F("SOLTO"));
  Serial.print(F(" janela="));
  Serial.print(tsInicioJanela == 0 ? 0UL : (unsigned long)(agora - tsInicioJanela));
  Serial.print(F("/"));
  Serial.print(JANELA_ESTABILIDADE_MS);
  Serial.print(F("ms autoriz="));
  Serial.println(autorizacaoAtiva ? F("ATIVA") : F("-"));
}
