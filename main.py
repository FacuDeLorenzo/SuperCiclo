import os
import sys
import threading
import time
from pathlib import Path

# config.ini / json/ / logs de app.py usan rutas relativas al cwd
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

import webview
import pystray
from PIL import Image, ImageDraw

from app import app

try:
    import pythoncom
    from win32com.client import Dispatch
except ImportError:
    pythoncom = None
    Dispatch = None

# -------------------------
# Variables globales
# -------------------------
window_visible = True
start_with_windows = False  # se actualizará al iniciar

# -------------------------
# Flask
# -------------------------
def start_flask():
    app.run(port=8001, debug=False, use_reloader=False)

# -------------------------
# Icono de tray
# -------------------------
def create_image():
    for name in ("static/img/trayicon.png", "static/img/trayicon.ico", "trayicon.ico"):
        p = ROOT / name
        if p.is_file():
            return Image.open(p)
    width = height = 64
    background = (30, 120, 60)
    foreground = (0, 0, 0)
    image = Image.new('RGB', (width, height), background)
    dc = ImageDraw.Draw(image)
    size = int(width * 0.8)
    offset = (width - size) // 2
    dc.rectangle((offset, offset, width - offset, height - offset), fill=foreground)
    return image

# -------------------------
# Mostrar/Ocultar ventana
# -------------------------
def show_window(icon=None, item=None):
    global window_visible
    if window and not window_visible:
        window.show()
        window.restore()
        window_visible = True

def hide_window(icon=None, item=None):
    global window_visible
    if window and window_visible:
        window.hide()
        window_visible = False

def on_minimize():
    hide_window()

# -------------------------
# Salir
# -------------------------
def quit_app(icon=None, item=None):
    if window:
        window.destroy()
    if icon:
        icon.stop()
    sys.exit(0)

# -------------------------
# Iniciar con Windows
# -------------------------
def startup_shortcut_path():
    startup_dir = Path(os.getenv('APPDATA')) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup_dir / "SuperCiclo.lnk"

def set_startup(enable=True):
    """
    Habilita o deshabilita el inicio automático de la app con Windows.
    """
    global start_with_windows
    shortcut_path = startup_shortcut_path()
    exe_path = Path(sys.argv[0]).resolve()  # apunta al script o exe

    try:
        if enable:
            if not pythoncom or not Dispatch:
                print("pywin32 no instalado")
                return
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(str(shortcut_path))
            shortcut.Targetpath = str(exe_path)
            shortcut.WorkingDirectory = str(exe_path.parent)
            shortcut.IconLocation = str(exe_path)
            shortcut.save()
            start_with_windows = True
        else:
            if shortcut_path.exists():
                shortcut_path.unlink()
            start_with_windows = False
    except Exception as e:
        print(f"No se pudo modificar inicio con Windows: {e}")
        start_with_windows = False

def toggle_startup(icon, item):
    """Se activa al click en menu. Actualiza check visual."""
    set_startup(not start_with_windows)
    icon.update_menu()  # fuerza actualización del menú para que se vea el check

def check_startup_status():
    """Al iniciar la app, detecta si el shortcut ya existe"""
    global start_with_windows
    shortcut_path = startup_shortcut_path()
    start_with_windows = shortcut_path.exists()

# -------------------------
# Tray
# -------------------------
def tray():
    check_startup_status()  # revisar estado al inicio

    image = create_image()
    image_with_alpha = image.convert('RGBA')

    menu = pystray.Menu(
        pystray.MenuItem('Mostrar', show_window),
        pystray.MenuItem('Ocultar', hide_window),
        pystray.MenuItem('Iniciar con Windows', toggle_startup, checked=lambda item: start_with_windows),
        pystray.MenuItem('Salir', quit_app)
    )

    icon = pystray.Icon(
        "superciclo",
        image_with_alpha,
        "SuperCiclo - supercannabis.ar",
        menu
    )

    try:
        icon.run()
    except KeyboardInterrupt:
        quit_app()

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    if sys.platform != "win32":
        print("main.py es solo para Windows (ventana + bandeja).")
        print("En Raspberry Pi / Linux: activá el venv, luego:")
        print("  export FLASK_APP=app:app && flask run --host=0.0.0.0 --port 8001")
        print("Abrí http://127.0.0.1:8001/ en el navegador (o usá el servicio systemd del README).")
        sys.exit(1)

    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)

    window = webview.create_window(
        "SuperCiclo by h4ch3 - supercannabis.ar",
        "http://127.0.0.1:8001",
        width=1230,
        height=850,
        resizable=True
    )
    window.events.minimized += on_minimize

    tray_thread = threading.Thread(target=tray, daemon=True)
    tray_thread.start()

    webview.start()
