import { CameraView, useCameraPermissions } from 'expo-camera'
import { Redirect, router, Stack } from 'expo-router'
import * as SecureStore from 'expo-secure-store'
import { useEffect, useRef, useState } from 'react'
import { Image, Pressable, StyleSheet, Text, View } from 'react-native'
import { CapturaRosto, PedirCamera } from '@/CapturaRosto'
import { useSessao } from '@/sessao'
import { Botao, Campo, Erro, Paragrafo, Tela, Titulo, useCores } from '@/ui'

// Leitura na catraca, só para validadores: o QR do ingresso, o rosto de quem
// está entrando e a decisão do processador (que confere o papel do validador,
// o rosto contra o dono do ingresso e se ele já foi usado).

const FILAS = ['fila-a', 'fila-b']
const CHAVE_FILA = 'catraca.fila'
const CODIGO_INGRESSO = /^[A-F0-9]{12}$/

type Resultado = {
  resultado: 'aceito' | 'recusado' | 'indeterminado'; motivo: string | null; ingressoId: string
  pessoa?: { nome: string; login: string }  // só quando aceito: o dono do ingresso
}

const MOTIVOS: Record<string, string> = {
  'validador-nao-autorizado': 'Sua conta não está autorizada a validar. Fale com a organização.',
  'rosto-nao-confere': 'O rosto não é o do dono deste ingresso.',
  'ingresso-inexistente': 'Este ingresso não existe.',
  'ingresso-cancelado': 'Este ingresso foi cancelado.',
  'ingresso-ja-usado': 'Este ingresso já foi usado para entrar.',
  'falha-reconhecimento': 'O reconhecimento facial falhou. Confira o documento da pessoa e decida.',
}

