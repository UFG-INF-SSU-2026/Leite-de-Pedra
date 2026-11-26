import type { ReactNode } from 'react'
import { POR_PAGINA } from './dados'

const ROTULOS: Record<string, string> = {
  livre: 'Livre', atencao: 'Atenção', bloqueada: 'Bloqueada',
  aceito: 'Aceito', recusado: 'Recusado', indeterminado: 'Indeterminado',
  disponivel: 'Disponível', usado: 'Usado', cancelado: 'Cancelado',
  cliente: 'Cliente', validador: 'Validador', admin: 'Admin',
}

export function Chip({ valor }: { valor: string | null | undefined }) {
  if (!valor) return <span className="vazio">–</span>
  return <span className={`chip chip-${valor}`}>{ROTULOS[valor] ?? valor}</span>
}

export function Id({ valor }: { valor: string | null | undefined }) {
  return valor ? <code title={valor}>{valor.length > 14 ? valor.slice(0, 12) + '…' : valor}</code> : <span className="vazio">–</span>
}

export function Erro({ mensagem }: { mensagem: string | null }) {
  return mensagem ? <p className="erro" role="alert">{mensagem}</p> : null
}

export function Paginacao({ total, deslocamento, mudar }: { total: number; deslocamento: number; mudar: (n: number) => void }) {
  const fim = Math.min(deslocamento + POR_PAGINA, total)
  return (
    <div className="paginacao">
      <span>{total ? `${deslocamento + 1}–${fim} de ${total}` : 'Nenhum registro'}</span>
      <button type="button" disabled={deslocamento === 0} onClick={() => mudar(Math.max(0, deslocamento - POR_PAGINA))}>Anterior</button>
      <button type="button" disabled={fim >= total} onClick={() => mudar(deslocamento + POR_PAGINA)}>Próxima</button>
    </div>
  )
}

export function Tabela({ cabecalho, children, vazio }: { cabecalho: string[]; children: ReactNode; vazio: boolean }) {
  return (
    <div className="tabela">
      <table>
        <thead><tr>{cabecalho.map(c => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {children}
          {vazio && <tr><td colSpan={cabecalho.length} className="vazio">Nada por aqui.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

export function Filtro({ rotulo, valor, mudar, opcoes }: {
  rotulo: string; valor: string; mudar: (v: string) => void; opcoes: [string, string][]
}) {
  return (
    <label>{rotulo}
      <select value={valor} onChange={e => mudar(e.target.value)}>
        <option value="">Todos</option>
        {opcoes.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
    </label>
  )
}
