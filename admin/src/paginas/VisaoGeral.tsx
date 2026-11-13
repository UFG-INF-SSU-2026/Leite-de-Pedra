import { useState } from 'react'
import type { AoVivo, MinutoHistorico, Resumo } from '../api'
import { Chip, Erro, Id, Tabela } from '../componentes'
import { hora, useDados } from '../dados'

function Numero({ rotulo, valor, detalhe }: { rotulo: string; valor: number; detalhe?: string }) {
  return (
    <div className="numero">
      <span className="rotulo">{rotulo}</span>
      <strong>{valor}</strong>
      {detalhe && <span className="detalhe">{detalhe}</span>}
    </div>
  )
}

const LARGURA = 640, ALTURA = 170, MARGEM = { esq: 40, dir: 12, topo: 10, base: 24 }

// Uma linha por fila ao longo dos minutos. SVG puro e cores por classe (a CSP não aceita estilo inline).
function Grafico({ titulo, unidade, dados, valor }: {
  titulo: string; unidade: string; dados: MinutoHistorico[]; valor: (m: MinutoHistorico) => number | null
}) {
  const filas = [...new Set(dados.map(d => d.filaId))].sort()
  const minutos = [...new Set(dados.map(d => d.minuto))].sort((a, b) => Date.parse(a) - Date.parse(b))
  const maximo = Math.max(1, ...dados.map(d => valor(d) ?? 0))
  const largura = LARGURA - MARGEM.esq - MARGEM.dir, altura = ALTURA - MARGEM.topo - MARGEM.base
  const x = (i: number) => MARGEM.esq + (minutos.length < 2 ? largura / 2 : i * largura / (minutos.length - 1))
  const y = (v: number) => MARGEM.topo + altura * (1 - v / maximo)

  // Pontos [x, y, continua a linha?] da fila; minuto sem dado interrompe a linha.
  const pontos = (fila: string) => {
    const porMinuto = new Map(dados.filter(d => d.filaId === fila).map(d => [d.minuto, valor(d)]))
    const lista: [number, number, boolean][] = []
    let anterior = false
    minutos.forEach((m, i) => {
      const v = porMinuto.get(m)
      if (v != null) lista.push([x(i), y(v), anterior])
      anterior = v != null
    })
    return lista
  }

  return (
    <figure className="grafico">
      <figcaption>
        {titulo}
        <span className="legenda">
          {filas.map((f, i) => <span key={f}><i className={`serie-${i % 4}`} />{f}</span>)}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${LARGURA} ${ALTURA}`} role="img" aria-label={`${titulo} por minuto, por fila`}>
        {[0, maximo / 2, maximo].map(v => (
          <g key={v}>
            <line className="grade" x1={MARGEM.esq} x2={LARGURA - MARGEM.dir} y1={y(v)} y2={y(v)} />
            <text className="eixo" x={MARGEM.esq - 6} y={y(v) + 4} textAnchor="end">{Math.round(v)}{unidade}</text>
          </g>
        ))}
        {minutos.length > 0 && <>
          <text className="eixo" x={MARGEM.esq} y={ALTURA - 6}>{hora(minutos[0])}</text>
          <text className="eixo" x={LARGURA - MARGEM.dir} y={ALTURA - 6} textAnchor="end">{hora(minutos[minutos.length - 1])}</text>
        </>}
        {filas.map((f, i) => {
          const lista = pontos(f)
          const d = lista.map(([px, py, segue]) => `${segue ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`).join(' ')
          // Ponto sem vizinho não vira linha: marca com um círculo.
          const soltos = lista.filter(([, , segue], k) => !segue && !lista[k + 1]?.[2])
          return (
            <g key={f} className={`serie-${i % 4}`}>
              <path className="linha" d={d} />
              {soltos.map(([px, py]) => <circle key={px} cx={px} cy={py} r={3} />)}
            </g>
          )
        })}
      </svg>
    </figure>
  )
}

export function VisaoGeral() {
  const resumo = useDados<Resumo>('/admin/resumo', 10000)
  const agora = useDados<AoVivo>('/admin/ao-vivo', 2000)
  const [minutos, setMinutos] = useState('60')
  const historico = useDados<MinutoHistorico[]>(`/admin/historico?minutos=${minutos}`, 30000)
  const r = resumo.dados

  return (
    <>
      <Erro mensagem={resumo.erro ?? agora.erro} />
      {r && (
        <section className="numeros">
          <Numero rotulo="Clientes" valor={r.usuarios.cliente} detalhe={`${r.usuarios.validador} validador(es), ${r.usuarios.admin} admin(s)`} />
          <Numero rotulo="Ingressos emitidos" valor={r.ingressos.emitidos}
            detalhe={`${r.ingressos.disponiveis} disponíveis · ${r.ingressos.usados} usados · ${r.ingressos.cancelados} cancelados`} />
          <Numero rotulo="Leituras aceitas" valor={r.leituras.aceito}
            detalhe={`${r.leituras.recusado} recusadas · ${r.leituras.indeterminado} indeterminadas`} />
          <Numero rotulo="Resultados a publicar" valor={r.saidaPendente}
            detalhe={r.saidaPendente ? 'gravados, sem confirmação do broker' : 'tudo confirmado pelo broker'} />
          <Numero rotulo="Pessoas nas filas" valor={r.filas.reduce((soma, f) => soma + f.ocupacao, 0)}
            detalhe={r.filas.map(f => `${f.filaId}: ${f.ocupacao}`).join(' · ') || 'nenhuma fila ainda'} />
        </section>
      )}

      <h2>Componentes</h2>
      <div className="filtros">
        {agora.dados?.componentes.map(c => (
          <span key={c.source} className={`chip chip-${c.online ? 'aceito' : 'recusado'}`}
            title={`${c.online ? 'online' : 'offline'} desde ${hora(c.atualizadoEm)}`}>
            {c.source} {c.online ? 'online' : 'offline'}
          </span>
        ))}
        {agora.dados && !agora.dados.componentes.length && <p className="vazio">Nenhum status recebido ainda.</p>}
      </div>
      {agora.dados && Object.keys(agora.dados.rejeitadas).length > 0 && (
        <p className="nota">Rejeitadas pelo processador: {Object.entries(agora.dados.rejeitadas)
          .map(([motivo, n]) => `${motivo} ${n}`).join(' · ')}</p>
      )}

      <h2>Filas agora {agora.dados && !agora.dados.brokerConectado && <span className="chip chip-recusado">broker desconectado</span>}</h2>
      <div className="cartoes">
        {agora.dados?.filas.map(f => (
          <article key={f.filaId} className={`cartao borda-${f.estado?.semaforo ?? 'nenhum'}`}>
            <header><h3>{f.filaId}</h3><Chip valor={f.estado?.semaforo} /></header>
            <dl>
              <dt>Ocupação</dt><dd>{f.estado?.ocupacao ?? '–'}</dd>
              <dt>Espera estimada</dt><dd>{f.estado?.tempoEsperaEstimado != null ? `${f.estado.tempoEsperaEstimado} s` : '–'}</dd>
              <dt>Recomendação</dt><dd>{f.estado?.sentidoRecomendado ?? '–'}</dd>
              <dt>ESP32</dt>
              <dd>{f.enlaceAtivo ? <span className="chip chip-aceito">no ar</span> : <span className="chip chip-recusado">
                {f.segundosSemHeartbeat == null ? 'sem heartbeat' : `caído há ${Math.round(f.segundosSemHeartbeat)} s`}</span>}</dd>
              <dt>Última tentativa</dt>
              <dd>{f.ultimaLeitura ? <>{f.ultimaLeitura.ingressoId} · {f.ultimaLeitura.reconhecimento} às {hora(f.ultimaLeitura.recebidoEm)}</> : '–'}</dd>
              <dt>Última leitura</dt>
              <dd>{f.ultimoResultado ? <><Chip valor={f.ultimoResultado.resultado} /> {f.ultimoResultado.motivo} às {hora(f.ultimoResultado.recebidoEm)}</> : '–'}</dd>
              <dt>Reação no Wokwi</dt>
              <dd>{f.ultimaReacao ? <><code>{f.ultimaReacao.acao}</code> às {hora(f.ultimaReacao.recebidoEm)}</> : '–'}</dd>
            </dl>
            {f.recomendacao?.motivo && <p className="motivo">{f.recomendacao.motivo}</p>}
          </article>
        ))}
        {agora.dados && !agora.dados.filas.length && <p className="vazio">Nenhuma mensagem do broker ainda.</p>}
      </div>

      <h2>Últimas mensagens do broker</h2>
      <Tabela cabecalho={['Recebida', 'Origem', 'Fila', 'Tipo', 'Correlação', 'Latência', 'Conteúdo']} vazio={!agora.dados?.mensagens.length}>
        {agora.dados?.mensagens.slice(0, 30).map(m => (
          <tr key={m.eventId}>
            <td>{hora(m.recebidoEm)}</td><td>{m.source}</td><td>{m.filaId ?? '–'}</td><td><code>{m.tipo}</code></td>
            <td><Id valor={m.correlationId} /></td>
            <td className="num">{m.latenciaMs != null ? `${Math.round(m.latenciaMs)} ms` : '–'}</td>
            <td className="json"><code>{JSON.stringify(m.payload)}</code></td>
          </tr>
        ))}
      </Tabela>

      <h2>Histórico por minuto
        <select className="inline" value={minutos} onChange={e => setMinutos(e.target.value)} aria-label="Período">
          <option value="30">30 min</option><option value="60">1 h</option><option value="360">6 h</option><option value="1440">24 h</option>
        </select>
      </h2>
      {!!historico.dados?.length && (
        <div className="graficos">
          <Grafico titulo="Espera média" unidade=" s" dados={historico.dados} valor={h => h.esperaMedia} />
          <Grafico titulo="Entradas por minuto" unidade="" dados={historico.dados} valor={h => h.entradas} />
        </div>
      )}
      <Tabela cabecalho={['Minuto', 'Fila', 'Entradas', 'Saídas', 'Aceitos', 'Recusados', 'Indet.', 'Espera média', 'Espera máx.', 'Ocupação máx.']}
        vazio={!historico.dados?.length}>
        {historico.dados?.map(h => (
          <tr key={h.minuto + h.filaId}>
            <td>{hora(h.minuto)}</td><td>{h.filaId}</td>
            {[h.entradas, h.saidas, h.aceitos, h.recusados, h.indeterminados].map((n, i) => <td key={i} className="num">{n}</td>)}
            <td className="num">{h.esperaMedia ?? '–'}</td><td className="num">{h.esperaMaxima ?? '–'}</td><td className="num">{h.ocupacaoMaxima ?? '–'}</td>
          </tr>
        ))}
      </Tabela>
    </>
  )
}
