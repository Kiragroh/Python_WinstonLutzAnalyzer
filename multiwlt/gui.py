"""Portable desktop interface for the CT-referenced MultiWLT evaluator."""
from pathlib import Path
import argparse
import json
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

VERSION = '0.2.0'


def analyse(images, profile, records, output, positioned):
    # Import lazily so a missing optional runtime component is shown in the GUI.
    from routine_registered import analyse_registered_folder
    if not positioned:
        raise ValueError('Confirm image-guided positioning to the reference CT pose.')
    if not Path(images).is_dir():
        raise ValueError('Select an MV image folder.')
    if not Path(profile).is_file():
        raise ValueError('Select the matching reference.json file beside its RTPLAN.')
    if not output.strip():
        raise ValueError('Select an output folder.')
    if records and not Path(records).is_dir():
        raise ValueError('The selected delivery-record folder does not exist.')
    return analyse_registered_folder(images, profile, output,
                                     positioned_in_ct=positioned,
                                     records_folder=records or None)


class MultiWLTApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'MultiWLT {VERSION} | CT-referenced analysis')
        self.geometry('1000x790')
        self.minsize(820, 680)
        self.events = queue.Queue()
        self.busy = False
        self.result = None
        self.error = None
        self.preview = None
        self.paths = {key: tk.StringVar() for key in ('images', 'profile', 'records', 'output')}
        self.positioned = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Select images and their matching CT/plan reference.')
        self.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(self, padding=22)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text='MultiWLT · expected versus observed', font=('Segoe UI', 20, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(frame, text='Extra displacement = measured ball–field vector − expected CT/plan vector', font=('Segoe UI', 11)).grid(row=1, column=0, columnspan=3, sticky='w', pady=(6, 18))
        self.inputs = []
        for row, (key, label) in enumerate((('images', 'MV image folder'), ('profile', 'Reference profile (.json)'), ('records', 'Delivery records (if required)'), ('output', 'Output folder')), 2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=5)
            entry = ttk.Entry(frame, textvariable=self.paths[key])
            entry.grid(row=row, column=1, sticky='ew', pady=5)
            button = ttk.Button(frame, text='Browse…', command=lambda k=key: self.browse(k))
            button.grid(row=row, column=2, padx=(8, 0), pady=5)
            self.inputs.extend((entry, button))
        ttk.Label(frame, text='Initial Leipzig dataset: choose MV, RT/reference.json and Records. Keep the reference JSON beside its plan DICOM.', wraplength=920).grid(row=6, column=0, columnspan=3, sticky='w', pady=(6, 12))
        confirm = ttk.Checkbutton(frame, text='I confirm image-guided positioning to the reference CT pose for these images.', variable=self.positioned)
        confirm.grid(row=7, column=0, columnspan=3, sticky='w')
        self.inputs.append(confirm)
        self.run_button = ttk.Button(frame, text='Analyse and create PDF / CSV / JSON', command=self.run)
        self.run_button.grid(row=8, column=0, columnspan=3, sticky='ew', pady=14)
        ttk.Label(frame, textvariable=self.status, font=('Segoe UI', 11, 'bold'), wraplength=920).grid(row=9, column=0, columnspan=3, sticky='w')
        self.details = tk.Text(frame, height=6, wrap='word', font=('Segoe UI', 10), relief='flat')
        self.details.grid(row=10, column=0, columnspan=3, sticky='ew', pady=8)
        self.details.configure(state='disabled')
        self.image_label = ttk.Label(frame, anchor='center')
        self.image_label.grid(row=11, column=0, columnspan=3, sticky='nsew')
        frame.rowconfigure(11, weight=1)
        ttk.Label(frame, text='Research evaluation. No automatic clinical pass/fail. Review detected centres and method flags in the PDF.', wraplength=920).grid(row=12, column=0, columnspan=3, sticky='w', pady=(8, 0))
        self.after(100, self.poll)

    def browse(self, key):
        if key == 'profile':
            value = filedialog.askopenfilename(parent=self, title='Matching reference profile', filetypes=[('Reference JSON', '*.json')])
        else:
            value = filedialog.askdirectory(parent=self, title=key.capitalize(), mustexist=key != 'output')
        if value:
            self.paths[key].set(value)

    def set_details(self, text):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def run(self):
        if self.busy:
            return
        values = {k: v.get().strip() for k, v in self.paths.items()}
        positioned = self.positioned.get()
        self.result = self.error = None
        self.preview = None
        self.image_label.configure(image='')
        self.busy = True
        for widget in self.inputs + [self.run_button]:
            widget.configure(state='disabled')
        self.status.set('Analysing images and writing report…')
        self.set_details('Inputs are read only. Each successful run writes a new timestamped result folder.')

        def worker():
            try:
                self.events.put(('result', analyse(**values, positioned=positioned)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            kind, value = self.events.get_nowait()
        except queue.Empty:
            self.after(100, self.poll)
            return
        self.busy = False
        for widget in self.inputs + [self.run_button]:
            widget.configure(state='normal')
        if kind == 'error':
            self.error = value
            self.status.set('Analysis not completed')
            self.set_details(value)
        else:
            self.result = value
            maximum = value.get('max_extra_mm')
            metric = f'{maximum:.3f} mm' if maximum is not None else 'unavailable'
            self.status.set(f"{value['valid_count']}/{value['expected_count']} pairs · maximum extra displacement {metric} · {value['status']}")
            notes = [str(value.get('reference_note', '')), 'PDF: ' + str(value['pdf_file']), 'CSV / JSON: ' + str(value['output_folder'])]
            if value.get('field_method_review'):
                notes.insert(0, 'Method review required: inspect the field-centre comparison in the PDF. This is not an automatic pass.')
            self.set_details('\n'.join(notes))
            figure = Path(value['output_folder']) / 'Ray_Envelopes.png'
            if figure.exists():
                try:
                    from PIL import Image, ImageTk
                    with Image.open(figure) as image:
                        image.thumbnail((910, 325))
                        self.preview = ImageTk.PhotoImage(image.copy(), master=self)
                    self.image_label.configure(image=self.preview)
                except Exception as exc:
                    self.set_details('\n'.join(notes) + '\nPreview unavailable: ' + str(exc))
        self.after(100, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('Analysis running', 'Please wait until the report is complete.', parent=self)
        else:
            self.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--smoke-gui', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--analyse', metavar='MV_FOLDER')
    parser.add_argument('--profile')
    parser.add_argument('--records', default='')
    parser.add_argument('--output')
    parser.add_argument('--positioned-in-ct', action='store_true')
    args = parser.parse_args(argv)
    if args.analyse:
        if not args.profile or not args.output:
            parser.error('--analyse requires --profile and --output')
        result = analyse(args.analyse, args.profile, args.records, args.output, args.positioned_in_ct)
        if sys.stdout is not None:
            print(json.dumps({k: result[k] for k in ('status', 'valid_count', 'max_extra_mm', 'pdf_file')}))
        return 0
    app = MultiWLTApp()
    if args.smoke_gui:
        app.withdraw()
        app.update_idletasks()
        app.update()
        app.destroy()
    else:
        app.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
