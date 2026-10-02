# DocSearch 🔍📖

Welcome to **DocSearch**, a containerized search solution designed to make PDF documents effortless to search, index, and navigate.

## What It Does

* **Smart Documentation Indexing:** Processes and indexes OCR'd PDF files so that users can find specific topics instantly.
* **Tagging Feature:** Organizes and filters search results using custom tags, making it easy to categorize and locate specific documents or sections by topic.
* **Lightweight & Fast:** Built for speed, allowing quick lookup across your documentation stack.
* **Dockerized Setup:** Fully containerized for easy deployment without manual dependency management.

## How It Works

1. **Ingestion & Parsing:** The application ingests your PDF sources.
2. **Tagging & Index Generation:** It associates content with custom tags and builds an internal search index mapping keywords and snippets to their corresponding source documents.
3. **Query Interface:** Exposes a clean interface/API where users can search, filter by tags, and retrieve matching document sections in real-time.

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
