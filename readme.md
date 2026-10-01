# DocSearch 🔍📖

Welcome to **DocSearch**, a containerized search solution designed to make documentation effortless to search, index, and navigate. 

---

## What It Does
* **Smart Documentation Indexing:** Processes and indexes documentation files so that users can find specific topics instantly.
* **Lightweight & Fast:** Built for speed, allowing quick lookup across your documentation stack.
* **Dockerized Setup:** Fully containerized for easy deployment without manual dependency management.

---

## How It Works
1. **Ingestion & Parsing:** The application ingests your documentation sources (such as markdown files or web pages).
2. **Index Generation:** It builds an internal search index mapping keywords and snippets to their corresponding source documents.
3. **Query Interface:** Exposes a clean interface/API where users can search and retrieve matching document sections in real-time.

---

## How to Run It

To run the application using the original, unmodified `docker-compose.yaml` file:

1. Clone or download the repository to your local machine.
2. Open your terminal in the root directory containing the `docker-compose.yaml` file.
3. Start the containers in detached mode by running:
   ```bash
   docker compose up -d
   ```
4. Access the service locally via your browser or the configured port.
5. To stop the application when you are finished, run:
   ```bash
   docker compose down
   ```