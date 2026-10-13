# Tailscale: por qué `tailscale status` devuelve 401

## El síntoma

```
failed to connect to local tailscaled (which appears to be running as
tailscaled.exe, pid 5096). Got error: 401 Unauthorized: Tailscale already in
use by <EQUIPO>\<usuario>, pid 18112
```

El servicio está corriendo y `tailscaled.exe` está vivo. El problema no es que
falte el daemon: es que **otro cliente de Tailscale ya tiene el lock del estado
local**.

## La causa, en concreto

En esta máquina hay dos `tailscale-ipn.exe` en sesiones de Windows distintas:

| PID    | Proceso         | Sesión | Usuario | Iniciado         | Rol                        |
|--------|-----------------|--------|---------|------------------|----------------------------|
| 5096   | tailscaled.exe  | 0      | SYSTEM  | 25/09 19:18      | El servicio, el bueno      |
| 6364   | tailscaled.exe  | 0      | SYSTEM  | 25/09 19:18      | Hijo del anterior          |
| 18112  | tailscale-ipn   | 1      | <usuario> | 25/09 19:18      | **Obsoleto. Retiene el lock** |
| 161568 | tailscale-ipn   | 2      | max     | 27/09 18:26      | El GUI actual              |

`query user` lo confirma:

```
<usuario>    1  Desc   25/09/2026 7:18   <- sesión RDP desconectada, lleva 4 días así
>max     2  Activo 27/09/2026 6:26
```

El `tailscale-ipn` de `<usuario>` se inició a la vez que el servicio, hace cuatro días,
y su sesión quedó en `Desc` — desconectada pero viva. El lock de estado de
Tailscale es **por sesión de usuario**, así que ese proceso lo retiene desde una
sesión que ya no tiene a nadie al frente.

El `tailscale-ipn` de `max` (161568) es el que funciona y el que se ve en la
bandeja del sistema. Los dos son hijos de `explorer.exe`, uno por sesión.

## Por qué no se puede arreglar desde dentro

El proceso obsoleto corre en la **sesión 1** y yo estoy en la **sesión 2**:

```powershell
session=$((Get-Process -Id $PID).SessionId)   # 2
admin=$(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(...))  # False
```

`Stop-Process -Id 18112 -Force` no hace nada y no da error. Sin elevación no se
puede matar un proceso de otra sesión, y sin acesso a la sesión 1 no se puede
cerrar la sesión que lo sostiene.

## Cómo se arregla

En una **PowerShell elevada** (botón derecho → *Ejecutar como administrador*):

```powershell
# 1. Terminar el tailscale-ipn obsoleto de la sesión 1
Stop-Process -Id 18112 -Force -ErrorAction SilentlyContinue

# 2. Reiniciar el servicio para que reabra el lock con la sesión actual
Restart-Service Tailscale

# 3. Comprobar
& "$env:ProgramFiles\Tailscale\tailscale.exe" status
```

Si el paso 1 falla porque el PID ya cambió, matar por sesión en vez de por PID:

```powershell
Get-Process tailscale-ipn |
  Where-Object { $_.SessionId -ne (Get-Process -Id $PID).SessionId } |
  Stop-Process -Force
```

Si aun así el 401 persiste, cerrar la sesión RDP de `<usuario>` desde
`tsdiscon.exe` o desconectarla del todo; al morir la sesión, el lock se libera
solo.

## Nota de por qué esto importa para herdr-notify

`tailscale serve` es lo que exponería el gateway fuera de `127.0.0.1`. Sin
Tailscale funcionando, el gateway sirve solo en loopback, que es exactamente lo
deseable por defecto: el gateway no debe ser alcanzable desde la red hasta que
haya una decisión explícita de exponerlo.

Ver [[herdr-notify-architecture]] para por qué el gateway escucha solo en loopback
y qué superficie queda expuesta cuando se añade `tailscale serve`.

## Cuando el síntoma es el gateway, no `tailscale status`

El servicio supervisado (`tooling/run-gateway-supervised.ps1`, gestionado con
`tooling/herdr-notify-service.ps1`) resuelve la dirección tailnet en cada arranque
con `tailscale ip -4` y enlaza `127.0.0.1` más esa dirección. Si el 401 de arriba
impide esa consulta, la dirección queda vacía y el gateway arranca **solo en
loopback**: el teléfono deja de alcanzarlo aunque el proceso siga vivo.

Cómo verlo:

```powershell
herdr-notify status                        # tailscale: unavailable => solo loopback
tooling\herdr-notify-service.ps1 status    # estado de la tarea y del puerto
```

El arreglo es el mismo de arriba (elevar, terminar el `tailscale-ipn` obsoleto,
`Restart-Service Tailscale`); el gateway recoge la dirección en su siguiente
reinicio:

```powershell
tooling\herdr-notify-service.ps1 restart
```
