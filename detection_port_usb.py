"""
Détection de port USB
----------------------
Affiche une boîte de dialogue demandant de brancher un câble USB,
surveille les ports COM pendant 10 secondes, puis affiche le port
détecté (ex: COM3) ou un message d'échec avec un bouton "Recommencer".

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

DUREE_ATTENTE = 10  # secondes


class App:
    def __init__(self, root):
        self.root = root
        root.title("Détection du port USB")
        root.geometry("440x230")
        root.resizable(False, False)

        self.label = tk.Label(
            root,
            text="Brancher votre câble à la prise USB",
            font=("Segoe UI", 13),
            wraplength=400,
            justify="center",
        )
        self.label.pack(expand=True, pady=(30, 10))

        self.countdown_label = tk.Label(root, text="", font=("Segoe UI", 10), fg="gray")
        self.countdown_label.pack()

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
        return set(p.device for p in list_ports.comports())

    def start_detection(self):
        self.restart_button.pack_forget()
        self.label.config(text="Brancher votre câble à la prise USB", fg="black")
        self.detecting = True
        self.initial_ports = self.get_ports()
        self.seconds_left = DUREE_ATTENTE
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
        found_port = None
        while time.time() < deadline:
            current = self.get_ports()
            new_ports = current - self.initial_ports
            if new_ports:
                found_port = sorted(new_ports)[0]
                break
            time.sleep(0.3)
        self.detecting = False
        self.root.after(0, lambda: self.show_result(found_port))

    def show_result(self, port):
        self.countdown_label.config(text="")
        if port:
            self.label.config(text=f"Port détecté : {port}", fg="dark green")
        else:
            self.label.config(
                text='Aucun port détecté.\n'
                'Retirez l\'accessoire de la prise USB et cliquez sur "Recommencer".',
                fg="red",
            )
        self.restart_button.pack(pady=15)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
