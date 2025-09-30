import logging
from flask import Flask, request, jsonify, render_template, send_from_directory
from datetime import datetime, timedelta
import os
import json
import threading
import tinytuya
import time
import configparser
import platform
import subprocess

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
    return send_from_directory(app.static_folder, 'favicon.ico')


CONFIG_PATH = "config.ini"
cfg = configparser.ConfigParser()

if not os.path.isfile(CONFIG_PATH):
    logging.error(f"No se encontró el archivo de configuración: {CONFIG_PATH}")
    raise FileNotFoundError(f"[ERROR] No se encontró el archivo de configuración: {CONFIG_PATH}")

cfg.read(CONFIG_PATH, encoding="utf-8")

if not cfg.has_section("tuya"):
    logging.error(f"El archivo {CONFIG_PATH} no contiene la sección [tuya]")
    raise ValueError(f"[ERROR] El archivo {CONFIG_PATH} no contiene la sección [tuya]")

TUYA_ID = cfg.get("tuya", "device_id")
TUYA_IP = cfg.get("tuya", "device_ip")
TUYA_KEY = cfg.get("tuya", "local_key")
TUYA_VERSION = cfg.getfloat("tuya", "version")

JSON_FOLDER = "json"
os.makedirs(JSON_FOLDER, exist_ok=True)

estado_actual = {"estado": "desconocido", "proximo": "", "hora": ""}
ciclo_en_ejecucion = False
ciclo_thread = None
horarios_actuales = None


@app.route("/")
@app.route("/ciclo")
def ciclo():
    return render_template("ciclo.html")


@app.route("/guardar-json", methods=["POST"])
def guardar_json():
    try:
        data = request.get_json()
        eventos = data.get("eventos")
        superciclo = data.get("superciclo")
        fecha_inicio = data.get("fecha_inicio")

        if not (eventos and superciclo and fecha_inicio):
            return jsonify({"success": False, "message": "Datos incompletos."})

        ruta = os.path.join(JSON_FOLDER, "horarios.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({
                "eventos": eventos,
                "superciclo": superciclo,
                "fecha_inicio": fecha_inicio
            }, f, ensure_ascii=False, indent=2)

        logging.info("Archivo horarios.json guardado correctamente.")
        return jsonify({"success": True})
    except Exception as e:
        logging.exception("Error al guardar el archivo JSON")
        return jsonify({"success": False, "message": str(e)})


def cargar_horarios():
    ruta = os.path.join(JSON_FOLDER, "horarios.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            data = json.load(f)
            if "fecha_inicio" in data:
                data["fecha_inicio"] = datetime.fromisoformat(data["fecha_inicio"])
            return data
    except Exception as e:
        logging.exception("Error al cargar horarios.json")
        return None


def construir_eventos_abs(data, ahora):
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
    global estado_actual, ciclo_en_ejecucion
    ciclo_en_ejecucion = True

    enchufe = tinytuya.OutletDevice(TUYA_ID, TUYA_IP, TUYA_KEY)
    enchufe.set_version(TUYA_VERSION)

    estado_previo = None
    logging.info("Iniciando ejecución de superciclo...")

    while ciclo_en_ejecucion:
        ahora = datetime.now()
        accion_actual, proximo_dt = calcular_estado_y_proximo(data, ahora)

        if accion_actual != estado_previo:
            estado_previo = accion_actual
            try:
                if accion_actual == "on":
                    enchufe.turn_on()
                    logging.info("Enchufe encendido")
                else:
                    enchufe.turn_off()
                    logging.info("Enchufe apagado")
            except Exception as e:
                logging.exception("Error controlando el enchufe")

        estado_actual.update(
            estado=accion_actual,
            proximo=proximo_dt.strftime("%Y-%m-%d %H:%M"),
            hora=ahora.strftime("%Y-%m-%d %H:%M:%S")
        )
        time.sleep(30)

    ciclo_en_ejecucion = False
    logging.info("Ciclo detenido.")


@app.route("/iniciar_ciclo", methods=["POST"])
def iniciar_ciclo():
    global ciclo_en_ejecucion, ciclo_thread, horarios_actuales

    nuevos_horarios = cargar_horarios()
    if nuevos_horarios is None:
        logging.error("No se pudo cargar horarios.json")
        return jsonify({"mensaje": "No se pudo cargar horarios.json"})

    if ciclo_en_ejecucion and nuevos_horarios == horarios_actuales:
        return jsonify({"mensaje": "SuperCiclo ya generado y ejecutado..."})

    if ciclo_en_ejecucion:
        ciclo_en_ejecucion = False
        time.sleep(1)

    horarios_actuales = nuevos_horarios

    ahora = datetime.now()
    estado, proximo_dt = calcular_estado_y_proximo(nuevos_horarios, ahora)

    dias_def = [e.get("dia") for e in nuevos_horarios.get("eventos", []) if isinstance(e.get("dia"), int)]
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
        f"""Info SuperCiclo...
    SuperCiclo: {nuevos_horarios.get('superciclo', '--')}
    Día: {dia_actual}
    Días restantes: {dias_restantes}
    Estado actual: {estado.upper()}
    Próximo estado: {proximo_dt.strftime('%Y-%m-%d %H:%M') if proximo_dt else '--'}
    Hora: {ahora.strftime('%Y-%m-%d %H:%M:%S')}
    """
    )

    ciclo_thread = threading.Thread(target=superciclo, args=(nuevos_horarios,))
    ciclo_thread.daemon = True
    ciclo_thread.start()

    return jsonify({"mensaje": "Nuevo SuperCiclo ejecutado..."})


