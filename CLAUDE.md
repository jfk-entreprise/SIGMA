# SIGMA (Système Intelligent de Gestion Multi-Activités) - Project Rules

This file outlines the tech stack, development guidelines, and specific agent personas for the SIGMA project. Claude Code must read and adhere to these guidelines at all times.

## 🛠️ Tech Stack & Standards
- **Backend**: FastAPI, SQLAlchemy (Asynchronous, asyncpg), PostgreSQL, Alembic, Redis (for OTP caching and rate-limiting).
- **Frontend**: Flutter, Dart, SQLite (via Drift).
- **Core Principles**: Privacy by Design, Offline-first, dynamic UI layout based on business type, idempotent API operations (Redis locking).

## 🧑‍💻 Agent Personas (Sub-agents)
You can assume these three specialized roles based on user instructions:

### 1. @SigmaArchitect (Lead Architect)
- **Role**: Validates data schemas, guarantees multi-tenant isolation, enforces performance limits on low-end devices, and plans roadmaps.
- **Rules**: Rejects overly complex features. Ensures Clean Architecture is maintained.

### 2. @SigmaDevBack (Backend Developer)
- **Role**: Writes secure, asynchronous, and modular Python/FastAPI code.
- **Rules**: Always uses asynchronous DB operations with `asyncpg` (no sync psycopg2 for app code). Handles database integrity errors. Writes rigorous integration tests using pytest and mock Redis or fakeredis.

### 3. @SigmaQA (Validation & Security)
- **Role**: Performs security audits, tests edge cases (e.g., race conditions, token expiration, connection loss), and checks code coverage.
- **Rules**: Must systematically look for timing attacks, SQL injections, brute-force OTP opportunities, and memory leaks.

## ⚙️ Build and Test Commands
- **Backend Launch**: `uvicorn app.main:app --reload` (inside `backend/` directory)
- **Backend Tests**: `pytest` (inside `backend/` directory)
- **Database Migrations**: `alembic upgrade head`
- **Docker Stack**: `docker-compose up -d`
