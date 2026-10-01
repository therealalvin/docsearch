import os
import re
import math
import json
import threading
from datetime import datetime, date, timedelta
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import meilisearch
import indexer

app = FastAPI()

app.mount("/thumbnails", StaticFiles(directory=indexer.THUMBNAIL_DIR), name="thumbnails")
templates = Jinja2Templates(directory="templates")
meili = meilisearch.Client('http://meilisearch:7700', 'thisismymasterkeydontloseit123456')

SYNC_STATUS = {
    "is_syncing": False,
    "last_sync": None
}

def start_background_sync():
    global SYNC_STATUS
    if SYNC_STATUS["is_syncing"]:
        return

    def _sync_worker():
        global SYNC_STATUS
        SYNC_STATUS["is_syncing"] = True
        try:
            indexer.sync_documents()
        except Exception as e:
            print(f"[Sync Error] {e}")
        finally:
            SYNC_STATUS["is_syncing"] = False
            SYNC_STATUS["last_sync"] = datetime.now().strftime("%I:%M:%S %p")

    thread = threading.Thread(target=_sync_worker, daemon=True)
    thread.start()

@app.on_event("startup")
def startup_event():
    indexer.configure_meilisearch()
    start_background_sync()

@app.get("/sync")
def sync():
    start_background_sync()
    return RedirectResponse(url="/", status_code=303)

@app.get("/api/sync-status")
def sync_status_api():
    return JSONResponse(SYNC_STATUS)

def cosine_similarity(v1, v2):
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    return float(sum(a * b for a, b in zip(v1, v2)))

def get_excluded_info(exclude_ids: list):
    if not exclude_ids:
        return [], []
    
    conn = indexer.get_db()
    row_map = {}
    
    chunk_size = 900
    for i in range(0, len(exclude_ids), chunk_size):
        chunk = exclude_ids[i:i + chunk_size]
        placeholders = ','.join('?' for _ in chunk)
        rows = conn.execute(
            f'SELECT id, filename, layout_vector FROM documents WHERE id IN ({placeholders})',
            chunk
        ).fetchall()
        for r in rows:
            row_map[r['id']] = r
            
    conn.close()

    info_list = []
    target_vectors = []

    for eid in exclude_ids:
        if eid in row_map:
            r = row_map[eid]
            vec = json.loads(r['layout_vector']) if r['layout_vector'] else None
            if vec:
                target_vectors.append(vec)
            
            rem_ids = [x for x in exclude_ids if x != eid]
            remove_str = ",".join(rem_ids)

            info_list.append({
                'id': r['id'],
                'filename': r['filename'],
                'remove_exclude_str': remove_str
            })
    return info_list, target_vectors

def get_date_bounds(date_range: str, custom_start: str = "", custom_end: str = ""):
    today = date.today()
    if date_range == 'last_month':
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
        return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')
    elif date_range == 'ytd':
        start_date = date(today.year, 1, 1)
        return start_date.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')
    elif date_range == 'last_year':
        last_year = today.year - 1
        return f"{last_year}-01-01", f"{last_year}-12-31"
    elif date_range == 'custom' and custom_start and custom_end:
        return custom_start, custom_end
    return None, None

