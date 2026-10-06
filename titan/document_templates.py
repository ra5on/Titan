"""Small original blank documents; no macros, external links or user XML."""
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from .core import Error

XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
OFFICE_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
TYPES = 'http://schemas.openxmlformats.org/package/2006/content-types'
SUPPORTED = frozenset({'docx', 'xlsx', 'odt', 'ods'})


def _zip(parts):
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content, compress_type=ZIP_STORED if name == 'mimetype' else ZIP_DEFLATED)
    return output.getvalue()


def _openxml(kind):
    document = kind == 'docx'
    main = 'word/document.xml' if document else 'xl/workbook.xml'
    main_type = ('application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
                 if document else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')
    overrides = f'<Override PartName="/{main}" ContentType="{main_type}"/>'
    if not document:
        overrides += '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    parts = {
        '[Content_Types].xml': XML + f'<Types xmlns="{TYPES}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>{overrides}</Types>',
        '_rels/.rels': XML + f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Type="{OFFICE_REL}/officeDocument" Target="{main}"/></Relationships>',
    }
    if document:
        parts[main] = XML + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/><w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
    else:
        ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        parts[main] = XML + f'<workbook xmlns="{ns}" xmlns:r="{OFFICE_REL}"><bookViews><workbookView/></bookViews><sheets><sheet name="Tabelle1" sheetId="1" r:id="rId1"/></sheets></workbook>'
        parts['xl/_rels/workbook.xml.rels'] = XML + f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Type="{OFFICE_REL}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{OFFICE_REL}/styles" Target="styles.xml"/></Relationships>'
        parts['xl/worksheets/sheet1.xml'] = XML + f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/><sheetData/></worksheet>'
        parts['xl/styles.xml'] = XML + f'<styleSheet xmlns="{ns}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    return _zip(parts)


def _opendocument(kind):
    text = kind == 'odt'
    mime = 'application/vnd.oasis.opendocument.' + ('text' if text else 'spreadsheet')
    namespaces = 'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    body = '<office:text><text:p/></office:text>' if text else '<office:spreadsheet><table:table table:name="Tabelle1"><table:table-column/><table:table-row><table:table-cell/></table:table-row></table:table></office:spreadsheet>'
    return _zip({
        'mimetype': mime,
        'content.xml': XML + f'<office:document-content {namespaces} office:version="1.2"><office:automatic-styles/><office:body>{body}</office:body></office:document-content>',
        'META-INF/manifest.xml': XML + f'<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',
    })


def blank_document(kind, filename):
    if not isinstance(kind, str) or kind not in SUPPORTED:
        raise Error('Bitte Word (DOCX), Excel (XLSX), ODT oder ODS auswählen.')
    if not isinstance(filename, str) or PurePosixPath(filename).suffix.lower() != '.' + kind:
        raise Error('Dateiname und Dokumenttyp stimmen nicht überein.')
    return _openxml(kind) if kind in ('docx', 'xlsx') else _opendocument(kind)
