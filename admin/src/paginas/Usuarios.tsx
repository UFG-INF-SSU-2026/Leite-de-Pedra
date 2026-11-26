import { useState } from 'react'
import { chamar, type Papel, type Usuario } from '../api'
import { Chip, Erro, Filtro, Id, Paginacao, Tabela } from '../componentes'
import { dataHora, useLista } from '../dados'

const PAPEIS: [Papel, string][] = [['cliente', 'Cliente'], ['validador', 'Validador'], ['admin', 'Admin']]

export function Usuarios({ meuId }: { meuId: string }) {
  const [busca, setBusca] = useState('')
  const [papel, setPapel] = useState('')
  const lista = useLista<Usuario>('/admin/usuarios', { busca, papel })
  const [erro, setErro] = useState<string | null>(null)

  async function mudarPapel(usuario: Usuario, novo: Papel) {
    if (novo === usuario.papel) return
    setErro(null)
    try {
      await chamar(`/admin/usuarios/${usuario.usuarioId}/papel`, { metodo: 'PUT', corpo: { papel: novo } })
      lista.recarregar()
    } catch (e) {
      setErro((e as Error).message)
    }
  }

  return (
    <>
      <div className="filtros">
        <label>Busca<input id="busca-usuarios" type="search" value={busca} onChange={e => setBusca(e.target.value)} placeholder="login, nome ou id" /></label>
        <Filtro rotulo="Papel" valor={papel} mudar={setPapel} opcoes={PAPEIS} />
      </div>
      <Erro mensagem={erro ?? lista.erro} />
      <p className="nota">A troca de papel vale na hora para o painel e na próxima entrada no app. Cada troca fica na auditoria.</p>
      <Tabela cabecalho={['Nome', 'Login', 'Papel', 'Cadastrado', 'Usuário', 'Rosto (FaceId)', 'Mudar papel']} vazio={!lista.dados?.itens.length}>
        {lista.dados?.itens.map(u => (
          <tr key={u.usuarioId}>
            <td>{u.nome}</td><td>{u.login}</td><td><Chip valor={u.papel} /></td><td>{dataHora(u.criadoEm)}</td>
            <td><Id valor={u.usuarioId} /></td><td><Id valor={u.faceId} /></td>
            <td>
              {u.usuarioId === meuId ? <span className="vazio">você</span> : (
                <select value={u.papel} onChange={e => mudarPapel(u, e.target.value as Papel)} aria-label={`Papel de ${u.login}`}>
                  {PAPEIS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select>
              )}
            </td>
          </tr>
        ))}
      </Tabela>
      {lista.dados && <Paginacao total={lista.dados.total} deslocamento={lista.deslocamento} mudar={lista.setDeslocamento} />}
    </>
  )
}
