# SuperCiclo by h4ch3

Aplicación de escritorio (Windows) que permite **programar ciclos de encendido / apagado** sobre un enchufe inteligente Tuya.  
Se ejecuta localmente con **Flask** (backend) y se muestra en una ventana **pywebview**; además incorpora un icono en la bandeja mediante **pystray**.

![image](https://github.com/user-attachments/assets/e5433efe-4fe4-45b3-8bf2-1c3b7b52efd4)
![image](https://github.com/user-attachments/assets/dcd667e6-d7ff-45ac-8ea4-f062341c3a86)
<img width="1216" height="843" alt="image" src="https://github.com/user-attachments/assets/8d57852e-a624-49fa-a216-9808ec27e3dc" />
<img width="1216" height="843" alt="image" src="https://github.com/user-attachments/assets/f26b4435-7a69-44e3-9d12-853f4f207ba2" />

<img width="246" height="125" alt="image" src="https://github.com/user-attachments/assets/d3052594-8f6a-4ab8-b877-60c381e92ddb" />



---

## 1. Características principales

| Función | Descripción |
|---------|-------------|
| Generador de ciclo | Calcula y muestra una matriz ON / OFF para *n* días a partir de una hora de inicio, horas ON y horas OFF. |
| Exportación de JSON | Guarda los eventos en `json/horarios.json` para que el backend los ejecute. |
| Ejecución automática | Detecta la presencia de `horarios.json`, inicia el ciclo y muestra su estado en tiempo real. |
| Configuración Tuya | Desde la web (**Dispositivo Tuya**): se guarda en `config.ini` automáticamente (o podés crear ese archivo a mano). |
| Icono de bandeja | Acciones Mostrar / Ocultar / Salir. |
| Partículas de fondo | Efecto visual en la interfaz (particles.js). |

---

## 2. Requisitos

* Python 3.9 +  
* **Escritorio (Windows):** `pip install -r requirements.txt` — incluye Flask, TinyTuya, pywebview, pystray, Pillow; `pywin32` solo en Windows (atajo “Iniciar con Windows”).
* **Servidor / Raspberry Pi:** `pip install -r requirements-pi.txt` (sin ventana ni bandeja).

> **Nota:** Todo lo relacionado con Raspberry Pi — `requirements-pi.txt`, scripts y servicio en `deploy/`, y el flujo de instalación documentado más abajo — **aún no fue probado** en hardware real; usalo con precaución y reportá lo que encuentres.

**Windows:** para “Iniciar con Windows” hace falta que `pywin32` esté instalado; el resto de la configuración Tuya es por la interfaz web.

---

## 3. Instalación rápida

```bash
git clone [https://github.com/tu_usuario/superciclo.git](https://github.com/hache-dev/SuperCiclo.git)
cd superciclo
python -m venv venv
venv\Scripts\activate  # Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## 4. Configuración Tuya y `config.ini`

**No hace falta** tener `config.ini` antes del primer arranque del backend: levantás Flask, abrís la web, menú **Dispositivo Tuya** → **Guardar en servidor**. Eso crea o actualiza `config.ini` y aplica los cambios en memoria (el ciclo usa los datos nuevos sin reiniciar el servicio en la mayoría de los casos).

Versión Tuya por defecto en la interfaz: **3.4** (elegí 3.3 si tu enchufe lo requiere).

Formato del archivo (equivalente a lo que guarda la web):

```ini
[tuya]
device_id  = TU_DISPOSITIVO_ID
device_ip  = 192.168.0.15
local_key  = XXXXXYYYYZZZZAAAA
version    = 3.4
```

*Modo escritorio Windows (`main.py`): si editás `config.ini` a mano, reiniciá la app para volver a cargar credenciales al importar `app.py`. En modo servidor, preferí guardar desde la web.*

---

## 5. Estructura de carpetas

```
superciclo/
│ main.py              ← Lanzador (GUI + bandeja)
│ app.py               ← Backend Flask
│ requirements.txt     ← Dependencias modo escritorio (Windows)
│ requirements-pi.txt  ← Dependencias mínimas (servidor / Pi)
│ config.ini           ← Opcional al inicio; la web puede crearlo
│ json/
│   └─ horarios.json   ← Generado desde la interfaz
│ deploy/
│   ├─ install-pi.sh
│   └─ superciclo.service.example
│ static/
│   └─ img/trayicon.png
│ templates/
│   └─ ciclo.html
```

---

## 6. Uso básico

1. Ejecutá `python main.py`; se abrirá la ventana **SuperCiclo**.  
2. Completá hora de inicio, horas ON, horas OFF y el número de días.  
3. **Generar** para visualizar la matriz.  
4. **Exportar** guarda el archivo `horarios.json`.  
5. **Ejecutar** inicia el ciclo: el enchufe se activará/desactivará según el cronograma.

La sección *Info SuperCiclo* muestra:

* **SuperCiclo** (HS ON / HS OFF)
* **Estado actual** (ON / OFF)
* **Próximo estado** (fecha‑hora del próximo cambio)
* **Hora** local del sistema

---

## 7. Compilación a EXE (opcional)

Se puede empaquetar con **auto‑py‑to‑exe** en modo **One Directory**:

```
auto-py-to-exe   --script main.py   --windowed --onefile   --icon static/img/trayicon.ico   --add-data "templates;ciclo"   --add-data "static;static"   --add-data "config.ini;."   --add-data "json;json"
```

El ejecutable resultante contendrá las carpetas `templates`, `static`, `json` y el `config.ini` en el mismo directorio del `.exe`.

---

## 8. Solución de problemas

| Mensaje | Causa común | Solución |
|---------|-------------|----------|
| `No se pudo cargar horarios.json` | El archivo no existe o está mal formado. | Generar y exportar nuevamente. |
| `Error controlando el enchufe` | ID/IP/Key incorrectos. | Revisar credenciales en **Dispositivo Tuya** o en `config.ini`. |
| Icono no aparece | Falta `trayicon.png`. | Verificá la ruta `static/img/`. |
| Tiempo incorrecto | Zona horaria del sistema | Ajustar reloj de la PC / servidor |


---

## 9. Manual de uso adicional tinytuya

### Requisitos previos

1. **Instalar Python 3.9 o superior**  
   Descargue Python desde [https://www.python.org/downloads/](https://www.python.org/downloads/) y asegúrese de seleccionar la opción **"Add Python to PATH"** durante la instalación.

2. **Instalar dependencias necesarias**
   ```bash
   pip install -r requirements-pi.txt
   ```
   *(En Windows con `main.py`, usá `requirements.txt`.)*

3. **Obtener datos para `config.ini` con TinyTuya Wizard**
   TinyTuya proporciona un asistente para detectar dispositivos inteligentes y extraer información como `device_id`, `local_key` y `ip`.

   - Ejecute el asistente con:
     ```bash
     python -m tinytuya wizard
     ```
   - Siga las instrucciones para vincular el dispositivo inteligente (enchufe) a la red y obtener los datos necesarios.

4. **Ejemplo de `config.ini`**
   ```ini
   [tuya]
   device_id = your_device_id_here
   device_ip = 192.168.x.x
   local_key = your_local_key_here
   version   = 3.4
   ```

   ⚠️ **IMPORTANTE**: Para obtener el `device_id`, es necesario vincular el enchufe inteligente con la app oficial de Tuya (Smart Life o similar) y asegurarse de que esté conectado en la misma red local (LAN) que el servidor donde se ejecuta la app Flask.


---

## 10. Deploy en Raspberry Pi / Linux (servidor)

> Esta sección y los artefactos de despliegue para Pi/Linux **no fueron verificados** todavía; el texto guía la intención del proyecto, pero falta validación en dispositivo.

Objetivo: el backend **Flask + web** siempre encendido en la Pi, **sin** `main.py` (ese es solo el modo ventana para Windows).

**Antes:** la Pi con internet (WiFi o cable), terminal o SSH. El enchufe Tuya en la **misma red** que la Pi.

---

### Camino más corto: un comando en la Pi

**Dónde:** estos comandos van en la **Raspberry Pi** (terminal local del escritorio Pi, o **SSH** desde tu PC: `ssh usuario@ip-de-la-pi`). **No** hace falta tener el repo clonado en tu computadora: el paso 1 del script baja el código **dentro de la Pi** (carpeta `~/SuperCiclo`).

Pegá **una línea**. Cuando pida contraseña es **`sudo`** (instala paquetes y registra el servicio):

```bash
curl -fsSL https://raw.githubusercontent.com/hache-dev/SuperCiclo/main/deploy/install-pi.sh | bash -s -- --quick
```

*(Si tu rama principal no es `main`, cambiala en la URL. Si no querés `curl | bash`, abrí el archivo `deploy/install-pi.sh` en GitHub, descargalo y ejecutá `bash install-pi.sh --quick`.)*

**Qué hace el script, en orden:**

| Paso | Acción |
|------|--------|
| 1 | Con **`--quick`** trabaja sobre **`~/SuperCiclo`**: clona el repo o, si esa carpeta ya es un clone, hace **`git pull`**. |
| 2 | Si hace falta, instala con **`apt`** cosas como **`git`** y **`python3-venv`**. |
| 3 | Crea **`.venv`** e instala **`requirements-pi.txt`**. |
| 4 | Escribe la unidad **systemd** **`superciclo`**, la habilita y la arranca (puerto **8001** por defecto). |

Luego en el navegador (PC o celular, misma WiFi): **`http://IP-DE-LA-PI:8001`** — la IP la ves con `hostname -I` en la Pi o en el router.

---

### Ya tenés el código en la Pi (USB, clone manual en la Pi)

También **en la Raspberry Pi**: si ya copiaste el proyecto o lo clonaste a mano **ahí**. Desde la carpeta donde está `app.py`:

```bash
bash deploy/install-pi.sh
```

Hace los pasos 2–4 de la tabla (venv, pip, systemd) **sin** clonar otra vez.

---

### Más opciones

```bash
bash deploy/install-pi.sh --help
```

Ejemplos: `… --quick --port 8080` · `… --quick --venv-only` (sin systemd) · otro repo:  
`SUPER_CICLO_REPO=https://github.com/tu-usuario/SuperCiclo.git bash deploy/install-pi.sh --quick`

---

### Sin script (solo para probar)

```bash
cd SuperCiclo
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-pi.txt
export FLASK_APP=app:app
flask run --host=0.0.0.0 --port 8001
```

La plantilla **`deploy/superciclo.service.example`** sirve si armás systemd a mano; el script ya genera la unidad automáticamente. Variable opcional: **`SUPERCICLO_NO_AUTOSTART=1`** (no reanuda el ciclo al boot aunque exista `json/horarios.json`).

---

### Después del deploy

1. Abrí la web. 2. **Dispositivo Tuya** → **Guardar en servidor**. 3. **Generar** → **Exportar** → **Ejecutar**.

WiFi o IP fija de la Pi se configuran en el sistema (Imager, router, etc.), no en este script.

---

## 11. Licencia

MIT. ¡Usalo, modificálo y compartí mejoras!  
Autor: **h4ch3**
