"""Tkinter UI for Noor PDF Page Reorganizer."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageTk

from noor_pdf_page_reorganizer import PageInfo, export_pages, inspect_pdf


class PageReorganizerApp:
    def __init__(self, root: tk.Tk):
        self.root=root
        root.title("Noor PDF Page Reorganizer")
        root.geometry("1000x720");root.minsize(760,540)
        self.source:Path|None=None;self.page_info:list[PageInfo]=[];self.order:list[int]=[];self.rotations={}
        self.pdfium_doc=None;self.preview_image=None;self.messages=queue.Queue();self.busy=False
        self._build();root.after(100,self._poll);root.protocol("WM_DELETE_WINDOW",self._close)

    def _build(self):
        main=ttk.Frame(self.root,padding=12);main.pack(fill="both",expand=True)
        ttk.Label(main,text="Noor PDF Page Reorganizer",font=("Segoe UI",16,"bold")).pack(anchor="w")
        ttk.Label(main,text="Reorder, rotate, remove or extract pages. The PDF page content stays vector/text; the source is not changed.").pack(anchor="w",pady=(3,8))
        row=ttk.Frame(main);row.pack(fill="x",pady=(0,8))
        self.source_label=ttk.Label(row,text="No PDF selected",anchor="w");self.source_label.pack(side="left",fill="x",expand=True)
        self.open_button=ttk.Button(row,text="Open PDF…",command=self._open);self.open_button.pack(side="right")
        pane=ttk.Panedwindow(main,orient="horizontal");pane.pack(fill="both",expand=True)
        left=ttk.Frame(pane,padding=(0,0,10,0));right=ttk.Frame(pane,padding=(10,0,0,0))
        pane.add(left,weight=3);pane.add(right,weight=4)
        ttk.Label(left,text="Output page order").pack(anchor="w",pady=(0,4))
        listframe=ttk.Frame(left);listframe.pack(fill="both",expand=True)
        self.listbox=tk.Listbox(listframe,selectmode=tk.EXTENDED,exportselection=False)
        scrollbar=ttk.Scrollbar(listframe,orient="vertical",command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set);self.listbox.pack(side="left",fill="both",expand=True);scrollbar.pack(side="right",fill="y")
        self.listbox.bind("<<ListboxSelect>>",self._preview_selected)
        controls=ttk.Frame(left);controls.pack(fill="x",pady=8)
        self.up_button=ttk.Button(controls,text="Move up",command=lambda:self._move(-1));self.up_button.grid(row=0,column=0,sticky="ew",padx=(0,4),pady=2)
        self.down_button=ttk.Button(controls,text="Move down",command=lambda:self._move(1));self.down_button.grid(row=0,column=1,sticky="ew",padx=4,pady=2)
        self.remove_button=ttk.Button(controls,text="Remove",command=self._remove);self.remove_button.grid(row=1,column=0,sticky="ew",padx=(0,4),pady=2)
        self.rotate_box=ttk.Combobox(controls,values=("90° clockwise","180°","270° clockwise"),state="readonly",width=18);self.rotate_box.current(0);self.rotate_box.grid(row=1,column=1,sticky="ew",padx=4,pady=2)
        self.rotate_button=ttk.Button(controls,text="Rotate selected",command=self._rotate);self.rotate_button.grid(row=2,column=0,columnspan=2,sticky="ew",pady=2)
        controls.columnconfigure(0,weight=1);controls.columnconfigure(1,weight=1)
        ttk.Label(right,text="Selected page preview").pack(anchor="w",pady=(0,4))
        self.preview=ttk.Label(right,text="Open a PDF and select a page",anchor="center",relief="sunken")
        self.preview.pack(fill="both",expand=True)
        self.page_detail=ttk.Label(right,text="",anchor="w");self.page_detail.pack(fill="x",pady=(5,0))
        self.warning=ttk.Label(main,text="Note: saving a modified PDF can invalidate digital signatures and may not preserve bookmarks, forms or document-level metadata.",wraplength=950)
        self.warning.pack(anchor="w",pady=(7,2))
        bottom=ttk.Frame(main);bottom.pack(fill="x",pady=(5,0))
        self.progress=ttk.Progressbar(bottom,mode="determinate",maximum=100);self.progress.pack(side="left",fill="x",expand=True)
        self.status=ttk.Label(bottom,text="Ready",anchor="w");self.status.pack(side="left",padx=8)
        self.extract_button=ttk.Button(bottom,text="Extract selected…",command=self._extract);self.extract_button.pack(side="right",padx=(4,0))
        self.save_button=ttk.Button(bottom,text="Save arranged copy…",command=self._save);self.save_button.pack(side="right")
        self._set_controls(False)

    def _set_controls(self,enabled:bool):
        state="normal" if enabled and not self.busy else "disabled"
        for item in (self.up_button,self.down_button,self.remove_button,self.rotate_button,self.rotate_box,self.extract_button,self.save_button):item.configure(state=state)
        self.open_button.configure(state="disabled" if self.busy else "normal")

    def _open(self):
        name=filedialog.askopenfilename(title="Open PDF",filetypes=[("PDF documents","*.pdf")])
        if not name:return
        try:
            info=inspect_pdf(name)
            doc=pdfium.PdfDocument(name)
        except Exception as exc:
            messagebox.showerror("Cannot open PDF",str(exc));return
        self._close_document();self.source=Path(name);self.page_info=info;self.order=list(range(len(info)));self.rotations={};self.pdfium_doc=doc
        self.source_label.configure(text=str(self.source));self._refresh();self.status.configure(text=f"Loaded {len(info)} page(s)")
        if self.order:
            self.listbox.selection_set(0);self.listbox.activate(0);self._show_preview(0)
        self._set_controls(True)

    def _close_document(self):
        if self.pdfium_doc is not None:
            try:self.pdfium_doc.close()
            except Exception:pass
            self.pdfium_doc=None
        self.preview_image=None

    def _refresh(self,select_positions=None):
        self.listbox.delete(0,"end")
        for display_pos,source_index in enumerate(self.order,1):
            info=self.page_info[source_index];turn=self.rotations.get(source_index,0)
            rotation=(info.rotation+turn)%360
            suffix=f" | rotate {turn:+d}°" if turn else ""
            self.listbox.insert("end",f"{display_pos:03d} → page {source_index+1} | {info.width:.0f} × {info.height:.0f} pt | /Rotate {rotation}°{suffix}")
        if select_positions:
            for position in select_positions:
                if 0<=position<len(self.order):self.listbox.selection_set(position)
            if self.order and select_positions:self.listbox.activate(select_positions[0]);self.listbox.see(select_positions[0])
        self._set_controls(bool(self.order))

    def _current_positions(self):return list(self.listbox.curselection())

    def _preview_selected(self,_event=None):
        selection=self._current_positions()
        if selection:self._show_preview(selection[0])

    def _show_preview(self,position):
        if self.pdfium_doc is None or not 0<=position<len(self.order):return
        source_index=self.order[position]
        page=None;bitmap=None;pil=None
        try:
            page=self.pdfium_doc[source_index]
            width,height=page.get_size()
            scale=min(620/max(width,1),580/max(height,1),1.0)
            bitmap=page.render(scale=scale)
            pil=bitmap.to_pil()
            turn=self.rotations.get(source_index,0)
            if turn:pil=pil.rotate(-turn,expand=True)
            self.preview_image=ImageTk.PhotoImage(pil)
            self.preview.configure(image=self.preview_image,text="")
            info=self.page_info[source_index]
            self.page_detail.configure(text=f"Current position {position+1} of {len(self.order)} • source page {source_index+1} • {info.width:.1f} × {info.height:.1f} pt • stored rotation {info.rotation}°")
        except Exception as exc:
            self.preview.configure(image="",text=f"Preview unavailable\n{exc}");self.preview_image=None
        finally:
            if pil is not None:
                try:pil.close()
                except Exception:pass
            if bitmap is not None:
                try:bitmap.close()
                except Exception:pass
            if page is not None:
                try:page.close()
                except Exception:pass

    def _move(self,direction):
        selected=self._current_positions()
        if not selected:return
        indexes=selected if direction<0 else list(reversed(selected))
        for pos in indexes:
            other=pos+direction
            if 0<=other<len(self.order):self.order[pos],self.order[other]=self.order[other],self.order[pos]
        new_positions=[max(0,min(len(self.order)-1,pos+direction)) for pos in selected]
        self._refresh(new_positions)
        if new_positions:self._show_preview(new_positions[0])

    def _remove(self):
        selected=set(self._current_positions())
        if not selected:return
        self.order=[page for pos,page in enumerate(self.order) if pos not in selected]
        self._refresh([min(min(selected),len(self.order)-1)] if self.order else None)
        if self.order:self._show_preview(min(min(selected),len(self.order)-1))
        else:self.preview.configure(image="",text="No pages remain");self.page_detail.configure(text="")
        self.status.configure(text=f"{len(self.order)} page(s) remain in the output plan")

    def _rotate(self):
        selected=self._current_positions()
        if not selected:return
        degrees=(90,180,270)[self.rotate_box.current()]
        for pos in selected:
            index=self.order[pos];self.rotations[index]=(self.rotations.get(index,0)+degrees)%360
        self._refresh(selected);self._show_preview(selected[0]);self.status.configure(text=f"Rotated {len(selected)} selected page(s)")

    def _save(self):self._run_export(list(self.order),"Save arranged PDF as…")

    def _extract(self):
        selected=self._current_positions()
        if not selected:messagebox.showwarning("Select pages","Select one or more pages to extract.");return
        subset=[self.order[pos] for pos in selected]
        self._run_export(subset,"Extract selected pages as…")

    def _run_export(self,order,title):
        if self.busy or self.source is None:return
        if not order:messagebox.showwarning("No pages","At least one page must remain in the output.");return
        suffix="_organized.pdf" if title.startswith("Save") else "_extracted.pdf"
        default=self.source.with_name(self.source.stem+suffix)
        filename=filedialog.asksaveasfilename(title=title,initialdir=str(default.parent),initialfile=default.name,defaultextension=".pdf",filetypes=[("PDF documents","*.pdf")])
        if not filename:return
        target=Path(filename)
        if target.exists() and not messagebox.askyesno("Replace existing PDF?",f"Replace this file after export succeeds?\n\n{target}"):
            return
        overwrite=target.exists();source=self.source;rotation_copy=dict(self.rotations);expected=len(order)
        self.busy=True;self._set_controls(bool(self.order));self.progress.configure(maximum=expected,value=0);self.status.configure(text="Writing PDF…")
        def progress(done,total):self.messages.put(("progress",done,total))
        def worker():
            try:
                result=export_pages(source,target,order,rotation_copy,overwrite=overwrite,progress=progress)
                self.messages.put(("done",result,expected))
            except Exception as exc:self.messages.put(("error",str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def _poll(self):
        try:
            while True:
                item=self.messages.get_nowait()
                if item[0]=="progress":
                    _,done,total=item;self.progress.configure(maximum=total,value=done);self.status.configure(text=f"Writing page {done}/{total}")
                elif item[0]=="done":
                    self.busy=False;self._set_controls(bool(self.order));self.progress.configure(value=self.progress.cget("maximum"));self.status.configure(text="PDF saved")
                    messagebox.showinfo("PDF saved",f"Created {item[1]} with {item[2]} page(s). The source PDF was not changed.")
                elif item[0]=="error":
                    self.busy=False;self._set_controls(bool(self.order));self.status.configure(text="Export failed");messagebox.showerror("Export failed",item[1])
        except queue.Empty:pass
        self.root.after(100,self._poll)

    def _close(self):
        if self.busy:
            messagebox.showinfo("Export in progress","Wait for the current PDF export to finish before closing.");return
        self._close_document();self.root.destroy()


def run_gui():
    root=tk.Tk();PageReorganizerApp(root);root.mainloop()


if __name__=="__main__":run_gui()
