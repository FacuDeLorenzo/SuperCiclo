"""Servidor Flask de SuperCiclo: horarios, enchufe Tuya local y ciclo automático."""

import configparser
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, render_template, send_from_directory  # pylint: disable=import-error
import tinytuya  # pylint: disable=import-error

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("superciclo.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Silenciar logs de Werkzeug para peticiones HTTP
logging.getLogger('werkzeug').setLevel(logging.WARNING)

app = Flask(__name__)

@app.route('/favicon.ico')
def favicon():
    """Sirve el favicon desde static."""
    return send_from_directory(app.static_folder, 'favicon.ico')


CONFIG_PATH = "config.ini"
DEFAULT_TUYA_VERSION = 3.4
TUYA_ID = None
TUYA_IP = None
TUYA_KEY = None
TUYA_VERSION = None
tuya_lock = threading.Lock()

JSON_FOLDER = "json"
os.makedirs(JSON_FOLDER, exist_ok=True)

estado_actual = {"estado": "desconocido", "proximo": "", "hora": ""}
ciclo_en_ejecucion = False
ciclo_thread = None
horarios_actuales = None


def load_tuya_from_file():
    """Si existe config.ini con [tuya], carga credenciales (opcional al primer arranque)."""
    global TUYA_ID, TUYA_IP, TUYA_KEY, TUYA_VERSION  # pylint: disable=global-statement
    if not os.path.isfile(CONFIG_PATH):
        logging.info("Sin config.ini: configurá Tuya desde la web; se creará el archivo al guardar.")
        return
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    if not cfg.has_section("tuya"):
        return
    with tuya_lock:
        TUYA_ID = (cfg.get("tuya", "device_id", fallback="") or "").strip() or None
        TUYA_IP = (cfg.get("tuya", "device_ip", fallback="") or "").strip() or None
        TUYA_KEY = (cfg.get("tuya", "local_key", fallback="") or "").strip() or None
        try:
            TUYA_VERSION = cfg.getfloat("tuya", "version")
        except (ValueError, TypeError):
            TUYA_VERSION = DEFAULT_TUYA_VERSION
    if tuya_configured():
        logging.info("Config Tuya cargada desde config.ini.")
    else:
        logging.warning("config.ini existe pero faltan datos Tuya completos.")


def tuya_configured():
    """Indica si hay credenciales Tuya locales completas en memoria."""
    with tuya_lock:
        return bool(TUYA_ID and TUYA_IP and TUYA_KEY and TUYA_VERSION is not None)


def _tuya_snapshot():
    """Copia thread-safe de device_id, ip, local_key y versión Tuya."""
    with tuya_lock:
        return TUYA_ID, TUYA_IP, TUYA_KEY, TUYA_VERSION


load_tuya_from_file()


@app.route("/")
@app.route("/ciclo")
def ciclo():
    """Página principal del planificador de ciclos."""
    return render_template("ciclo.html")


@app.route("/guardar-json", methods=["POST"])
def guardar_json():
    """Persiste eventos, nombre de superciclo y fecha de inicio en json/horarios.json."""
    try:
        data = request.get_json()
        eventos = data.get("eventos")
        superciclo_val = data.get("superciclo")
        fecha_inicio = data.get("fecha_inicio")

        if not (eventos and superciclo_val and fecha_inicio):
            return jsonify({"success": False, "message": "Datos incompletos."})

        ruta = os.path.join(JSON_FOLDER, "horarios.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({
                "eventos": eventos,
                "superciclo": superciclo_val,
                "fecha_inicio": fecha_inicio
            }, f, ensure_ascii=False, indent=2)

        logging.info("Archivo horarios.json guardado correctamente.")
        return jsonify({"success": True})
    except (OSError, TypeError, ValueError, KeyError, AttributeError) as exc:
        logging.exception("Error al guardar el archivo JSON")
        return jsonify({"success": False, "message": str(exc)})


