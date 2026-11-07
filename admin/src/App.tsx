import { useEffect, useState, type FormEvent } from 'react'
import { entrar, quandoPerderSessao, token } from './api'
import { Erro } from './componentes'
import { Ingressos } from './paginas/Ingressos'
import { Auditoria, Estados, Leituras, Movimentos } from './paginas/Registros'
import { Usuarios } from './paginas/Usuarios'
import { VisaoGeral } from './paginas/VisaoGeral'

const ABAS = {
  geral: 'Visão geral',
  usuarios: 'Usuários',
  ingressos: 'Ingressos',
  leituras: 'Leituras',
  movimentos: 'Movimentos',
  estados: 'Estados',
  auditoria: 'Auditoria',
} as const
type Aba = keyof typeof ABAS

function abaDoEndereco(): Aba {
  const nome = location.hash.slice(1)
  return nome in ABAS ? (nome as Aba) : 'geral'
}

// Só para a interface (por exemplo, não oferecer trocar o próprio papel);
// quem decide o acesso é o backend, a cada requisição.
function meuId() {
  try {
    return JSON.parse(atob(token.ler()!.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).sub as string
  } catch {
    return ''
  }
}

function Login({ aoEntrar }: { aoEntrar: () => void }) {
  const [login, setLogin] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  async function enviar(evento: FormEvent) {
    evento.preventDefault()
    setEnviando(true)
    setErro(null)
    try {
      await entrar(login, senha)
      aoEntrar()
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <main className="login">
      <form onSubmit={enviar}>
        <p className="marca">Leite de Pedra</p>
        <h1>Painel de administração</h1>
        <label>Login<input id="login" autoComplete="username" required value={login} onChange={e => setLogin(e.target.value)} /></label>
        <label>Senha<input id="senha" type="password" autoComplete="current-password" required value={senha} onChange={e => setSenha(e.target.value)} /></label>
        <Erro mensagem={erro} />
        <button type="submit" disabled={enviando}>{enviando ? 'Entrando…' : 'Entrar'}</button>
      </form>
    </main>
  )
}

export default function App() {
  const [logado, setLogado] = useState(() => token.ler() !== null)
  const [aba, setAba] = useState<Aba>(abaDoEndereco)

  useEffect(() => quandoPerderSessao(() => setLogado(false)), [])
  useEffect(() => {
    const mudou = () => setAba(abaDoEndereco())
    addEventListener('hashchange', mudou)
    return () => removeEventListener('hashchange', mudou)
  }, [])

  if (!logado) return <Login aoEntrar={() => setLogado(true)} />

  function sair() {
    token.apagar()
    setLogado(false)
  }

  return (
    <div className="app">
      <header className="topo">
        <p className="marca">Leite de Pedra <span>· painel</span></p>
        <nav aria-label="Seções">
          {(Object.keys(ABAS) as Aba[]).map(nome => (
            <a key={nome} href={`#${nome}`} aria-current={aba === nome ? 'page' : undefined}>{ABAS[nome]}</a>
          ))}
        </nav>
        <button type="button" className="sair" onClick={sair}>Sair</button>
      </header>
      <main>
        <h1>{ABAS[aba]}</h1>
        {aba === 'geral' && <VisaoGeral />}
        {aba === 'usuarios' && <Usuarios meuId={meuId()} />}
        {aba === 'ingressos' && <Ingressos />}
        {aba === 'leituras' && <Leituras />}
        {aba === 'movimentos' && <Movimentos />}
        {aba === 'estados' && <Estados />}
        {aba === 'auditoria' && <Auditoria />}
      </main>
    </div>
  )
}
