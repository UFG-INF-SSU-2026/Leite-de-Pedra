import { router } from 'expo-router'
import { useState } from 'react'
import { cadastrar } from '@/api'
import { CapturaRosto } from '@/CapturaRosto'
import { useSessao } from '@/sessao'
import { Botao, Campo, Erro, Paragrafo, Tela, Titulo } from '@/ui'

const LOGIN_VALIDO = /^[a-z0-9_.-]{3,32}$/
const SENHA_MINIMA = 10

// Duas etapas: os dados da conta e depois a foto do rosto. A conta só é
// criada no fim, quando o backend aceita o rosto.
export default function Cadastro() {
  const { entrar } = useSessao()
  const [etapa, setEtapa] = useState<'dados' | 'rosto'>('dados')
  const [nome, setNome] = useState('')
  const [login, setLogin] = useState('')
  const [senha, setSenha] = useState('')
  const [confirmacao, setConfirmacao] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  function avancar() {
    const loginNormalizado = login.trim().toLowerCase()
    if (!nome.trim()) return setErro('Informe seu nome.')
    if (!LOGIN_VALIDO.test(loginNormalizado)) return setErro('O login precisa ter de 3 a 32 letras minúsculas, números, ponto, hífen ou sublinhado.')
    if (senha.length < SENHA_MINIMA) return setErro(`A senha precisa ter pelo menos ${SENHA_MINIMA} caracteres.`)
    if (senha !== confirmacao) return setErro('As senhas não conferem.')
    setErro(null)
    setLogin(loginNormalizado)
    setEtapa('rosto')
  }

  async function concluir(foto: string) {
    setErro(null)
    setEnviando(true)
    try {
      await cadastrar({ login, senha, nome: nome.trim(), foto })
      await entrar(login, senha)
      router.replace('/ingressos')
    } catch (e) {
      setErro((e as Error).message)
      setEnviando(false)
    }
  }

  if (etapa === 'rosto') {
    return (
      <Tela>
        <Titulo>Seu rosto</Titulo>
        <Paragrafo>É ele que libera a sua entrada: na catraca, o validador confere se o rosto é o do dono do ingresso. A foto vai para o reconhecimento facial e não fica guardada no aparelho.</Paragrafo>
        <Erro mensagem={erro} />
        <CapturaRosto aoConfirmar={concluir} enviando={enviando} />
        <Botao titulo="Voltar aos dados" aoTocar={() => setEtapa('dados')} secundario desativado={enviando} />
      </Tela>
    )
  }

  return (
    <Tela>
      <Titulo>Criar conta</Titulo>
      <Campo rotulo="Nome" value={nome} onChangeText={setNome} autoCapitalize="words" autoComplete="name" textContentType="name" />
      <Campo rotulo="Login" value={login} onChangeText={setLogin} autoComplete="username-new" textContentType="username" />
      <Campo rotulo={`Senha (mínimo de ${SENHA_MINIMA} caracteres)`} value={senha} onChangeText={setSenha} secureTextEntry
        autoComplete="new-password" textContentType="newPassword" />
      <Campo rotulo="Repita a senha" value={confirmacao} onChangeText={setConfirmacao} secureTextEntry
        autoComplete="new-password" textContentType="newPassword" onSubmitEditing={avancar} />
      <Erro mensagem={erro} />
      <Botao titulo="Continuar para a foto" aoTocar={avancar} />
    </Tela>
  )
}