def cargar_horarios():
    """Lee horarios.json y normaliza fecha_inicio a datetime; None si el archivo falta o es inválido."""
    ruta = os.path.join(JSON_FOLDER, "horarios.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            data = json.load(f)
            if "fecha_inicio" in data:
                data["fecha_inicio"] = datetime.fromisoformat(data["fecha_inicio"])
            return data
    except (
        FileNotFoundError,
        IsADirectoryError,
        PermissionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        logging.error("Error al cargar horarios.json: %s", exc, exc_info=True)
        return None


def construir_eventos_abs(data, ahora):
    """Expande eventos relativos a datetimes absolutos y repite según duración del superciclo."""
    ref = data.get("fecha_inicio") or ahora.replace(hour=0, minute=0, second=0, microsecond=0)

    if isinstance(ref, str):
        ref = datetime.fromisoformat(ref)

    eventos_base = []
    dias_def = [ev.get("dia") for ev in data.get("eventos", []) if isinstance(ev.get("dia"), int)]
    duracion_superciclo = max(dias_def) + 1 if dias_def else 1  # Evitar división por cero

    for ev in data["eventos"]:
        h, m = map(int, ev["hora"].split(":"))
        dia = ev.get("dia", 0)
        dt = ref + timedelta(days=dia, hours=h, minutes=m)
        eventos_base.append((ev["accion"].lower(), dt))

    fecha_mas_lejana = max(dt for _, dt in eventos_base)
    horizonte = max((fecha_mas_lejana - ahora).days + duracion_superciclo, duracion_superciclo * 2)

    eventos_ext = []
    for accion, dt in eventos_base:
        current_dt = dt
        while (current_dt - ahora).days <= horizonte:
            if current_dt >= ahora - timedelta(days=1):
                eventos_ext.append((accion, current_dt))
            current_dt += timedelta(days=duracion_superciclo)  # ✅ incremento flexible

    eventos_ext.sort(key=lambda x: x[1])
    return eventos_ext




def superciclo(data):
    """Hilo principal: mantiene estado/on-off del enchufe según horarios hasta que se detiene."""
    global ciclo_en_ejecucion  # pylint: disable=global-statement
    ciclo_en_ejecucion = True

    estado_previo = None
    logging.info("Iniciando ejecución de superciclo...")

    while ciclo_en_ejecucion:
        ahora = datetime.now()
        tid, tip, tkey, tver = _tuya_snapshot()
        if not (tid and tip and tkey and tver is not None):
            logging.warning("Tuya sin configurar: el ciclo espera hasta que guardes credenciales en la web.")
            estado_actual.update(
                estado="desconocido",
                proximo="--",
                hora=ahora.strftime("%Y-%m-%d %H:%M:%S"),
            )
            time.sleep(30)
            continue

        accion_actual, proximo_dt = calcular_estado_y_proximo(data, ahora)

        if accion_actual != estado_previo:
            estado_previo = accion_actual
            try:
                enchufe = tinytuya.OutletDevice(tid, tip, tkey)
                enchufe.set_version(float(tver))
                if accion_actual == "on":
                    enchufe.turn_on()
                    logging.info("Enchufe encendido")
                else:
                    enchufe.turn_off()
                    logging.info("Enchufe apagado")
            except (OSError, TimeoutError, ConnectionError, RuntimeError):
                logging.exception("Error controlando el enchufe")

        estado_actual.update(
            estado=accion_actual,
            proximo=proximo_dt.strftime("%Y-%m-%d %H:%M"),
            hora=ahora.strftime("%Y-%m-%d %H:%M:%S")
        )
        time.sleep(30)

    ciclo_en_ejecucion = False
    logging.info("Ciclo detenido.")


def start_superciclo_from_horarios(nuevos_horarios, *, allow_skip_duplicate=True):
    """
    Arranca el hilo del superciclo con datos ya cargados (mismo flujo que POST /iniciar_ciclo).
    Retorna dict: ok, mensaje, started (si se lanzó un hilo nuevo).
    """
    global ciclo_en_ejecucion, ciclo_thread, horarios_actuales  # pylint: disable=global-statement

    if not tuya_configured():
        return {
            "ok": False,
            "mensaje": "Configurá el enchufe Tuya en el menú «Dispositivo Tuya» (guardar en servidor) antes de ejecutar el ciclo.",
            "started": False,
        }

    if nuevos_horarios is None:
        logging.error("No se pudo cargar horarios.json")
        return {"ok": False, "mensaje": "No se pudo cargar horarios.json", "started": False}

    if allow_skip_duplicate and ciclo_en_ejecucion and nuevos_horarios == horarios_actuales:
        return {"ok": True, "mensaje": "SuperCiclo ya generado y ejecutado...", "started": False}

    if ciclo_en_ejecucion:
        ciclo_en_ejecucion = False
        time.sleep(1)

    horarios_actuales = nuevos_horarios

    ahora = datetime.now()
    estado, proximo_dt = calcular_estado_y_proximo(nuevos_horarios, ahora)

    dias_def = [ev.get("dia") for ev in nuevos_horarios.get("eventos", []) if isinstance(ev.get("dia"), int)]
    duracion_superciclo = max(dias_def) + 1 if dias_def else 0

    raw_inicio = nuevos_horarios.get("fecha_inicio")
    if isinstance(raw_inicio, datetime):
        fecha_inicio = raw_inicio.date()
    elif isinstance(raw_inicio, str):
        try:
            fecha_inicio = datetime.fromisoformat(raw_inicio).date()
        except ValueError:
            fecha_inicio = None
    else:
        fecha_inicio = None

    if duracion_superciclo and fecha_inicio:
        dias_transcurridos = (ahora.date() - fecha_inicio).days
        dia_actual = (dias_transcurridos % duracion_superciclo) + 1
        dias_restantes = duracion_superciclo - dia_actual 
    else:
        dia_actual = "--"
        dias_restantes = "--"

    logging.info(
        "Info SuperCiclo...\n"
        "    SuperCiclo: %s\n"
        "    Día: %s\n"
        "    Días restantes: %s\n"
        "    Estado actual: %s\n"
        "    Próximo estado: %s\n"
        "    Hora: %s\n",
        nuevos_horarios.get("superciclo", "--"),
        dia_actual,
        dias_restantes,
        estado.upper(),
        proximo_dt.strftime("%Y-%m-%d %H:%M") if proximo_dt else "--",
        ahora.strftime("%Y-%m-%d %H:%M:%S"),
    )

    ciclo_thread = threading.Thread(target=superciclo, args=(nuevos_horarios,))
    ciclo_thread.daemon = True
    ciclo_thread.start()

    return {"ok": True, "mensaje": "Nuevo SuperCiclo ejecutado...", "started": True}


@app.route("/iniciar_ciclo", methods=["POST"])
def iniciar_ciclo():
    """Carga horarios desde disco e intenta arrancar o reanudar el hilo del superciclo."""
    nuevos_horarios = cargar_horarios()
    result = start_superciclo_from_horarios(nuevos_horarios, allow_skip_duplicate=True)
    return jsonify({"mensaje": result["mensaje"]})


def calcular_estado_y_proximo(data, ahora):
    """Devuelve (accion_on_off_actual, datetime del próximo cambio) a partir de los eventos."""
    eventos = construir_eventos_abs(data, ahora)

    estado = None
    proximo_evento = None

    for i, (_, dt) in enumerate(eventos):
        if dt > ahora:
            estado = eventos[i - 1][0] if i > 0 else eventos[-1][0]
            proximo_evento = dt
            break
    else:
        estado = eventos[-1][0]
        proximo_evento = eventos[0][1] + timedelta(days=7)

    return estado, proximo_evento


@app.route("/estado_ciclo")
def estado_ciclo():
    """JSON con estado del enchufe, próximo evento y día dentro del superciclo."""
    data = cargar_horarios()
    if not data:
        return jsonify({
            "superciclo": "--",
            "estado": "desconocido",
            "proximo": "--",
            "hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "supercicloDiaActual": "--",
            "supercicloDiasRestantes": "--"
        })

    ahora = datetime.now()
    estado, proximo_dt = calcular_estado_y_proximo(data, ahora)

    dias_def = [ev.get("dia") for ev in data.get("eventos", []) if isinstance(ev.get("dia"), int)]
    duracion_superciclo = max(dias_def) + 1 if dias_def else 0

    raw_inicio = data.get("fecha_inicio")
    if isinstance(raw_inicio, datetime):
        fecha_inicio = raw_inicio.date()
    elif isinstance(raw_inicio, str):
        try:
            fecha_inicio = datetime.fromisoformat(raw_inicio).date()
        except ValueError:
            fecha_inicio = None
    else:
        fecha_inicio = None

    if duracion_superciclo and fecha_inicio:
        dias_transcurridos = (ahora.date() - fecha_inicio).days
        dia_actual = (dias_transcurridos % duracion_superciclo) + 1
        dias_restantes = duracion_superciclo - dia_actual
    else:
        dia_actual = "--"
        dias_restantes = "--"

    return jsonify({
        "superciclo": data.get("superciclo", "--"),
        "estado": estado,
        "proximo": proximo_dt.strftime("%Y-%m-%d %H:%M") if proximo_dt else "--",
        "hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "supercicloDiaActual": dia_actual,
        "supercicloDiasRestantes": dias_restantes
    })


@app.route("/verificar_horarios")
def verificar_horarios():
    """Indica si existe horarios.json, si el ciclo corre y si Tuya está configurado."""
    ruta = os.path.join(JSON_FOLDER, 'horarios.json')
    return jsonify({
        "existe": os.path.isfile(ruta),
        "ejecutando": ciclo_en_ejecucion,
        "tuya_configured": tuya_configured(),
    })


@app.route("/api/config/tuya", methods=["GET", "POST"])
def api_config_tuya():
    """GET: estado de configuración Tuya sin exponer la clave. POST: guarda en config.ini y memoria."""
    global TUYA_ID, TUYA_IP, TUYA_KEY, TUYA_VERSION  # pylint: disable=global-statement

    if request.method == "GET":
        with tuya_lock:
            ver = TUYA_VERSION if TUYA_VERSION is not None else DEFAULT_TUYA_VERSION
            configured = bool(TUYA_ID and TUYA_IP and TUYA_KEY and TUYA_VERSION is not None)
            return jsonify({
                "configured": configured,
                "device_id": TUYA_ID or "",
                "ip": TUYA_IP or "",
                "version": ver,
                "local_key_saved": bool(TUYA_KEY),
            })

    data = request.get_json(force=True, silent=True) or {}
    device_id = (data.get("device_id") or "").strip()
    ip = (data.get("ip") or "").strip()
    local_key = (data.get("local_key") or "").strip()
    ver_raw = data.get("version", str(DEFAULT_TUYA_VERSION))

    try:
        ver = float(ver_raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Versión Tuya inválida."}), 400

    if not device_id or not ip:
        return jsonify({"ok": False, "error": "Completá Device ID e IP."}), 400

    with tuya_lock:
        if not local_key:
            local_key = (TUYA_KEY or "").strip()
    if not local_key:
        return jsonify({"ok": False, "error": "Completá Local Key (o guardá una vez antes para conservar la clave)."}), 400

    cfg = configparser.ConfigParser()
    if os.path.isfile(CONFIG_PATH):
        cfg.read(CONFIG_PATH, encoding="utf-8")
    cfg["tuya"] = {
        "device_id": device_id,
        "device_ip": ip,
        "local_key": local_key,
        "version": str(ver),
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)

    with tuya_lock:
        TUYA_ID, TUYA_IP, TUYA_KEY, TUYA_VERSION = device_id, ip, local_key, ver

    logging.info("Config Tuya guardada en %s", CONFIG_PATH)
    return jsonify({"ok": True})


def make_device(cfg, persist=True, retry_limit=2, retry_delay=1, timeout=5):
    """
    Crea y configura el objeto dispositivo de TinyTuya de forma segura.
    - cfg: dict con keys: device_id, ip, local_key, version
    - persist: si mantener socket abierto (True/False)
    - retry_limit: cantidad de reintentos (set_socketRetryLimit)
    - retry_delay: delay entre reintentos (set_socketRetryDelay)
    - timeout: tiempo de conexión en segundos (set_socketTimeout)
    """
    dev = tinytuya.OutletDevice(
        cfg["device_id"],
        cfg["ip"],
        cfg.get("local_key")
    )
    # versión
    try:
        dev.set_version(float(cfg.get("version", str(DEFAULT_TUYA_VERSION))))
    except (TypeError, ValueError, AttributeError):
        dev.set_version(DEFAULT_TUYA_VERSION)

    # configuración socket / timeouts (nombres correctos)
    try:
        dev.set_socketPersistent(bool(persist))
    except (TypeError, AttributeError):
        pass

    try:
        dev.set_socketRetryLimit(int(retry_limit))
        dev.set_socketRetryDelay(int(retry_delay))
    except (TypeError, ValueError, AttributeError):
        pass

    try:
        dev.set_socketTimeout(float(timeout))
    except (TypeError, ValueError, AttributeError):
        pass

    # opcional: set NODELAY si lo querés
    try:
        dev.set_socketNODELAY(True)
    except (TypeError, AttributeError):
        pass

    # opcional: set_sendWait si necesitás esperar respuesta
    try:
        dev.set_sendWait(0.4)
    except (TypeError, ValueError, AttributeError):
        pass

    return dev


@app.post("/api/tuya/on")
def api_on():
    """Enciende el dispositivo con credenciales enviadas en el cuerpo JSON."""
    cfg = request.get_json(force=True)
    try:
        dev = make_device(cfg)
        result = dev.set_status(True)   # usa set_status (sin dps explícito)
        return jsonify({"ok": True, "result": result})
    except (TypeError, ValueError, KeyError, OSError, ConnectionError, TimeoutError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.post("/api/tuya/off")
def api_off():
    """Apaga el dispositivo con credenciales enviadas en el cuerpo JSON."""
    cfg = request.get_json(force=True)
    try:
        dev = make_device(cfg)
        result = dev.set_status(False)
        return jsonify({"ok": True, "result": result})
    except (TypeError, ValueError, KeyError, OSError, ConnectionError, TimeoutError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def _process_should_autostart_superciclo():
    """True si este proceso debe intentar reanudar el ciclo al importar el módulo."""
    if os.environ.get("SUPERCICLO_NO_AUTOSTART", "").strip().lower() in ("1", "true", "yes"):
        return False
    # Evitar proceso supervisor del reloader de Werkzeug cuando marque explícitamente "false"
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return False
    return True


def try_autostart_superciclo_on_boot():
    """Si existe json/horarios.json válido, reanuda el hilo del ciclo (p. ej. tras reboot)."""
    if not _process_should_autostart_superciclo():
        logging.info("Auto-inicio del superciclo deshabilitado (SUPERCICLO_NO_AUTOSTART) o proceso no apto.")
        return
    ruta = os.path.join(JSON_FOLDER, "horarios.json")
    if not os.path.isfile(ruta):
        return
    data = cargar_horarios()
    if data is None:
        logging.warning("horarios.json existe pero no se pudo cargar; el ciclo no se auto-inicia.")
        return
    result = start_superciclo_from_horarios(data, allow_skip_duplicate=True)
    if result.get("started"):
        logging.info("Superciclo reanudado al iniciar el servidor.")
    elif result.get("ok"):
        logging.info("Superciclo al arranque: %s", result.get("mensaje"))
    else:
        logging.info("Ciclo no auto-iniciado: %s", result.get("mensaje", ""))


try_autostart_superciclo_on_boot()
