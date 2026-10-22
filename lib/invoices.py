"""Leitura segura de XMLs de NF-e para vincular às movimentações de estoque."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from lib.errors import DomainError

MAX_INVOICE_XML_BYTES = 5 * 1024 * 1024
_FORBIDDEN_XML_DECLARATION = re.compile(
    r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE
)
_ACCESS_KEY = re.compile(r"^\d{44}$")


def _decode_xml(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class InvoiceData:
    """Dados normalizados de uma NF-e importada."""

    number: str | None
    series: str | None
    access_key: str | None
    issued_at: str | None
    issuer_name: str | None
    recipient_name: str | None
    total_value: float | None
    xml: str
    file_name: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_by_name(node: ET.Element, name: str) -> ET.Element | None:
    for item in node.iter():
        if _local_name(item.tag) == name:
            return item
    return None


def _child_by_name(node: ET.Element | None, name: str) -> ET.Element | None:
    if node is None:
        return None
    for item in node:
        if _local_name(item.tag) == name:
            return item
    return None


def _text_by_name(node: ET.Element | None, name: str) -> str | None:
    found = _first_by_name(node, name) if node is not None else None
    if found is None:
        return None
    value = (found.text or "").strip()
    return value or None


def _child_text(node: ET.Element | None, name: str) -> str | None:
    found = _child_by_name(node, name)
    if found is None:
        return None
    value = (found.text or "").strip()
    return value or None


def _only_digits(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits or None


def _parse_decimal(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.strip().replace(" ", "")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return round(float(normalized), 2)
    except ValueError:
        return None


def parse_nfe_xml(
    payload: bytes | str,
    file_name: str | None = None,
) -> InvoiceData:
    """Valida e extrai os dados principais de um XML de NF-e.

    O arquivo é limitado a 5 MB e declarações de DTD/entidades são rejeitadas.
    O XML original é preservado para consulta e auditoria.
    """
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
        xml_text = payload
    else:
        raw = bytes(payload)
        xml_text = _decode_xml(raw)

    if not raw.strip():
        raise DomainError("O arquivo XML está vazio.")
    if len(raw) > MAX_INVOICE_XML_BYTES:
        raise DomainError("O XML da nota fiscal deve ter no máximo 5 MB.")
    if _FORBIDDEN_XML_DECLARATION.search(xml_text):
        raise DomainError("O XML contém uma declaração de DTD ou entidade não aceita.")

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DomainError(
            "Não foi possível ler o XML. Verifique se o arquivo é válido."
        ) from exc

    inf_nfe = _first_by_name(root, "infNFe")
    if inf_nfe is None:
        raise DomainError("O XML não contém uma NF-e (elemento infNFe).")

    ide = _child_by_name(inf_nfe, "ide")
    number = _only_digits(_child_text(ide, "nNF"))
    series = _child_text(ide, "serie")
    issued_at = _child_text(ide, "dhEmi") or _child_text(ide, "dEmi")

    emit = _child_by_name(inf_nfe, "emit")
    dest = _child_by_name(inf_nfe, "dest")
    issuer_name = _child_text(emit, "xNome")
    recipient_name = _child_text(dest, "xNome")

    total = _child_by_name(inf_nfe, "total")
    total_value = _parse_decimal(_text_by_name(total, "vNF"))

    access_key = _only_digits(_text_by_name(root, "chNFe"))
    if access_key is None:
        raw_id = (inf_nfe.attrib.get("Id") or "").strip()
        if raw_id.upper().startswith("NFE"):
            raw_id = raw_id[3:]
        candidate = _only_digits(raw_id)
        if candidate and len(candidate) == 44:
            access_key = candidate
    if access_key and not _ACCESS_KEY.fullmatch(access_key):
        access_key = None

    if not number and not access_key:
        raise DomainError("O XML não contém número nem chave de acesso da NF-e.")

    safe_file_name = Path(file_name or "nota-fiscal.xml").name or "nota-fiscal.xml"
    return InvoiceData(
        number=number,
        series=series,
        access_key=access_key,
        issued_at=issued_at,
        issuer_name=issuer_name,
        recipient_name=recipient_name,
        total_value=total_value,
        xml=xml_text,
        file_name=safe_file_name,
    )
