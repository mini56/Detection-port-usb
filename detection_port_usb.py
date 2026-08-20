"""
Détection de port USB
----------------------
Affiche une boîte de dialogue demandant de brancher un câble USB,
surveille les ports COM pendant 15 secondes, puis affiche le port
détecté (ex: COM3) ainsi que le modèle de puce identifié (FTDI,
Prolific PL2303, CH340/CH341...), ou un message d'échec avec un
bouton "Recommencer".

Important : seuls les adaptateurs USB-SÉRIE (câble KKL, câble de
diagnostic, puce FTDI/CH340/Prolific, etc.) créent un port COM.
Une clé USB de stockage classique n'en crée pas.

Prérequis : pip install pyserial
Lancement : python detection_port_usb.py
"""

import tkinter as tk
import threading
import time

try:
    import serial.tools.list_ports as list_ports
except ImportError:
    list_ports = None

DUREE_ATTENTE = 15  # secondes

# Correspondance VID:PID -> nom de puce, pour les adaptateurs
# USB-série les plus courants sur les câbles KKL / diagnostic.
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
    """Retourne le nom de la puce identifiée à partir du VID/PID,
    ou une estimation basée sur la description si le VID/PID est
    inconnu, ou None si rien n'est reconnaissable."""
    if port_info.vid is not None and port_info.pid is not None:
        nom = PUCES_CONNUES.get((port_info.vid, port_info.pid))
        if nom:
            return nom
    desc = (port_info.description or "") + " " + (port_info.manufacturer or "")
    desc_low = desc.lower()
    if "ftdi" in desc_low or "ft232" in desc_low:
        return "FTDI (modèle exact non identifié)"
    if "prolific" in desc_low or "pl2303" in desc_low:
        return "Prolific PL2303 (modèle exact non identifié)"
    if "ch340" in desc_low or "ch341" in desc_low or "wch" in desc_low:
        return "CH340/CH341 (modèle exact non identifié)"
    if "cp210" in desc_low or "silicon labs" in desc_low:
        return "Silicon Labs CP210x"
    return None


class App:
    def __init__(self, root):
        self.root = root
        root.title("Détection du port USB")
        root.geometry("480x320")
        root.resizable(False, False)

        self.label = tk.Label(
            root,
            text="Brancher votre câble à la prise USB",
            font=("Segoe UI", 13),
            wraplength=440,
            justify="center",
        )
        self.label.pack(expand=True, pady=(25, 5))

        self.puce_label = tk.Label(
            root, text="", font=("Segoe UI", 10, "bold"), fg="#333333"
        )
        self.puce_label.pack()

        self.countdown_label = tk.Label(root, text="", font=("Segoe UI", 10), fg="gray")
        self.countdown_label.pack()

        self.debug_label = tk.Label(
            root, text="", font=("Consolas", 9), fg="#555555", justify="left", wraplength=440
        )
        self.debug_label.pack(pady=(10, 0))

        self.restart_button = tk.Button(
            root, text="Recommencer", command=self.start_detection, width=16
        )

        self.detecting = False

        if list_ports is None:
            self.label.config(
                text="Le module 'pyserial' est requis.\n"
                "Installez-le avec : pip install pyserial",
                fg="red",
            )
        else:
            self.start_detection()

    def get_ports(self):
        return {p.device: p for p in list_ports.comports()}

    def start_detection(self):
        self.restart_button.pack_forget()
        self.label.config(text="Brancher votre câble à la prise USB", fg="black")
        self.puce_label.config(text="")
        self.detecting = True
        self.initial_ports = self.get_ports()
        self.seconds_left = DUREE_ATTENTE
        noms = sorted(self.initial_ports.keys())
        self.debug_label.config(
            text="Ports COM présents au départ : " + (", ".join(noms) if noms else "aucun")
        )
        threading.Thread(target=self.monitor, daemon=True).start()
        self.update_countdown()

    def update_countdown(self):
        if not self.detecting:
            return
        self.countdown_label.config(text=f"Temps restant : {self.seconds_left}s")
        if self.seconds_left > 0:
            self.seconds_left -= 1
            self.root.after(1000, self.update_countdown)

    def monitor(self):
        deadline = time.time() + DUREE_ATTENTE
        found_device = None
        found_info = None
        last_seen = set(self.initial_ports.keys())
        while time.time() < deadline:
            current = self.get_ports()
            current_names = set(current.keys())
            if current_names != last_seen:
                last_seen = current_names
                noms = sorted(current_names)
                self.root.after(0, lambda n=noms: self.debug_label.config(
                    text="Ports COM actuels : " + (", ".join(n) if n else "aucun")
                ))
            nouveaux = current_names - set(self.initial_ports.keys())
            if nouveaux:
                found_device = sorted(nouveaux)[0]
                found_info = current[found_device]
                break
            time.sleep(0.3)
        self.detecting = False
        self.root.after(0, lambda: self.show_result(found_device, found_info))

    def show_result(self, device, info):
        self.countdown_label.config(text="")
        if device:
            self.label.config(text=f"Port détecté : {device}", fg="dark green")
            puce = identifier_puce(info) if info else None
            if puce:
                self.puce_label.config(text=f"Puce identifiée : {puce}", fg="dark green")
            else:
                self.puce_label.config(
                    text="Puce non identifiée (VID/PID inconnu)", fg="#B8860B"
                )
        else:
            self.label.config(
                text='Aucun port détecté.\n'
                'Retirez l\'accessoire de la prise USB et cliquez sur "Recommencer".\n'
                '(Rappel : seul un adaptateur USB-série crée un port COM,\n'
                'pas une clé USB de stockage.)',
                fg="red",
            )
        self.restart_button.pack(pady=15)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
