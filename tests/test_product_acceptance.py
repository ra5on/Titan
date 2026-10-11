import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('product_acceptance',Path(__file__).resolve().parents[1]/'scripts/validate-product-acceptance.py')
acceptance=importlib.util.module_from_spec(spec);spec.loader.exec_module(acceptance)


class ProductAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        (self.root/'ab-input').mkdir()
        (self.root/'ab-input/image-info.json').write_text(json.dumps({'version':'0.8.0','titan_source_commit':'a'*40}))
        self.image=self.root/'titan-0.8.0-amd64.img';self.image.write_bytes(b'disposable image fixture')
        self.rescue=self.root/'titan-0.8.0-recovery-amd64.iso';self.rescue.write_bytes(b'disposable rescue fixture')
        self.report={'schema':1,'ok':True,'scope':'installed-nas-and-replacement-recovery','source_commit':'a'*40,
            'checks':{name:True for name in acceptance.REQUIRED},'catalog_revision':'b'*40,'catalog_archive_sha256':'c'*64,
            'image_sha256':acceptance.digest(self.image),'recovery_iso_sha256':acceptance.digest(self.rescue)}
        self.coverage={'complete':True,'blocked':[],'total':393,'translated':393,'revision':'b'*40,'archive_sha256':'c'*64}
    def save(self):
        (self.root/'product-acceptance.json').write_text(json.dumps(self.report))
        (self.root/'umbrel-coverage.json').write_text(json.dumps(self.coverage))
    def test_exact_complete_evidence_accepts(self):
        self.save();self.assertTrue(acceptance.validate(self.root))
    def test_rescue_only_or_another_commit_does_not_accept(self):
        for change in ({'scope':'rescue-iso-real-block-devices'},{'source_commit':'d'*40},{'ok':False}):
            original=copy.deepcopy(self.report);self.report.update(change);self.save()
            with self.assertRaises(ValueError):acceptance.validate(self.root)
            self.report=original
    def test_each_required_check_must_be_true(self):
        for name in acceptance.REQUIRED:
            for value in (False,'passed',1,None):
                self.report['checks']={key:True for key in acceptance.REQUIRED}
                self.report['checks'][name]=value;self.save()
                with self.assertRaises(ValueError):acceptance.validate(self.root)
    def test_incomplete_or_different_catalog_blocks_release(self):
        for change in ({'complete':False},{'blocked':[{'id':'missing'}]},{'translated':11},{'total':True},{'revision':'d'*40},{'archive_sha256':'d'*64}):
            original=copy.deepcopy(self.coverage);self.coverage.update(change);self.save()
            with self.assertRaises(ValueError):acceptance.validate(self.root)
            self.coverage=original
    def test_changed_image_or_rescue_is_not_accepted(self):
        self.save()
        for path in (self.image,self.rescue):
            original=path.read_bytes();path.write_bytes(original+b'changed')
            with self.assertRaises(ValueError):acceptance.validate(self.root)
            path.write_bytes(original)
    def test_missing_evidence_never_counts_as_success(self):
        with self.assertRaises(FileNotFoundError):acceptance.validate(self.root)
