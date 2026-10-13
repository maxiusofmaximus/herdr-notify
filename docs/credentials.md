# Credenciales: qué se automatiza y qué no

Este proyecto tiene dos credenciales. Una se genera con un script y la otra
necesita que hagas algo tú. La diferencia no es de conveniencia: una es un
secreto que hay que proteger, la otra es un consentimiento sobre tu cuenta de
Google, y esas dos cosas no se pueden tratar igual.

| Credencial | ¿Automatizable? | Cómo |
|---|---|---|
| Key de firma Android | **Sí, entera** | `tooling/setup-signing.ps1` |
| Credenciales de FCM | **No, y no debería** | `gcloud auth application-default login` |

---

## 1. Key de firma Android — automatizada

Ya está hecha. `keystore.properties` y `keystores/release.jks` existen, y el APK
de release está firmado con v2 y v3, verificado con `apksigner`.

Para rehacerla desde cero:

```powershell
cd <ruta-del-repo>
.\tooling\setup-signing.ps1
cd android
.\gradlew.bat :app:assembleRelease
```

**El script se niega a sobrescribir una clave existente.** No es prudencia
decorativa: si una release ya salió firmada con esa clave, Android identifica las
actualizaciones por la clave de firma, así que una clave nueva produce una app
distinta instalada en paralelo en vez de una actualización, y la instalada queda
inaccesible sin restauración de fábrica. Para empezar de cero hay que borrar el
fichero a mano.

El password se genera, no se teclea, y **no se imprime por pantalla**. Solo
aparece en `keystore.properties`, que está en `.gitignore`. Así una captura de
esta terminal o una transcripción de la sesión no contienen el secreto.

### Tu única decisión: la copia de seguridad

Esto no lo puede hacer un agente por ti, porque el destino es una decisión sobre
dónde vas a seguir teniendo algo dentro de cinco años:

- `keystores\release.jks`
- `keystore.properties`

Los dos juntos, o ninguno sirve: el binario sin las contraseñas es inútil.

### Detalle que salió al verificar

`apksigner` reporta `v1: false` y `v2: true`, `v3: true`. Es lo correcto: el
esquema v1 (JAR signing) solo hace falta por debajo de API 24, y el minSdk de
esta app es 26. Forzarlo añadiría firma sin propósito.

---

## 2. Credenciales de FCM — este paso lo tienes que dar tú

### Por qué aquí no hay script

`gcloud auth application-default login` abre el navegador y muestra una pantalla
de **consentimiento OAuth sobre tu cuenta de Google**. Ningún agente puede —ni
debería— pulsar ese botón: es un acto autenticado que solo corresponde a la
persona propietaria de la cuenta. Un script que lo automatizara convertiría un
consentimiento en un efecto secundario, que es exactamente el hábito que la
auditoría de seguridad marca.

Lo que sí es automatizable es todo lo demás, y por eso existe
`tooling/setup-firebase-credentials.ps1`: comprueba que gcloud está instalado,
verifica que la credencial existe, y —lo que de verdad importa— **la ejerce con
`firebase-admin`** para detectar el caso en que el fichero está pero no sirve.

### Los pasos

**a) Instalar gcloud** (una vez):

```powershell
winget install Google.CloudSDK
```

Cierra y reabre la terminal para que quede en el PATH.

**b) Autenticarte** (una vez):

```powershell
gcloud init
```

Se abre el navegador. Elige el proyecto `herdr-notify` cuando lo pida.

**c) Crear la credencial que usa el gateway** (una vez):

```powershell
gcloud auth application-default login
```

Escribe `%APPDATA%\gcloud\application_default_credentials.json`.

**d) Verificarlo:**

```powershell
cd <ruta-del-repo>
.\tooling\setup-firebase-credentials.ps1
```

Si el paso (c) funcionó, dice `credential ok`. Si no, dice exactamente por qué,
incluyendo las tres causas habituales: `firebase-admin` no instalado, la cuenta
sin rol en el proyecto, o la API sin activar.

**e) Arrancar el gateway con FCM:**

```powershell
cd gateway
.venv\Scripts\python -m herdr_notify.cli serve
```

`firebase-admin` encuentra la credencial por su cuenta. **No hay variable de
entorno que configurar**, y ese es el punto: la credencial vive en una ruta
estándar, se renueva sola, y se revoca cerrando sesión en tu cuenta de Google en
lugar de borrando un fichero y esperando acordarte.

### La vía que no vamos a usar

Existe la vía corta: `gcloud iam service-accounts keys create` escribe un JSON
con una clave RSA privada permanente. Funciona. Google lleva desde 2024
desaconsejándolo y ha añadido una política de organización,
`iam.disableServiceAccountKeyCreation`, específicamente para frenarlo.

La diferencia no es de estilo. Un fichero de clave es una credencial de portador:
cualquiera que lo tenga puede enviar como la service account hasta que alguien se
dé cuenta y la borre. Una credencial ADC está atada a una sesión que puedes cerrar
desde un navegador.

El script ofrece esa vía solo con `-UseServiceAccountKey` explícito, y explica
por qué antes de hacerlo:

```powershell
.\tooling\setup-firebase-credentials.ps1 -UseServiceAccountKey
```

---

## 3. Lo que ya funciona sin ninguna de las dos

El listado de agentes, el tiempo real y la firma de peticiones funcionan **sin FCM
y sin clave de release**. FCM es un acelerante: avisa cuando la app está cerrada.
El stream SSE cubre el caso en que está abierta.

Eso significa que un fallo en cualquiera de estas dos credenciales degrada la
experiencia pero no la rompe, y que puedes resolver una y dejar la otra para más
adelante sin bloquearte.
