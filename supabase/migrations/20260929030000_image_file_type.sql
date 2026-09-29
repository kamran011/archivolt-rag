-- Image uploads (screenshots, scanned pages) are ingested via OCR.
-- Matches FileType.image in backend/app/models/document.py.
ALTER TYPE filetype ADD VALUE IF NOT EXISTS 'image';
