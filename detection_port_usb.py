"""
Détection d'adaptateur de diagnostic
--------------------------------------
Deux modes :
  1) USB / Bluetooth : surveille les ports COM pendant 15 secondes.
  2) WiFi : scanne le réseau local à la recherche d'un adaptateur
     WiFi type ELM327 (port réseau 35000) et identifie son modèle.

Prérequis : pip install pyserial
Lancement : python detection_port_usb.py
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import serial.tools.list_ports as list_ports
except ImportError:
    list_ports = None

DUREE_ATTENTE_COM = 15
PORT_WIFI_ELM327 = 35000
TIMEOUT_SCAN_WIFI = 0.3

# ---------- Thème visuel ----------
COULEUR_FOND = "#0a0a0a"
COULEUR_FOND_CARTE = "#141414"
COULEUR_TEXTE = "#FFFFFF"
COULEUR_TEXTE_SECONDAIRE = "#B0B0B0"
COULEUR_ACCENT = "#FF8C00"
COULEUR_OK = "#4CD964"
COULEUR_ERREUR = "#FF5C5C"
POLICE_TITRE = ("Segoe UI Semibold", 15)
POLICE_TEXTE = ("Segoe UI", 11)
POLICE_RESULTAT = ("Segoe UI Semibold", 12)
POLICE_MONO = ("Consolas", 9)

PUCES_CONNUES = {
    (0x0403, 0x6001): "FTDI FT232",
    (0x0403, 0x6015): "FTDI FT230X",
    (0x0403, 0x6014): "FTDI FT232H",
    (0x0403, 0x6010): "FTDI FT2232",
    (0x067B, 0x2303): "Prolific PL2303",
    (0x1A86, 0x7523): "CH340",
    (0x1A86, 0x5523): "CH341",
    (0x10C4, 0xEA60): "Silicon Labs CP210x",
}


def identifier_puce(port_info):
    if port_info.vid is not None and port_info.pid is not None:
        nom = PUCES_CONNUES.get((port_info.vid, port_info.pid))
        if nom:
            return nom
    desc = (port_info.description or "") + " " + (port_info.manufacturer or "")
    desc_low = desc.lower()
    if "bluetooth" in desc_low:
        return "Liaison Bluetooth (SPP)"
    if "ftdi" in desc_low or "ft232" in desc_low:
        return "FTDI (modèle exact non identifié)"
    if "prolific" in desc_low or "pl2303" in desc_low:
        return "Prolific PL2303 (modèle exact non identifié)"
    if "ch340" in desc_low or "ch341" in desc_low or "wch" in desc_low:
        return "CH340/CH341 (modèle exact non identifié)"
    if "cp210" in desc_low or "silicon labs" in desc_low:
        return "Silicon Labs CP210x"
    return None


def obtenir_ip_locale():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def tester_adresse_wifi(ip):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(TIMEOUT_SCAN_WIFI)
            if s.connect_ex((str(ip), PORT_WIFI_ELM327)) == 0:
                return str(ip)
    except Exception:
        pass
    return None


def identifier_modele_wifi(ip, port=PORT_WIFI_ELM327, timeout=2.0):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((str(ip), port))
            s.sendall(b"ATI\r")
            reponse = b""
            fin = time.time() + timeout
            while time.time() < fin:
                try:
                    morceau = s.recv(256)
                except socket.timeout:
                    break
                if not morceau:
                    break
                reponse += morceau
                if b">" in reponse:
                    break
            texte = reponse.decode(errors="ignore").replace("\r", " ").replace(">", "").strip()
            return texte if texte else None
    except Exception:
        return None


class App:
    def __init__(self, root):
        self.root = root
        root.title("Détection d'adaptateur de diagnostic")
        root.geometry("540x420")
        root.resizable(False, False)
        root.configure(bg=COULEUR_FOND)

        self._configurer_style()

        self.notebook = ttk.Notebook(root, style="Sombre.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=14, pady=14)

        self.onglet_com = tk.Frame(self.notebook, bg=COULEUR_FOND_CARTE)
        self.onglet_wifi = tk.Frame(self.notebook, bg=COULEUR_FOND_CARTE)
        self.notebook.add(self.onglet_com, text="  USB / Bluetooth  ")
        self.notebook.add(self.onglet_wifi, text="  WiFi  ")

        self._construire_onglet_com()
        self._construire_onglet_wifi()

        self.detecting_com = False
        if list_ports is None:
            self.label_com.config(
                text="Le module 'pyserial' est requis.\nInstallez-le avec : pip install pyserial",
                fg=COULEUR_ERREUR,
            )
        else:
            self.start_detection_com()

    def _configurer_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Sombre.TNotebook", background=COULEUR_FOND, borderwidth=0
        )
        style.configure(
            "Sombre.TNotebook.Tab",
            background=COULEUR_FOND_CARTE,
            foreground=COULEUR_TEXTE_SECONDAIRE,
            font=("Segoe UI Semibold", 10),
            padding=(14, 8),
            borderwidth=0,
        )
        style.map(
            "Sombre.TNotebook.Tab",
            background=[("selected", COULEUR_ACCENT)],
            foreground=[("selected", "#1a1200")],
        )

        style.configure(
            "Orange.Horizontal.TProgressbar",
            troughcolor=COULEUR_FOND,
            background=COULEUR_ACCENT,
            bordercolor=COULEUR_FOND,
            lightcolor=COULEUR_ACCENT,
            darkcolor=COULEUR_ACCENT,
            thickness=16,
        )

    # ---------- Onglet USB / Bluetooth ----------

    def _construire_onglet_com(self):
        cadre = self.onglet_com

        self.label_com = tk.Label(
            cadre,
            text="Branchez votre câble à la prise USB\n(ou appairez votre adaptateur Bluetooth)",
            font=POLICE_TITRE, fg=COULEUR_TEXTE, bg=COULEUR_FOND_CARTE,
            wraplength=460, justify="center",
        )
        self.label_com.pack(pady=(26, 14))

        self.progress_com = ttk.Progressbar(
            cadre, style="Orange.Horizontal.TProgressbar",
            orient="horizontal", mode="determinate",
            maximum=DUREE_ATTENTE_COM, length=420,
        )
        self.progress_com.pack(pady=(0, 8))

        self.countdown_label_com = tk.Label(
            cadre, text="", font=POLICE_TEXTE, fg=COULEUR_TEXTE_SECONDAIRE, bg=COULEUR_FOND_CARTE
        )
        self.countdown_label_com.pack()

        self.puce_label = tk.Label(
            cadre, text="", font=POLICE_RESULTAT, fg=COULEUR_TEXTE, bg=COULEUR_FOND_CARTE
        )
        self.puce_label.pack(pady=(16, 0))

        self.debug_label_com = tk.Label(
            cadre, text="", font=POLICE_MONO, fg=COULEUR_TEXTE_SECONDAIRE, bg=COULEUR_FOND_CARTE,
            justify="left", wraplength=460,
        )
        self.debug_label_com.pack(pady=(14, 0))

        self.restart_button_com = tk.Button(
            cadre, text="Recommencer", command=self.start_detection_com, width=18,
            bg=COULEUR_ACCENT, fg="#1a1200", activebackground="#FFA733",
            activeforeground="#1a1200", relief="flat", font=("Segoe UI Semibold", 10),
            cursor="hand2",
        )

    def get_ports(self):
        return {p.device: p for p in list_ports.comports()}

    def start_detection_com(self):
        self.restart_button_com.pack_forget()
        self.label_com.config(
            text="Branchez votre câble à la prise USB\n(ou appairez votre adaptateur Bluetooth)",
            fg=COULEUR_TEXTE,
        )
        self.puce_label.config(text="")
        self.progress_com["value"] = 0
        self.detecting_com = True
        self.initial_ports = self.get_ports()
        self.seconds_left = DUREE_ATTENTE_COM
        noms = sorted(self.initial_ports.keys())
        self.debug_label_com.config(
            text="Ports COM présents au départ : " + (", ".join(noms) if noms else "aucun")
        )
        threading.Thread(target=self.monitor_com, daemon=True).start()
        self.update_countdown_com()

    def update_countdown_com(self):
        if not self.detecting_com:
            return
        self.countdown_label_com.config(text=f"Temps restant : {self.seconds_left}s")
        self.progress_com["value"] = DUREE_ATTENTE_COM - self.seconds_left
        if self.seconds_left > 0:
            self.seconds_left -= 1
            self.root.after(1000, self.update_countdown_com)

    def monitor_com(self):
        deadline = time.time() + DUREE_ATTENTE_COM
        found_device, found_info = None, None
        last_seen = set(self.initial_ports.keys())
        while time.time() < deadline:
            current = self.get_ports()
            current_names = set(current.keys())
            if current_names != last_seen:
                last_seen = current_names
                noms = sorted(current_names)
                self.root.after(0, lambda n=noms: self.debug_label_com.config(
                    text="Ports COM actuels : " + (", ".join(n) if n else "aucun")
                ))
            nouveaux = current_names - set(self.initial_ports.keys())
            if nouveaux:
                found_device = sorted(nouveaux)[0]
                found_info = current[found_device]
                break
            time.sleep(0.3)
        self.detecting_com = False
        self.root.after(0, lambda: self.show_result_com(found_device, found_info))

    def show_result_com(self, device, info):
        self.countdown_label_com.config(text="")
        self.progress_com["value"] = DUREE_ATTENTE_COM
        if device:
            self.label_com.config(text=f"Port détecté : {device}", fg=COULEUR_OK)
            puce = identifier_puce(info) if info else None
            if puce:
                self.puce_label.config(text=f"Identifié : {puce}", fg=COULEUR_OK)
            else:
                self.puce_label.config(text="Identification non reconnue (VID/PID inconnu)", fg=COULEUR_ACCENT)
        else:
            self.label_com.config(
                text='Aucun port détecté.\n'
                'Retirez/déconnectez l\'accessoire et cliquez sur "Recommencer".',
                fg=COULEUR_ERREUR,
            )
        self.restart_button_com.pack(pady=18)

    # ---------- Onglet WiFi ----------

    def _construire_onglet_wifi(self):
        cadre = self.onglet_wifi

        self.label_wifi = tk.Label(
            cadre,
            text="Connectez-vous d'abord au réseau WiFi de votre adaptateur,\npuis cliquez sur \"Rechercher\".",
            font=POLICE_TITRE, fg=COULEUR_TEXTE, bg=COULEUR_FOND_CARTE,
            wraplength=460, justify="center",
        )
        self.label_wifi.pack(pady=(26, 16))

        self.search_button_wifi = tk.Button(
            cadre, text="Rechercher", command=self.start_scan_wifi, width=18,
            bg=COULEUR_ACCENT, fg="#1a1200", activebackground="#FFA733",
            activeforeground="#1a1200", relief="flat", font=("Segoe UI Semibold", 10),
            cursor="hand2",
        )
        self.search_button_wifi.pack()

        self.progress_wifi = ttk.Progressbar(
            cadre, style="Orange.Horizontal.TProgressbar",
            orient="horizontal", mode="determinate",
            maximum=100, length=420,
        )
        self.progress_wifi.pack(pady=(20, 8))

        self.progress_label_wifi = tk.Label(
            cadre, text="", font=POLICE_TEXTE, fg=COULEUR_TEXTE_SECONDAIRE, bg=COULEUR_FOND_CARTE
        )
        self.progress_label_wifi.pack()

        self.result_label_wifi = tk.Label(
            cadre, text="", font=POLICE_RESULTAT, fg=COULEUR_TEXTE, bg=COULEUR_FOND_CARTE,
            wraplength=460, justify="center",
        )
        self.result_label_wifi.pack(pady=(18, 0))

    def start_scan_wifi(self):
        self.search_button_wifi.config(state="disabled")
        self.result_label_wifi.config(text="")
        self.progress_wifi["value"] = 0
        self.progress_label_wifi.config(text="Recherche en cours sur le réseau local...")
        threading.Thread(target=self.scan_wifi, daemon=True).start()

    def scan_wifi(self):
        ip_locale = obtenir_ip_locale()
        try:
            reseau = ipaddress.ip_network(ip_locale + "/24", strict=False)
            hotes = list(reseau.hosts())
        except Exception:
            hotes = []

        total = max(len(hotes), 1)
        trouve = None
        termines = 0

        with ThreadPoolExecutor(max_workers=64) as executor:
            futures = {executor.submit(tester_adresse_wifi, h): h for h in hotes}
            for future in as_completed(futures):
                termines += 1
                pourcentage = (termines / total) * 100
                self.root.after(0, lambda p=pourcentage: self.progress_wifi.config(value=p))
                resultat = future.result()
                if resultat and not trouve:
                    trouve = resultat

        modele = None
        if trouve:
            self.root.after(0, lambda: self.progress_label_wifi.config(
                text="Adaptateur trouvé, identification du modèle..."
            ))
            modele = identifier_modele_wifi(trouve)

        self.root.after(0, lambda: self.show_result_wifi(trouve, ip_locale, modele))

    def show_result_wifi(self, ip_trouvee, ip_locale, modele):
        self.progress_label_wifi.config(text="")
        self.search_button_wifi.config(state="normal")
        if ip_trouvee:
            texte = f"Adaptateur WiFi détecté : {ip_trouvee}:{PORT_WIFI_ELM327}"
            if modele:
                texte += f"\nModèle identifié : {modele}"
            else:
                texte += "\nModèle non identifié (pas de réponse à la commande ATI)"
            self.result_label_wifi.config(text=texte, fg=COULEUR_OK)
        else:
            self.result_label_wifi.config(
                text="Aucun adaptateur WiFi détecté sur le réseau.\n"
                f"(Votre PC est actuellement sur : {ip_locale})\n"
                "Vérifiez que vous êtes bien connecté au réseau WiFi\n"
                "créé par l'adaptateur, puis réessayez.",
                fg=COULEUR_ERREUR,
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
