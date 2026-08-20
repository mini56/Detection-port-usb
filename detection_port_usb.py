"""
Détection d'adaptateur de diagnostic
--------------------------------------
Deux modes :
  1) USB / Bluetooth : surveille les ports COM pendant 15 secondes
     (un adaptateur Bluetooth apparié apparaît aussi comme un port
     COM sous Windows, via le profil SPP).
  2) WiFi : scanne le réseau local à la recherche d'un adaptateur
     WiFi de type ELM327 (port réseau 35000, standard sur ce type
     de matériel).

Prérequis : pip install pyserial
Lancement : python detection_port_usb.py
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor

try:
    import serial.tools.list_ports as list_ports
except ImportError:
    list_ports = None

DUREE_ATTENTE_COM = 15   # secondes, mode USB/Bluetooth
PORT_WIFI_ELM327 = 35000  # port réseau standard des adaptateurs WiFi type ELM327
TIMEOUT_SCAN_WIFI = 0.3   # secondes par adresse testée

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
    """Retourne l'adresse IP locale de la machine (celle utilisée
    pour sortir sur le réseau), sans envoyer de vraies données."""
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
    """Teste si un hôte répond sur le port ELM327 WiFi standard."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(TIMEOUT_SCAN_WIFI)
            resultat = s.connect_ex((str(ip), PORT_WIFI_ELM327))
            if resultat == 0:
                return str(ip)
    except Exception:
        pass
    return None


def identifier_modele_wifi(ip, port=PORT_WIFI_ELM327, timeout=2.0):
    """Se connecte à l'adaptateur WiFi et envoie la commande AT 'ATI'
    (identification), standard sur les interfaces compatibles ELM327.
    Retourne le texte de réponse brut (ex: 'ELM327 v1.5'), ou None
    si l'adaptateur ne répond pas à cette commande."""
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
        root.geometry("520x400")
        root.resizable(False, False)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.onglet_com = tk.Frame(self.notebook)
        self.onglet_wifi = tk.Frame(self.notebook)
        self.notebook.add(self.onglet_com, text="USB / Bluetooth (port COM)")
        self.notebook.add(self.onglet_wifi, text="WiFi (réseau)")

        self._construire_onglet_com()
        self._construire_onglet_wifi()

        self.detecting_com = False
        if list_ports is None:
            self.label_com.config(
                text="Le module 'pyserial' est requis.\nInstallez-le avec : pip install pyserial",
                fg="red",
            )
        else:
            self.start_detection_com()

    # ---------- Onglet USB / Bluetooth ----------

    def _construire_onglet_com(self):
        self.label_com = tk.Label(
            self.onglet_com,
            text="Brancher votre câble à la prise USB\n(ou appairer votre adaptateur Bluetooth)",
            font=("Segoe UI", 12), wraplength=460, justify="center",
        )
        self.label_com.pack(pady=(20, 5))

        self.puce_label = tk.Label(self.onglet_com, text="", font=("Segoe UI", 10, "bold"), fg="#333333")
        self.puce_label.pack()

        self.countdown_label_com = tk.Label(self.onglet_com, text="", font=("Segoe UI", 10), fg="gray")
        self.countdown_label_com.pack()

        self.debug_label_com = tk.Label(
            self.onglet_com, text="", font=("Consolas", 9), fg="#555555", justify="left", wraplength=460
        )
        self.debug_label_com.pack(pady=(10, 0))

        self.restart_button_com = tk.Button(
            self.onglet_com, text="Recommencer", command=self.start_detection_com, width=16
        )

    def get_ports(self):
        return {p.device: p for p in list_ports.comports()}

    def start_detection_com(self):
        self.restart_button_com.pack_forget()
        self.label_com.config(
            text="Brancher votre câble à la prise USB\n(ou appairer votre adaptateur Bluetooth)",
            fg="black",
        )
        self.puce_label.config(text="")
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
        if device:
            self.label_com.config(text=f"Port détecté : {device}", fg="dark green")
            puce = identifier_puce(info) if info else None
            if puce:
                self.puce_label.config(text=f"Identifié : {puce}", fg="dark green")
            else:
                self.puce_label.config(text="Identification non reconnue (VID/PID inconnu)", fg="#B8860B")
        else:
            self.label_com.config(
                text='Aucun port détecté.\n'
                'Retirez/déconnectez l\'accessoire et cliquez sur "Recommencer".',
                fg="red",
            )
        self.restart_button_com.pack(pady=15)

    # ---------- Onglet WiFi ----------

    def _construire_onglet_wifi(self):
        self.label_wifi = tk.Label(
            self.onglet_wifi,
            text="Connectez-vous d'abord au réseau WiFi de votre adaptateur,\npuis cliquez sur \"Rechercher\".",
            font=("Segoe UI", 12), wraplength=460, justify="center",
        )
        self.label_wifi.pack(pady=(20, 10))

        self.search_button_wifi = tk.Button(
            self.onglet_wifi, text="Rechercher", command=self.start_scan_wifi, width=16
        )
        self.search_button_wifi.pack()

        self.progress_label_wifi = tk.Label(self.onglet_wifi, text="", font=("Segoe UI", 10), fg="gray")
        self.progress_label_wifi.pack(pady=(10, 0))

        self.result_label_wifi = tk.Label(
            self.onglet_wifi, text="", font=("Segoe UI", 11, "bold"), fg="#333333",
            wraplength=460, justify="center",
        )
        self.result_label_wifi.pack(pady=(15, 0))

    def start_scan_wifi(self):
        self.search_button_wifi.config(state="disabled")
        self.result_label_wifi.config(text="")
        self.progress_label_wifi.config(text="Recherche en cours sur le réseau local...")
        threading.Thread(target=self.scan_wifi, daemon=True).start()

    def scan_wifi(self):
        ip_locale = obtenir_ip_locale()
        try:
            reseau = ipaddress.ip_network(ip_locale + "/24", strict=False)
            hotes = list(reseau.hosts())
        except Exception:
            hotes = []

        trouve = None
        with ThreadPoolExecutor(max_workers=64) as executor:
            for resultat in executor.map(tester_adresse_wifi, hotes):
                if resultat:
                    trouve = resultat
                    break

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
            self.result_label_wifi.config(text=texte, fg="dark green")
        else:
            self.result_label_wifi.config(
                text="Aucun adaptateur WiFi détecté sur le réseau.\n"
                f"(Votre PC est actuellement sur : {ip_locale})\n"
                "Vérifiez que vous êtes bien connecté au réseau WiFi\n"
                "créé par l'adaptateur, puis réessayez.",
                fg="red",
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
