import { CameraView, useCameraPermissions, type CameraType } from 'expo-camera'
import { useRef, useState } from 'react'
import { Image, Linking, StyleSheet, View } from 'react-native'
import { Botao, Erro, Paragrafo, useCores } from './ui'

// Captura de um rosto. Devolve o JPEG em base64 (sem prefixo), que o backend
// envia ao Rekognition; a foto não fica guardada no aparelho.
// No cadastro a pessoa usa a câmera frontal; na catraca, o validador aponta a
// traseira para quem está entrando (e pode trocar).
export function CapturaRosto({ aoConfirmar, enviando, camera: cameraInicial = 'front', textoConfirmar = 'Usar esta foto' }: {
  aoConfirmar: (base64: string) => void
  enviando: boolean
  camera?: CameraType
  textoConfirmar?: string
}) {
  const cores = useCores()
  const [permissao, pedirPermissao] = useCameraPermissions()
  const camera = useRef<CameraView>(null)
  const [lado, setLado] = useState<CameraType>(cameraInicial)
  const [pronta, setPronta] = useState(false)
  const [foto, setFoto] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  if (!permissao) return null
  if (!permissao.granted) return <PedirCamera podePedir={permissao.canAskAgain} pedir={pedirPermissao} />

  async function tirar() {
    setErro(null)
    try {
      const imagem = await camera.current?.takePictureAsync({ base64: true, quality: 0.6 })
      if (imagem?.base64) setFoto(imagem.base64)
    } catch {
      setErro('Não foi possível tirar a foto. Tente de novo.')
    }
  }

  function trocarCamera() {
    setPronta(false)
    setLado(atual => (atual === 'front' ? 'back' : 'front'))
  }

  return (
    <View style={{ gap: 12 }}>
      <View style={[estilos.moldura, { borderColor: cores.linha }]}>
        {foto
          ? <Image source={{ uri: `data:image/jpg;base64,${foto}` }} style={StyleSheet.absoluteFill} accessibilityLabel="Foto do rosto" />
          : <CameraView ref={camera} style={StyleSheet.absoluteFill} facing={lado} onCameraReady={() => setPronta(true)} />}
      </View>
      <Erro mensagem={erro} />
      {foto ? (
        <>
          <Botao titulo={textoConfirmar} aoTocar={() => aoConfirmar(foto)} carregando={enviando} />
          <Botao titulo="Tirar outra" aoTocar={() => setFoto(null)} secundario desativado={enviando} />
        </>
      ) : (
        <>
          <Paragrafo>Rosto de frente, sem óculos escuros nem boné, com boa luz.</Paragrafo>
          <Botao titulo="Tirar foto" aoTocar={tirar} desativado={!pronta} />
          <Botao titulo={lado === 'front' ? 'Usar a câmera traseira' : 'Usar a câmera frontal'} aoTocar={trocarCamera} secundario />
        </>
      )}
    </View>
  )
}

export function PedirCamera({ podePedir, pedir }: { podePedir: boolean; pedir: () => void }) {
  return (
    <View style={{ gap: 12 }}>
      <Paragrafo>O app precisa da câmera para ler o rosto e o QR do ingresso.</Paragrafo>
      {podePedir
        ? <Botao titulo="Permitir a câmera" aoTocar={pedir} />
        : <Botao titulo="Abrir os ajustes para liberar a câmera" aoTocar={() => Linking.openSettings()} />}
    </View>
  )
}

const estilos = StyleSheet.create({
  moldura: { width: '100%', aspectRatio: 3 / 4, borderRadius: 16, overflow: 'hidden', borderWidth: 1 },
})
