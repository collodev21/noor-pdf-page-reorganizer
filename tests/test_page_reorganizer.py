import sys
import tempfile
import unittest
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject,NumberObject
from reportlab.pdfgen import canvas

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from noor_pdf_page_reorganizer import (export_pages,inspect_pdf,parse_page_order,parse_rotation_specs)


class PageReorganizerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="pdf-pages-عربي-é-")
        self.root=Path(self.temp.name)
        self.source=self.root/"source.pdf"
        self._make_source(self.source)

    def tearDown(self):self.temp.cleanup()

    @staticmethod
    def _make_source(path):
        pdf=canvas.Canvas(str(path),pagesize=(100,200),pageCompression=0)
        pdf.setTitle("Synthetic source document")
        pdf.drawString(12,100,"PAGE-ONE-VECTOR-CONTENT")
        pdf.showPage()
        pdf.setPageSize((300,150));pdf.drawString(12,80,"PAGE-TWO-MIXED-SIZE")
        pdf.showPage()
        pdf.setPageSize((80,160));pdf.drawString(12,90,"PAGE-THREE-EXTRACT")
        pdf.showPage();pdf.save()
        # Give page 2 an existing /Rotate entry to test rotation normalization.
        reader=PdfReader(str(path));writer=PdfWriter()
        for index,page in enumerate(reader.pages):
            if index==1:page.rotate(270)
            writer.add_page(page)
        with path.open("wb") as stream:writer.write(stream)

    def _texts(self,path):
        return [page.extract_text().strip() for page in PdfReader(str(path)).pages]

    def test_inspect_returns_mixed_page_sizes_and_existing_rotation(self):
        info=inspect_pdf(self.source)
        self.assertEqual(len(info),3)
        self.assertEqual([(round(p.width),round(p.height)) for p in info],[(100,200),(300,150),(80,160)])
        self.assertEqual([p.rotation for p in info],[0,270,0])

    def test_parse_order_ranges_and_reject_bad_or_duplicate_numbers(self):
        self.assertEqual(parse_page_order("3,1-2",3),[2,0,1])
        for spec in ("", "1,,2", "0", "4", "3-1", "1,1", "x"):
            with self.subTest(spec=spec),self.assertRaises(ValueError):parse_page_order(spec,3)

    def test_parse_rotation_specs_and_validate_page_and_angle(self):
        self.assertEqual(parse_rotation_specs(["1:90","3:270"],3),{0:90,2:270})
        for specs in (("0:90",),("4:90",),("2:45",),("1:90","1:180"),("bad",)):
            with self.subTest(specs=specs),self.assertRaises(ValueError):parse_rotation_specs(specs,3)

    def test_reorder_rotate_and_keep_pdf_text_and_page_boxes(self):
        before=self.source.read_bytes();output=self.root/"reordered.pdf";events=[]
        export_pages(self.source,output,[2,0],{2:90},progress=lambda done,total:events.append((done,total)))
        reader=PdfReader(str(output))
        self.assertEqual(self._texts(output),["PAGE-THREE-EXTRACT","PAGE-ONE-VECTOR-CONTENT"])
        self.assertEqual([int(p.get("/Rotate",0))%360 for p in reader.pages],[90,0])
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width),80)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.height),160)
        self.assertEqual(events,[(1,2),(2,2)])
        self.assertEqual(before,self.source.read_bytes())
        self.assertNotIn("/Image",str(reader.pages[0].get("/Resources",{}).get("/XObject",{})))

    def test_rotation_accumulates_on_existing_entry(self):
        output=self.root/"rotated.pdf"
        export_pages(self.source,output,[1],{1:90})
        page=PdfReader(str(output)).pages[0]
        self.assertEqual(int(page.get("/Rotate",0))%360,0)
        self.assertEqual(page.extract_text().strip(),"PAGE-TWO-MIXED-SIZE")

    def test_extract_selected_pages_in_requested_order_and_pdfium_can_render(self):
        output=self.root/"extracted.pdf"
        export_pages(self.source,output,[2,0])
        reader=PdfReader(str(output))
        self.assertEqual(len(reader.pages),2)
        self.assertEqual(self._texts(output),["PAGE-THREE-EXTRACT","PAGE-ONE-VECTOR-CONTENT"])
        document=pdfium.PdfDocument(str(output))
        try:
            self.assertEqual(len(document),2)
            page=document[0];bitmap=page.render(scale=.5)
            try:self.assertGreater(bitmap.to_pil().getbbox()[2],0)
            finally:bitmap.close();page.close()
        finally:document.close()

    def test_existing_output_is_protected_and_failed_overwrite_keeps_it(self):
        output=self.root/"existing.pdf";output.write_bytes(b"keep this exact data")
        original=output.read_bytes()
        with self.assertRaises(FileExistsError):export_pages(self.source,output)
        self.assertEqual(output.read_bytes(),original)
        bad=self.root/"broken.pdf";bad.write_bytes(b"not a pdf")
        with self.assertRaises(ValueError):export_pages(bad,output,overwrite=True)
        self.assertEqual(output.read_bytes(),original)
        self.assertEqual(list(self.root.glob(".existing.tmp-*.pdf")),[])

    def test_reject_same_source_empty_or_duplicate_order_and_invalid_rotations(self):
        with self.assertRaisesRegex(ValueError,"different file"):
            export_pages(self.source,self.source)
        for order in ([],[0,0],[-1],[3]):
            with self.subTest(order=order),self.assertRaises(ValueError):export_pages(self.source,self.root/"bad-plan.pdf",order)
        for rotations in ({0:45},{3:90},{True:90}):
            with self.subTest(rotations=rotations),self.assertRaises(ValueError):export_pages(self.source,self.root/"bad-rotation.pdf",[0],rotations)

    def test_bad_extension_corrupt_and_encrypted_pdfs_are_reported(self):
        with self.assertRaisesRegex(ValueError,"end in .pdf"):
            export_pages(self.source,self.root/"output.txt")
        corrupt=self.root/"corrupt.pdf";corrupt.write_bytes(b"broken pdf")
        with self.assertRaises(ValueError):inspect_pdf(corrupt)
        encrypted=self.root/"locked.pdf";writer=PdfWriter();writer.add_blank_page(100,100);writer.encrypt("secret")
        with encrypted.open("wb") as stream:writer.write(stream)
        with self.assertRaisesRegex(ValueError,"Password-protected"):
            inspect_pdf(encrypted)

    def test_invalid_page_rotation_metadata_is_rejected(self):
        invalid=self.root/"invalid-rotation.pdf"
        reader=PdfReader(str(self.source));writer=PdfWriter();writer.add_page(reader.pages[0])
        writer.pages[0][NameObject("/Rotate")]=NumberObject(45)
        with invalid.open("wb") as stream:writer.write(stream)
        with self.assertRaisesRegex(ValueError,"non-right-angle rotation"):
            inspect_pdf(invalid)

    def test_unicode_paths(self):
        source=self.root/"دليل-é.pdf";self._make_source(source)
        output=self.root/"résultat"/"صفحات.pdf"
        export_pages(source,output,[1,0])
        self.assertEqual(self._texts(output),["PAGE-TWO-MIXED-SIZE","PAGE-ONE-VECTOR-CONTENT"])
        self.assertTrue(source.exists())


if __name__=="__main__":unittest.main()
