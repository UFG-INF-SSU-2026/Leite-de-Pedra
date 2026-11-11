import { useState } from 'react'
import { chamar, type EstadoRegistrado, type Leitura, type Movimento, type RegistroAuditoria } from '../api'
import { Chip, Erro, Filtro, Id, Paginacao, Tabela } from '../componentes'
import { dataHora, useLista } from '../dados'

const MOTIVOS: Record<string, string> = {
  'validador-nao-autorizado': 'quem leu não é validador',
  'rosto-nao-confere': 'o rosto não é do dono do ingresso',
  'ingresso-inexistente': 'ingresso inexistente',
  'ingresso-cancelado': 'ingresso cancelado',
  'ingresso-ja-usado': 'ingresso já usado',
  'falha-reconhecimento': 'falha no reconhecimento',
}

function Foto({ eventId }: { eventId: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  async function abrir() {
    try {
      const dados = await chamar<{ url: string }>(`/admin/leituras/${eventId}/foto`, { metodo: 'POST' })
      setUrl(dados.url)
    } catch (e) {
      setErro((e as Error).message)
    }
  }
  if (url) return <a href={url} target="_blank" rel="noreferrer"><img className="foto" src={url} alt="Rosto capturado na leitura" /></a>
  if (erro) return <span className="vazio">{erro}</span>
  return <button type="button" onClick={abrir} title="Abre um link de 5 minutos e registra na auditoria">Ver foto</button>
}

export function Leituras() {
  const [resultado, setResultado] = useState('')
  const [fila, setFila] = useState('')
  const [ingresso, setIngresso] = useState('')
  const lista = useLista<Leitura>('/admin/leituras', { resultado, fila, ingresso })
  return (
    <>
      <div className="filtros">
        <Filtro rotulo="Resultado" valor={resultado} mudar={setResultado}
          opcoes={[['aceito', 'Aceito'], ['recusado', 'Recusado'], ['indeterminado', 'Indeterminado']]} />
        <label>Fila<input id="fila-leituras" value={fila} onChange={e => setFila(e.target.value)} placeholder="fila-a" /></label>
        <label>Ingresso<input id="ingresso-leituras" value={ingresso} onChange={e => setIngresso(e.target.value.toUpperCase())} /></label>
      </div>
      <Erro mensagem={lista.erro} />
      <p className="nota">Filtre por Aceito para ver quem passou. Fotos de entradas aceitas são apagadas na hora; as demais ficam no bucket por 1 dia. Cada foto aberta fica registrada na auditoria.</p>
      <Tabela cabecalho={['Momento', 'Fila', 'Resultado', 'Dono do ingresso', 'Motivo', 'Ingresso', 'Validador', 'Leitura', 'Foto']} vazio={!lista.dados?.itens.length}>
        {lista.dados?.itens.map(m => (
          <tr key={m.eventId}>
            <td>{dataHora(m.momento)}</td><td>{m.filaId}</td><td><Chip valor={m.resultado} /></td>
            <td>{m.dono ? <>{m.dono.nome} <span className="vazio">@{m.dono.login}</span></> : '–'}</td>
            <td>{m.motivo ? MOTIVOS[m.motivo] ?? m.motivo : '–'}</td><td><Id valor={m.ingressoId} /></td>
            <td>{m.validadorLogin ?? <Id valor={m.validadorId} />}</td><td><Id valor={m.eventId} /></td><td><Foto eventId={m.eventId} /></td>
          </tr>
        ))}
      </Tabela>
      {lista.dados && <Paginacao total={lista.dados.total} deslocamento={lista.deslocamento} mudar={lista.setDeslocamento} />}
    </>
  )
}

export function Movimentos() {
  const [tipo, setTipo] = useState('')
  const [fila, setFila] = useState('')
  const [correlacao, setCorrelacao] = useState('')
  const lista = useLista<Movimento>('/admin/movimentos', { tipo, fila, correlacao })
  return (
    <>
      <div className="filtros">
        <Filtro rotulo="Tipo" valor={tipo} mudar={setTipo}
          opcoes={[['contagem', 'Entrada'], ['saida', 'Saída'], ['leitura', 'Leitura'], ['resultado', 'Resultado']]} />
        <label>Fila<input id="fila-movimentos" value={fila} onChange={e => setFila(e.target.value)} placeholder="fila-a" /></label>
        <label>Correlação<input id="correlacao-movimentos" value={correlacao} onChange={e => setCorrelacao(e.target.value.trim())} /></label>
      </div>
      <Erro mensagem={lista.erro} />
      <Tabela cabecalho={['Momento', 'Recebido', 'Origem', 'Fila', 'Tipo', 'Evento', 'Correlação', 'Resultado', 'Ingresso']} vazio={!lista.dados?.itens.length}>
        {lista.dados?.itens.map(m => (
          <tr key={m.eventId + m.tipo + m.momento}>
            <td>{dataHora(m.momento)}</td><td>{dataHora(m.recebidoEm)}</td><td>{m.origem ?? '–'}</td><td>{m.filaId}</td>
            <td><code>{m.tipo}</code></td><td><Id valor={m.eventId} /></td>
            <td>{m.correlationId ? <button type="button" className="link" onClick={() => setCorrelacao(m.correlationId!)}
              title="Mostrar só esta operação"><Id valor={m.correlationId} /></button> : '–'}</td>
            <td><Chip valor={m.resultado} /></td><td><Id valor={m.ingressoId} /></td>
          </tr>
        ))}
      </Tabela>
      {lista.dados && <Paginacao total={lista.dados.total} deslocamento={lista.deslocamento} mudar={lista.setDeslocamento} />}
    </>
  )
}

export function Estados() {
  const [fila, setFila] = useState('')
  const lista = useLista<EstadoRegistrado>('/admin/estados', { fila })
  return (
    <>
      <div className="filtros">
        <label>Fila<input id="fila-estados" value={fila} onChange={e => setFila(e.target.value)} placeholder="fila-a" /></label>
      </div>
      <Erro mensagem={lista.erro} />
      <Tabela cabecalho={['Momento', 'Fila', 'Semáforo', 'Ocupação', 'Espera estimada']} vazio={!lista.dados?.itens.length}>
        {lista.dados?.itens.map(e => (
          <tr key={e.momento + e.filaId}>
            <td>{dataHora(e.momento)}</td><td>{e.filaId}</td><td><Chip valor={e.semaforo} /></td>
            <td className="num">{e.ocupacao}</td><td className="num">{e.esperaSegundos != null ? `${e.esperaSegundos} s` : '–'}</td>
          </tr>
        ))}
      </Tabela>
      {lista.dados && <Paginacao total={lista.dados.total} deslocamento={lista.deslocamento} mudar={lista.setDeslocamento} />}
    </>
  )
}

const ACOES: Record<string, string> = {
  'mudar-papel': 'Mudou papel', 'cancelar-ingresso': 'Cancelou ingresso', 'ver-foto': 'Abriu foto',
}

export function Auditoria() {
  const lista = useLista<RegistroAuditoria>('/admin/auditoria', {})
  return (
    <>
      <Erro mensagem={lista.erro} />
      <Tabela cabecalho={['Momento', 'Admin', 'Ação', 'Alvo', 'Detalhe']} vazio={!lista.dados?.itens.length}>
        {lista.dados?.itens.map((a, i) => (
          <tr key={i}>
            <td>{dataHora(a.momento)}</td><td>{a.admin}</td><td>{ACOES[a.acao] ?? a.acao}</td>
            <td><Id valor={a.alvo} /></td><td>{a.detalhe ?? '–'}</td>
          </tr>
        ))}
      </Tabela>
      {lista.dados && <Paginacao total={lista.dados.total} deslocamento={lista.deslocamento} mudar={lista.setDeslocamento} />}
    </>
  )
}