def calcular_estado_y_proximo(data, ahora):
    eventos = construir_eventos_abs(data, ahora)

    estado_actual = None
    proximo_evento = None

    for i, (accion, dt) in enumerate(eventos):
        if dt > ahora:
            estado_actual = eventos[i - 1][0] if i > 0 else eventos[-1][0]
            proximo_evento = dt
            break
    else:
        estado_actual = eventos[-1][0]
        proximo_evento = eventos[0][1] + timedelta(days=7)

    return estado_actual, proximo_evento


@app.route("/estado_ciclo")
def estado_ciclo():
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

    dias_def = [e.get("dia") for e in data.get("eventos", []) if isinstance(e.get("dia"), int)]
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
    ruta = os.path.join(JSON_FOLDER, 'horarios.json')
    return jsonify({"existe": os.path.isfile(ruta), "ejecutando": ciclo_en_ejecucion})


@app.route("/config-ini", methods=["POST"])
def abrir_config_ini():
    try:
        if platform.system() == "Windows":
            os.startfile(CONFIG_PATH)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", CONFIG_PATH])
        else:
            subprocess.Popen(["xdg-open", CONFIG_PATH])
        logging.info("Archivo config.ini abierto.")
        return jsonify(ok=True)
    except Exception as e:
        logging.exception("Error al abrir config.ini")
        return jsonify(ok=False, error=str(e)), 500


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
        dev.set_version(float(cfg.get("version", "3.3")))
    except Exception:
        dev.set_version(3.3)

    # configuración socket / timeouts (nombres correctos)
    try:
        dev.set_socketPersistent(bool(persist))
    except Exception:

        pass

    try:
        dev.set_socketRetryLimit(int(retry_limit))
        dev.set_socketRetryDelay(int(retry_delay))
    except Exception:
        pass

    try:
        dev.set_socketTimeout(float(timeout))
    except Exception:
        pass

    # opcional: set NODELAY si lo querés
    try:
        dev.set_socketNODELAY(True)
    except Exception:
        pass

    # opcional: set_sendWait si necesitás esperar respuesta
    try:
        dev.set_sendWait(0.4)
    except Exception:
        pass

    return dev


@app.post("/api/tuya/on")
def api_on():
    cfg = request.get_json(force=True)
    try:
        dev = make_device(cfg)
        result = dev.set_status(True)   # usa set_status (sin dps explícito)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/tuya/off")
def api_off():
    cfg = request.get_json(force=True)
    try:
        dev = make_device(cfg)
        result = dev.set_status(False)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500