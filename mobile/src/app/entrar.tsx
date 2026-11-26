import { Link, Redirect, router } from 'expo-router'
import { useState } from 'react'
import { Text } from 'react-native'
import { useSessao } from '@/sessao'
import { Botao, Campo, Erro, Paragrafo, Tela, Titulo, useCores } from '@/ui'

export default function Entrar() {
  const { sessao, entrar } = useSessao()
  const cores = useCores()
  const [login, setLogin] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  if (sessao) return <Redirect href="/" />

  async function enviar() {
    setErro(null)
    setEnviando(true)
    try {
      await entrar(login.trim().toLowerCase(), senha)
      router.replace('/')
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Tela>
      <Text style={{ color: cores.destaque, fontWeight: '700', marginTop: 48 }}>Leite de Pedra</Text>
      <Titulo>Entre para ver seus ingressos</Titulo>
      <Paragrafo>Na entrada do evento, mostre o QR do ingresso e olhe para a câmera do validador.</Paragrafo>
      <Campo rotulo="Login" value={login} onChangeText={setLogin} autoComplete="username" textContentType="username" />
      <Campo rotulo="Senha" value={senha} onChangeText={setSenha} secureTextEntry autoComplete="current-password"
        textContentType="password" onSubmitEditing={enviar} returnKeyType="go" />
      <Erro mensagem={erro} />
      <Botao titulo="Entrar" aoTocar={enviar} carregando={enviando} desativado={!login || !senha} />
      <Link href="/cadastro" style={{ color: cores.destaque, textAlign: 'center', fontSize: 16, padding: 8 }}>
        Ainda não tenho conta
      </Link>
    </Tela>
  )
}
