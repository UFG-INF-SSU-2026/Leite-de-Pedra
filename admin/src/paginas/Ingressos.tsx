import { useState } from 'react'
import { chamar, type Ingresso } from '../api'
import { Chip, Erro, Filtro, Id, Paginacao, Tabela } from '../componentes'
import { dataHora, useLista } from '../dados'

export function Ingressos() {
  const [busca, setBusca] = useState('')
  const [situacao, setSituacao] = useState('')
  const lista = useLista<Ingresso>('/admin/ingressos', { busca, situacao })
  const [cancelando, setCancelando] = useState<string | null>(null)
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)

  async function cancelar(evento: React.FormEvent) {
    evento.preventDefault()
    setErro(null)
    try {
      await chamar(`/admin/ingressos/${cancelando}/cancelar`, { metodo: 'POST', corpo: { motivo } })
      setCancelando(null)
      setMotivo('')
      lista.recarregar()
    } catch (e) {
      setErro((e as Error).message)
    }
  }

  return (
    <>
      <div className="filtros">
        <label>Ingresso<input id="busca-ingressos" type="search" value={busca} onChange={e => setBusca(e.target.value.toUpperCase())} placeholder="código" /></label>
        <Filtro rotulo="Situação" valor={situacao} mudar={setSituacao}
          opcoes={[['disponivel', 'Disponível'], ['usado', 'Usado'], ['cancelado', 'Cancelado']]} />
      </div>
      <Erro mensagem={erro ?? lista.erro} />
      {cancelando && (
        <form className="confirmacao" onSubmit={cancelar}>
          <p>Cancelar o ingresso <code>{cancelando}</code>? Ele deixa de entrar na catraca e isso não se desfaz.</p>
          <label>Motivo<input id="motivo-cancelamento" required minLength={3} maxLength={200} value={motivo} onChange={e => setMotivo(e.target.value)} /></label>
          <div className="acoes">
            <button type="submit" className="perigo">Cancelar ingresso</button>
            <button type="button" onClick={() => setCancelando(null)}>Voltar</button>
          </div>
        </form>
      )}
      <Tabela cabecalho={['Ingresso', 'Dono', 'Situação', 'Emitido', 'Entrada', 'Fila', 'Validador', 'Leitura', '']} vazio={!lista.dados?.itens.length}>
        {lista.dados?.itens.map(i => (
          <tr key={i.ingressoId}>
            <td><code>{i.ingressoId}</code></td><td>{i.dono}</td><td><Chip valor={i.situacao} /></td>
            <td>{dataHora(i.emitidoEm)}</td>
            <td>{i.situacao === 'cancelado' ? `cancelado ${dataHora(i.canceladoEm)}` : dataHora(i.usadoEm)}</td>
            <td>{i.filaEntrada ?? '–'}</td><td><Id valor={i.validadorId} /></td><td><Id valor={i.leituraId} /></td>
            <td>{i.situacao === 'disponivel' && <button type="button" className="perigo" onClick={() => setCancelando(i.ingressoId)}>Cancelar</button>}</td>
          </tr>
        ))}
      </Tabela>
      {lista.dados && <Paginacao total={lista.dados.total} deslocamento={lista.deslocamento} mudar={lista.setDeslocamento} />}
    </>
  )
}
