"""Tkinter dashboard; refreshes worker snapshots without blocking the GUI."""
import json
import tkinter as tk
from tkinter import ttk, messagebox


def run_dashboard():
    from main import Runner, load_config, pending_tickets
    root = tk.Tk()
    root.title("Air Quality System")
    root.geometry("800x600")
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Air Quality System", font=("Arial", 20)).pack(anchor="w")
    ttk.Label(frame, text="Fan status shows acknowledged output, not measured rotation.").pack(anchor="w")
    missing = pending_tickets()
    if missing:
        ttk.Label(frame, text="Automatic mode pending:\n" + "\n".join(missing),
                  wraplength=750).pack(anchor="w", pady=10)
    holder = {"runner": None, "closing": False}
    display = tk.Text(frame, height=20, wrap="word", state="disabled")

    def show(value):
        display.configure(state="normal")
        display.delete("1.0", "end")
        display.insert("end", value)
        display.configure(state="disabled")

    def action(command):
        try:
            if holder["runner"] is None:
                holder["runner"] = Runner(load_config())
            holder["runner"].command(command)
        except Exception as exc:
            messagebox.showerror("Setup required", str(exc))

    buttons = ttk.Frame(frame)
    buttons.pack(anchor="w", pady=12)
    for label, command in (("Start / Auto", "start"), ("Stop", "stop"),
                           ("Manual ON", "on"), ("Manual OFF", "off"), ("Check ESP32", "check")):
        ttk.Button(buttons, text=label, command=lambda c=command: action(c)).pack(side="left", padx=3)
    display.pack(fill="both", expand=True)
    show("Fill in config.yaml, power the configured ESP32, then check its connection.\n"
         "Manual fan controls work independently of the three HW modules.")

    def refresh():
        if holder["runner"]:
            show(json.dumps(holder["runner"].snapshot(), indent=2))
        if not holder["closing"]:
            root.after(250, refresh)

    def close():
        holder["closing"] = True
        for button in buttons.winfo_children():
            button.configure(state="disabled")
        runner = holder["runner"]
        if not runner:
            root.destroy()
            return
        runner.command("close")
        show("Stopping and requesting fan OFF…")
        def wait(attempt=0):
            if not runner.worker.is_alive():
                root.destroy()
            elif attempt >= 60:
                messagebox.showwarning("Shutdown", "Worker did not finish. ESP32 will turn OFF "
                                       "when its 30-second command lease expires.")
                root.destroy()
            else:
                root.after(100, lambda: wait(attempt + 1))
        wait()

    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()
