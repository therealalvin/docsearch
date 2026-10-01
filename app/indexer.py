import os
import re
import json
import sqlite3
import pymupdf as fitz
from PIL import Image
import numpy as np
import meilisearch
import glob
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure /data exists BEFORE we set database paths, handling permission errors
try:
    os.makedirs("/data/thumbnails", exist_ok=True)
    has_data_dir = True
except Exception:
    has_data_dir = os.path.exists("/data")

DB_PATH = "/data/vault.db" if has_data_dir else "vault.db"
DOCS_DIR_PATTERNS = ["/data/documents*", "./documents*"]
THUMBNAIL_DIR = "/data/thumbnails" if has_data_dir else "./thumbnails"
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# Thread lock for safe concurrent SQLite writes
db_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT,
            filepath TEXT,
            doc_date TEXT,
            content TEXT,
            tags TEXT,
            layout_vector TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS tag_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_name TEXT UNIQUE,
            keywords TEXT,
            allow_fuzzy INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_docs_directories():
    dirs = []
    for pattern in DOCS_DIR_PATTERNS:
        for path in glob.glob(pattern):
            if os.path.isdir(path):
                dirs.append(path)
    return dirs

def is_pdf(filename):
    return filename.lower().endswith('.pdf')

def generate_thumbnail_and_layout_vector(filepath, doc_id):
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{doc_id}.jpg")
    try:
        doc = fitz.open(filepath)
        if len(doc) == 0:
            return None
        page = doc[0]
        pix = page.get_pixmap(dpi=100)
        pix.save(thumb_path)
        doc.close()

        img = Image.open(thumb_path).convert('L').resize((32, 32))
        arr = 255.0 - np.array(img, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.flatten().tolist()
    except Exception as e:
        print(f"Error processing visual layout for {filepath}: {e}")
        return None

def extract_text_and_date(filepath):
    try:
        doc = fitz.open(filepath)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()

        dates = re.findall(r'\b(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]20\d{2})\b', text)
        doc_date = None
        if dates:
            d = dates[0]
            parts = re.split(r'[-/.]', d)
            if len(parts[0]) == 4:
                doc_date = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            elif len(parts[2]) == 4:
                doc_date = f"{parts[2]}-{int(parts[0]):02d}-{int(parts[1]):02d}"

        return text, doc_date
    except Exception as e:
        print(f"Text extraction error for {filepath}: {e}")
        return "", None

def configure_meilisearch():
    """Ensures Meilisearch has the correct filterable and searchable attributes configured."""
    try:
        client = meilisearch.Client('http://meilisearch:7700', 'thisismymasterkeydontloseit123456')
        index = client.index('documents')
        index.update_filterable_attributes(['tags', 'id', 'doc_date'])
        index.update_sortable_attributes(['doc_date', 'filename'])
        index.update_searchable_attributes(['filename', 'content', 'tags'])
    except Exception as e:
        print(f"Meilisearch config warning: {e}")

def process_single_pdf(abs_path, file, tag_rules):
    doc_id = re.sub(r'[^a-zA-Z0-9_-]', '_', file)
    content, doc_date = extract_text_and_date(abs_path)
    layout_vector = generate_thumbnail_and_layout_vector(abs_path, doc_id)

    assigned_tags = []
    text_to_search = (content + " " + file).lower()

    for rule in tag_rules:
        kw_list = [k.strip().lower() for k in rule['keywords'].split(',') if k.strip()]
        allow_fuzzy = bool(rule['allow_fuzzy'])
        assigned = False
        
        for kw in kw_list:
            if allow_fuzzy:
                if kw in text_to_search:
                    assigned = True
                    break
            else:
                pattern = r'\b' + re.escape(kw) + r'\b'
                if re.search(pattern, text_to_search):
                    assigned = True
                    break

        if assigned:
            assigned_tags.append(rule['tag_name'])

    return {
        'id': doc_id,
        'filename': file,
        'filepath': abs_path,
        'doc_date': doc_date,
        'content': content,
        'tags': assigned_tags,
        'layout_vector': layout_vector
    }

def sync_documents():
    """Efficient delta-sync: Processes only new files, and purges deleted files from SQLite and Meilisearch."""
    init_db()
    configure_meilisearch()
    conn = get_db()
    tag_rules = conn.execute('SELECT * FROM tag_rules').fetchall()

    disk_files = {}
    for docs_dir in get_docs_directories():
        for root, _, files in os.walk(docs_dir):
            for file in files:
                if is_pdf(file):
                    abs_path = os.path.abspath(os.path.join(root, file))
                    disk_files[abs_path] = file

    existing_docs = conn.execute('SELECT id, filepath FROM documents').fetchall()
    existing_paths = {row['filepath']: row['id'] for row in existing_docs}

    deleted_paths = set(existing_paths.keys()) - set(disk_files.keys())
    deleted_ids = []
    if deleted_paths:
        for path in deleted_paths:
            doc_id = existing_paths[path]
            deleted_ids.append(doc_id)
            conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
            
            thumb_path = os.path.join(THUMBNAIL_DIR, f"{doc_id}.jpg")
            if os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except Exception:
                    pass
        conn.commit()

    new_tasks = []
    for abs_path, file in disk_files.items():
        if abs_path not in existing_paths:
            new_tasks.append((abs_path, file))

    conn.close()

    meili_added_docs = []
    if new_tasks:
        max_workers = min(32, (os.cpu_count() or 4) * 2)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_single_pdf, abs_path, file, tag_rules): (abs_path, file) for abs_path, file in new_tasks}
            
            for future in as_completed(futures):
                try:
                    res = future.result()
                    if res:
                        with db_lock:
                            db_conn = get_db()
                            db_conn.execute('''
                                INSERT OR REPLACE INTO documents 
                                (id, filename, filepath, doc_date, content, tags, layout_vector)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                res['id'],
                                res['filename'],
                                res['filepath'],
                                res['doc_date'],
                                res['content'],
                                json.dumps(res['tags']),
                                json.dumps(res['layout_vector']) if res['layout_vector'] else None
                            ))
                            db_conn.commit()
                            db_conn.close()

                        meili_added_docs.append({
                            'id': res['id'],
                            'filename': res['filename'],
                            'filepath': res['filepath'],
                            'doc_date': res['doc_date'],
                            'content': res['content'],
                            'tags': res['tags']
                        })
                except Exception as e:
                    print(f"Error in worker thread: {e}")

    try:
        client = meilisearch.Client('http://meilisearch:7700', 'thisismymasterkeydontloseit123456')
        index = client.index('documents')
        
        if meili_added_docs:
            index.add_documents(meili_added_docs)
        
        if deleted_ids:
            index.delete_documents(deleted_ids)
            
    except Exception as e:
        print(f"Meilisearch delta sync error: {e}")

def retag_all_documents():
    """Lightning-fast retagging: Re-evaluates tags using cached SQLite text without touching disk or parsing PDFs."""
    init_db()
    configure_meilisearch()
    conn = get_db()
    tag_rules = conn.execute('SELECT * FROM tag_rules').fetchall()
    
    docs = conn.execute('SELECT id, filename, filepath, doc_date, content FROM documents').fetchall()
    meili_docs = []
    
    for doc in docs:
        doc_id = doc['id']
        filename = doc['filename']
        content = doc['content'] or ""
        
        assigned_tags = []
        text_to_search = (content + " " + filename).lower()

        for rule in tag_rules:
            kw_list = [k.strip().lower() for k in rule['keywords'].split(',') if k.strip()]
            allow_fuzzy = bool(rule['allow_fuzzy'])
            assigned = False
            
            for kw in kw_list:
                if allow_fuzzy:
                    if kw in text_to_search:
                        assigned = True
                        break
                else:
                    pattern = r'\b' + re.escape(kw) + r'\b'
                    if re.search(pattern, text_to_search):
                        assigned = True
                        break

            if assigned:
                assigned_tags.append(rule['tag_name'])

        conn.execute('''
            UPDATE documents SET tags = ? WHERE id = ?
        ''', (json.dumps(assigned_tags), doc_id))

        meili_docs.append({
            'id': doc_id,
            'filename': filename,
            'filepath': doc['filepath'],
            'doc_date': doc['doc_date'],
            'content': content,
            'tags': assigned_tags
        })

    conn.commit()
    conn.close()

    if meili_docs:
        try:
            client = meilisearch.Client('http://meilisearch:7700', 'thisismymasterkeydontloseit123456')
            index = client.index('documents')
            index.add_documents(meili_docs)
        except Exception as e:
            print(f"Meilisearch tag update error: {e}")
