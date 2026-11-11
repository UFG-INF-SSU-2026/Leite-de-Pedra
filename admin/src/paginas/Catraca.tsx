import { useEffect, useRef, useState } from 'react'
import { chamar } from '../api'
import { Erro } from '../componentes'

// Catraca no computador, para validadores: a webcam lê o QR do ingresso e
// depois o rosto de quem entra. Quem decide é o processador, como no app.

const FILAS = ['fila-a', 'fila-b']
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

const TITULOS = { aceito: 'Liberar entrada', recusado: 'Não liberar', indeterminado: 'Decidir manualmente' }

// Leitor de QR nativo do navegador (Chrome e Edge); ainda fora dos tipos do TypeScript.
type Detector = { detect(fonte: HTMLVideoElement): Promise<{ rawValue: string }[]> }
declare global {
  interface Window { BarcodeDetector?: new (opcoes: { formats: string[] }) => Detector }
}

export function Catraca() {
  const video = useRef<HTMLVideoElement>(null)
  const quadro = useRef<HTMLCanvasElement>(null)
  const [fila, setFila] = useState(FILAS[0])
  const [pronta, setPronta] = useState(false)
  const [erroCamera, setErroCamera] = useState<string | null>(
    window.isSecureContext ? null
      : 'O navegador só libera a câmera em https ou em localhost. Abra http://localhost:8444/painel/ neste computador.')
  const [ingresso, setIngresso] = useState<string | null>(null)
  const [digitado, setDigitado] = useState('')
  const [aviso, setAviso] = useState<string | null>(null)
  const [foto, setFoto] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [resultado, setResultado] = useState<Resultado | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const temLeitorQr = 'BarcodeDetector' in window

  // A câmera abre uma vez e fica ligada nas duas etapas.
  useEffect(() => {
    if (!window.isSecureContext) return  // fora de https/localhost não há câmera
    let fluxo: MediaStream | null = null
    let saiu = false
    navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false })
      .then(novo => {
        if (saiu) return novo.getTracks().forEach(t => t.stop())
        fluxo = novo
        video.current!.srcObject = novo
        return video.current!.play().then(() => setPronta(true))
      })
      .catch(() => setErroCamera('Não foi possível abrir a câmera. Libere o acesso no navegador e recarregue a página.'))
    return () => {
      saiu = true
      fluxo?.getTracks().forEach(t => t.stop())
    }
  }, [])

  // Etapa 1: procura um QR no vídeo a cada 250 ms até achar um ingresso.
  useEffect(() => {
    if (ingresso || resultado || !pronta || !window.BarcodeDetector) return
    const detector = new window.BarcodeDetector({ formats: ['qr_code'] })
    let parar = false
    const procurar = async () => {
      if (parar) return
      try {
        const [lido] = await detector.detect(video.current!)
        if (lido && !parar) {
          const codigo = lido.rawValue.trim().toUpperCase()
          if (CODIGO_INGRESSO.test(codigo)) return setIngresso(codigo)
          setAviso('Este QR não é de um ingresso do Leite de Pedra.')
        }
      } catch { /* quadro ainda sem imagem: tenta de novo */ }
      setTimeout(procurar, 250)
    }
    procurar()
    return () => { parar = true }
  }, [ingresso, resultado, pronta])

  function usarDigitado() {
    if (CODIGO_INGRESSO.test(digitado)) setIngresso(digitado)
    else setAviso('O código tem 12 letras de A a F e números.')
  }

  // Etapa 2: congela o quadro atual como JPEG (base64 sem prefixo, como no app).
  function tirarFoto() {
    const v = video.current!, c = quadro.current!
    c.width = v.videoWidth
    c.height = v.videoHeight
    c.getContext('2d')!.drawImage(v, 0, 0)
    setFoto(c.toDataURL('image/jpeg', 0.85).split(',')[1])
  }

  async function validar() {
    setEnviando(true)
    setErro(null)
    try {
      setResultado(await chamar<Resultado>('/leituras', { metodo: 'POST', corpo: { ingressoId: ingresso, filaId: fila, foto } }))
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  function proxima() {
    setIngresso(null)
    setDigitado('')
    setAviso(null)
    setFoto(null)
    setResultado(null)
    setErro(null)
  }

  return (
    <div className="catraca">
      <div className="filas" role="radiogroup" aria-label="Fila desta catraca">
        {FILAS.map(f => (
          <button key={f} type="button" role="radio" aria-checked={fila === f} onClick={() => setFila(f)}
            className={fila === f ? 'ativa' : ''} disabled={!!ingresso && !resultado}>{f}</button>
        ))}
      </div>

      {resultado ? (
        <section className={`resultado resultado-${resultado.resultado}`} aria-live="assertive">
          {foto && <img className="rosto" src={`data:image/jpeg;base64,${foto}`} alt="Rosto capturado na catraca" />}
          <div className="dados">
            <h2>{TITULOS[resultado.resultado]}</h2>
            {resultado.pessoa && (
              <dl>
                <dt>Nome</dt><dd>{resultado.pessoa.nome}</dd>
                <dt>Login</dt><dd>{resultado.pessoa.login}</dd>
              </dl>
            )}
            <p>{resultado.resultado === 'aceito'
              ? 'O rosto confere com o dono do ingresso. Ele foi marcado como usado.'
              : MOTIVOS[resultado.motivo ?? ''] ?? 'A entrada não foi confirmada.'}</p>
            <p className="ingresso">Ingresso {resultado.ingressoId} · {fila}</p>
            <button type="button" onClick={proxima} autoFocus>Próxima pessoa</button>
          </div>
        </section>
      ) : (
        <ol className="etapas">
          <li className={ingresso ? 'feita' : 'atual'}>QR do ingresso{ingresso && <> · <code>{ingresso}</code></>}</li>
          <li className={ingresso ? 'atual' : ''}>Rosto de quem está entrando</li>
        </ol>
      )}

      <Erro mensagem={erroCamera} />
      <div className="camera" hidden={!!resultado || !!erroCamera}>
        <video ref={video} muted playsInline hidden={!!foto} className={ingresso ? 'espelho' : ''} />
        <canvas ref={quadro} hidden={!foto} />
        {!ingresso && <div className="mira" aria-hidden="true" />}
      </div>

      {!resultado && !ingresso && (
        <div className="acoes-catraca">
          <p className="nota">
            {temLeitorQr ? 'Mostre o QR do ingresso para a câmera.'
              : 'Este navegador não lê QR pela câmera (use Chrome ou Edge). Digite o código do ingresso.'}
          </p>
          <Erro mensagem={aviso} />
          <div className="digitar">
            <label>Ou digite o código
              <input id="codigo-ingresso" value={digitado} maxLength={12} placeholder="12 letras e números"
                onChange={e => setDigitado(e.target.value.trim().toUpperCase())}
                onKeyDown={e => e.key === 'Enter' && usarDigitado()} />
            </label>
            <button type="button" onClick={usarDigitado} disabled={digitado.length !== 12}>Usar este código</button>
          </div>
        </div>
      )}

      {!resultado && ingresso && (
        <div className="acoes-catraca">
          <p className="nota">Rosto de frente, sem óculos escuros nem boné, com boa luz.</p>
          <Erro mensagem={erro} />
          <div className="acoes">
            {foto ? <>
              <button type="button" className="principal" onClick={validar} disabled={enviando}>
                {enviando ? 'Validando…' : 'Validar entrada'}</button>
              <button type="button" onClick={() => setFoto(null)} disabled={enviando}>Tirar outra</button>
            </> : (
              <button type="button" className="principal" onClick={tirarFoto} disabled={!pronta}>Tirar foto</button>
            )}
            <button type="button" onClick={proxima} disabled={enviando}>Ler outro ingresso</button>
          </div>
        </div>
      )}
    </div>
  )
}
