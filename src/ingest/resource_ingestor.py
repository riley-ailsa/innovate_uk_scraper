"""
Resource ingestor for fetching and parsing supporting documents.

Handles:
- PDF text extraction
- Web page text extraction
- Content de-duplication via hashing
"""

import io
import logging
from typing import List, Optional, Set

import requests
from bs4 import BeautifulSoup

from src.core.models import (
    SupportingResource,
    Document,
    ResourceType,
)
from src.core.utils import sha1_text, clean_text


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


DEFAULT_HEADERS = {
    "User-Agent": "GrantAnalystBot/0.1 (contact: dev@example.com)"
}


class ResourceIngestor:
    """
    Fetches and parses supporting resources into documents.

    Usage:
        ingestor = ResourceIngestor()
        docs = ingestor.fetch_documents_for_resources(resources, existing_hashes)
    """

    def __init__(self, session: Optional[requests.Session] = None):
        """
        Initialize ingestor.

        Args:
            session: Optional requests.Session for connection pooling
        """
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch_documents_for_resources(
        self,
        resources: List[SupportingResource],
        existing_hashes: Optional[Set[str]] = None,
    ) -> List[Document]:
        """
        Fetch and parse resources into documents.

        Enhanced with Content-Type detection:
        - Automatically detects PDFs from HTTP headers
        - Falls back to file signature detection (%PDF-)
        - Handles misclassified resources

        Args:
            resources: List of SupportingResource objects
            existing_hashes: Set of content_hash values already processed

        Returns:
            List of Document objects
        """
        existing_hashes = existing_hashes or set()
        docs: List[Document] = []

        logger.info(f"Processing {len(resources)} resources")

        for i, res in enumerate(resources, 1):
            logger.debug(f"[{i}/{len(resources)}] Processing {res.url}")

            # Skip videos (metadata only)
            if res.type == ResourceType.VIDEO:
                logger.debug(f"Skipping video: {res.url}")
                continue

            try:
                # Fetch resource
                resp = self.session.get(res.url, timeout=30)
                resp.raise_for_status()
                content = resp.content

                # Detect actual content type from HTTP headers and file signature
                content_type = resp.headers.get("Content-Type", "").lower()
                is_pdf = self._is_pdf_content(content_type, content)

                if is_pdf:
                    # Process as PDF
                    doc = self._process_pdf_content(res, content, existing_hashes)
                    if doc:
                        docs.append(doc)
                        logger.info(f"✓ PDF: {res.title} ({len(doc.text)} chars)")
                else:
                    # Process as webpage/HTML
                    doc = self._process_html_content(res, resp.text, existing_hashes)
                    if doc:
                        docs.append(doc)
                        logger.info(f"✓ Webpage: {res.title} ({len(doc.text)} chars)")

            except Exception as e:
                logger.error(f"✗ Error processing {res.url}: {e}")
                continue

        logger.info(f"Created {len(docs)} documents from {len(resources)} resources")
        return docs

    def _is_pdf_content(self, content_type: str, content: bytes) -> bool:
        """
        Detect if content is a PDF.

        Checks:
        1. Content-Type header
        2. File signature (%PDF-)

        Args:
            content_type: HTTP Content-Type header value
            content: File bytes

        Returns:
            True if content is a PDF
        """
        # Check Content-Type header
        if "application/pdf" in content_type:
            return True

        # Check file signature (PDFs start with %PDF-)
        if content.startswith(b"%PDF-"):
            return True

        return False

    def _process_pdf_content(
        self,
        res: SupportingResource,
        content: bytes,
        existing_hashes: Set[str]
    ) -> Optional[Document]:
        """
        Process PDF content into a Document.

        Args:
            res: SupportingResource
            content: PDF file bytes
            existing_hashes: Set of known content hashes

        Returns:
            Document or None if extraction fails or duplicate
        """
        # Extract text
        text = self._extract_pdf_text(content)

        if not text or not text.strip():
            logger.warning(f"No text extracted from PDF: {res.url}")
            return None

        # Check for duplicates
        content_hash = sha1_text(text)
        if content_hash in existing_hashes:
            logger.debug(f"Duplicate PDF content: {res.url}")
            return None

        # Update resource and hash set
        res.content_hash = content_hash
        existing_hashes.add(content_hash)

        doc_id = f"doc_{content_hash[:16]}"

        return Document(
            id=doc_id,
            competition_id=res.competition_id,
            resource_id=res.id,
            doc_type="briefing_pdf",
            source_url=res.url,
            text=text,
        )

    def _process_html_content(
        self,
        res: SupportingResource,
        html: str,
        existing_hashes: Set[str]
    ) -> Optional[Document]:
        """
        Process HTML content into a Document.

        Args:
            res: SupportingResource
            html: HTML string
            existing_hashes: Set of known content hashes

        Returns:
            Document or None if extraction fails or duplicate
        """
        # Extract text
        text = self._extract_html_text(html)

        if not text or not text.strip():
            logger.warning(f"No text extracted from webpage: {res.url}")
            return None

        # Check for duplicates
        content_hash = sha1_text(text)
        if content_hash in existing_hashes:
            logger.debug(f"Duplicate webpage content: {res.url}")
            return None

        # Update resource and hash set
        res.content_hash = content_hash
        existing_hashes.add(content_hash)

        doc_id = f"doc_{content_hash[:16]}"

        return Document(
            id=doc_id,
            competition_id=res.competition_id,
            resource_id=res.id,
            doc_type="guidance",
            source_url=res.url,
            text=text,
        )

    def _extract_html_text(self, html: str) -> str:
        """
        Extract text from HTML content.

        Args:
            html: HTML string

        Returns:
            Extracted text
        """
        soup = BeautifulSoup(html, "html.parser")

        # Remove nav/footer/script elements
        for tag in soup(["nav", "footer", "script", "style", "aside"]):
            tag.decompose()

        # Extract text from relevant elements
        text_parts = []
        for tag in soup.find_all(["p", "li", "h1", "h2", "h3", "div"]):
            text = tag.get_text(" ", strip=True)
            if text and len(text) > 20:  # Filter very short fragments
                text_parts.append(text)

        full_text = "\n\n".join(text_parts)
        return clean_text(full_text)

    def _extract_pdf_text(self, content: bytes) -> str:
        """
        Extract text from PDF bytes.

        Uses pdfplumber for robust text extraction.

        Args:
            content: PDF file bytes

        Returns:
            Extracted text
        """
        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber not installed. Run: pip install pdfplumber")
            return ""

        text_parts = []

        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                    else:
                        logger.debug(f"No text on page {page_num}")
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            return ""

        full_text = "\n\n".join(text_parts)
        return clean_text(full_text)