export default function Catraca() {
  const { sessao, api, sair } = useSessao()
  const cores = useCores()
  const [fila, setFila] = useState<string | null>(null)
  const [ingresso, setIngresso] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [resultado, setResultado] = useState<Resultado | null>(null)
  const [fotoEnviada, setFotoEnviada] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    SecureStore.getItemAsync(CHAVE_FILA).then(salva => salva && setFila(salva)).catch(() => {})
  }, [])

  if (!sessao) return <Redirect href="/entrar" />
  if (sessao.papel !== 'validador') return <Redirect href="/ingressos" />

  function escolherFila(nova: string) {
    setFila(nova)
    SecureStore.setItemAsync(CHAVE_FILA, nova).catch(() => {})
  }

  function proxima() {
    setIngresso(null)
    setResultado(null)
    setFotoEnviada(null)
    setErro(null)
  }

  async function validar(foto: string) {
    setEnviando(true)
    setErro(null)
    setFotoEnviada(foto)
    try {
      setResultado(await api<Resultado>('/leituras', { metodo: 'POST', corpo: { ingressoId: ingresso, filaId: fila, foto } }))
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  const cabecalho = (
    <Stack.Screen options={{
      headerRight: () => (
        <Pressable accessibilityRole="button" onPress={sair} hitSlop={12}>
          <Text style={{ color: cores.destaque, fontSize: 16 }}>Sair</Text>
        </Pressable>
      ),
    }} />
  )

  if (resultado) return <>{cabecalho}<TelaResultado resultado={resultado} foto={fotoEnviada} aoContinuar={proxima} /></>

  return (
    <Tela>
      {cabecalho}
      <View style={{ gap: 8 }}>
        <Text style={{ color: cores.suave, fontSize: 14 }}>Fila desta catraca</Text>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          {FILAS.map(f => (
            <Pressable key={f} accessibilityRole="radio" accessibilityState={{ selected: fila === f }} onPress={() => escolherFila(f)}
              style={[estilos.opcao, { borderColor: fila === f ? cores.destaque : cores.linha, backgroundColor: fila === f ? cores.destaque : cores.superficie }]}>
              <Text style={{ color: fila === f ? cores.sobreDestaque : cores.texto, fontWeight: '600' }}>{f}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      {!fila ? <Paragrafo>Escolha a fila em que você está para começar.</Paragrafo>
        : !ingresso ? <LerIngresso aoLer={setIngresso} />
        : (
          <>
            <Titulo>Rosto da pessoa</Titulo>
            <Paragrafo>Ingresso {ingresso}. Aponte a câmera para o rosto de quem está entrando.</Paragrafo>
            <Erro mensagem={erro} />
            <CapturaRosto camera="back" aoConfirmar={validar} enviando={enviando} textoConfirmar="Validar entrada" />
            <Botao titulo="Ler outro ingresso" aoTocar={proxima} secundario desativado={enviando} />
          </>
        )}

      <Botao titulo="Meus ingressos" aoTocar={() => router.replace('/ingressos')} secundario />
    </Tela>
  )
}

function LerIngresso({ aoLer }: { aoLer: (codigo: string) => void }) {
  const cores = useCores()
  const [permissao, pedirPermissao] = useCameraPermissions()
  const [digitado, setDigitado] = useState('')
  const [aviso, setAviso] = useState<string | null>(null)
  const lido = useRef(false) // a câmera dispara várias leituras do mesmo QR

  function receber(codigo: string) {
    const normalizado = codigo.trim().toUpperCase()
    if (!CODIGO_INGRESSO.test(normalizado)) {
      setAviso('Este QR não é de um ingresso do Leite de Pedra.')
      return
    }
    if (lido.current) return
    lido.current = true
    aoLer(normalizado)
  }

  return (
    <View style={{ gap: 12 }}>
      <Titulo>QR do ingresso</Titulo>
      <Paragrafo>Peça para a pessoa abrir o ingresso no app e aponte a câmera para o QR.</Paragrafo>
      {!permissao ? null : !permissao.granted ? <PedirCamera podePedir={permissao.canAskAgain} pedir={pedirPermissao} /> : (
        <View style={[estilos.leitor, { borderColor: cores.linha }]}>
          <CameraView style={StyleSheet.absoluteFill} facing="back" barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
            onBarcodeScanned={({ data }) => receber(data)} />
          <View pointerEvents="none" style={estilos.mira} />
        </View>
      )}
      <Erro mensagem={aviso} />
      <Campo rotulo="Ou digite o código" value={digitado} onChangeText={t => setDigitado(t.toUpperCase())}
        autoCapitalize="characters" maxLength={12} placeholder="12 letras e números" />
      <Botao titulo="Usar este código" aoTocar={() => receber(digitado)} desativado={digitado.length !== 12} secundario />
    </View>
  )
}

function TelaResultado({ resultado, foto, aoContinuar }: { resultado: Resultado; foto: string | null; aoContinuar: () => void }) {
  const aparencia = {
    aceito: { fundo: '#1d7a46', titulo: 'Liberar entrada' },
    recusado: { fundo: '#b3261e', titulo: 'Não liberar' },
    indeterminado: { fundo: '#8a5a00', titulo: 'Decidir manualmente' },
  }[resultado.resultado]
  return (
    <View style={[estilos.resultado, { backgroundColor: aparencia.fundo }]} accessibilityLiveRegion="assertive">
      {foto && <Image source={{ uri: `data:image/jpg;base64,${foto}` }} style={estilos.rosto}
        accessibilityLabel="Rosto capturado na catraca" />}
      <Text style={estilos.resultadoTitulo}>{aparencia.titulo}</Text>
      {resultado.pessoa && (
        <View style={{ gap: 2 }}>
          <Text style={estilos.pessoaNome}>{resultado.pessoa.nome}</Text>
          <Text style={[estilos.resultadoTexto, { opacity: 0.85 }]}>@{resultado.pessoa.login}</Text>
        </View>
      )}
      <Text style={estilos.resultadoTexto}>
        {resultado.resultado === 'aceito'
          ? 'O rosto confere com o dono do ingresso. Ele foi marcado como usado.'
          : MOTIVOS[resultado.motivo ?? ''] ?? 'A entrada não foi confirmada.'}
      </Text>
      <Text style={[estilos.resultadoTexto, { opacity: 0.8 }]}>Ingresso {resultado.ingressoId}</Text>
      <Pressable accessibilityRole="button" onPress={aoContinuar} style={estilos.resultadoBotao}>
        <Text style={{ color: aparencia.fundo, fontSize: 18, fontWeight: '700' }}>Próxima pessoa</Text>
      </Pressable>
    </View>
  )
}

const estilos = StyleSheet.create({
  opcao: { flex: 1, alignItems: 'center', paddingVertical: 12, borderRadius: 10, borderWidth: 1 },
  leitor: { width: '100%', aspectRatio: 1, borderRadius: 16, overflow: 'hidden', borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  mira: { width: '60%', aspectRatio: 1, borderWidth: 3, borderColor: '#ffffff', borderRadius: 16, opacity: 0.85 },
  resultado: { flex: 1, padding: 28, justifyContent: 'center', gap: 16 },
  resultadoTitulo: { color: '#ffffff', fontSize: 36, fontWeight: '800' },
  rosto: { width: 160, aspectRatio: 3 / 4, borderRadius: 12, borderWidth: 3, borderColor: '#ffffff' },
  pessoaNome: { color: '#ffffff', fontSize: 26, fontWeight: '700' },
  resultadoTexto: { color: '#ffffff', fontSize: 18, lineHeight: 26 },
  resultadoBotao: { backgroundColor: '#ffffff', borderRadius: 12, paddingVertical: 16, alignItems: 'center', marginTop: 16 },
})
