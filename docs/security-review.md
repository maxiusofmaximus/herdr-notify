# Auditoría de seguridad

> Alcance: `gateway/src/herdr_notify/api/**` (autenticación, rate limit,
> acciones) y `android/app/src/main/**` (manifiesto, keystore, notificaciones,
> red).
>
> Método: lectura de fuente, más una ejecución real en un TECNO KI7-GL
> (Android 13). No se hizo probing de red ni se tocó ningún sistema ajeno.

## Límites de confianza

| Frontera | Quién está de un lado | Control |
|---|---|---|
| Red → gateway | cualquier cosa que alcance el puerto | firma P-256/Ed25519 por petición, sin token estático |
| Red → app Android | FCM, o quien controla el dispositivo | `exported=false` en todo menos `MainActivity`; payload validado campo a campo |
| Host → gateway | CLI local (`enroll`, `add-device`, `devices`) | codes de un solo uso, 10 min, filesystem local |
| Gateway → herdr | named pipe en `%APPDATA%\herdr` | acciones allowlisted; nunca se reenvía un método de herdr |

La consecuencia de diseño que atraviesa todo: **el gateway puede pilotar
cualquier agente de la máquina**, así que un token filtrado equivale a entregar
una shell. Por eso no existe token: un device es una clave pública, y probar que
la llamante tiene la privada es lo único que autentica.

## Lo que está bien, y por qué importa que lo esté

- **`_load()` falla cerrado.** Un trust store ilegible deja `_devices` vacío, no
  populado. El error fácil sería tratar un JSON corrupto como "no hay devices" y
  que eso significase "acepta a cualquiera"; aquí significa "no acepta a nadie".
- **El nonce se consume después de conocer la device** (`verify.py:266-269`).
  Un atacante no autenticado no puede evictar nonces legítimos del cache.
- **Un solo mensaje de 401** para toda clase de rechazo (`verify.py:77-83`).
  Distinguir "device desconocida" de "firma mala" convertiría el endpoint en un
  oráculo de qué ids existen.
- **El `_save()` es atómico** (`os.replace`, `devices.py:173`). Un trust store a
  medio escribir es un gateway que rechaza a todos o cree en las devices
  equivocadas.
- **`ctrl+c` exige `confirm`**, y las keys están allowlisted.

## Hallazgos corregidos

### F1 — `enroll()` consumía el code antes de validar el payload

`devices.py`. El comentario lo justificaba y el razonamiento era correcto para
*su* amenaza, pero el efecto era el contrario: un atacante que robase un code
del historial del terminal podía **denegar el emparejamiento del teléfono
legítimo** con un body inválido, y el operador vería "code inválido" sin poder
distinguir un typo de un intento.

Corregido: el payload se valida primero y el code se consume solo cuando la
petición puede tener éxito. El single-use se mantiene donde importa, y ahora hay
dos tests que fijan ambas mitades.

### F2 — `touch()` reescribía el trust store en cada request

`require_device` llama a `touch()` en cada petición, y `touch` hacía un
`write_text` + `os.replace`. Un teléfono reconectando en bucle convertía lecturas
en escrituras al disco del host. Corregido: escrituras limited a una vez por
minuto y por device, con el timestamp en memoria siempre exacto.

### F3 — el backoff de reconexión no tenía jitter

Gateway y teléfonos despiertan juntos. El backoff determinista hacía que todos
calculasen el mismo intervalo y reconectasen en el mismo instante, contra un
gateway con cap por stream. Corregido con un 20% de dispersión.

### F4 — la app no tenía forma de emparejarse

Anotado como hueco, no como vulnerabilidad. Resuelto en `98f0771` con la pantalla
de pairing.

### F5 — la clave de firma podía acabar en el repositorio

Encontrado al verificar el build de release. `.gitignore` tenía `*.keystore` pero
el fichero se llama `release.jks`, así que `git add .` lo habría commiteado.
Corregido con `*.jks` y el directorio `keystores/` como red de seguridad.

## Hallazgos que solo aparecieron en hardware real

Ninguno de estos era visible desde la JVM, y los tres habrían shipped con la
suite de tests en verde.

### F6 — el chequeo de curva P-256 comparaba `ECParameterSpec` por igualdad

La clave del Keystore viene de Conscrypt y la de referencia del provider de
software; su `equals` no es simétrico entre providers. El primer arranque real
murió con `expected a P-256 key but got a 256-bit curve`. En la JVM ambos
lados venían de SunEC y el test pasaba.

Corregido identificando la curva por su primo de campo, que es el mismo
BigInteger en todos los providers. Deliberadamente **no** por el tamaño del
campo: 256 bits también acepta brainpoolP256r1, misma anchura de coordenadas,
curva distinta.

### F7 — cleartext bloqueado impedía conectar con el gateway

Android 28+ bloquea HTTP en claro. El gateway sirve HTTP plano en loopback y no
había network security config, así que la app no podía hablar con su propio
gateway en absoluto.

Corregido con una excepción acotada a loopback y al alias del emulador. No se
activó cleartext globalmente: eso dejaría que un `http://` mal escrito
degradase en silencio una conexión real.

### F8 — la app nunca salía de la pantalla de pairing

`App` leía el pairing una vez con `produceState`, que responde al arrancar y
nunca más. El gateway había recibido cero peticiones, y así se encontró.

## Cosas que deliberadamente NO son hallazgos

- **El gateway escucha solo en `127.0.0.1`.** Endurecerlo sin exposición previa
  sería consejo genérico, no un defecto.
- **`/v1/health` es sin auth.** Devuelve contadores, no datos del operador. No
  expone versión de herdr ni nombres de pane, que sí serían reconocimiento.
- **OpenAPI/docs desactivados.** Endurecimiento, no una frontera saltada.
- **Los componentes FCM son `exported=false`.** El payload se valida en
  `HerdrMessagingService` de todos modos.
- **`setUserAuthenticationRequired(false)`.** El gate biométrico es de UI, no de
  clave. Es una decisión consciente —la clave debe poder firmar en background
  para que un push sea accionable— pero debe estar escrita como decisión, no
  ser un descuido. **Pendiente de documentar formalmente.**
- **La clave pública en base64 no es secreto.** Es público por definición, y toda
  la threat model depende de que eso sea cierto.

## Cobertura y lo que esto NO demuestra

Esta revisión leyó `api/auth/{verify,devices,canonical}.py`,
`api/{app,actions,ratelimit}.py`, el manifiesto fusionado, y
`DeviceKeyStore`, `RequestSigner`, `LiveStream`, `PairingStore`. Además
ejecutó la app en un dispositivo real.

**No** cubrió: el transporte de named pipe a herdr, la política de push, la
implementación de FCM en el gateway, ni el pipeline de release. Ninguna
afirmación aquí dice que esas partes estén bien — solo que nadie las miró.
