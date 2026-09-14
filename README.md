Gym Management SaaS
A multi-tenant gym management platform built with FastAPI, PostgreSQL, SQLAlchemy, and Jinja2, with a strong focus on authentication, tenant isolation, database security, and production readiness.
Overview
Gym Management SaaS provides the core workflows needed to operate a gym while applying production-oriented security and database engineering practices.
The application supports member management, memberships, renewals, payment history, authentication, role-based authorization, and isolated data access between gyms.
The project has progressed beyond basic feature development into security hardening, production engineering, deployment, and SaaS-readiness validation.


⸻


Features
Gym & Member Management
Register new members
Import existing members
Edit member profiles
Soft-delete members
Restore deleted members
Search and filter members
Track active, expired, and due-soon memberships
Configure gym settings
Memberships & Payments
Membership registration
Membership renewal
Monthly membership billing
Registration fees
Payment history
Payment records linked to members
Renewal validation based on configured monthly fees
Authentication & Authorization
User authentication
Secure session management
Role-based access control
Protected application routes
Password hashing
Login throttling
CSRF protection


⸻


Multi-Tenant Security
Tenant isolation is implemented using a defense-in-depth architecture.
The application does not rely solely on application-level filtering. PostgreSQL also enforces tenant boundaries at the database layer using Row-Level Security (RLS).
Tenant isolation includes
Application-level tenant scoping
Request-scoped trusted tenant context
SQLAlchemy session-level tenant binding
PostgreSQL Row-Level Security
Forced RLS on tenant-sensitive tables
Restricted PostgreSQL runtime role
Cross-tenant access validation
Role-based authorization
The current PostgreSQL RLS configuration protects:
gyms
members
payments
audit_logs
legacy_member_records
The tenant isolation policy is enforced through:
tenant_gym_isolation


⸻


Security Engineering
Security hardening includes:
CSRF protection on state-changing requests
Secure session cookies
Production session configuration
Login throttling
Password hashing
Protected routes
Role-based authorization
Explicit tenant context
PostgreSQL RLS
Restricted database runtime privileges
Explicit database migrations
Backup and recovery validation
Production deployment checks
The application is designed so that a failure in one tenant-isolation layer does not become the only barrier protecting another tenant’s data.


⸻


Technology Stack
Layer
Technology
Language
Python
Backend
FastAPI
ORM
SQLAlchemy 2.x
Database
PostgreSQL
Local/Test Database
SQLite where appropriate
Templates
Jinja2
Frontend
HTML, CSS, JavaScript
Migrations
Alembic
Authentication
Session-based authentication
Password Hashing
pwdlib / Argon2
Testing
Pytest
Static Analysis
Ruff
Infrastructure
Docker / Docker Compose


⸻


Architecture
                    Browser
                       │
                       ▼
              ┌─────────────────┐
              │     FastAPI     │
              │                 │
              │ Authentication  │
              │ RBAC            │
              │ CSRF            │
              │ Tenant Context  │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │    SQLAlchemy   │
              │                 │
              │ ORM / Sessions  │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │   PostgreSQL    │
              │                 │
              │ Row-Level       │
              │ Security (RLS)  │
              └─────────────────┘
The frontend is server-rendered using Jinja2 templates, with HTML, CSS, and JavaScript providing the browser interface.


⸻


Database & Migrations
Database schema changes are managed explicitly through Alembic migrations.
The current release migration head is:0009_postgresql_tenant_rls
Production database changes are not automatically applied during application startup. Migration execution is treated as an explicit deployment operation.
This approach makes schema changes easier to review, test, reproduce, and recover.


⸻


Engineering Validation
The project has been validated through automated testing and production-oriented security checks.
Current test suite:
127 tests passed
Validation includes:
Application functionality
Authentication and authorization
CSRF protection
Tenant isolation
PostgreSQL RLS
Cross-tenant access attempts
Database migrations
Backup and restore workflows
Restricted database runtime roles
HTTPS/session behavior
Controlled migration failure scenarios
Static analysis
Cross-tenant access validation confirms that unauthorized tenant access is rejected rather than merely hidden at the UI level.


⸻


Production Readiness
The project is being developed with production deployment requirements in mind.
Production configuration includes controls for:
PostgreSQL
Secure session cookies
Secret management
Explicit allowed hosts
Trusted proxy configuration
Database migrations
Database backups
Recovery procedures
Restricted database privileges
Tenant isolation
The application also includes operational tooling for database backup, schema validation, and first-owner bootstrap.


⸻


Local Development
Requirements
Python 3.13+
PostgreSQL
Docker Desktop
Git
Clone the repository
git clone https://github.com/samt2760/gym-management-saas.git
cd gym-management-saas
Create a virtual environment
Windows PowerShell:
python -m venv .venv
.venv\Scripts\Activate.ps1
Install dependencies
pip install -r requirements.txt
Configure environment variables
Create a local .env file from the example configuration:
Copy-Item .env.example .env
Set a strong local SESSION_SECRET and configure the appropriate database connection before starting the application.
Run migrations
alembic upgrade head
Start the application
uvicorn app.main:app --reload
The application will be available locally at:
http://127.0.0.1:8000
Health check:
/health


⸻


Testing
Run the full test suite with:
pytest -q
Run Ruff:
ruff check .
For PostgreSQL-specific validation, use the project’s dedicated database and security validation tooling.


⸻


Project Structure
app/
├── auth.py
├── main.py
├── web.py
├── core/
│   ├── config.py
│   ├── database.py
│   └── tenant_context.py
├── models/
├── routes/
└── templates/

alembic/
└── versions/

scripts/
├── postgres_backup.py
├── schema_release_gate.py
└── bootstrap_first_owner.py

tests/

docs/
The exact structure may evolve as the project moves through deployment and SaaS-readiness work.


⸻


Current Status
Production security hardening: Validated
PostgreSQL tenant isolation: Validated
Current migration head:
0009_postgresql_tenant_rls
Automated tests:
127 passed
Current development focus:
Production deployment
Infrastructure hardening
Operational reliability
SaaS readiness


⸻


Engineering Focus
This project is intentionally being developed as more than a CRUD application.
The engineering focus is on building a system that can evolve from a single-gym application into a secure multi-tenant SaaS platform, with particular attention to:
Security boundaries
Database integrity
Tenant isolation
Authentication
Deployment safety
Migration safety
Backup and recovery
Automated validation
Operational reliability


⸻


Project Repository
GitHub:
https://github.com/samt2760/gym-management-saas