def execute_search(
    query_str: str, 
    is_fuzzy: bool,
    tag_filter: str = None, 
    date_start: str = None, 
    date_end: str = None, 
    sort_by: str = "doc_date:desc", 
    page: int = 1, 
    limit: int = 25,
    exclude_ids: list = None,
    target_exclude_vectors: list = None,
    layout_threshold: float = 0.75
):
    index = meili.index('documents')
    query_str = query_str.strip()
    offset = (page - 1) * limit
    meili_filter = f'tags = "{tag_filter}"' if tag_filter else None
    fetch_limit = 10000

    def format_query(clause: str):
        clean_clause = re.sub(r'\bAND\b', ' ', clause, flags=re.IGNORECASE).strip()
        if not is_fuzzy and clean_clause:
            words = [w for w in clean_clause.replace('"', '').split() if w.strip()]
            return " ".join([f'"{w}"' for w in words])
        return clean_clause

    or_clauses = [clause.strip() for clause in re.split(r'\bOR\b', query_str, flags=re.IGNORECASE) if clause.strip()]

    if len(or_clauses) > 1:
        combined_hits = []
        seen_ids = set()
        for clause in or_clauses:
            formatted_clause = format_query(clause)
            res = index.search(formatted_clause, {
                'filter': meili_filter,
                'matchingStrategy': 'all',
                'limit': fetch_limit
            })
            for hit in res['hits']:
                if hit['id'] not in seen_ids:
                    seen_ids.add(hit['id'])
                    combined_hits.append(hit)
        hits = combined_hits
    else:
        formatted_query = format_query(query_str) if query_str else ""
        search_params = {
            'matchingStrategy': 'all' if formatted_query else 'last',
            'limit': fetch_limit,
            'offset': 0
        }
        if meili_filter:
            search_params['filter'] = meili_filter
        if sort_by and sort_by != "relevance":
            search_params['sort'] = [sort_by]

        res = index.search(formatted_query, search_params)
        hits = res.get('hits', [])

    if date_start and date_end:
        hits = [h for h in hits if h.get("doc_date") and date_start <= h["doc_date"] <= date_end]

    if sort_by == "doc_date:desc":
        hits.sort(key=lambda x: x.get("doc_date") or "0000-00-00", reverse=True)
    elif sort_by == "doc_date:asc":
        hits.sort(key=lambda x: x.get("doc_date") or "9999-99-99", reverse=False)
    elif sort_by == "filename:asc":
        hits.sort(key=lambda x: x.get("filename", "").lower())

    if exclude_ids or target_exclude_vectors:
        exclude_set = set(exclude_ids) if exclude_ids else set()
        candidate_hits = [h for h in hits if h['id'] not in exclude_set]

        if target_exclude_vectors and candidate_hits:
            conn = indexer.get_db()
            candidate_ids = [h['id'] for h in candidate_hits]
            vector_map = {}
            
            chunk_size = 900
            for i in range(0, len(candidate_ids), chunk_size):
                chunk = candidate_ids[i:i + chunk_size]
                placeholders = ','.join('?' for _ in chunk)
                rows = conn.execute(
                    f'SELECT id, layout_vector FROM documents WHERE id IN ({placeholders})',
                    chunk
                ).fetchall()
                for r in rows:
                    if r['layout_vector']:
                        try:
                            vector_map[r['id']] = json.loads(r['layout_vector'])
                        except Exception:
                            pass
            conn.close()

            filtered_hits = []
            for hit in candidate_hits:
                hit_vec = vector_map.get(hit['id'])
                if hit_vec:
                    is_similar = False
                    for target_vec in target_exclude_vectors:
                        if cosine_similarity(hit_vec, target_vec) >= layout_threshold:
                            is_similar = True
                            break
                    if not is_similar:
                        filtered_hits.append(hit)
                else:
                    filtered_hits.append(hit)
            hits = filtered_hits
        else:
            hits = candidate_hits

    total_hits = len(hits)
    paged_hits = hits[offset:offset + limit]

    return paged_hits, total_hits

@app.get("/", response_class=HTMLResponse)
def search_ui(
    request: Request, 
    q: str = "", 
    tag: str = "", 
    date_range: str = "all", 
    start_date: str = "", 
    end_date: str = "", 
    sort: str = "doc_date:desc", 
    page: int = 1, 
    limit: int = 25,
    exclude: str = "",
    fuzzy: str = "false"
):
    filter_start, filter_end = get_date_bounds(date_range, start_date, end_date)
    limit = limit if limit in [10, 25, 50, 100] else 25
    page = max(1, page)
    is_fuzzy = fuzzy.lower() == "true"

    exclude_ids = [x.strip() for x in exclude.split(',') if x.strip()]
    excluded_items, target_exclude_vectors = get_excluded_info(exclude_ids)

    results, total_hits = execute_search(
        query_str=q,
        is_fuzzy=is_fuzzy,
        tag_filter=tag,
        date_start=filter_start,
        date_end=filter_end,
        sort_by=sort,
        page=page,
        limit=limit,
        exclude_ids=exclude_ids,
        target_exclude_vectors=target_exclude_vectors
    )

    total_pages = max(1, math.ceil(total_hits / limit))

    conn = indexer.get_db()
    all_tags = conn.execute('SELECT * FROM tag_rules ORDER BY tag_name ASC').fetchall()
    conn.close()

    undo_exclude = ",".join(exclude_ids[:-1]) if len(exclude_ids) > 1 else ""

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "results": results,
            "query": q,
            "is_fuzzy": is_fuzzy,
            "selected_tag": tag,
            "date_range": date_range,
            "start_date": start_date,
            "end_date": end_date,
            "all_tags": all_tags,
            "sort": sort,
            "page": page,
            "limit": limit,
            "total_hits": total_hits,
            "total_pages": total_pages,
            "start_index": min((page - 1) * limit + 1, total_hits) if total_hits > 0 else 0,
            "end_index": min(page * limit, total_hits),
            "sync_status": SYNC_STATUS,
            "exclude": exclude,
            "exclude_ids": exclude_ids,
            "excluded_items": excluded_items,
            "undo_exclude": undo_exclude
        }
    )

