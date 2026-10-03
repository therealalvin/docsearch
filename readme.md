# 📄 Local Document Search Vault

A high-performance, self-hosted document search engine and intelligence vault designed for fast indexing, advanced filtering, and automated metadata tagging of local PDF libraries. Built with **FastAPI**, **Meilisearch**, **SQLite**, and **PyMuPDF**.

![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)
![Meilisearch](https://img.shields.io/badge/Meilisearch-latest-283fc3.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

---

## ✨ Key Features

* **⚡ Blazing Fast Full-Text Search:** Powered by Meilisearch with support for exact phrase matching, boolean operators (`AND`, `OR`), and optional fuzzy search toggles.
* **🏷️ Dynamic Rule-Based Tagging:** Define keyword rules with exact or fuzzy matching. Saving or deleting rules instantly triggers cached re-evaluation across your entire library without rescanning disk storage.
* **👁️ Visual Layout Similarity Filtering:** Generates grayscale layout vector embeddings from document thumbnails, allowing you to filter out or exclude visually repetitive document templates.
* **📅 Advanced Date Filtering:** Filter documents instantly by predefined ranges (Year-to-Date, Last Month, Last Year) or custom date pickers.
* **🔄 Asynchronous Background Delta-Sync:** Scans your local directories for new or deleted files in a background worker thread, keeping SQLite and Meilisearch perfectly synchronized.
* **📄 In-Browser PDF Viewing:** Securely serves original PDFs and generates thumbnail previews on the fly.

---
## 🛠️ Tech Stack

* **Backend & API:** Python, FastAPI, Uvicorn
* **Search Engine:** Meilisearch (Rust-backed)
* **Metadata & Caching:** SQLite (with WAL mode enabled for concurrent reads/writes)
* **PDF Processing & Vision:** PyMuPDF (`fitz`), Pillow, NumPy
* **Frontend:** Server-side rendered HTML templates (Jinja2) with responsive layouts

---

## 🚀 Getting Started

### Prerequisites
* Docker & Docker Compose (Recommended)
* Python 3.11+ (if running locally)

### Running with Docker Compose
1. Clone the repository and navigate to your project directory.
2. Place your PDF documents into your designated documents folder (e.g., `./documents`).
3. Spin up the containers:
   ```bash
   docker-compose up --build

## How to Run It

To run the application using the original, unmodified `docker-compose.yaml` file:

1. Clone or download the repository to your local machine.
2. Open your terminal in the root directory containing the `docker-compose.yaml` file.
3. Start the containers in detached mode by running:
   ```bash
   docker compose up -d
   ```
4. Access the service locally via your browser by navigating to:
   ```text
   http://localhost:8080
   ```
   *(Note: Adjust the port above if a custom port mapping is defined in your environment).*
5. To stop the application when you are finished, run:
   ```bash
   docker compose down
   ```