@app.get("/pdf/{doc_id}")
def serve_pdf(doc_id: str):
    conn = indexer.get_db()
    row = conn.execute('SELECT filepath, filename FROM documents WHERE id = ?', (doc_id,)).fetchone()
    
    if row:
        filepath = row['filepath']
        if filepath and os.path.exists(filepath):
            conn.close()
            return FileResponse(filepath, media_type="application/pdf")

    target_filename = row['filename'] if row else None
    conn.close()

    for docs_dir in indexer.get_docs_directories():
        if os.path.exists(docs_dir):
            for root, _, files in os.walk(docs_dir):
                for file in files:
                    if indexer.is_pdf(file):
                        abs_path = os.path.abspath(os.path.join(root, file))
                        if target_filename and file == target_filename:
                            return FileResponse(abs_path, media_type="application/pdf")

    return HTMLResponse(
        content="<div style='font-family:sans-serif; padding:2rem;'><h2>404 - Document Not Found</h2></div>",
        status_code=404
    )

@app.get("/tags", response_class=HTMLResponse)
def tags_ui(request: Request):
    conn = indexer.get_db()
    all_tags = conn.execute('SELECT * FROM tag_rules ORDER BY tag_name ASC').fetchall()
    conn.close()
    return templates.TemplateResponse(
        request=request, 
        name="tags.html", 
        context={
            "request": request,
            "all_tags": all_tags
        }
    )

@app.post("/tags/save")
def save_tag(
    tag_name: str = Form(...), 
    keywords: str = Form(...), 
    tag_id: str = Form(None),
    allow_fuzzy: str = Form(None)
):
    tag_name = tag_name.strip().lower().replace(" ", "-")
    is_fuzzy = 1 if allow_fuzzy == "true" else 0
    conn = indexer.get_db()
    
    if tag_id and tag_id.strip():
        conn.execute(
            'UPDATE tag_rules SET tag_name = ?, keywords = ?, allow_fuzzy = ? WHERE id = ?',
            (tag_name, keywords, is_fuzzy, int(tag_id))
        )
    else:
        conn.execute(
            'INSERT INTO tag_rules (tag_name, keywords, allow_fuzzy) VALUES (?, ?, ?)',
            (tag_name, keywords, is_fuzzy)
        )
        
    conn.commit()
    conn.close()

    # INSTANT CACHED RETAGGING: Apply tag rule changes immediately without rescanning disk
    try:
        indexer.retag_all_documents()
    except Exception as e:
        print(f"[Retag Error] {e}")

    return RedirectResponse(url="/tags", status_code=303)

@app.post("/tags/delete")
def delete_tag(tag_id: int = Form(...)):
    conn = indexer.get_db()
    conn.execute('DELETE FROM tag_rules WHERE id = ?', (tag_id,))
    conn.commit()
    conn.close()

    # INSTANT CACHED RETAGGING: Remove deleted tags from cached records immediately
    try:
        indexer.retag_all_documents()
    except Exception as e:
        print(f"[Retag Error] {e}")

    return RedirectResponse(url="/tags", status_code=303)
